"""LangGraph RAG 状态定义。节点只返回要更新的字段，key 必须与这里一致。"""
from typing import Optional, TypedDict


class RAGState(TypedDict, total=False):
    question: str                  # 用户问题
    kb_id: Optional[str]           # 目标知识库（None=全库）
    is_kb_query: bool              # 分析节点：是否为知识库查询
    retrieved_chunks: list         # 检索到的分块
    has_relevant_content: bool     # 评估节点：是否有关联内容
    context: str                   # 编号后的上下文
    answer: str                    # 生成的回答
    sources: list                  # 引用来源
    error: str                     # 错误信息
