"""解析器工厂：按扩展名分派。"""
from app.services.document_parser.base import DocumentParser
from app.services.document_parser.docx import WordParser
from app.services.document_parser.markdown import MarkdownParser
from app.services.document_parser.pdf import PDFParser
from app.services.document_parser.txt import TxtParser

# file_type 值取自 DB 字段（pdf/word/markdown/txt）
_PARSERS: dict[str, DocumentParser] = {
    "pdf": PDFParser(),
    "word": WordParser(),
    "markdown": MarkdownParser(),
    "txt": TxtParser(),
}

# 上传扩展名 → file_type
EXTENSION_TO_TYPE: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "word",
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "txt",
}


def get_parser(file_type: str) -> DocumentParser:
    if file_type not in _PARSERS:
        raise ValueError(f"不支持的文档类型: {file_type}")
    return _PARSERS[file_type]


def file_type_from_name(filename: str) -> str:
    ext = filename.lower().rsplit(".", 1)[-1]
    ext = "." + ext if ext != filename.lower() else ""
    if ext not in EXTENSION_TO_TYPE:
        raise ValueError(f"不支持的格式: {ext or '无扩展名'}，仅支持 pdf/docx/md/txt")
    return EXTENSION_TO_TYPE[ext]
