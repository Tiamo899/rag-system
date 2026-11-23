"""混合检索：向量(knn) + 关键词(BM25)，应用层 RRF 融合（k=60）。

可用性设计（fail-soft）：
    向量路（Embedding 服务）异常时不中断整条检索，降级为纯关键词检索，
    并把错误写入 SearchOutcome.vector_error 供调用方（RAG 流程 / 调试台）感知。
    两路都不可用时返回空列表，由上层走兜底文案，不抛 500。
"""
from dataclasses import dataclass, field
from datetime import date

from app.core.config import get_settings
from app.core.elasticsearch import get_es
from app.services.embedding.factory import get_embedding_provider

_settings = get_settings()
RRF_K = 60


@dataclass
class SearchOutcome:
    """一次检索的完整产出（含过程数据，供调试台与评测使用）。"""

    results: list[dict] = field(default_factory=list)
    vector_hits: list[dict] = field(default_factory=list)
    keyword_hits: list[dict] = field(default_factory=list)
    rrf: dict[str, float] = field(default_factory=dict)
    vector_rank: dict[str, int] = field(default_factory=dict)
    keyword_rank: dict[str, int] = field(default_factory=dict)
    query_vector: list[float] | None = None
    embedding_ms: float = 0.0
    vector_error: str | None = None
    keyword_error: str | None = None
    search_type: str = "hybrid"


