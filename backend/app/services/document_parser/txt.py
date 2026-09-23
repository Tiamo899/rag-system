"""TXT 解析：优先 UTF-8，失败回退 GBK（中文 Windows 常见编码）。"""
from pathlib import Path

from app.services.document_parser.base import DocumentParser


class TxtParser(DocumentParser):
    def parse(self, file_path: str) -> str:
        path = Path(file_path)
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return path.read_text(encoding="gbk", errors="replace")
