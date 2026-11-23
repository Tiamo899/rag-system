"""分块合并与检索后处理（邻块扩展 / 来源去重）的回归测试。

覆盖三个容易回退的点：
1. 同一章内的短小节必须合并到下限以上，否则政策文档会退回「一个条款一块」；
2. 合并不跨一级标题，避免把无关章节拼到一起；
3. 邻块扩展在 ES 不可用时必须 fail-soft 返回原分块，不能拖垮问答链路。
"""
import pytest

from app.services.chunking.splitter import split_text
from app.services.search.postprocess import (
    diversify,
    expand_with_neighbors,
    strip_boilerplate,
)


def _md(*sections: str) -> str:
    return "\n".join(sections)


def test_short_sections_merged_under_same_chapter():
    tiny = "\n".join(
        f"### 第{i}条 事项{i}\n本条规定第{i}类事项的办理流程与所需材料，具体以窗口要求为准。"
        for i in range(1, 6)
    )
    text = _md("# 学生手册", "## 第一章 总则", tiny)
    chunks = split_text(text, chunk_size=500, strategy="markdown")  # 2000 字符上限
    assert len(chunks) < 6, "短小节应被合并，不应逐条成块"
    for c in chunks:
        assert len(c) >= 300 or len(text) < 300


def test_merge_never_crosses_top_level_heading():
    a = "## 第一章 总则\n" + "本章说明制定依据。" * 3
    b = "## 第二章 申报\n" + "本章说明申报条件。" * 3
    text = _md("# 甲办法", a, "# 乙办法", b)
    chunks = split_text(text, chunk_size=500, strategy="markdown")
    joined_in_one = [
        c for c in chunks if "第一章 总则" in c and "第二章 申报" in c
    ]
    # 跨「甲办法 / 乙办法」的块必然跨章，必须不存在
    assert not joined_in_one


def test_diversify_caps_same_document():
    chunks = [{"doc_id": "A", "content": str(i)} for i in range(5)] + [
        {"doc_id": "B", "content": "b"}
    ]
    picked = diversify(chunks, limit=3, max_per_doc=2)
    assert len(picked) == 3
    assert sum(1 for c in picked if c["doc_id"] == "A") == 2
    assert any(c["doc_id"] == "B" for c in picked)


def test_diversify_pads_when_not_enough_docs():
    chunks = [{"doc_id": "A", "content": str(i)} for i in range(4)]
    picked = diversify(chunks, limit=3, max_per_doc=2)
    assert len(picked) == 3
    # 同样文档不足时按原顺序补齐，不丢召回结果
    assert [c["content"] for c in picked] == ["0", "1", "2"]


def test_diversify_respects_char_budget():
    chunks = [{"doc_id": d, "content": "x" * 1000} for d in ("A", "B", "C")]
    picked = diversify(chunks, limit=3, max_per_doc=2, budget_chars=2200)
    # 前两条已接近预算，第三条必须被挡掉，不能把上下文堆到 3000 字
    assert len(picked) == 2


def test_strip_boilerplate():
    text = "# 标题\n本文档为通用示例文档，用于演示，不代表任何学校。\n正文条款"
    assert strip_boilerplate(text) == "# 标题\n正文条款"


@pytest.mark.asyncio
async def test_expand_fail_soft_when_es_unavailable(monkeypatch):
    def boom():
        raise RuntimeError("es down")

    monkeypatch.setattr("app.services.search.postprocess.get_es", boom)
    chunks = [{"doc_id": "A", "chunk_index": 1, "content": "原文"}]
    out = await expand_with_neighbors(chunks)
    assert out == chunks


@pytest.mark.asyncio
async def test_expand_reads_chunk_index_from_metadata(monkeypatch):
    """回归：chunk_index 只在 metadata 里，读顶层会全落成 0，把最后一块当上文重复拼入。"""

    class FakeES:
        async def search(self, **_kwargs):
            return {
                "hits": {
                    "hits": [
                        {
                            "_id": "d:0",
                            "_source": {
                                "doc_id": "A",
                                "content": "第零段",
                                "metadata": {"chunk_index": 0},
                            },
                        },
                        {
                            "_id": "d:1",
                            "_source": {
                                "doc_id": "A",
                                "content": "第一段",
                                "metadata": {"chunk_index": 1},
                            },
                        },
                        {
                            "_id": "d:2",
                            "_source": {
                                "doc_id": "A",
                                "content": "第二段",
                                "metadata": {"chunk_index": 2},
                            },
                        },
                    ]
                }
            }

    monkeypatch.setattr("app.services.search.postprocess.get_es", lambda: FakeES())
    out = await expand_with_neighbors([{"doc_id": "A", "chunk_index": 1, "content": "第一段"}])
    assert "第零段" in out[0]["content"]
    assert "第二段" in out[0]["content"]
    assert out[0]["content"].count("第一段") == 1  # 不允许把自身当邻块重复拼


@pytest.mark.asyncio
async def test_expand_adds_neighbors_within_budget(monkeypatch):
    class FakeES:
        async def search(self, **_kwargs):
            return {
                "hits": {
                    "hits": [
                        {"_source": {"doc_id": "A", "chunk_index": 0, "content": "上一段"}},
                        {"_source": {"doc_id": "A", "chunk_index": 1, "content": "本段"}},
                        {"_source": {"doc_id": "A", "chunk_index": 2, "content": "下一段"}},
                    ]
                }
            }

    monkeypatch.setattr("app.services.search.postprocess.get_es", lambda: FakeES())
    out = await expand_with_neighbors(
        [{"doc_id": "A", "chunk_index": 1, "content": "本段"}]
    )
    assert len(out) == 1
    assert "上一段" in out[0]["content"] and "下一段" in out[0]["content"]
    assert out[0]["expanded"] is True
