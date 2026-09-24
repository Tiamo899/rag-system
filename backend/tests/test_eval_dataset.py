"""数据集 schema 校验：字段齐全、文件名存在于语料、JSONL 可逐行解析。"""
import json
from pathlib import Path

DATASET = Path(__file__).resolve().parents[1] / "evals" / "dataset"
DOCS = Path(__file__).resolve().parents[1] / "evals" / "docs"
CORPUS = Path(__file__).resolve().parents[1].parent / "knowledge_base_docs_campus"


def _load(name):
    lines = (DATASET / name).read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_single_turn_schema():
    cases = _load("single_turn.jsonl")
    assert len(cases) >= 10
    for c in cases:
        assert c["id"] and c["question"]
        assert c["expect_docs"], f"{c['id']} 缺 expect_docs"
        assert c["expect_keywords"], f"{c['id']} 缺 expect_keywords"


def test_multi_turn_schema():
    cases = _load("multi_turn.jsonl")
    assert len(cases) >= 3
    for c in cases:
        assert c["id"] and len(c["turns"]) >= 2
        for t in c["turns"]:
            assert t["q"] and t["expect_docs"]
            assert "expect_keywords" in t, f"{c['id']} turns 缺 expect_keywords"


def test_governance_schema():
    cases = _load("governance.jsonl")
    assert len(cases) >= 2
    for c in cases:
        assert c["id"] and c["question"]
        assert c["expect_docs"] and c["expect_keywords"]
        assert c["forbidden_keywords"], f"{c['id']} 缺 forbidden_keywords"


def test_expect_docs_exist_in_corpus():
    """所有 expect_docs 必须是真实存在的语料文件名，防止手误。"""
    names = {p.name for p in CORPUS.rglob("*.docx")}
    names |= {p.name for p in DOCS.glob("*.md")}
    for name in ("single_turn.jsonl", "multi_turn.jsonl", "governance.jsonl"):
        for c in _load(name):
            if "turns" in c:  # multi_turn 的 expect_docs 嵌在各 turn 里
                docs = [d for t in c["turns"] for d in t["expect_docs"]]
            else:
                docs = c["expect_docs"]
            for d in docs:
                assert d in names, f"{c['id']} 的 expect_docs 不存在: {d}"


def test_governance_docs_have_conflicting_numbers():
    old = (DOCS / "请假管理办法_2023版.md").read_text(encoding="utf-8")
    new = (DOCS / "请假管理办法_2024版.md").read_text(encoding="utf-8")
    assert "3天" in old and "5天" not in old
    assert "5天" in new and "3天" not in new
