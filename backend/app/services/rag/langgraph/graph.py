"""RAG 工作流入口（两阶段，Phase 1 起支持多轮历史）。

① prepare_rag：分析 →(直接回答 | 改写 → 检索 → 评估 → 兜底)，返回分支计划
② 流式生成：仅 generate 模式由 chat 层调 llm.generate_stream 逐 token 输出，
   prompt 统一由 plan["prompt"] 提供（含近 3 轮历史 + 编号资料 + 独立化问题）。
"""
from app.services.llm.factory import get_llm_provider
from app.services.rag.langgraph.nodes import (
    analyze_node,
    direct_node,
    evaluate_node,
    fallback_node,
    format_history,
    retrieve_node,
    rewrite_node,
)


def build_chat_prompt(context: str, question: str, history: list | None) -> str:
    """生成阶段 prompt：无历史时与 Phase 0 逐字一致（回归护栏）。"""
    if not history:
        return f"{context}\n\n问题：{question}"
    return (
        "以下是最近的对话历史（仅供理解指代，不要重复复述）：\n"
        f"{format_history(history)}\n\n"
        f"{context}\n\n问题：{question}"
    )


async def prepare_rag(
    question: str,
    kb_id: str | None,
    history: list | None = None,
    kb_ids: list[str] | None = None,
) -> dict:
    """准备阶段：跑完「分析/改写/检索/评估」，返回分支计划。

    history = 本轮之前的对话消息 [{role, content}]，最多 6 条；首轮传 None/[]。
    kb_ids = 当前用户可见的知识库集合；None 表示不受限（admin），[] 表示无可见库。
    返回 {mode, answer, context, sources, question, prompt}：
    - direct / fallback：answer 为固定文案，prompt 为 ""
    - generate：context 为编号资料，prompt 为完整生成提示词，sources 为引用来源
    """
    history = history or []
    state: dict = {
        "question": question,
        "kb_id": kb_id,
        "kb_ids": kb_ids,
        "history": history,
    }

    state.update(analyze_node(state))
    if not state.get("is_kb_query"):
        state.update(direct_node(state))
        return {
            "mode": "direct",
            "answer": state.get("answer", ""),
            "sources": [],
            "context": "",
            "question": question,
            "prompt": "",
        }

    state.update(await rewrite_node(state))   # 无历史/mock/失败 → 透传（fail-open）
    state.update(await retrieve_node(state))
    state.update(await evaluate_node(state))
    if not state.get("has_relevant_content"):
        state.update(fallback_node(state))
        return {
            "mode": "fallback",
            "answer": state.get("answer", ""),
            "sources": [],
            "context": "",
            "question": question,
            "prompt": "",
        }

    standalone = state.get("standalone_query") or question
    return {
        "mode": "generate",
        "answer": "",
        "sources": state.get("selected_chunks") or (state.get("retrieved_chunks") or [])[:3],
        "context": state.get("context", ""),
        "question": standalone,
        "prompt": build_chat_prompt(state.get("context", ""), standalone, history),
        "degraded": bool(state.get("degraded")),
    }


async def run_rag_flow(
    question: str,
    kb_id: str | None,
    history: list | None = None,
    kb_ids: list[str] | None = None,
) -> dict:
    """非流式完整流程：返回 {answer, sources}。history 语义同 prepare_rag。"""
    plan = await prepare_rag(question, kb_id, history=history, kb_ids=kb_ids)
    if plan["mode"] == "generate":
        llm = get_llm_provider()
        answer = await llm.generate(plan["prompt"])
    else:
        answer = plan["answer"]
    return {"answer": answer, "sources": plan["sources"]}
