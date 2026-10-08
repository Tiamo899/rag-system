"""Mock LLM：基于编号资料拼装回答，回填 [n] 引用标记。

prompt 约定（由 generate 节点构造，每个块可跨多行）：
    [1] 《奖学金评定办法》（可选版本/生效标注）：申请条件…
        - 评定年度内无不及格课程
    [2] 《选课管理办法》：学分要求…

    问题：<问题>
"""
import re

from app.services.llm.base import BaseLLM

FALLBACK_TEXT = "未在知识库中找到相关内容，请换个问法或联系教务老师补充资料。"
_HEADER_RE = re.compile(r"^\[\d+\]\s*《([^》]*)》(?:（[^）]*）)?[：:]\s?(.*)$")
_MAX_QUOTE = 300


def _parse_blocks(prompt: str) -> list[tuple[str | None, str]]:
    """逐行解析：块以 [n] 《标题》： 开头，延续到下一个块头或「问题」行。"""
    blocks: list[tuple[str | None, str]] = []
    current_title: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_title, current_lines
        content = "\n".join(current_lines).strip()
        if content:
            blocks.append((current_title, content))
        current_title, current_lines = None, []

    for line in prompt.splitlines():
        if line.strip().startswith("问题"):
            flush()
            break
        if line.startswith("[提示]"):
            continue  # 冲突提示行不是块头也不是引用内容，不进 mock 回答
        m = _HEADER_RE.match(line)
        if m:
            flush()
            current_title = m.group(1).strip()
            first = m.group(2).strip()
            current_lines = [first] if first else []
        else:
            current_lines.append(line)
    flush()
    return blocks


class MockLLM(BaseLLM):
    async def generate(self, user_prompt: str, temperature: float = 0.3) -> str:
        # temperature 仅协议兼容，Mock 输出确定性，忽略
        blocks = _parse_blocks(user_prompt)
        if not blocks:
            return FALLBACK_TEXT

        def quote(content: str) -> str:
            # 标题已由《》标注，去掉正文开头的 markdown 标题行，避免重复
            lines = content.splitlines()
            while lines and re.match(r"^\s*#{1,6}\s+", lines[0]):
                lines.pop(0)
            text = "\n".join(lines).strip()
            return text if len(text) <= _MAX_QUOTE else text[:_MAX_QUOTE] + "……"

        lines: list[str] = []
        for i, (title, content) in enumerate(blocks[:3], start=1):
            tag = f"[{i}]（《{title}》）" if title else f"[{i}]"
            lines.append(f"根据知识库资料{tag}中的内容：\n{quote(content)}")

        return "\n\n".join(lines)
