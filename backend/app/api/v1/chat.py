"""智能问答接口：会话 CRUD + 发送消息（SSE 流式）。"""
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.core.config import get_settings
from app.core.deps import get_current_user, require_permission
from app.core.exceptions import AppError, ForbiddenError, NotFoundError
from app.db.session import AsyncSessionLocal, get_db
from app.models import ChatMessage, ChatSession, User
from app.schemas.chat import (
    ChatFeedbackRequest,
    ChatMessageOut,
    ChatSendRequest,
    ChatSessionCreate,
    ChatSessionOut,
)
from app.services.access import ensure_kb_visible, visible_kb_ids
from app.services.llm.factory import get_llm_provider
from app.services.rag.extractive import build_extractive_answer
from app.services.rag.langgraph.graph import prepare_rag

router = APIRouter(prefix="/chat", tags=["chat"])


def _current_model_name() -> str:
    """落库的模型名：provider=openai 用真实模型名，否则 mock。"""
    settings = get_settings()
    return settings.llm_model if settings.llm_provider == "openai" else "mock"


async def _get_session(
    db: AsyncSession, session_id: uuid.UUID, user: User
) -> ChatSession:
    session = await db.get(ChatSession, session_id)
    if session is None:
        raise NotFoundError("会话不存在")
    if session.user_id != user.id:
        raise ForbiddenError("无权访问该会话")
    return session


async def _get_message(db: AsyncSession, message_id: uuid.UUID) -> ChatMessage:
    msg = await db.get(ChatMessage, message_id)
    if msg is None:
        raise NotFoundError("消息不存在")
    return msg


@router.post("/sessions", response_model=ChatSessionOut, status_code=201)
async def create_session(
    body: ChatSessionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("chat:use")),
):
    if body.kb_id is not None:
        await ensure_kb_visible(db, body.kb_id, user)
    session = ChatSession(
        title=body.title or "新对话",
        user_id=user.id,
        kb_id=body.kb_id,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


@router.get("/sessions", response_model=list[ChatSessionOut])
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("chat:history")),
):
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == user.id)
        .order_by(ChatSession.updated_at.desc())
    )
    return result.scalars().all()


@router.get("/sessions/{session_id}", response_model=dict)
async def get_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("chat:history")),
):
    session = await _get_session(db, session_id, user)
    messages = (
        await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc())
        )
    ).scalars().all()
    return {
        "session": ChatSessionOut.model_validate(session),
        "messages": [ChatMessageOut.model_validate(m) for m in messages],
    }


@router.put("/sessions/{session_id}", response_model=ChatSessionOut)
async def update_session(
    session_id: uuid.UUID,
    body: ChatSessionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("chat:history")),
):
    session = await _get_session(db, session_id, user)
    if body.title is not None:
        session.title = body.title
    if body.kb_id is not None:
        await ensure_kb_visible(db, body.kb_id, user)
        session.kb_id = body.kb_id
    await db.commit()
    await db.refresh(session)
    return session


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("chat:history")),
):
    session = await _get_session(db, session_id, user)
    await db.delete(session)  # 级联删除消息
    await db.commit()


