"""Mock Embedding：确定性 hash-ngram 向量。

核心设计（勿改成纯随机）：
- 对文本做字符 2-gram/3-gram 特征哈希，累计到 dims 维再 L2 归一化
- 保证「同文本同向量、相似文本余弦可分」，让检索和相关性评估有真实信号
- 纯随机向量会丢失语义，检索演示与阈值判断全部失效
"""
import asyncio
import hashlib
import math

from app.services.embedding.base import BaseEmbedding


class MockEmbedding(BaseEmbedding):
    def __init__(self, dims: int = 1536):
        super().__init__(dims)

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(self._embed_sync, texts)

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dims
        for n in (2, 3):
            for i in range(len(text) - n + 1):
                gram = text[i:i + n]
                digest = hashlib.sha256(gram.encode("utf-8")).digest()
                idx = int.from_bytes(digest[:4], "big") % self.dims
                sign = 1.0 if digest[4] & 1 else -1.0
                vec[idx] += sign

        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec
