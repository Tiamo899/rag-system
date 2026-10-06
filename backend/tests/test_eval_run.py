# backend/tests/test_eval_run.py
"""run_eval 编排逻辑测试：monkeypatch 掉 run_rag_flow 与裁判，零外部依赖。"""
import asyncio
import json
from pathlib import Path

from evals import run_eval


def _mk_case(cid="c1", q="国家助学金怎么申请？", expect_docs=None,
             keywords=None, forbidden=None):
    c = {"id": cid, "question": q,
         "expect_docs": expect_docs or ["国家助学金评审办法.docx"],
         "expect_keywords": keywords or ["助学金"]}
    if forbidden is not None:
        c["forbidden_keywords"] = forbidden
    return c


def _patch_flow(monkeypatch, answers_sources):
    """answers_sources: list of (answer, sources) 按调用顺序返回。"""
    calls = []

    async def fake_flow(question, kb_id, history=None):
        calls.append((question, kb_id))  # 既有断言依赖此元组形态
        ans, src = answers_sources.pop(0)
        return {"answer": ans, "sources": src}

    monkeypatch.setattr(run_eval, "run_rag_flow", fake_flow)
    return calls


def test_single_case_hit_and_keyword(monkeypatch, tmp_path):
    _patch_flow(monkeypatch, [(
        "申请助学金需在系统提交",
        [{"doc_name": "国家助学金评审办法.docx"}],
    )])
    case = _mk_case()
    report = asyncio.run(
        run_eval.run_single_cases([case], kb_id="kb", use_judge=False,
                                  results_dir=tmp_path, tag="t")
    )
    assert report["hit_at3_rate"] == 1.0
    assert report["keyword_rate"] == 1.0
    assert report["judge_rate"] is None
    assert report["cases"][0]["hit_at3"] is True


def test_forbidden_keyword_marks_case_failed(monkeypatch, tmp_path):
    _patch_flow(monkeypatch, [(
        "最多3天",  # 旧版数字
        [{"doc_name": "请假管理办法_2024版.md"}],
    )])
    case = _mk_case(expect_docs=["请假管理办法_2024版.md"],
                    keywords=["5天"], forbidden=["3天"])
    report = asyncio.run(
        run_eval.run_single_cases([case], kb_id="kb", use_judge=False,
                                  results_dir=tmp_path, tag="t")
    )
    assert report["keyword_rate"] == 0.0
    assert report["cases"][0]["keyword"] is False


def test_multi_turn_runs_turns_independently(monkeypatch, tmp_path):
    """Phase 0 基线语义：每轮独立调用、原句、绝不携带历史。"""
    calls = _patch_flow(monkeypatch, [
        ("转专业有条件", [{"doc_name": "转专业实施办法.docx"}]),
        ("流程不明确", [{"doc_name": "学籍管理规定.docx"}]),  # 追问未命中目标
    ])
    case = {
        "id": "mt-x",
        "turns": [
            {"q": "转专业需要满足什么条件？",
             "expect_docs": ["转专业实施办法.docx"], "expect_keywords": ["转专业"]},
            {"q": "那具体要走什么流程？",
             "expect_docs": ["转专业实施办法.docx"], "expect_keywords": []},
        ],
    }
    report = asyncio.run(
        run_eval.run_multi_turn_cases([case], kb_id="kb", use_judge=False,
                                      results_dir=tmp_path, tag="t")
    )
    assert calls == [("转专业需要满足什么条件？", "kb"),
                     ("那具体要走什么流程？", "kb")]
    # 首轮命中、追问未命中 → 平均 Hit@3 = 0.5
    assert report["hit_at3_rate"] == 0.5


def test_judge_skipped_when_mock_provider(monkeypatch, tmp_path):
    # 真实 provider 判定链路：conftest 强制 LLM_PROVIDER=mock → _judge_enabled() 必须 False
    assert run_eval._judge_enabled() is False
    _patch_flow(monkeypatch, [(
        "答案", [{"doc_name": "国家助学金评审办法.docx"}])])
    report = asyncio.run(
        run_eval.run_single_cases([_mk_case()], kb_id="kb",
                                  use_judge=run_eval._judge_enabled(),
                                  results_dir=tmp_path, tag="t")
    )
    assert report["judge_rate"] is None
    # 结果文件已写出且 judge_rate 为 null
    files = list(tmp_path.glob("*.json"))
    assert files and json.loads(files[0].read_text(encoding="utf-8"))["judge_rate"] is None


def test_results_written_to_disk(monkeypatch, tmp_path):
    _patch_flow(monkeypatch, [(
        "有", [{"doc_name": "国家助学金评审办法.docx"}])])
    asyncio.run(
        run_eval.run_single_cases([_mk_case()], kb_id="kb", use_judge=False,
                                  results_dir=tmp_path, tag="baseline")
    )
    js = list(tmp_path.glob("*-baseline-single_turn.json"))
    md = list(tmp_path.glob("*-baseline-single_turn.md"))
    assert js and md
    payload = json.loads(js[0].read_text(encoding="utf-8"))
    assert payload["tag"] == "baseline"
    assert "hit_at3_rate" in payload


def test_case_flow_error_recorded_and_run_continues(monkeypatch, tmp_path):
    """单 case 失败不拖垮整轮：记录 error、速率只按成功 case 计、报告仍落盘。"""
    async def fake_flow(question, kb_id):
        if "失败" in question:
            raise RuntimeError("provider boom")
        return {"answer": "申请助学金需在系统提交",
                "sources": [{"doc_name": "国家助学金评审办法.docx"}]}

    monkeypatch.setattr(run_eval, "run_rag_flow", fake_flow)
    cases = [_mk_case(cid="ok"), _mk_case(cid="bad", q="这里会失败？")]
    report = asyncio.run(
        run_eval.run_single_cases(cases, kb_id="kb", use_judge=False,
                                  results_dir=tmp_path, tag="t")
    )
    # 报告仍生成
    assert list(tmp_path.glob("*.json")) and list(tmp_path.glob("*.md"))
    ok, bad = report["cases"]
    assert ok["hit_at3"] is True and ok["keyword"] is True and "error" not in ok
    assert bad["hit_at3"] is None and bad["keyword"] is None and bad["judge"] is None
    assert bad["sources"] == [] and bad["answer"] == ""
    assert "provider boom" in bad["error"]
    # 速率只按成功 case 计，失败 case 被剔除
    assert report["hit_at3_rate"] == 1.0
    assert report["keyword_rate"] == 1.0


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
