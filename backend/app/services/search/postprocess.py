"""检索后处理：来源去重 + 命中块邻块扩展。

两个问题各有对策：
1. **同一文档包场**：top_k 结果常被同一份文档的相邻小节占满，三个引用位只覆盖
   一处内容。`diversify` 限制同文档最多占 2 个位置，剩下用其它文档的高分块补，
   让回答能看到跨文档的规定（例如奖学金与助学金各自的条件）。
2. **限定条件落在邻块**：分块会切断「第 X 条…；但下列情形除外」这类长句结构。
   `expand_with_neighbors` 命中后从 ES 取同文档相邻块，作为【上文/下文相邻段落】
   附在正文后，让模型看到完整语境；不重建索引、不改分块，纯读取侧增强。
"""
import logging

from app.core.config import get_settings
from app.core.elasticsearch import get_es

logger = logging.getLogger(__name__)
_settings = get_settings()

NEIGHBOR_WINDOW = 1        # 向前后各取几个相邻块
EXPAND_BUDGET = 2600       # 单块扩展后的字符上限（原块 + 邻块），防止上下文膨胀
CTX_BUDGET = 2600          # 三条来源合计的字符预算：够用即可，越界只会拖慢生成、增加串号
UP_MARK = "【上文相邻段落】"
DOWN_MARK = "【下文相邻段落】"

_BOILERPLATE_PREFIX = "本文档为通用示例文档"


def strip_boilerplate(text: str) -> str:
    """剔除示例文档里每篇都重复的免责声明行——它不携带任何答案信息，只占预算。"""
    if not text:
        return text
    kept = [line for line in text.splitlines() if not line.strip().startswith(_BOILERPLATE_PREFIX)]
    return "\n".join(kept).strip()


def diversify(
    chunks: list[dict],
    limit: int = 3,
    max_per_doc: int = 2,
    budget_chars: int = CTX_BUDGET,
) -> list[dict]:
    """限制同一文档入选数量 + 限制合计字符预算，保证多来源但不臃肿。

    预算只约束「第 3 条及以后」：至少保留 2 条，避免预算过紧把上下文砍成一条。
    """
    if not chunks:
        return []
    picked: list[dict] = []
    per_doc: dict[str, int] = {}
    total_chars = 0
    for c in chunks:
        key = str(c.get("doc_id") or c.get("doc_name") or "")
        if per_doc.get(key, 0) >= max_per_doc:
            continue
        size = len(c.get("content") or "")
        if len(picked) >= 2 and total_chars + size > budget_chars:
            continue
        picked.append(c)
        per_doc[key] = per_doc.get(key, 0) + 1
        total_chars += size
        if len(picked) >= limit:
            break
    if len(picked) < limit:
        selected = {id(c) for c in picked}
        for c in chunks:
            if id(c) in selected:
                continue
            size = len(c.get("content") or "")
            if len(picked) >= 2 and total_chars + size > budget_chars:
                continue
            picked.append(c)
            total_chars += size
            if len(picked) >= limit:
                break
    return picked


async def expand_with_neighbors(
    chunks: list[dict],
    window: int = NEIGHBOR_WINDOW,
    budget: int = EXPAND_BUDGET,
    max_chunks: int = 4,
) -> list[dict]:
    """给排在前 max_chunks 的命中块补上同文档相邻块正文。

    任何异常（ES 不可用、字段缺失）都 fail-soft 返回原结果——扩展是锦上添花，
    不能让它把整条问答链路拖垮。只对前几块扩展，避免把整个文档塞进上下文。
    """
    if not chunks:
        return []
    doc_ids = sorted({str(c["doc_id"]) for c in chunks[:max_chunks] if c.get("doc_id")})
    if not doc_ids:
        return chunks
    try:
        es = get_es()
        resp = await es.search(
            index=_settings.es_index,
            query={"terms": {"doc_id": doc_ids}},
            size=500,
            source=["doc_id", "chunk_index", "content"],
        )
        by_doc: dict[str, dict[int, str]] = {}
        for hit in resp["hits"]["hits"]:
            src = hit["_source"]
            # chunk_index 落在 metadata 里（顶层没有这个字段），读错会把所有块当成第 0 块，
            # 导致「上文相邻段落」取到的是本文档最后一块，正文被重复塞进上下文。
            idx = (src.get("metadata") or {}).get("chunk_index")
            if idx is None:
                idx = src.get("chunk_index")
            if idx is None:
                _id = str(hit.get("_id") or "")
                idx = int(_id.rsplit(":", 1)[1]) if ":" in _id else 0
            by_doc.setdefault(str(src["doc_id"]), {})[int(idx)] = src.get("content") or ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("邻块扩展失败，按原分块继续: %s", exc)
        return chunks

    expanded: list[dict] = []
    for pos, c in enumerate(chunks):
        if pos >= max_chunks:
            expanded.append(c)
            continue
        doc = str(c.get("doc_id") or "")
        idx = int(c.get("chunk_index") or 0)
        base = c.get("content") or ""
        neighbors = by_doc.get(doc, {})
        before = neighbors.get(idx - window)
        after = neighbors.get(idx + window)

        room = budget - len(base)
        parts = [base]
        if before and len(before) + len(UP_MARK) <= room:
            parts.insert(0, f"{UP_MARK}{before}")
            room -= len(before) + len(UP_MARK)
        if after and len(after) + len(DOWN_MARK) <= room:
            parts.append(f"{DOWN_MARK}{after}")
            room -= len(after) + len(DOWN_MARK)
        expanded.append(
            {**c, "content": "\n".join(parts), "expanded": len(parts) > 1}
        )
    return expanded
