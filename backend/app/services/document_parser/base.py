"""文档解析器协议。所有解析器同步 CPU 密集，调用方用 asyncio.to_thread 包装。"""
from abc import ABC, abstractmethod


class DocumentParser(ABC):
    @abstractmethod
    def parse(self, file_path: str) -> str:
        """从文件提取纯文本。失败抛异常由上层转为 failed 状态。"""
