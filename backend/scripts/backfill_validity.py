# backend/scripts/backfill_validity.py
"""存量文档时效回填：只改 ES metadata，零 embedding，幂等可重跑。

用法（backend/ 下）：python -m scripts.backfill_validity
"""
import asyncio
from datetime import date, datetime

from sqlalchemy import select

from app.core.config import get_settings
from app.core.elasticsearch import get_es
from app.db.session import AsyncSessionLocal
from app.models import Document


async def backfill_all() -> dict:
    """把 PG 中现行文档的时效默认值刷进 ES metadata。返回 {updated, skipped}。"""
    es = get_es()
    index = get_settings().es_index
    updated = skipped = 0
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Document).where(Document.superseded_by.is_(None))
        )
        for doc in result.scalars().all():
            params = {
                "valid_from": (doc.valid_from or (doc.created_at or datetime.now()).date()).isoformat(),
                "valid_to": (doc.valid_to or date(9999, 12, 31)).isoformat(),
                "version_no": doc.version_no,
            }
            resp = await es.update_by_query(
                index=index,
                query={"term": {"doc_id": str(doc.id)}},
                script={
                    # 值未变化 → noop，让第二次运行如实报 updated: 0（计数幂等）；
                    # 字段缺失（待回填）时 Map.get 返回 null → 走赋值分支
                    "source": (
                        "if (ctx._source.metadata.valid_from == params.valid_from "
                        "&& ctx._source.metadata.valid_to == params.valid_to "
                        "&& ctx._source.metadata.version_no == params.version_no) "
                        "{ ctx.op = 'noop'; } else { "
                        "ctx._source.metadata.valid_from = params.valid_from;"
                        "ctx._source.metadata.valid_to = params.valid_to;"
                        "ctx._source.metadata.version_no = params.version_no }"
                    ),
                    "params": params,
                },
                refresh=True,
            )
            if resp.get("updated", 0):
                updated += resp["updated"]
            else:
                skipped += 1
    return {"updated": updated, "skipped": skipped}


if __name__ == "__main__":
    out = asyncio.run(backfill_all())
    print(f"backfill done: {out}")
