"""RAG 工作流入口（两阶段）。

① prepare_rag：分析 →(直接回答 | 检索 → 评估 → 兜底)，返回分支计划
② 流式生成：仅 generate 模式由 chat 层调 llm.generate_stream 逐 token 输出

节点函数复用 nodes.py（analyze/direct/retrieve/evaluate/fallback），generate 改由
调用方流式驱动，不再放进图内。
"""
from app.services.llm.factory import get_llm_provider
from app.services.rag.langgraph.nodes import (
    analyze_node,
    direct_node,
    evaluate_node,
    fallback_node,
    retrieve_node,
)


async def prepare_rag(question: str, kb_id: str | None) -> dict:
    """准备阶段：跑完「分析/检索/评估」，返回分支计划。

    返回 {mode: direct|fallback|generate, answer, context, sources, question}。
    - direct / fallback：answer 为固定文案，直接输出
    - generate：context 为编号资料，供流式生成；sources 为引用来源
    """
    state: dict = {"question": question, "kb_id": kb_id}

    state.update(analyze_node(state))
    if not state.get("is_kb_query"):
        state.update(direct_node(state))
        return {
            "mode": "direct",
            "answer": state.get("answer", ""),
            "sources": [],
            "context": "",
            "question": question,
        }

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
        }

    return {
        "mode": "generate",
        "answer": "",
        "sources": (state.get("retrieved_chunks") or [])[:3],
        "context": state.get("context", ""),
        "question": question,
    }


async def run_rag_flow(question: str, kb_id: str | None) -> dict:
    """非流式完整流程（向后兼容）：返回 {answer, sources}。"""
    plan = await prepare_rag(question, kb_id)
    if plan["mode"] == "generate":
        llm = get_llm_provider()
        prompt = f"{plan['context']}\n\n问题：{plan['question']}"
        answer = await llm.generate(prompt)
    else:
        answer = plan["answer"]
    return {"answer": answer, "sources": plan["sources"]}