@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: uuid.UUID,
    body: ChatSendRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("chat:use")),
):
    session = await _get_session(db, session_id, user)
    kb_id = body.kb_id or session.kb_id
    if kb_id is not None:
        await ensure_kb_visible(db, kb_id, user)
    # 检索范围收敛到当前用户可见的知识库（admin 返回 None = 不受限）
    visible_kbs = await visible_kb_ids(db, user)

    # 本轮之前的历史（近 3 轮 = 6 条）。必须在落库当前消息之前查询，
    # 否则 history 会包含当前这条问题，改写拿到自指输入。
    hist_res = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session.id)
        .order_by(ChatMessage.created_at.desc())
        .limit(6)
    )
    history = [
        {"role": m.role, "content": m.content}
        for m in reversed(hist_res.scalars().all())
    ]

    # 先落库用户消息，并刷新会话时间戳（列表按活跃度排序）
    db.add(ChatMessage(session_id=session.id, role="user", content=body.content))
    session.updated_at = datetime.now(timezone.utc)
    await db.commit()

    async def event_generator():
        yield {"event": "start", "data": json.dumps({"session_id": str(session_id)})}
        try:
            # 阶段 1：检索与评估
            yield {"event": "status", "data": json.dumps({"stage": "retrieving"})}
            plan = await prepare_rag(
                body.content,
                str(kb_id) if kb_id else None,
                history=history,
                kb_ids=visible_kbs,
            )

            if plan["mode"] == "generate":
                # 阶段 2：真实 LLM 流式输出（逐 token）；prompt 已由 prepare_rag 统一构造
                yield {"event": "status", "data": json.dumps({"stage": "thinking"})}
                llm = get_llm_provider()
                prompt = plan["prompt"]
                model_name = _current_model_name()
                answer_parts: list[str] = []
                try:
                    async for token in llm.generate_stream(prompt):
                        answer_parts.append(token)
                        yield {"event": "token", "data": json.dumps({"text": token})}
                    answer = "".join(answer_parts)
                    sources = plan["sources"]
                    # 走备用模型时，落库/前端要展示真正产出的那个模型
                    model_name = getattr(llm, "last_model", None) or model_name
                except Exception as llm_exc:  # noqa: BLE001
                    # LLM 欠费/超时/限流：不把整轮对话做成报错，降级为抽取式作答
                    degraded_answer = build_extractive_answer(
                        plan.get("question") or body.content, plan.get("context") or ""
                    )
                    if not degraded_answer:
                        raise llm_exc
                    answer_parts = []
                    step = 8
                    for i in range(0, len(degraded_answer), step):
                        answer_parts.append(degraded_answer[i:i + step])
                        yield {
                            "event": "token",
                            "data": json.dumps({"text": degraded_answer[i:i + step]}),
                        }
                    answer = degraded_answer
                    sources = plan["sources"]
                    model_name = "local-extractive"
                    yield {
                        "event": "status",
                        "data": json.dumps(
                            {"stage": "degraded", "reason": "LLM 服务不可用，已降级为原文抽取"}
                        ),
                    }
            else:
                # direct / fallback：固定文案切块模拟流式
                answer = plan["answer"] or ""
                sources = []
                step = 8
                for i in range(0, len(answer), step):
                    yield {"event": "token", "data": json.dumps({"text": answer[i:i + step]})}
                model_name = _current_model_name()

            # 落库 assistant 消息（SSE 生成器内自建会话）
            async with AsyncSessionLocal() as db2:
                msg = ChatMessage(
                    session_id=session.id,
                    role="assistant",
                    content=answer,
                    sources=sources,
                    model=model_name,
                )
                db2.add(msg)
                await db2.commit()
                await db2.refresh(msg)
                msg_id = str(msg.id)

            yield {
                "event": "done",
                "data": json.dumps(
                    {
                        "message_id": msg_id,
                        "answer": answer,
                        "sources": sources,
                        "model": model_name,
                        "degraded": model_name == "local-extractive",
                    }
                ),
            }
        except Exception as exc:  # noqa: BLE001
            yield {"event": "error", "data": json.dumps({"message": str(exc)})}

    return EventSourceResponse(event_generator())


@router.post("/messages/{message_id}/feedback", response_model=ChatMessageOut)
async def set_feedback(
    message_id: uuid.UUID,
    body: ChatFeedbackRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("chat:use")),
):
    msg = await _get_message(db, message_id)
    if msg.role != "assistant":
        raise AppError("仅可对助手消息反馈", code="INVALID_FEEDBACK", status_code=400)
    await _get_session(db, msg.session_id, user)  # 归属校验：仅自己会话的消息
    # 切换语义：点 like 再点 like = 取消；点 like 再点 dislike = 切换；null = 强制清除
    msg.feedback = None if msg.feedback == body.feedback else body.feedback
    await db.commit()
    await db.refresh(msg)
    return msg
