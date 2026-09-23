"""PDF 解析：pdfplumber 逐页抽取，空结果回退 pypdf。仅支持文本型 PDF。"""
from app.services.document_parser.base import DocumentParser


class PDFParser(DocumentParser):
    def parse(self, file_path: str) -> str:
        text = self._with_pdfplumber(file_path)
        if text and text.strip():
            return text
        return self._with_pypdf(file_path)

    def _with_pdfplumber(self, file_path: str) -> str:
        import pdfplumber

        parts: list[str] = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                parts.append(page.extract_text() or "")
        return "\n".join(parts)

    def _with_pypdf(self, file_path: str) -> str:
        from pypdf import PdfReader

        reader = PdfReader(file_path)
        parts: list[str] = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        return "\n".join(parts)
