"""Markdown 解析：直接读取 UTF-8 文本。"""
from pathlib import Path

from app.services.document_parser.base import DocumentParser


class MarkdownParser(DocumentParser):
    def parse(self, file_path: str) -> str:
        return Path(file_path).read_text(encoding="utf-8", errors="replace")
