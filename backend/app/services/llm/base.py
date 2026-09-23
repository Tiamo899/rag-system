"""LLM 协议。未来接真实模型（OpenAI/本地）只需实现本接口并注册到 factory。"""
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class BaseLLM(ABC):
    @abstractmethod
    async def generate(self, user_prompt: str) -> str:
        """基于 prompt 生成回答。RAG 场景的 system 提示词由实现内部固定。"""

    async def generate_stream(self, user_prompt: str) -> AsyncIterator[str]:
        """流式生成：默认整体生成后一次 yield（MockLLM 等同步实现零改动）。"""
        yield await self.generate(user_prompt)
