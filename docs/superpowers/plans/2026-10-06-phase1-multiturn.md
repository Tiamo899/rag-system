# Phase 1 多轮上下文（查询改写）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让追问听懂指代——检索前用对话历史把最新问题改写成独立问题，生成时附带近 3 轮原文，并用评测裁判分验证前后提升。

**Architecture:** `RAGState` 增加 `history`/`standalone_query`，新增 `rewrite_node`（有历史且真实模型时 LLM 改写，否则一律透传 fail-open）；`prepare_rag`/`run_rag_flow` 增加 `history` 参数并统一由 `build_chat_prompt` 构造生成 prompt；`chat.py` 从会话消息取本轮之前最近 6 条作为 history 传入（SSE 协议与前端零改动）；评测 runner 增加 `--multi-turn-mode history` 显式开关（默认 independent 保持基线可复现）。

**Tech Stack:** Python 3.10 · FastAPI · LangGraph 风格节点编排 · pytest（单测不需容器，集成测试需 PG/ES）· 既有 `backend/evals` 跑分体系

**Spec:** `docs/superpowers/specs/2026-09-23-thesis-roadmap-design.md`（§2 原则、§4 Phase 1 全部；Phase 2 由后续计划覆盖）

**Phase 0 既成事实（本计划的输入）：**
- `run_rag_flow(question: str, kb_id: str | None) -> dict` 返回 `{"answer", "sources"}`（graph.py:60）
- `BaseLLM.generate(user_prompt: str, temperature: float = 0.3) -> str`（已支持温度参数）
- 评测基线（git 留档）：`multi_turn` Hit@3=100%、关键词=100%、**judge=50%（t2 追问轮全 0）**——Hit@3/关键词已饱和，**judge 是 Phase 1 唯一有区分度的验收指标**
- 全量测试基线：**82 passed / 55 warnings**

## Global Constraints

- **fail-open**：改写失败、输出为空、provider≠openai 一律透传原问题；聊天主流程不得因改写挂掉
- **mock 不破坏**：mock provider 下 rewrite 零 LLM 调用（透传）；现有 82 测试必须全绿
- **首轮零开销**：history 为空时不触发任何 LLM 调用
- **SSE 协议不变、前端零改动、`API.md` 不动**（history 是服务端会话内数据，不新增请求字段）
- **history 规格**：最多 6 条（近 3 轮），仅含**本轮之前**的消息；进入 prompt 的单条内容截断 **300 字符**
- **改写调用温度**：`temperature=0.0`（确定性）
- **评测基线语义默认不变**：`--multi-turn-mode` 默认 `independent`（与 Phase 0 基线一致），`history` 必须显式指定
- **验收指标**：Phase 1 对比以 `multi_turn` 的 **judge_rate 为主**（基线 50%），Hit@3/关键词作回归护栏（不得下降）
- **YAGNI**：不做会话摘要压缩、不做多知识库路由、不加前端"已结合上下文"角标、不改 rewrite prompt 之外的任何提示词

## Review Focus

最可能咬人的五个点，各自钉在所属任务的测试里：

1. **改写失败/空输出必须回退原问题**——LLM 超时或返回空白时聊天不能挂、检索不能用空串 → Task 1 `test_rewrite_failure_falls_back`、`test_rewrite_empty_falls_back`
2. **mock 下零额外 LLM 调用**——测试环境全 mock，透传被绕过会让 82 绿变红或测试偷偷打网络 → Task 1 `test_rewrite_mock_passthrough_no_llm_call`
3. **history 绝不能含当前这条消息**——`send_message` 先落库当前问题再进生成器，取历史时机错了会把本轮问题重复喂给改写（自指）→ Task 3 `test_chat_history_excludes_current_message`
4. **检索/评估必须用改写后的问句**——改写做了但 retrieve/evaluate 还在用 raw question 等于白做 → Task 2 `test_retrieve_uses_standalone_query`、`test_evaluate_uses_standalone_query`
5. **eval 默认 independent 不能被悄悄改掉**——基线可复现性是整个对比体系的锚；默认值漂移会让历史结果失去参照 → Task 4 `test_multi_turn_default_independent_no_history`

