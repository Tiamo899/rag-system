"""文档接口：上传 / 列表 / 详情 / 分块预览 / 删除。"""
import asyncio
import uuid
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.deps import require_permission
from app.core.exceptions import AppError, NotFoundError
from app.db.session import get_db
from app.models import Document, KnowledgeBase, User
from app.schemas.document import DocumentChunkOut, DocumentOut
from app.services.chunking.splitter import derive_title, split_text
from app.services.document_parser.factory import file_type_from_name, get_parser
from app.services.vectorizer import trigger_vectorization

router = APIRouter(tags=["documents"])


async def _get_doc(db: AsyncSession, doc_id: uuid.UUID) -> Document:
    doc = await db.get(Document, doc_id)
    if doc is None:
        raise NotFoundError("文档不存在")
    return doc


@router.post("/knowledge-bases/{kb_id}/docs", response_model=DocumentOut, status_code=201)
async def upload_document(
    kb_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("doc:upload")),
) -> Document:
    settings = get_settings()
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise NotFoundError("知识库不存在")

    original_name = Path(file.filename or "untitled").name  # 防路径穿越
    file_type = file_type_from_name(original_name)  # 不支持的格式直接 400

    data = await file.read()
    size_mb = settings.max_upload_size_mb * 1024 * 1024
    if len(data) > size_mb:
        raise AppError(
            f"文件超过大小限制 {settings.max_upload_size_mb}MB",
            code="FILE_TOO_LARGE", status_code=413,
        )

    doc = Document(
        kb_id=kb_id,
        filename=original_name,
        original_name=original_name,
        file_type=file_type,
        file_size=len(data),
        created_by=user.id,
        status="pending",
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    upload_dir = Path(settings.upload_dir) / str(kb_id) / str(doc.id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / original_name
    async with aiofiles.open(file_path, "wb") as f:
        await f.write(data)

    doc.file_path = str(file_path)
    await db.commit()
    await db.refresh(doc)
    return doc


@router.get("/knowledge-bases/{kb_id}/docs", response_model=list[DocumentOut])
async def list_documents(
    kb_id: uuid.UUID,
    search: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("doc:read")),
):
    q = select(Document).where(Document.kb_id == kb_id)
    if search:
        q = q.where(Document.original_name.ilike(f"%{search}%"))
    q = q.order_by(Document.created_at.desc())
    q = q.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/docs/{doc_id}", response_model=DocumentOut)
async def get_document(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("doc:read")),
):
    return await _get_doc(db, doc_id)


@router.post("/docs/{doc_id}/vectorize", status_code=202)
async def trigger_vectorize(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("doc:vectorize")),
):
    """手动触发向量化（小眼睛）。异步执行，前端轮询 GET /docs/{id} 看状态。"""
    doc = await _get_doc(db, doc_id)
    if doc.status == "processing":
        raise AppError("文档正在向量化中", code="ALREADY_PROCESSING", status_code=409)
    trigger_vectorization(doc_id)
    return {"doc_id": str(doc_id), "status": "processing"}


@router.get("/docs/{doc_id}/chunks", response_model=list[DocumentChunkOut])
async def preview_chunks(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("doc:read")),
):
    """解析 + 分块预览（不落库；向量化时才会持久化分块）。"""
    doc = await _get_doc(db, doc_id)
    kb = await db.get(KnowledgeBase, doc.kb_id)
    parser = get_parser(doc.file_type)
    text = await asyncio.to_thread(parser.parse, doc.file_path)
    strategy = "markdown" if doc.file_type in ("markdown", "word") else "fixed"
    chunks = split_text(text, kb.chunk_size, kb.chunk_overlap, strategy=strategy)
    return [
        DocumentChunkOut(
            id=uuid.uuid4(),
            doc_id=doc.id,
            title=derive_title(c, i),
            chunk_index=i,
            content=c,
            token_count=None,
            es_doc_id=None,
        )
        for i, c in enumerate(chunks)
    ]


@router.delete("/docs/{doc_id}", status_code=204)
async def delete_document(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("doc:delete")),
):
    doc = await _get_doc(db, doc_id)
    file_path = doc.file_path
    # 先清 ES（与 PG 无跨库事务，取「先 ES 后 DB」）
    try:
        from app.core.elasticsearch import get_es

        await get_es().delete_by_query(
            index=get_settings().es_index,
            query={"term": {"doc_id": str(doc.id)}},
            refresh=True,
        )
    except Exception:  # noqa: BLE001
        pass
    # DB 级联删除 document_chunks
    await db.delete(doc)
    await db.commit()
    # 本地文件 best-effort 清理
    if file_path:
        try:
            Path(file_path).unlink(missing_ok=True)
        except OSError:
            pass