def _rrf_scores(ranked_id_lists: list[list[str]], k: int = RRF_K) -> dict[str, float]:
    """Reciprocal Rank Fusion：score = Σ 1/(k + rank)。"""
    scores: dict[str, float] = {}
    for ranked in ranked_id_lists:
        for rank, doc_id in enumerate(ranked, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return scores


def _hit_to_result(hit: dict) -> dict:
    src = hit.get("_source") or {}
    meta = src.get("metadata") or {}
    return {
        "chunk_id": src.get("chunk_id"),
        "doc_id": src.get("doc_id"),
        "doc_name": meta.get("doc_name"),
        "kb_name": meta.get("kb_name"),
        "title": meta.get("title"),
        "chunk_index": meta.get("chunk_index"),
        "content": src.get("content"),
        "content_vector": src.get("content_vector"),
        "version_no": meta.get("version_no"),
        "valid_from": meta.get("valid_from"),
        "valid_to": meta.get("valid_to"),
        "score": hit.get("_score") or 0.0,
    }


def _kb_filter(kb_id: str | None, kb_ids: list[str] | None = None) -> dict | None:
    """知识库过滤：单库优先；kb_ids=[] 表示当前用户无可见库（不命中任何文档）。"""
    if kb_id:
        return {"term": {"kb_id": kb_id}}
    if kb_ids is not None:
        return {"terms": {"kb_id": kb_ids}}
    return None


def build_validity_filters(today: str | None = None) -> list[dict]:
    """时效过滤（严格语义：缺字段即不命中）。存量数据须先跑回填脚本。"""
    day = today or date.today().isoformat()
    return [
        {"range": {"metadata.valid_from": {"lte": day}}},
        {"range": {"metadata.valid_to": {"gte": day}}},
    ]


async def search_vector(
    query_vector: list[float],
    kb_id: str | None,
    top_k: int,
    kb_ids: list[str] | None = None,
) -> list[dict]:
    """向量路召回（ES kNN + HNSW），返回按 ES 分数降序的候选。"""
    es = get_es()
    kb_f = _kb_filter(kb_id, kb_ids)
    validity_f = build_validity_filters()
    knn: dict = {
        "field": "content_vector",
        "query_vector": query_vector,
        "k": top_k,
        "num_candidates": top_k * 10,
    }
    # ES knn 不接受 filter: null；validity_f 恒存在，故 filter 键恒有值
    knn["filter"] = {"bool": {"filter": ([kb_f] if kb_f else []) + validity_f}}
    resp = await es.search(index=_settings.es_index, knn=knn)
    return [_hit_to_result(h) for h in resp["hits"]["hits"]]


async def search_keyword(
    query: str,
    kb_id: str | None,
    top_k: int,
    kb_ids: list[str] | None = None,
) -> list[dict]:
    """关键词路召回（IK 分词 + BM25），返回按 ES 分数降序的候选。"""
    es = get_es()
    kb_f = _kb_filter(kb_id, kb_ids)
    validity_f = build_validity_filters()
    bool_q: dict = {"must": {"match": {"content": query}}}
    bool_q["filter"] = ([kb_f] if kb_f else []) + validity_f
    resp = await es.search(
        index=_settings.es_index, size=top_k, query={"bool": bool_q}
    )
    return [_hit_to_result(h) for h in resp["hits"]["hits"]]


async def execute_search(
    query: str,
    kb_id: str | None,
    top_k: int = 5,
    search_type: str = "hybrid",
    kb_ids: list[str] | None = None,
) -> SearchOutcome:
    """执行检索并返回完整过程数据（不含 cosine，由上层按需补充）。

    fail-soft：向量路异常 → 记 vector_error 并继续关键词路；关键词路异常 → 记
    keyword_error。两路都拿不到候选时返回空结果，不抛异常。
    """
    import time

    out = SearchOutcome(search_type=search_type)
    result_map: dict[str, dict] = {}
    ranked_lists: list[list[str]] = []

    # 无可见知识库：直接返回空结果，走上层兜底文案（不下发任何文档）
    if kb_ids is not None and not kb_ids:
        return out

    if search_type in ("hybrid", "vector"):
        t0 = time.perf_counter()
        try:
            provider = get_embedding_provider()
            out.query_vector = (await provider.embed_texts([query]))[0]
            out.embedding_ms = round((time.perf_counter() - t0) * 1000, 1)
            out.vector_hits = await search_vector(out.query_vector, kb_id, top_k, kb_ids)
        except Exception as exc:  # noqa: BLE001 —— 可用性优先：向量路失败不阻断检索
            out.vector_error = f"{type(exc).__name__}: {exc}"
            out.embedding_ms = round((time.perf_counter() - t0) * 1000, 1)

        ids: list[str] = []
        for r in out.vector_hits:
            cid = r.get("chunk_id")
            if cid and cid not in result_map:
                ids.append(cid)
                result_map[cid] = r
        if ids:
            ranked_lists.append(ids)
            out.vector_rank = {cid: i for i, cid in enumerate(ids, start=1)}

    if search_type in ("hybrid", "keyword"):
        try:
            out.keyword_hits = await search_keyword(query, kb_id, top_k, kb_ids)
        except Exception as exc:  # noqa: BLE001 —— 关键词路失败同样降级而非 500
            out.keyword_error = f"{type(exc).__name__}: {exc}"

        ids = []
        for r in out.keyword_hits:
            cid = r.get("chunk_id")
            if not cid:
                continue
            ids.append(cid)
            result_map.setdefault(cid, r)
        if ids:
            ranked_lists.append(ids)
            out.keyword_rank = {cid: i for i, cid in enumerate(ids, start=1)}

    if search_type == "hybrid":
        out.rrf = _rrf_scores(ranked_lists)
        ordered = sorted(out.rrf, key=lambda d: out.rrf[d], reverse=True)[:top_k]
        for cid in ordered:
            r = result_map.get(cid)
            if r:
                r = dict(r)
                r["score"] = out.rrf[cid]
                out.results.append(r)
        return out

    # vector / keyword：按 ES 原始分数排序
    merged = list(result_map.values())
    merged.sort(key=lambda r: r["score"], reverse=True)
    out.results = merged[:top_k]
    return out


async def hybrid_search(
    query: str,
    kb_id: str | None,
    top_k: int = 5,
    search_type: str = "hybrid",
    kb_ids: list[str] | None = None,
) -> list[dict]:
    """search_type: hybrid(默认) | vector | keyword。kb_id=None 表示全库检索。"""
    outcome = await execute_search(query, kb_id, top_k, search_type, kb_ids)
    return outcome.results