---

### Task 1: rewrite 节点与状态字段

**Files:**
- Modify: `backend/app/services/rag/langgraph/state.py`
- Modify: `backend/app/services/rag/langgraph/nodes.py`
- Test: `backend/tests/test_rag_rewrite.py`（新建）

**Interfaces:**
- Consumes: `get_llm_provider()`（`app.services.llm.factory`，返回 `BaseLLM`，`generate(prompt, temperature=0.0)`）；模块级 `_settings.llm_provider`（nodes.py 已有）
- Produces（Task 2 依赖，签名逐字）:
  - `async def rewrite_node(state: RAGState) -> dict` —— 返回 `{"standalone_query": str}`
  - `def format_history(history: list) -> str` —— 近 6 条、单条截断 300 字符、`"role: content"` 每行一条
  - `RAGState` 新增字段：`history: list`、`standalone_query: str`
  - 常量：`REWRITE_PROMPT`（含 `{history}`/`{question}` 占位）、`PROMPT_TRUNCATE = 300`

- [ ] **Step 1: 写失败测试**

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/test_rag_rewrite.py -v`
Expected: FAIL — `ImportError: cannot import name 'rewrite_node'`（或 `format_history`/`PROMPT_TRUNCATE` 不存在）

- [ ] **Step 3: 最小实现**

`state.py` 的 `RAGState` 增加两字段（插在 `question`/`kb_id` 之后）：

```python
class RAGState(TypedDict, total=False):
    question: str                  # 用户问题
    kb_id: Optional[str]           # 目标知识库（None=全库）
    history: list                  # 本轮之前的对话历史 [{role, content}]，最多 6 条
    standalone_query: str          # 改写后的独立问题（无历史/失败时 = question）
    is_kb_query: bool              # 分析节点：是否为知识库查询
    retrieved_chunks: list         # 检索到的分块
    has_relevant_content: bool     # 评估节点：是否有关联内容
    context: str                   # 编号后的上下文
    answer: str                    # 生成的回答
    sources: list                  # 引用来源
    error: str                     # 错误信息
```

`nodes.py` 顶部 import 区增加（其余 import 不动）：

```python
from app.services.llm.factory import get_llm_provider
```

`nodes.py` 在 `_GREETINGS` 常量之后、`analyze_node` 之前加入：

```python
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
        return {"standalone_query": question}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && python -m pytest tests/test_rag_rewrite.py -v`
Expected: PASS（6 项全绿）

- [ ] **Step 5: 全量回归后提交**

Run: `cd backend && python -m pytest -q`
Expected: 88 passed（82 + 6）, 55 warnings

```bash
git add backend/app/services/rag/langgraph/state.py backend/app/services/rag/langgraph/nodes.py backend/tests/test_rag_rewrite.py
git commit -m "feat(rag): rewrite_node with fail-open history-based query rewriting"
```

---

### Task 2: graph 流程接入改写 + 统一 prompt 构造

**Files:**
- Modify: `backend/app/services/rag/langgraph/graph.py`
- Modify: `backend/app/services/rag/langgraph/nodes.py`（`retrieve_node`/`evaluate_node` 改用 `standalone_query`）
- Test: `backend/tests/test_rag_flow.py`（新建）

**Interfaces:**
- Consumes: Task 1 的 `rewrite_node`、`format_history`、`PROMPT_TRUNCATE`、`RAGState.history/standalone_query`
- Produces（Task 3/4/5 依赖，签名逐字）:
  - `async def prepare_rag(question: str, kb_id: str | None, history: list | None = None) -> dict`
  - `async def run_rag_flow(question: str, kb_id: str | None, history: list | None = None) -> dict`
  - `def build_chat_prompt(context: str, question: str, history: list | None) -> str`
  - generate 分支的 plan 新增键 `"prompt": str`（direct/fallback 分支 `"prompt": ""`）

- [ ] **Step 1: 写失败测试**

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/test_rag_flow.py -v`
Expected: FAIL — `AssertionError`（`test_retrieve_uses_standalone_query`：检索仍用 raw question）

