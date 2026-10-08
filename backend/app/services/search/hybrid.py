"""混合检索：向量(knn) + 关键词(BM25)，应用层 RRF 融合（k=60）。"""
from datetime import date

from app.core.config import get_settings
from app.core.elasticsearch import get_es
from app.services.embedding.factory import get_embedding_provider

_settings = get_settings()
RRF_K = 60


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
        "score": hit.get("_score") or 0.0,
    }


def _kb_filter(kb_id: str | None) -> dict | None:
    return {"term": {"kb_id": kb_id}} if kb_id else None


def build_validity_filters(today: str | None = None) -> list[dict]:
    """时效过滤（严格语义：缺字段即不命中）。存量数据须先跑回填脚本。"""
    day = today or date.today().isoformat()
    return [
        {"range": {"metadata.valid_from": {"lte": day}}},
        {"range": {"metadata.valid_to": {"gte": day}}},
    ]


async def hybrid_search(
    query: str,
    kb_id: str | None,
    top_k: int = 5,
    search_type: str = "hybrid",
) -> list[dict]:
    """search_type: hybrid(默认) | vector | keyword。kb_id=None 表示全库检索。"""
    es = get_es()
    index = _settings.es_index
    provider = get_embedding_provider()

    ranked_lists: list[list[str]] = []
    result_map: dict[str, dict] = {}

    kb_f = _kb_filter(kb_id)  # kb_id=None 时为 None，此时不传 filter 键
    validity_f = build_validity_filters()

    if search_type in ("hybrid", "vector"):
        query_vector = (await provider.embed_texts([query]))[0]
        knn: dict = {
            "field": "content_vector",
            "query_vector": query_vector,
            "k": top_k,
            "num_candidates": top_k * 10,
        }
        # ES knn 不接受 filter: null；validity_f 恒存在，故 filter 键恒有值
        knn_filter = {"bool": {"filter": ([kb_f] if kb_f else []) + validity_f}}
        knn["filter"] = knn_filter
        resp = await es.search(index=index, knn=knn)
        ids: list[str] = []
        for hit in resp["hits"]["hits"]:
            ids.append(hit["_id"])
            result_map[hit["_id"]] = _hit_to_result(hit)
        if ids:
            ranked_lists.append(ids)

    if search_type in ("hybrid", "keyword"):
        bool_q: dict = {"must": {"match": {"content": query}}}
        bool_q["filter"] = ([kb_f] if kb_f else []) + validity_f
        resp = await es.search(index=index, size=top_k, query={"bool": bool_q})
        ids = []
        for hit in resp["hits"]["hits"]:
            ids.append(hit["_id"])
            result_map.setdefault(hit["_id"], _hit_to_result(hit))
        if ids:
            ranked_lists.append(ids)

    if search_type == "hybrid":
        scores = _rrf_scores(ranked_lists)
        ordered_ids = sorted(scores, key=lambda d: scores[d], reverse=True)[:top_k]
        results = []
        for doc_id in ordered_ids:
            r = result_map.get(doc_id)
            if r:
                r["score"] = scores[doc_id]
                results.append(r)
        return results

    # vector / keyword：按 ES 原始分数排序
    results = list(result_map.values())
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top_k]
