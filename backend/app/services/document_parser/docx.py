"""Word 解析：按正文顺序输出段落与表格，标题转成 markdown 层级标记。

这样下游分块器可复用 markdown 的「按标题分块」策略，标题即分块标题。
支持样式名：Heading 1/2/3… 或中文本地化「标题 1/2/3…」。
"""
import re

from docx import Document as DocxDocument
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.services.document_parser.base import DocumentParser

_HEADING_LEVEL_RE = re.compile(r"(?:Heading|标题)\s*(\d+)")


class WordParser(DocumentParser):
    def parse(self, file_path: str) -> str:
        doc = DocxDocument(file_path)
        lines: list[str] = []
        for child in doc.element.body.iterchildren():
            if child.tag == qn("w:p"):
                para = Paragraph(child, doc)
                text = para.text.strip()
                if not text:
                    continue
                m = _HEADING_LEVEL_RE.search(para.style.name)
                if m:
                    level = min(int(m.group(1)), 6)
                    lines.append("#" * level + " " + text)
                else:
                    lines.append(text)
            elif child.tag == qn("w:tbl"):
                table = Table(child, doc)
                for row in table.rows:
                    cells = [c.text.replace("\n", " ").strip() for c in row.cells]
                    # 去重合并单元格产生的重复（按文本+位置粗略去重）
                    deduped: list[str] = []
                    for cell in cells:
                        if not deduped or cell != deduped[-1]:
                            deduped.append(cell)
                    lines.append(" | ".join(c for c in deduped if c))
        return "\n".join(lines)
