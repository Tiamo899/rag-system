"""Embedding 协议。未来接 OpenAI/BGE 只需实现本接口并注册到 factory。"""
from abc import ABC, abstractmethod


class BaseEmbedding(ABC):
    def __init__(self, dims: int):
        self.dims = dims

    @abstractmethod
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """批量嵌入，返回 list[list[float]]，每个向量长度必须等于 self.dims。"""
