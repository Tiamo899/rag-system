# backend/tests/test_eval_setup.py
"""setup_dataset 纯函数测试（语料发现/已有库识别），不建真库。"""
from evals.setup_dataset import discover_corpus, find_eval_kb


def test_discover_corpus_counts():
    files = discover_corpus()
    names = [p.name for p in files]
    assert sum(1 for n in names if n.endswith(".docx")) == 20
    assert sum(1 for n in names if n.endswith(".md")) == 2
    assert "请假管理办法_2023版.md" in names
    assert "请假管理办法_2024版.md" in names


def test_discover_corpus_sorted_and_unique():
    files = discover_corpus()
    assert files == sorted(files)
    assert len(set(files)) == len(files)


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, payload):
        self._payload = payload

    def get(self, url, params=None, headers=None):
        return _FakeResp(self._payload)


def test_find_eval_kb_found():
    client = _FakeClient([{"id": "kb-1", "name": "评测库"}])
    kb = find_eval_kb(client, {})
    assert kb and kb["id"] == "kb-1"


def test_find_eval_kb_absent():
    client = _FakeClient([])
    assert find_eval_kb(client, {}) is None
