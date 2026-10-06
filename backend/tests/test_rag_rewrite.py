# backend/tests/test_rag_rewrite.py
"""Phase 1 查询改写节点：透传 / 改写 / fail-open。mock 环境，无需容器与真实 key。"""
import asyncio

from app.services.rag.langgraph import nodes


from unittest.mock import Mock


def test_rewrite_no_history_passthrough_without_llm_call(monkeypatch):
    """首轮（无历史）零开销：绝不触碰 LLM。

    用 Mock 调用计数断言（不能用抛 AssertionError 的 tripwire——
    会被 fail-open 的 except Exception 吞掉造成假绿）。
    """
    spy = Mock(name="get_llm_provider")
    monkeypatch.setattr(nodes, "get_llm_provider", spy)
    out = asyncio.run(nodes.rewrite_node({"question": "那这个呢？", "history": []}))
    spy.assert_not_called()
    assert out == {"standalone_query": "那这个呢？"}


def test_rewrite_mock_passthrough_no_llm_call(monkeypatch):
    """conftest 强制 LLM_PROVIDER=mock：透传，零 LLM 调用。"""
    spy = Mock(name="get_llm_provider")
    monkeypatch.setattr(nodes, "get_llm_provider", spy)
    assert nodes._settings.llm_provider == "mock"  # 环境前提
    out = asyncio.run(nodes.rewrite_node({
        "question": "那这个呢？",
        "history": [{"role": "user", "content": "转专业条件？"},
                    {"role": "assistant", "content": "前20%"}],
    }))
    spy.assert_not_called()
    assert out == {"standalone_query": "那这个呢？"}


class _FakeLLM:
    def __init__(self, ret="转专业需要走什么流程？", raise_exc=None):
        self.ret = ret
        self.raise_exc = raise_exc
        self.calls = []

    async def generate(self, prompt, temperature=0.3):
        self.calls.append({"prompt": prompt, "temperature": temperature})
        if self.raise_exc:
            raise self.raise_exc
        return self.ret


def _patch_openai(monkeypatch, llm):
    """把 nodes 的 provider 判定切到 openai，并注入假 LLM。"""
    import types
    monkeypatch.setattr(nodes, "_settings", types.SimpleNamespace(llm_provider="openai"))
    monkeypatch.setattr(nodes, "get_llm_provider", lambda: llm)


def test_rewrite_openai_uses_llm_with_temp_zero(monkeypatch):
    llm = _FakeLLM(ret="转专业需要走什么流程？")
    _patch_openai(monkeypatch, llm)
    state = {
        "question": "那具体要走什么流程？",
        "history": [{"role": "user", "content": "转专业需要满足什么条件？"},
                    {"role": "assistant", "content": "需要成绩排名前20%"}],
    }
    out = asyncio.run(nodes.rewrite_node(state))
    assert out == {"standalone_query": "转专业需要走什么流程？"}
    assert len(llm.calls) == 1
    call = llm.calls[0]
    assert call["temperature"] == 0.0
    assert "转专业需要满足什么条件？" in call["prompt"]   # 历史进提示词
    assert "那具体要走什么流程？" in call["prompt"]        # 最新问题进提示词


def test_rewrite_failure_falls_back(monkeypatch):
    """LLM 抛异常 → 透传原问题（fail-open）。"""
    llm = _FakeLLM(raise_exc=RuntimeError("provider timeout"))
    _patch_openai(monkeypatch, llm)
    out = asyncio.run(nodes.rewrite_node({
        "question": "那这个呢？",
        "history": [{"role": "user", "content": "上一问"}],
    }))
    assert out == {"standalone_query": "那这个呢？"}


def test_rewrite_empty_falls_back(monkeypatch):
    """LLM 返回空白 → 透传原问题，检索绝不能拿到空串。"""
    llm = _FakeLLM(ret="   \n")
    _patch_openai(monkeypatch, llm)
    out = asyncio.run(nodes.rewrite_node({
        "question": "那这个呢？",
        "history": [{"role": "user", "content": "上一问"}],
    }))
    assert out == {"standalone_query": "那这个呢？"}


def test_format_history_truncates_and_limits():
    history = [{"role": "user", "content": f"第{i}问" + "长" * 400} for i in range(10)]
    history += [{"role": "assistant", "content": "答"}]
    text = nodes.format_history(history)
    lines = text.splitlines()
    assert len(lines) == 6                       # 只取近 6 条
    assert all(len(line) <= len("user: ") + nodes.PROMPT_TRUNCATE for line in lines)
    assert lines[-1].startswith("assistant:")     # 保序
