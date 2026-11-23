"""LangGraph RAG 状态定义。节点只返回要更新的字段，key 必须与这里一致。"""
from typing import Optional, TypedDict


class RAGState(TypedDict, total=False):
    question: str                  # 用户问题
    kb_id: Optional[str]           # 目标知识库（None=全库）
    history: list                  # 本轮之前的对话历史 [{role, content}]，最多 6 条
    standalone_query: str          # 改写后的独立问题（无历史/失败时 = question）
    is_kb_query: bool              # 分析节点：是否为知识库查询
    retrieved_chunks: list         # 检索到的分块
    has_relevant_content: bool     # 评估节点：是否有关联内容
    context: str                   # 编号后的上下文
    selected_chunks: list          # 评估节点选中的 3 条（去重后，上下文与来源同源）
    answer: str                    # 生成的回答
    sources: list                  # 引用来源
    error: str                     # 错误信息