- [ ] **Step 3: 实现**

`nodes.py` —— `retrieve_node` 与 `evaluate_node` 改用 `standalone_query`（两处替换）：

```python
async def retrieve_node(state: RAGState) -> dict:
    query = state.get("standalone_query") or state["question"]  # 改写结果缺失时回退原问题
    chunks = await hybrid_search(
        query,
        state.get("kb_id"),
        top_k=5,
        search_type="hybrid",
    )
    return {"retrieved_chunks": chunks}
```

`evaluate_node` 函数体开头（`chunks = ...` 之后、嵌入调用之前）取查询句，并替换两处 `state["question"]`：

```python
    query = state.get("standalone_query") or state["question"]
    # ...原有 top_score/rrf_ok 计算不动...
    provider = get_embedding_provider()
    query_vector = (await provider.embed_texts([query]))[0]
```

（同函数内构造 context 与 fail-soft 逻辑一律不动。）

`graph.py` —— 整体替换为以下内容（模块 docstring 同步更新）：

```python
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
    question: str, kb_id: str | None, history: list | None = None
) -> dict:
    """准备阶段：跑完「分析/改写/检索/评估」，返回分支计划。

    history = 本轮之前的对话消息 [{role, content}]，最多 6 条；首轮传 None/[]。
    返回 {mode, answer, context, sources, question, prompt}：
    - direct / fallback：answer 为固定文案，prompt 为 ""
    - generate：context 为编号资料，prompt 为完整生成提示词，sources 为引用来源
    """
    history = history or []
    state: dict = {"question": question, "kb_id": kb_id, "history": history}

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
        "sources": (state.get("retrieved_chunks") or [])[:3],
        "context": state.get("context", ""),
        "question": standalone,
        "prompt": build_chat_prompt(state.get("context", ""), standalone, history),
    }


async def run_rag_flow(
    question: str, kb_id: str | None, history: list | None = None
) -> dict:
    """非流式完整流程：返回 {answer, sources}。history 语义同 prepare_rag。"""
    plan = await prepare_rag(question, kb_id, history=history)
    if plan["mode"] == "generate":
        llm = get_llm_provider()
        answer = await llm.generate(plan["prompt"])
    else:
        answer = plan["answer"]
    return {"answer": answer, "sources": plan["sources"]}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && python -m pytest tests/test_rag_flow.py tests/test_rag_rewrite.py -v`
Expected: PASS（12 项：新 6 + Task 1 的 6）

- [ ] **Step 5: 全量回归后提交**

Run: `cd backend && python -m pytest -q`
Expected: 94 passed（88 + 6）, 55 warnings

```bash
git add backend/app/services/rag/langgraph/graph.py backend/app/services/rag/langgraph/nodes.py backend/tests/test_rag_flow.py
git commit -m "feat(rag): wire rewrite into prepare_rag and unify chat prompt builder"
```

---

### Task 3: chat 层接入会话历史

**Files:**
- Modify: `backend/app/api/v1/chat.py`（`send_message` 两处：取历史、传 history 并改用 `plan["prompt"]`）
- Test: `backend/tests/test_chat.py`（追加 2 个测试）

