# backend/tests/test_eval_metrics.py
"""Phase 0 指标纯函数测试。无 I/O，无需 PG/ES。"""
from evals.metrics import hit_at3, keyword_verdict, parse_judge


def _src(name):
    return [{"doc_name": name, "content": "x", "score": 0.1}]


def test_hit_at3_match():
    assert hit_at3(_src("转专业实施办法.docx"), ["转专业实施办法.docx"])


def test_hit_at3_miss():
    assert not hit_at3(_src("图书馆指南.docx"), ["转专业实施办法.docx"])


def test_hit_at3_any_of_multiple_expectations():
    sources = _src("学生手册.docx")
    assert hit_at3(sources, ["转专业实施办法.docx", "学生手册.docx"])


def test_hit_at3_empty_sources():
    assert not hit_at3([], ["任何.docx"])


def test_keyword_verdict_any_keyword_passes():
    assert keyword_verdict("补考不过可以申请重修，最多两次", ["重修"], [])


def test_keyword_verdict_no_keyword_fails():
    assert not keyword_verdict("答案未提及要点", ["重修"], [])


def test_keyword_verdict_forbidden_wins():
    # 即使新旧数字都在，含旧版数字也判负
    assert not keyword_verdict(
        "2023版3天，2024版5天", ["5天"], ["3天"]
    )


def test_keyword_verdict_forbidden_without_expectations():
    assert not keyword_verdict("最多3天", [], ["3天"])


def test_parse_judge_numeric():
    assert parse_judge("1") == 1
    assert parse_judge("0") == 0
    assert parse_judge("1\n回答切题且正确\n理由……") == 1  # 首字符 1（裁判先输出 1 再附解释）
    assert parse_judge("错误答案以 0 开头不行……") == 0  # 非 1 开头 → 0
