"""评测指标纯函数：Hit@3 / 关键词判定 / 裁判输出解析。"""


def hit_at3(sources: list[dict], expect_docs: list[str]) -> bool:
    """top-3 来源文档命中任一期望文档。sources 元素含 doc_name。"""
    names = {s.get("doc_name") for s in sources}
    return any(d in names for d in expect_docs)


def keyword_verdict(
    answer: str, expect_keywords: list[str], forbidden_keywords: list[str]
) -> bool:
    """forbidden 任一命中 → False；否则 expect 任一命中 → True；expect 为空 → False。"""
    if any(k in answer for k in forbidden_keywords):
        return False
    if not expect_keywords:
        return False
    return any(k in answer for k in expect_keywords)


def parse_judge(text: str) -> int:
    """裁判输出 → 0/1。首字符为 '1' 判 1，否则 0。"""
    return 1 if text.strip().startswith("1") else 0