**Interfaces:**
- Consumes: Task 2 的 `prepare_rag(question, kb_id, history=None)`、plan 键 `"prompt"`；`ChatMessage`（role/content，已有）
- Produces: 无新接口（行为变化：生成 prompt 含近 3 轮历史；SSE 帧格式完全不变）

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_chat.py` 文件末尾追加：

```python
def test_chat_history_excludes_current_message(client, admin_headers, prepared_kb, monkeypatch):
    """history 只含本轮之前的消息：第一轮为空，第二轮恰为上一轮 user+assistant，
    绝不包含当前这条问题（否则改写拿到自指输入）。"""
    import app.api.v1.chat as chat_mod

    captured = []

    async def spy(question, kb_id, history=None):
        captured.append({"q": question, "history": history})
        return {"mode": "direct", "answer": "收到", "sources": [],
                "question": question, "prompt": ""}

    monkeypatch.setattr(chat_mod, "prepare_rag", spy)

    sess = client.post(
        "/api/v1/chat/sessions",
        json={"title": "历史传递", "kb_id": prepared_kb},
        headers=admin_headers,
    ).json()

    _send(client, admin_headers, sess["id"], "第一问")
    assert captured[0]["history"] == []          # 首轮无历史

    _send(client, admin_headers, sess["id"], "那这个呢？")
    h = captured[1]["history"]
    assert [m["role"] for m in h] == ["user", "assistant"]
    assert h[0]["content"] == "第一问"            # 上一轮问题
    assert h[1]["content"] == "收到"              # 上一轮回答（spy 的 direct 答案已落库）
    assert all(m["content"] != "那这个呢？" for m in h)  # 当前消息不在 history 里


def test_chat_sse_shape_unchanged_with_history(client, admin_headers, prepared_kb):
    """有历史的第二轮 SSE 帧序仍为 start/token/done——协议零改动。"""
    sess = client.post(
        "/api/v1/chat/sessions",
        json={"title": "协议回归", "kb_id": prepared_kb},
        headers=admin_headers,
    ).json()
    _send(client, admin_headers, sess["id"], "FastAPI 是什么框架？")  # 真实流程，产生历史
    events = _send(client, admin_headers, sess["id"], "那它是用来做什么的？")
    names = [e["event"] for e in events]
    assert names[0] == "start"
    assert "token" in names and "done" in names
    assert "error" not in names, [e for e in events if e["event"] == "error"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/test_chat.py::test_chat_history_excludes_current_message -v`
Expected: FAIL — `assert captured[0]["history"] == []` 变成 `KeyError: 'history'` 或 `TypeError`（当前 `prepare_rag` 调用不带 history）

- [ ] **Step 3: 实现**

`backend/app/api/v1/chat.py` 的 `send_message`，在「先落库用户消息」之前插入历史查询（顺序是关键——**查历史必须发生在落库当前消息之前**）：

```python
    session = await _get_session(db, session_id, user)
    kb_id = body.kb_id or session.kb_id

    # 本轮之前的历史（近 3 轮 = 6 条）。必须在落库当前消息之前查询，
    # 否则 history 会包含当前这条问题，改写拿到自指输入。
    hist_res = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.created_at.desc())
        .limit(6)
    )
    history = [
        {"role": m.role, "content": m.content}
        for m in reversed(hist_res.scalars().all())
    ]

    # 先落库用户消息，并刷新会话时间戳（列表按活跃度排序）
    db.add(ChatMessage(session_id=session.id, role="user", content=body.content))
```

`event_generator` 内两处改动：

```python
            plan = await prepare_rag(
                body.content, str(kb_id) if kb_id else None, history=history
            )

            if plan["mode"] == "generate":
                # 阶段 2：真实 LLM 流式输出（逐 token）；prompt 已由 prepare_rag 统一构造
                yield {"event": "status", "data": json.dumps({"stage": "thinking"})}
                llm = get_llm_provider()
                prompt = plan["prompt"]
                answer_parts: list[str] = []
```

（`direct`/`fallback` 分支、落库、`done` 事件与 SSE 帧格式一律不动。）

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && python -m pytest tests/test_chat.py -v`
Expected: PASS（既有 8 项 + 新 2 项 = 10）

- [ ] **Step 5: 全量回归后提交**

Run: `cd backend && python -m pytest -q`
Expected: 96 passed（94 + 2）, 55 warnings

