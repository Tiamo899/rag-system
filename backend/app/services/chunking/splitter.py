"""文本分块：固定长度(优先段落边界) / markdown 按标题层级。

无独立 tokenizer，用 4 字符 ≈ 1 token 的近似（未来接真实 tokenizer 只改这里）。
"""
import re

CHARS_PER_TOKEN = 4  # 近似值
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+)")


def split_text(
    text: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
    strategy: str = "fixed",
) -> list[str]:
    size_chars = max(chunk_size * CHARS_PER_TOKEN, 100)
    overlap_chars = chunk_overlap * CHARS_PER_TOKEN

    if strategy == "markdown":
        chunks = _split_markdown(text, size_chars)
    else:
        chunks = _split_fixed(text, size_chars, overlap_chars)

    return [c.strip() for c in chunks if c and c.strip()]


def derive_title(chunk: str, index: int) -> str:
    """给分块生成一个可读标题。markdown 用首个标题；其他用首行摘要。"""
    lines = [l.strip() for l in chunk.splitlines() if l.strip()]
    if lines:
        m = _HEADING_RE.match(lines[0])
        if m:
            return m.group(1).strip()
        return lines[0][:20]
    return f"第 {index + 1} 段"


def _split_fixed(text: str, size: int, overlap: int) -> list[str]:
    """按空行段落预分，合并到 size；单段超长再硬切；重叠窗口取上一块尾部。"""
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    if not paragraphs:
        return []

    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 2 <= size:
            current = f"{current}\n\n{para}" if current else para
            continue
        if current:
            chunks.append(current)
        if len(para) <= size:
            current = para
        else:
            # 单段超长：硬切 + 重叠
            start = 0
            while start < len(para):
                piece = para[start:start + size]
                chunks.append(piece)
                start += size - overlap
            current = ""
    if current:
        chunks.append(current)

    if overlap > 0 and len(chunks) > 1:
        merged: list[str] = []
        for i, c in enumerate(chunks):
            if i > 0 and len(c) < size // 3:
                # 尾部小段并入前一块，减少碎片
                merged[-1] = f"{merged[-1]}\n\n{c}"
            else:
                merged.append(c)
        chunks = merged

    return chunks


def _split_markdown(text: str, size: int) -> list[str]:
    """按 #/##/### 标题切块：每个标题及下属内容成一块，超长再按段落切。"""
    lines = text.splitlines()
    sections: list[list[str]] = []
    current: list[str] = []

    heading_re = re.compile(r"^\s{0,3}#{1,6}\s+")

    for line in lines:
        if heading_re.match(line) and current:
            sections.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append(current)

    chunks: list[str] = []
    for section in sections:
        body = "\n".join(section).strip()
        if not body:
            continue
        # 只有标题、无正文的段（如《学生手册》仅含标题，正文在下级标题）跳过，避免空分块
        body_lines = [l for l in body.splitlines() if not heading_re.match(l)]
        if not any(l.strip() for l in body_lines):
            continue
        if len(body) <= size:
            chunks.append(body)
        else:
            chunks.extend(_split_fixed(body, size, size // 5))
    return chunks
