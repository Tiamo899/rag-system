"""概览大屏统计 Pydantic 模型。"""
import uuid
from datetime import datetime

from pydantic import BaseModel


class RecentSessionStat(BaseModel):
    id: uuid.UUID
    title: str
    updated_at: datetime
    preview: str


class KBStat(BaseModel):
    name: str
    doc_count: int


class DailyStat(BaseModel):
    date: str
    count: int


class OverviewStats(BaseModel):
    kb_total: int
    doc_total: int
    user_total: int
    today_chat_count: int
    recent_sessions: list[RecentSessionStat]
    kb_distribution: list[KBStat]
    doc_upload_trend: list[DailyStat]