```bash
git add backend/app/api/v1/chat.py backend/tests/test_chat.py
git commit -m "feat(chat): pass session history into RAG with prompt from prepare_rag"
```

---

### Task 4: 评测 runner 多轮 history 模式

**Files:**
- Modify: `backend/evals/run_eval.py`（`run_multi_turn_cases` 加 `mode` 参数、CLI 加 `--multi-turn-mode`）
- Test: `backend/tests/test_eval_run.py`（追加 2 个测试）

**Interfaces:**
- Consumes: Task 2 的 `run_rag_flow(question, kb_id, history=None)`（向后兼容，旧调用不带 history 仍可用）
- Produces（Task 5 依赖）:
  - `async def run_multi_turn_cases(cases, kb_id, use_judge, results_dir, tag, mode: str = "independent") -> dict`
  - CLI：`--multi-turn-mode {independent,history}`，**默认 `independent`**
  - history 模式下报告 JSON 增加字段 `"multi_turn_mode": "history"|"independent"`

- [ ] **Step 1: 写失败测试**

**先同步修改既有的 `_patch_flow`**（新实现带 `history=` kwarg 调用，旧 fake 无此参会 TypeError；
断言用的元组形态保持 `(question, kb_id)` 不变）：

```python
def _patch_flow(monkeypatch, answers_sources):
    """answers_sources: list of (answer, sources) 按调用顺序返回。"""
    calls = []

    async def fake_flow(question, kb_id, history=None):
        calls.append((question, kb_id))  # 既有断言依赖此元组形态
        ans, src = answers_sources.pop(0)
        return {"answer": ans, "sources": src}

    monkeypatch.setattr(run_eval, "run_rag_flow", fake_flow)
    return calls
```

**然后在文件末尾追加两个新测试：

```python
def _multi_case():
    return {
        "id": "mt-x",
        "turns": [
            {"q": "转专业需要满足什么条件？",
             "expect_docs": ["转专业实施办法.docx"], "expect_keywords": ["转专业"]},
            {"q": "那具体要走什么流程？",
             "expect_docs": ["转专业实施办法.docx"], "expect_keywords": ["流程"]},
        ],
    }


def test_multi_turn_default_independent_no_history(monkeypatch, tmp_path):
    """默认（不传 mode）= Phase 0 基线语义：每轮 history 为空，基线可复现。"""
    calls = []

    async def fake_flow(question, kb_id, history=None):
        calls.append({"q": question, "history": history})
        return {"answer": "答案含转专业与流程",
                "sources": [{"doc_name": "转专业实施办法.docx"}]}

    monkeypatch.setattr(run_eval, "run_rag_flow", fake_flow)
    report = asyncio.run(
        run_eval.run_multi_turn_cases([_multi_case()], kb_id="kb", use_judge=False,
                                      results_dir=tmp_path, tag="t")
    )
    assert len(calls) == 2
    assert all(not c["history"] for c in calls)   # 默认绝不携带历史
    assert report["multi_turn_mode"] == "independent"


def test_multi_turn_history_mode_passes_prior_turns(monkeypatch, tmp_path):
    """history 模式：第 N 轮拿到前 N-1 轮的 user+assistant 消息。"""
    calls = []

    async def fake_flow(question, kb_id, history=None):
        calls.append({"q": question, "history": history})
        return {"answer": f"回答-{question[:2]}",
                "sources": [{"doc_name": "转专业实施办法.docx"}]}

    monkeypatch.setattr(run_eval, "run_rag_flow", fake_flow)
    report = asyncio.run(
        run_eval.run_multi_turn_cases([_multi_case()], kb_id="kb", use_judge=False,
                                      results_dir=tmp_path, tag="t", mode="history")
    )
    assert calls[0]["history"] == []                       # 首轮无历史
    h2 = calls[1]["history"]
    assert [m["role"] for m in h2] == ["user", "assistant"]
    assert h2[0]["content"] == "转专业需要满足什么条件？"
    assert h2[1]["content"].startswith("回答-")
    assert report["multi_turn_mode"] == "history"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/test_eval_run.py -v`
