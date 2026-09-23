"""概览大屏统计接口：基于现有表聚合，无新表。"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_permission
from app.db.session import get_db
from app.models import ChatMessage, ChatSession, Document, KnowledgeBase, User
from app.schemas.stats import (
    DailyStat,
    KBStat,
    OverviewStats,
    RecentSessionStat,
)

router = APIRouter(prefix="/stats", tags=["stats"])

_RECENT_LIMIT = 10
_TREND_DAYS = 7


def _utc_today_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


@router.get("/overview", response_model=OverviewStats)
async def overview(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("kb:read")),
):
    # 1. 总量计数
    kb_total = await db.scalar(select(func.count(KnowledgeBase.id))) or 0
    doc_total = await db.scalar(select(func.count(Document.id))) or 0
    user_total = await db.scalar(select(func.count(User.id))) or 0
    utc_today = _utc_today_start()
    today_chat_count = (
        await db.scalar(
            select(func.count(ChatMessage.id)).where(
                ChatMessage.role == "user",
                ChatMessage.created_at >= utc_today,
            )
        )
        or 0
    )

    # 2. 最近会话 + 各自首条用户消息摘要（两轮查询，无 N+1）
    sessions = (
        await db.execute(
            select(ChatSession)
            .order_by(ChatSession.updated_at.desc())
            .limit(_RECENT_LIMIT)
        )
    ).scalars().all()
    preview_map: dict[str, str] = {}
    if sessions:
        first_msgs = (
            await db.execute(
                select(ChatMessage)
                .where(
                    ChatMessage.session_id.in_([s.id for s in sessions]),
                    ChatMessage.role == "user",
                )
                .order_by(ChatMessage.created_at.asc())
            )
        ).scalars().all()
        seen: set = set()
        for m in first_msgs:
            sid = str(m.session_id)
            if sid not in seen:
                seen.add(sid)
                preview_map[sid] = m.content or ""
    recent_sessions = [
        RecentSessionStat(
            id=s.id,
            title=s.title,
            updated_at=s.updated_at,
            preview=(preview_map.get(str(s.id)) or "")[:60],
        )
        for s in sessions
    ]

    # 3. 知识库分布（外连接保证 0 文档的库也出现）
    kb_dist = (
        await db.execute(
            select(KnowledgeBase.name, func.count(Document.id))
            .outerjoin(Document, Document.kb_id == KnowledgeBase.id)
            .group_by(KnowledgeBase.id, KnowledgeBase.name)
            .order_by(KnowledgeBase.created_at.asc())
        )
    ).all()
    kb_distribution = [KBStat(name=name, doc_count=count) for name, count in kb_dist]

    # 4. 近 7 天文档上传趋势（统一 UTC 截日，Python 侧补齐缺日）
    since = utc_today - timedelta(days=_TREND_DAYS - 1)
    rows = (
        await db.execute(
            select(
                func.date(func.timezone("UTC", Document.created_at)).label("d"),
                func.count(Document.id),
            )
            .where(Document.created_at >= since)
            .group_by("d")
            .order_by("d")
        )
    ).all()
    count_by_day = {str(day): cnt for day, cnt in rows}
    doc_upload_trend = []
    for i in range(_TREND_DAYS):
        day = (utc_today - timedelta(days=_TREND_DAYS - 1 - i)).date()
        doc_upload_trend.append(DailyStat(date=day.isoformat(), count=count_by_day.get(day.isoformat(), 0)))

    return OverviewStats(
        kb_total=kb_total,
        doc_total=doc_total,
        user_total=user_total,
        today_chat_count=today_chat_count,
        recent_sessions=recent_sessions,
        kb_distribution=kb_distribution,
        doc_upload_trend=doc_upload_trend,
    )
