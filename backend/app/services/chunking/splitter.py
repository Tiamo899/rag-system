"""文本分块：固定长度(优先段落边界) / markdown 按标题层级并合并过短小节。

无独立 tokenizer，用 4 字符 ≈ 1 token 的近似（未来接真实 tokenizer 只改这里）。

markdown 策略的两个要点：
1. 先按标题切小节，再在同一一级章节内把过短小节合并到 min_chars 以上，
   避免「一个条款一块」把检索粒度打得太碎（政策类文档标题极密，逐标题切会
   产生大量一两句话的碎片，限定条件被切到邻块）。
2. 合并只在同一一级标题内进行，不跨章节拼接，保持语义边界清晰。
"""
import re

CHARS_PER_TOKEN = 4  # 近似值
_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+)")


def split_text(
    text: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
    strategy: str = "fixed",
) -> list[str]:
    size_chars = max(chunk_size * CHARS_PER_TOKEN, 100)
    overlap_chars = chunk_overlap * CHARS_PER_TOKEN

    if strategy == "markdown":
        chunks = _split_markdown(text, size_chars, _min_chars(size_chars))
    else:
        chunks = _split_fixed(text, size_chars, overlap_chars)

    return [c.strip() for c in chunks if c and c.strip()]


def _min_chars(size: int) -> int:
    """合并下限：块长目标约为上限的 35%（500 tokens≈2000 字符 → 约 700 字符）。"""
    return max(int(size * 0.35), 300)


def derive_title(chunk: str, index: int) -> str:
    """给分块生成一个可读标题。markdown 用首个标题；其他用首行摘要。"""
    lines = [l.strip() for l in chunk.splitlines() if l.strip()]
    if lines:
        m = _HEADING_RE.match(lines[0])
        if m:
            return m.group(2).strip()
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


def _parse_sections(text: str) -> list[tuple[str, str]]:
    """把 markdown 拆成 (一级标题, 小节正文) 序列，正文含本节标题行。

    只有标题、正文在下一级标题的「空壳小节」直接丢弃，避免产生无正文的块。
    """
    sections: list[tuple[str, str]] = []
    buf: list[str] = []
    root = ""
    has_body = False
    stack: list[tuple[int, str]] = []

    def flush() -> None:
        nonlocal buf, has_body
        if buf and has_body:
            sections.append((root, "\n".join(buf).strip()))
        buf, has_body = [], False

    for line in text.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            flush()
            level, title = len(m.group(1)), m.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            root = stack[0][1] if stack else title
            buf, has_body = [line.strip()], False
            continue
        if not buf:
            if line.strip():
                buf, has_body = [line], True
            continue
        buf.append(line)
        if line.strip():
            has_body = True
    flush()
    return sections


def _split_markdown(text: str, size: int, min_chars: int = 300) -> list[str]:
    """按标题切小节后，同一章内合并到 min_chars 以上；超长小节再按段落切。"""
    chunks: list[str] = []
    pending = ""
    pending_root = ""

    for root, body in _parse_sections(text):
        if pending and root != pending_root:
            chunks.append(pending)
            pending, pending_root = "", ""

        if not pending:
            if len(body) >= min_chars:
                if len(body) <= size:
                    chunks.append(body)
                else:
                    chunks.extend(_split_fixed(body, size, size // 5))
            else:
                pending, pending_root = body, root
            continue

        if len(pending) + 2 + len(body) <= size:
            pending = f"{pending}\n\n{body}"
            if len(pending) >= min_chars:
                chunks.append(pending)
                pending, pending_root = "", ""
        else:
            chunks.append(pending)
            pending, pending_root = "", ""
            if len(body) <= size:
                pending, pending_root = body, root
            else:
                chunks.extend(_split_fixed(body, size, size // 5))

    if pending:
        chunks.append(pending)

    return _merge_tiny(chunks, size, min_chars // 2)


def _merge_tiny(chunks: list[str], size: int, floor: int) -> list[str]:
    """收尾合并：小于 floor 的孤块并入**前一块**，避免出现「附则一句话」这种碎片。

    只向前合并不向后：向后合会跨过一级标题边界，把甲章节的尾巴拼到乙章节头上。
    """
    if not chunks:
        return []
    out: list[str] = [chunks[0]]
    for c in chunks[1:]:
        # 并入前一块的前提：前一块本身已经够长（说明它是正常块，不是在连环吞碎片）
        if (
            len(c) < floor
            and len(out[-1]) >= floor
            and len(out[-1]) + 2 + len(c) <= size
        ):
            out[-1] = f"{out[-1]}\n\n{c}"
        else:
            out.append(c)
    return out
