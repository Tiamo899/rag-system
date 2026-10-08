# backend/tests/test_governance_prompt.py
"""机制三：context 时效标注与多来源提示。纯节点测试，无需容器。"""
import asyncio

from app.services.rag.langgraph import nodes


def _chunk(doc_id, doc_name, content, version_no=None, valid_from=None, score=0.95):
    # score 0.95：高于 relevance_threshold 的任何配置值（0.02/0.30），
    # 保证走 rrf_ok 分支、无需 embedding provider
    return {
        "doc_id": doc_id, "doc_name": doc_name, "title": None,
        "content": content, "score": score, "content_vector": None,
        "version_no": version_no, "valid_from": valid_from,
    }


def test_context_line_carries_version_and_validity():
    chunks = [_chunk("d1", "学籍管理规定.docx", "旧规内容",
                     version_no="2023 版", valid_from="2023-09-01")]
    state = {"question": "q", "retrieved_chunks": chunks}
    out = asyncio.run(nodes.evaluate_node(state))
    assert out["has_relevant_content"] is True
    line = out["context"]
    assert "《学籍管理规定.docx》" in line
    assert "2023 版" in line
    assert "生效2023-09-01" in line
    assert "旧规内容" in line


def test_context_without_meta_unchanged_format():
    chunks = [_chunk("d1", "单文档.md", "普通内容")]
    out = asyncio.run(nodes.evaluate_node(
        {"question": "q", "retrieved_chunks": chunks}
    ))
    assert out["context"] == "[1] 《单文档.md》：普通内容"
    assert "提示" not in out["context"]


def test_multi_source_notice_appended():
    chunks = [
        _chunk("d1", "A办法.docx", "甲规定"),
        _chunk("d2", "B办法.docx", "乙规定"),
    ]
    out = asyncio.run(nodes.evaluate_node(
        {"question": "q", "retrieved_chunks": chunks}
    ))
    assert "资料来自多份文档" in out["context"]
    assert "生效日期较新者为准" in out["context"]


def test_single_source_no_notice_even_with_two_chunks():
    chunks = [
        _chunk("d1", "同文档.md", "甲"),
        _chunk("d1", "同文档.md", "乙"),
    ]
    out = asyncio.run(nodes.evaluate_node(
        {"question": "q", "retrieved_chunks": chunks}
    ))
    assert "资料来自多份文档" not in out["context"]


def test_mock_parses_meta_header_and_skips_notice():
    """机制三兼容 mock provider：标注行按块头解析、提示行不进回答。"""
    import asyncio as _a

    from app.services.llm.mock import MockLLM

    prompt = (
        "[1] 《学籍管理规定》（2023 版，生效2023-09-01）：旧规内容\n"
        "[2] 《B办法》：乙规定\n"
        "\n[提示] 以上资料来自多份文档，若规定不一致，请指出差异并以生效日期较新者为准。"
        "\n\n问题：测试问题"
    )
    answer = _a.run(MockLLM().generate(prompt))
    assert "[提示]" not in answer, "提示行不应被 mock 引用进回答"
    assert "（2023 版，生效2023-09-01）" not in answer, "原始标注行不应被当正文引用"
    assert "学籍管理规定" in answer, "标注后的标题应仍被识别为块头"