Expected: FAIL — `AssertionError: 'multi_turn_mode'`（报告尚无该键）/ `TypeError: unexpected keyword 'mode'`

- [ ] **Step 3: 实现**

`run_multi_turn_cases`（run_eval.py:135 起）——**整函数替换为**（相对现状的差异只有：签名 `mode` 参数、docstring、`case_history`/`history` 两行、成功分支末尾累积历史两行、报告 `"multi_turn_mode"` 键；异常分支/judge 条件/`_rate`/`_write_report` 调用与现状逐字一致）：

```python
async def run_multi_turn_cases(
    cases: list[dict],
    kb_id: str,
    use_judge: bool,
    results_dir: Path,
    tag: str,
    mode: str = "independent",  # independent=Phase 0 基线语义 | history=传前轮
) -> dict:
    """多轮跑分。independent：每轮独立、不带历史（基线可复现，保持默认）；
    history：第 N 轮携带前 N-1 轮的 user/assistant 消息（Phase 1 验收用）。"""
    details = []
    hits, kws, judges = [], [], []
    for c in cases:
        turn_rows = []
        case_history: list[dict] = []  # 每个 case 重置
        for t in c["turns"]:
            # 传快照而非活引用：防止累积追加污染调用前的历史、
            # 也防止被调用方持有多条 turn 共享同一 list 对象
            history = list(case_history) if mode == "history" else []
            try:
                plan = await run_rag_flow(t["q"], kb_id, history=history)
                answer, sources = plan["answer"], plan["sources"]
            except Exception as exc:  # 单轮失败不拖垮整轮次序列
                hits.append(None)
                kws.append(None)
                judges.append(None)
                turn_rows.append(
                    {
                        "q": t["q"],
                        "hit_at3": None,
                        "keyword": None,
                        "judge": None,
                        "sources": [],
                        "answer": "",
                        "error": str(exc),
                    }
                )
                continue
            hit = hit_at3(sources, t.get("expect_docs", []))
            kw = keyword_verdict(
                answer, t.get("expect_keywords", []), t.get("forbidden_keywords", [])
            )
            jd, err = None, None
            if use_judge and t.get("expect_keywords"):
                try:
                    jd = await _judge(
                        t["q"], t.get("expect_keywords", []) or ["要点"], answer
                    )
                except Exception as exc:
                    jd, err = None, str(exc)
            hits.append(hit)
            kws.append(kw)
            judges.append(jd)
            row = {
                "q": t["q"],
                "hit_at3": hit,
                "keyword": kw,
                "judge": jd,
                "sources": [s.get("doc_name") for s in sources],
                "answer": answer[:300],
            }
            if err is not None:
                row["error"] = err
            turn_rows.append(row)
            case_history.append({"role": "user", "content": t["q"]})
            case_history.append({"role": "assistant", "content": answer})
        details.append({"id": c["id"], "turns": turn_rows})
    report = {
        "tag": tag,
        "dataset": "multi_turn",
        "date": date.today().isoformat(),
        "kb_id": kb_id,
        "multi_turn_mode": mode,
        "hit_at3_rate": _rate(hits),
        "keyword_rate": _rate(kws),
        "judge_rate": _rate(judges) if use_judge else None,
        "cases": details,
    }
    _write_report(report, results_dir, tag, "multi_turn")
    return report
```

CLI（`main()` 内 `parser` 区，在 `--dataset` 行之后加）：

```python
    parser.add_argument("--multi-turn-mode", default="independent",
                        choices=("independent", "history"),
                        help="多轮跑分是否携带前轮历史（默认 independent=基线语义）")
```

`_amain` 中 `multi_turn` 分支的调用行替换为：

