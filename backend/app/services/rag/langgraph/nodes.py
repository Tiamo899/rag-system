"""LangGraph 节点实现：分析 / 直接回答(闲聊) / 检索 / 评估 / 生成 / 兜底。"""
import logging
from functools import partial

from app.core.config import get_settings
from app.services.embedding.factory import get_embedding_provider
from app.services.llm.base import BaseLLM
from app.services.llm.factory import get_llm_provider
from app.services.llm.mock import FALLBACK_TEXT
from app.services.rag.langgraph.state import RAGState
from app.services.search.hybrid import hybrid_search

_settings = get_settings()
logger = logging.getLogger(__name__)

_GREETINGS = ("你好", "您好", "hi", "hello", "hey", "早上好", "下午好", "晚上好", "在吗", "你是谁")

MULTI_SOURCE_NOTICE = (
    "\n[提示] 以上资料来自多份文档，若规定不一致，请指出差异并以生效日期较新者为准。"
)

PROMPT_TRUNCATE = 300  # 进入改写/生成 prompt 的单条消息截断长度

REWRITE_PROMPT = """结合对话历史，把用户最新问题改写成独立完整的问题（补全其中的指代与省略）。
只输出改写后的问题，不要输出任何其他内容。

对话历史：
{history}

最新问题：{question}"""


def format_history(history: list) -> str:
    """近 6 条（约 3 轮），单条截断 PROMPT_TRUNCATE 字符，'role: content' 每行一条。"""
    return "\n".join(
        f"{m.get('role', 'user')}: {(m.get('content') or '')[:PROMPT_TRUNCATE]}"
        for m in (history or [])[-6:]
    )


async def rewrite_node(state: RAGState) -> dict:
    """检索前把「历史 + 最新问题」改写为独立问题。

    fail-open：无历史 / provider 非 openai（mock 透传）/ LLM 异常 / 空输出
    → 一律返回原问题，绝不让改写挂掉聊天主流程。
    """
    question = state["question"]
    history = state.get("history") or []
    if not history:
        return {"standalone_query": question}
    if _settings.llm_provider != "openai":
        return {"standalone_query": question}
    try:
        llm = get_llm_provider()
        out = await llm.generate(
            REWRITE_PROMPT.format(history=format_history(history), question=question),
            temperature=0.0,
        )
        out = (out or "").strip()
        return {"standalone_query": out or question}
    except Exception:  # noqa: BLE001 —— fail-open，改写失败不打断主流程
        logger.warning("rewrite_node failed, falling back to raw question", exc_info=True)
        return {"standalone_query": question}


def analyze_node(state: RAGState) -> dict:
    """判断是否为知识库查询：短问候语→闲聊，其余→知识库查询。"""
    question = state["question"].strip()
    q = question.lower()
    is_greeting_only = len(question) <= 6 and any(g in q for g in _GREETINGS)
    return {"is_kb_query": not is_greeting_only}


def direct_node(state: RAGState) -> dict:
    """闲聊分支：直接回复，不检索。"""
    return {
        "answer": "你好！我是高校教务知识库助手，可以问我选课、奖学金、转专业、助学金、学籍等教务与学生服务相关问题。",
        "sources": [],
    }


async def retrieve_node(state: RAGState) -> dict:
    query = state.get("standalone_query") or state["question"]  # 改写结果缺失时回退原问题
    chunks = await hybrid_search(
        query,
        state.get("kb_id"),
        top_k=5,
        search_type="hybrid",
    )
    return {"retrieved_chunks": chunks}


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


async def evaluate_node(state: RAGState) -> dict:
    """判定检索结果是否相关。

    双判据取 OR（任一达标即相关）：
      ① RRF 融合分 top_score >= relevance_threshold
      ② query 与 top chunk 的余弦相似度 >= relevance_cos_threshold
    RRF 分对候选集敏感（量级 0.01-0.03），真相关内容可能低于阈值被误杀；
    余弦相似度是绝对量纲，作为语义二次验证兜底。余弦计算失败时 fail-soft 回 RRF。
    """
    chunks = state.get("retrieved_chunks") or []
    if not chunks:
        return {"has_relevant_content": False, "context": ""}
    query = state.get("standalone_query") or state["question"]
    top_score = max(c["score"] for c in chunks)
    rrf_ok = top_score >= _settings.relevance_threshold

    cos_ok = False
    try:
        provider = get_embedding_provider()
        query_vector = (await provider.embed_texts([query]))[0]
        best_cos = max(
            _cosine(query_vector, c["content_vector"])
            for c in chunks
            if c.get("content_vector")
        )
        cos_ok = best_cos >= _settings.relevance_cos_threshold
    except Exception:  # noqa: BLE001 —— 语义验证失败不影响 RRF 判定
        pass

    def _fmt(i: int, c: dict) -> str:
        name = c.get("title") or c.get("doc_name") or "资料"
        meta_parts = []
        if c.get("version_no"):
            meta_parts.append(c["version_no"])
        if c.get("valid_from"):
            meta_parts.append(f"生效{c['valid_from']}")
        meta = f"（{'，'.join(meta_parts)}）" if meta_parts else ""
        return f"[{i + 1}] 《{name}》{meta}：{c['content']}"

    lines = [_fmt(i, c) for i, c in enumerate(chunks[:3])]
    doc_ids = {c.get("doc_id") for c in chunks[:3] if c.get("doc_id")}
    context = "\n".join(lines)
    if len(doc_ids) >= 2:
        context += MULTI_SOURCE_NOTICE
    return {"has_relevant_content": rrf_ok or cos_ok, "context": context}


async def generate_node(state: RAGState, llm: BaseLLM) -> dict:
    prompt = f"{state.get('context') or ''}\n\n问题：{state['question']}"
    answer = await llm.generate(prompt)
    # 引用来源只保留回答实际引用的前 3 条，避免与 [n] 编号不一致
    return {"answer": answer, "sources": (state.get("retrieved_chunks") or [])[:3]}


def fallback_node(state: RAGState) -> dict:
    """检索不到相关内容时的兜底回复（按规格文案）。"""
    return {"answer": FALLBACK_TEXT, "sources": []}


def build_generate(llm: BaseLLM):
    return partial(generate_node, llm=llm)
