"""检索链路追踪：为调试台输出两路召回、RRF 融合、余弦校验与阈值判定全过程。

与 RAG 主流程保持同一套判据（RRF 分 OR 余弦相似度），保证"调试台看到什么，
线上问答就按什么判"，避免调试与生产两套逻辑漂移。
"""
from app.core.config import get_settings
from app.services.search.hybrid import RRF_K, execute_search
from app.services.search.postprocess import diversify, expand_with_neighbors, strip_boilerplate
from app.services.search.relevance import decide_relevance

_settings = get_settings()

MULTI_SOURCE_NOTICE = (
    "\n[提示] 以上资料来自多份文档，若规定不一致，请指出差异并以生效日期较新者为准。"
)


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def build_context(chunks: list[dict]) -> str:
    """按 [n] 编号拼装上下文，每块带标题与文档名，与主流程格式一致。"""
    def _fmt(i: int, c: dict) -> str:
        name = c.get("title") or c.get("doc_name") or "资料"
        meta_parts = []
        if c.get("version_no"):
            meta_parts.append(c["version_no"])
        if c.get("valid_from"):
            meta_parts.append(f"生效{c['valid_from']}")
        meta = f"（{'，'.join(meta_parts)}）" if meta_parts else ""
        return f"[{i + 1}] 《{name}》{meta}：{strip_boilerplate(c['content'])}"

    lines = [_fmt(i, c) for i, c in enumerate(chunks[:3])]
    doc_ids = {c.get("doc_id") for c in chunks[:3] if c.get("doc_id")}
    ctx = "\n".join(lines)
    if len(doc_ids) >= 2:
        ctx += MULTI_SOURCE_NOTICE
    return ctx


async def trace_search(
    query: str,
    kb_id: str | None,
    top_k: int = 5,
    search_type: str = "hybrid",
    rrf_threshold: float | None = None,
    cos_threshold: float | None = None,
    kb_ids: list[str] | None = None,
) -> dict:
    """返回可序列化的检索全过程快照。"""
    rrf_th = (
        rrf_threshold
        if rrf_threshold is not None
        else float(_settings.relevance_threshold)
    )
    cos_th = (
        cos_threshold
        if cos_threshold is not None
        else float(_settings.relevance_cos_threshold)
    )

    outcome = await execute_search(query, kb_id, top_k, search_type, kb_ids)

    def _brief(r: dict, rank: int | None, score: float) -> dict:
        content = (r.get("content") or "").strip()
        return {
            "chunk_id": r.get("chunk_id"),
            "doc_id": r.get("doc_id"),
            "doc_name": r.get("doc_name"),
            "title": r.get("title"),
            "chunk_index": r.get("chunk_index"),
            "version_no": r.get("version_no"),
            "valid_from": r.get("valid_from"),
            "rank": rank,
            "score": round(float(score), 6),
            "preview": content[:180] + ("…" if len(content) > 180 else ""),
        }

    vector_side = [
        _brief(r, i + 1, r.get("score") or 0.0)
        for i, r in enumerate(outcome.vector_hits)
    ]
    keyword_side = [
        _brief(r, i + 1, r.get("score") or 0.0)
        for i, r in enumerate(outcome.keyword_hits)
    ]

    # 融合候选：RRF 前 top_k（与主流程截断一致）
    fused = []
    for r in outcome.results:
        cid = r.get("chunk_id")
        cos = 0.0
        if outcome.query_vector and r.get("content_vector"):
            cos = _cosine(outcome.query_vector, r["content_vector"])
        fused.append(
            {
                **_brief(r, outcome.vector_rank.get(cid), r.get("score") or 0.0),
                "vector_rank": outcome.vector_rank.get(cid),
                "keyword_rank": outcome.keyword_rank.get(cid),
                "rrf_score": round(float(outcome.rrf.get(cid, 0.0)), 6),
                "rrf_raw": outcome.rrf.get(cid, 0.0),
                "cosine": round(cos, 4),
                "rrf_ok": outcome.rrf.get(cid, 0.0) >= rrf_th,
                "cos_ok": cos >= cos_th,
            }
        )

    top_rrf = max((f["rrf_raw"] for f in fused), default=0.0)
    top_cos = max((f["cosine"] for f in fused), default=0.0)
    decision = decide_relevance(
        top_rrf=top_rrf,
        top_cosine=top_cos,
        rrf_threshold=rrf_th,
        cos_threshold=cos_th,
        cos_available=not outcome.vector_error,
        has_candidates=bool(fused),
    )
    is_relevant = decision.is_relevant

    # 与主流程同一套后处理：先补邻块、再做来源去重，调试台看到的就是模型看到的
    ctx_chunks = diversify(
        await expand_with_neighbors(outcome.results),
        limit=3,
        max_per_doc=2,
        budget_chars=int(_settings.ctx_budget_chars),
    )
    ctx = build_context(ctx_chunks) if is_relevant else ""
    context_meta = {
        "chunks": len(ctx_chunks),
        "chars": len(ctx),
        "doc_names": [c.get("doc_name") for c in ctx_chunks],
        "expanded": sum(1 for c in ctx_chunks if c.get("expanded")),
    }

    return {
        "query": query,
        "search_type": search_type,
        "top_k": top_k,
        "kb_id": kb_id,
        "rrf_k": RRF_K,
        "embedding": {
            "dim": len(outcome.query_vector) if outcome.query_vector else 0,
            "elapsed_ms": outcome.embedding_ms,
            "error": outcome.vector_error,
        },
        "vector": {
            "count": len(vector_side),
            "error": outcome.vector_error,
            "hits": vector_side,
        },
        "keyword": {
            "count": len(keyword_side),
            "error": outcome.keyword_error,
            "hits": keyword_side,
        },
        "fusion": {
            "thresholds": {"rrf": rrf_th, "cosine": cos_th},
            "items": fused,
        },
        "verdict": {
            "is_relevant": is_relevant,
            "top_rrf": round(top_rrf, 6),
            "top_cosine": round(top_cos, 4),
            "rrf_pass": decision.rrf_pass,
            "cosine_pass": decision.cosine_pass,
            "reason": decision.reason,
            "degraded": decision.degraded,
        },
        "context": ctx,
        "context_meta": context_meta,
        "degraded": bool(outcome.vector_error) and bool(outcome.keyword_hits),
    }
