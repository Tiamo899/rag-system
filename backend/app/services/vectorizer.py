"""向量化后台任务：进程内 asyncio 任务 + 状态流转。

MVP 用 asyncio.create_task（重启丢失，文档停在 processing，可手动重试）。
未来换 Celery 时，本模块的 _run_vectorize 体可直接迁移为 Celery task。
"""
import asyncio
import logging
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import delete

from app.core.config import get_settings
from app.core.elasticsearch import get_es
from app.db.session import AsyncSessionLocal
from app.models import Document, DocumentChunk, KnowledgeBase
from app.services.chunking.splitter import derive_title, split_text
from app.services.document_parser.factory import get_parser
from app.services.embedding.factory import get_embedding_provider

logger = logging.getLogger(__name__)
_settings = get_settings()
_tasks: dict[uuid.UUID, asyncio.Task] = {}

EMBEDDING_BATCH = 16


def trigger_vectorization(doc_id: uuid.UUID) -> bool:
    """幂等触发向量化。已在执行返回 False，新启动返回 True。"""
    task = _tasks.get(doc_id)
    if task is not None and not task.done():
        return False
    _tasks[doc_id] = asyncio.create_task(_run_vectorize(doc_id))
    return True


async def _run_vectorize(doc_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        doc = await db.get(Document, doc_id)
        if doc is None:
            return
        doc.status = "processing"
        await db.commit()
        try:
            await _do_vectorize(db, doc)
        except Exception as exc:  # noqa: BLE001
            logger.exception("文档 %s 向量化失败: %s", doc_id, exc)
            await db.rollback()
            doc = await db.get(Document, doc_id)
            if doc is not None:
                doc.status = "failed"
                await db.commit()


async def _do_vectorize(db, doc: Document) -> None:
    kb = await db.get(KnowledgeBase, doc.kb_id)
    parser = get_parser(doc.file_type)
    text = await asyncio.to_thread(parser.parse, doc.file_path)
    if not text or not text.strip():
        raise ValueError("未能从文档提取文本（扫描版 PDF 可能不支持）")

    # markdown 与 word（解析后已含标题标记）都按标题层级分块
    strategy = "markdown" if doc.file_type in ("markdown", "word") else "fixed"
    chunks = split_text(text, kb.chunk_size, kb.chunk_overlap, strategy=strategy)
    if not chunks:
        raise ValueError("分块结果为空")

    provider = get_embedding_provider()
    embeddings: list[list[float]] = []
    for i in range(0, len(chunks), EMBEDDING_BATCH):
        vecs = await provider.embed_texts(chunks[i:i + EMBEDDING_BATCH])
        for v in vecs:
            assert len(v) == _settings.embedding_dim, "向量维度与 EMBEDDING_DIM 不符"
        embeddings.extend(vecs)

    es = get_es()
    # 幂等：重新向量化前清掉旧 ES 文档与旧分块行
    await es.delete_by_query(
        index=_settings.es_index,
        query={"term": {"doc_id": str(doc.id)}},
        refresh=True,
    )
    await db.execute(delete(DocumentChunk).where(DocumentChunk.doc_id == doc.id))

    operations: list[dict] = []
    for i, (content, vec) in enumerate(zip(chunks, embeddings)):
        title = derive_title(content, i)
        chunk_row = DocumentChunk(
            doc_id=doc.id,
            kb_id=doc.kb_id,
            content=content,
            title=title,
            chunk_index=i,
            token_count=max(len(content) // 4, 1),
            es_doc_id=f"{doc.id}:{i}",
        )
        db.add(chunk_row)
        await db.flush()

        es_id = f"{doc.id}:{i}"
        operations.append({"index": {"_index": _settings.es_index, "_id": es_id}})
        operations.append(
            {
                "chunk_id": str(chunk_row.id),
                "doc_id": str(doc.id),
                "kb_id": str(doc.kb_id),
                "content": content,
                "content_vector": vec,
                "metadata": {
                    "doc_name": doc.original_name,
                    "chunk_index": i,
                    "kb_name": kb.name,
                    "title": title,
                    # 时效默认值：缺省 = 上传日 / 永久（与回填脚本同一契约）
                    "valid_from": (doc.valid_from or doc.created_at.date()).isoformat(),
                    "valid_to": (doc.valid_to or date(9999, 12, 31)).isoformat(),
                    "version_no": doc.version_no,
                },
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    if operations:
        await es.bulk(operations=operations, refresh=True)

    doc.status = "completed"
    doc.chunk_count = len(chunks)
    doc.vectorized_at = datetime.now(timezone.utc)
    await db.commit()
