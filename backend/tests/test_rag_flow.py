# backend/tests/test_rag_flow.py
"""Phase 1 graph 接入：standalone_query 进检索/评估、prompt 带历史。无需容器。"""
import asyncio

from app.services.rag.langgraph import graph, nodes


def test_retrieve_uses_standalone_query(monkeypatch):
    """检索必须用改写后的问句，不是 raw question（否则改写白做）。"""
    seen = {}

    async def spy(query, kb_id, top_k=5, search_type="hybrid"):
        seen["query"] = query
        return []

    monkeypatch.setattr(nodes, "hybrid_search", spy)
    state = {"question": "那具体要走什么流程？",
             "standalone_query": "转专业需要走什么流程？",
             "kb_id": None}
    out = asyncio.run(nodes.retrieve_node(state))
    assert seen["query"] == "转专业需要走什么流程？"
    assert out == {"retrieved_chunks": []}


def test_retrieve_without_rewrite_falls_back_to_question(monkeypatch):
    """standalone_query 缺失（防御）→ 用原问题，不崩。"""
    seen = {}

    async def spy(query, kb_id, top_k=5, search_type="hybrid"):
        seen["query"] = query
        return []

    monkeypatch.setattr(nodes, "hybrid_search", spy)
    asyncio.run(nodes.retrieve_node({"question": "原问题", "kb_id": None}))
    assert seen["query"] == "原问题"


def test_evaluate_uses_standalone_query(monkeypatch):
    """语义二次验证的余弦输入必须是改写后问句的向量。"""
    seen = {}

    class _Provider:
        async def embed_texts(self, texts):
            seen["texts"] = texts
            return [[1.0, 0.0]]

    monkeypatch.setattr(nodes, "get_embedding_provider", lambda: _Provider())
    chunks = [{"score": 0.05, "content": "资料", "content_vector": [1.0, 0.0]}]
    state = {"question": "那这个呢？", "standalone_query": "转专业流程是什么？",
             "retrieved_chunks": chunks}
    asyncio.run(nodes.evaluate_node(state))
    assert seen["texts"] == ["转专业流程是什么？"]


def _patched_graph(monkeypatch, captured):
    """把检索/评估打桩，只测 prompt 管道。"""
    async def fake_retrieve(state):
        return {"retrieved_chunks": [{"doc_name": "x.md", "content": "资料内容",
                                      "score": 0.05, "title": "t"}]}

    async def fake_evaluate(state):
        return {"has_relevant_content": True, "context": "[1] 《x.md》：资料内容"}

    class _LLM:
        async def generate(self, prompt, temperature=0.3):
            captured.append(prompt)
            return "回答"

    monkeypatch.setattr(graph, "retrieve_node", fake_retrieve)
    monkeypatch.setattr(graph, "evaluate_node", fake_evaluate)
    monkeypatch.setattr(graph, "get_llm_provider", lambda: _LLM())


def test_run_rag_flow_prompt_contains_history(monkeypatch):
    captured = []
    _patched_graph(monkeypatch, captured)
    history = [{"role": "user", "content": "转专业需要满足什么条件？"},
               {"role": "assistant", "content": "成绩排名前20%"}]
    plan = asyncio.run(
        graph.run_rag_flow("那具体要走什么流程？", None, history=history)
    )
    assert plan["answer"] == "回答"
    assert len(captured) == 1
    prompt = captured[0]
    assert "对话历史" in prompt                       # 历史段存在
    assert "转专业需要满足什么条件？" in prompt        # 近 3 轮原文进 prompt
    assert "那具体要走什么流程？" in prompt            # 独立化问题（mock 下=原句）
    assert "[1] 《x.md》" in prompt                    # 编号资料仍在


def test_run_rag_flow_prompt_unchanged_without_history(monkeypatch):
    """首轮 prompt 与 Phase 0 完全一致：`{context}\n\n问题：{question}`。"""
    captured = []
    _patched_graph(monkeypatch, captured)
    asyncio.run(graph.run_rag_flow("FastAPI 是什么？", None))
    assert captured[0].endswith("\n\n问题：FastAPI 是什么？")
    assert "对话历史" not in captured[0]


def test_prepare_rag_direct_path_skips_rewrite(monkeypatch):
    """闲聊直答不走改写（首轮零开销之外，闲聊也不该触碰 LLM 改写）。"""
    def _boom(*_a, **_k):
        raise AssertionError("direct path must not call rewrite/LLM")

    monkeypatch.setattr(graph, "rewrite_node", _boom)  # graph 持有自己的导入引用
    plan = asyncio.run(graph.prepare_rag("你好", None, history=[]))
    assert plan["mode"] == "direct"
    assert plan["prompt"] == ""


def test_prepare_rag_kb_path_calls_rewrite_and_feeds_retrieve(monkeypatch):
    """接线钉点：kb 分支必须执行 rewrite，且其输出进入检索 query。

    mock 透传下 prompt 测不出 rewrite 是否被调用——直接桩掉 rewrite 返回
    独立问题，用 nodes.hybrid_search 间谍验证检索拿到的正是它的输出。
    """
    from unittest.mock import AsyncMock

    from app.services.rag.langgraph import nodes

    monkeypatch.setattr(
        graph, "rewrite_node",
        AsyncMock(return_value={"standalone_query": "改写后独立问题"}),
    )
    seen = {}

    async def spy(query, kb_id, top_k=5, search_type="hybrid"):
        seen["query"] = query
        return []

    monkeypatch.setattr(nodes, "hybrid_search", spy)
    plan = asyncio.run(
        graph.prepare_rag("那这个呢？", None, history=[{"role": "user", "content": "上一问"}])
    )
    assert seen["query"] == "改写后独立问题"   # rewrite 被调用且输出进检索
    assert plan["mode"] in ("fallback", "generate")  # 检索空 → fallback，流程不崩
