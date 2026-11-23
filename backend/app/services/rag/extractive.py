"""大模型不可用时的抽取式兜底作答。

设计取舍：宁可给"有出处但不流畅"的原文摘录，也不要给"报错"或"编造"。
  - 内容只从已检索到的 context 中摘取，不新增任何事实；
  - 保留 [n] 编号，与线上引用溯源规则一致；
  - 明确标注当前为抽取式模式，避免被误认为模型生成结果。
"""
import re

_LINE_RE = re.compile(r"\[(\d+)\] 《([^》]+)》(?:（([^）]*)）)?：")
_NOTICE_RE = re.compile(r"\[提示\][^\n]*")


def _blocks(context: str) -> list[tuple[str, str, str, str]]:
    """把拼接好的 context 还原成 (编号, 标题, 元信息, 正文) 列表。"""
    found = []
    matches = list(_LINE_RE.finditer(context))
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(context)
        body = context[start:end]
        body = _NOTICE_RE.sub("", body).strip()
        found.append((m.group(1), m.group(2), m.group(3) or "", body))
    return found


def _first_sentences(text: str, limit: int = 110) -> str:
    text = re.sub(r"^#+\s*", "", text.strip())
    text = re.sub(r"\s+", " ", text)
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for sep in ("。", "；", "，"):
        idx = cut.rfind(sep)
        if idx > limit // 2:
            return cut[: idx + 1]
    return cut + "…"


def build_extractive_answer(question: str, context: str, max_chunks: int = 3) -> str:
    items = _blocks(context or "")
    if not items:
        return ""

    head = f"根据知识库检索到的资料，关于“{question}”，相关原文摘录如下："
    lines = [head, ""]
    for no, title, meta, body in items[:max_chunks]:
        brief = _first_sentences(body)
        # 正文首行常是「## 第三章 申请条件」这类与标题重复的小节名，去掉避免重复
        if brief.startswith(title):
            brief = _first_sentences(brief[len(title):], 110) or brief
        suffix = f"（{meta}）" if meta else ""
        lines.append(f"[{no}] 《{title}》{suffix}：{brief}")
        lines.append("")
    lines.append(
        "（说明：大模型服务当前不可用，以上为检索原文的抽取式摘录，未经过语言组织，"
        "请以条款原文为准；服务恢复后会自动切换回生成式作答。）"
    )
    return "\n".join(lines)