```python
        if name == "multi_turn":
            report = await run_multi_turn_cases(
                cases, kb["id"], use_judge, results_dir, args.tag,
                mode=args.multi_turn_mode,
            )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && python -m pytest tests/test_eval_run.py -v`
Expected: PASS（既有 6 项 + 新 2 项 = 8）

- [ ] **Step 5: 全量回归后提交**

Run: `cd backend && python -m pytest -q`
Expected: 98 passed（96 + 2）, 57 warnings（Task 3 后基线含 +2 条 jwt 环境警告）

```bash
git add backend/evals/run_eval.py backend/tests/test_eval_run.py
git commit -m "feat(eval): multi-turn history mode behind explicit flag (default independent)"
```

---

### Task 5: Phase 1 实跑验收 + 文档

**Files:**
- Create: `backend/evals/results/<日期>-phase1-multi_turn.{json,md}`（命令生成）
- Modify: `backend/evals/README.md`（阶段对比 + 主指标说明）

**Interfaces:**
- Consumes: Task 4 的 `--multi-turn-mode history`；既有 `python -m evals.run_eval --tag ...`
- Produces: Phase 1 对比结果文件（与 `2026-09-24-baseline-multi_turn.*` 同表对比，git 留档）

- [ ] **Step 1: 更新 README**

`backend/evals/README.md`「阶段对比」一节，把 Phase 1 那行替换为：

```markdown
- Phase 1 后：`--tag phase1 --multi-turn-mode history`（对比 `multi_turn` 的 **judge_rate**——基线 50%；Hit@3/关键词已饱和，仅作回归护栏不得下降）
```

并在「指标」表格的裁判行之后追加一行：

```markdown
| 多轮模式 | `--multi-turn-mode` 默认 `independent`（=基线语义，不带历史）；`history` 显式开启，第 N 轮携带前 N-1 轮消息 |
```

- [ ] **Step 2: 实跑 Phase 1 对比（需 PG/ES + 真实模型）**

Run: `cd backend && PYTHONIOENCODING=utf-8 python -m evals.run_eval --tag phase1 --dataset multi_turn --multi-turn-mode history`
Expected: 打印 `[multi_turn] Hit@3=… keyword=… judge=…`；生成 `results/<日期>-phase1-multi_turn.json/.md`（JSON 含 `"multi_turn_mode": "history"`）；judge 若遇瞬时 provider 超时会记 error 并继续（重跑一次即可）

- [ ] **Step 3: 抽查对比**

Run: `cat backend/evals/results/*-phase1-multi_turn.md`
Expected:
- `judge_rate` 是数值（真实模型）——与基线 0.5 对比：**提升即改写生效；持平/下降同样是有效结论，如实记录，不许调数据**
- `hit_at3_rate` 与 `keyword_rate` 不低于基线（100%/100%）——下降说明改写引入回归，须查明
- 逐行 t2（追问轮）的 judge 应不再是清一色 0（基线特征）

- [ ] **Step 4: 全量回归后提交**

Run: `cd backend && python -m pytest -q`
Expected: 98 passed, 55 warnings

```bash
git add backend/evals/README.md backend/evals/results
git commit -m "feat(eval): Phase 1 multi-turn baseline comparison results"
```

---

## 完成定义

- [ ] `rewrite_node` 五种路径（无历史/mock/改写/异常/空输出）测试全绿，改写温度 0.0
- [ ] `prepare_rag`/`run_rag_flow` 带 `history` 参数，首轮 prompt 与 Phase 0 逐字一致
- [ ] chat 第二轮 history 恰为上一轮 user+assistant、不含当前消息；SSE 帧序不变
- [ ] eval 默认 independent 可复现基线，`history` 模式显式 flag 且 JSON 留痕 `multi_turn_mode`
- [ ] `results/` 新增 phase1 multi_turn 对比文件已 commit；README 主指标说明已更新
- [ ] 全量 `pytest` 98 passed（82 基线 + 16 新增），`API.md` 与前端零改动
