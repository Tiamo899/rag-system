"""文档接口：上传 / 列表 / 详情 / 分块预览 / 删除。"""
import asyncio
import logging
import uuid
from datetime import date
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.deps import require_permission
from app.core.exceptions import AppError, ForbiddenError, NotFoundError
from app.db.session import get_db
from app.models import Document, KnowledgeBase, User
from app.schemas.document import DocumentChunkOut, DocumentOut, DocumentUpdate
from app.services.access import can_view_kb, ensure_kb_visible, get_visible_kb
from app.services.chunking.splitter import derive_title, split_text
from app.services.document_parser.factory import file_type_from_name, get_parser
from app.services.vectorizer import trigger_vectorization

router = APIRouter(tags=["documents"])
logger = logging.getLogger(__name__)


async def _get_doc(db: AsyncSession, doc_id: uuid.UUID) -> Document:
    doc = await db.get(Document, doc_id)
    if doc is None:
        raise NotFoundError("文档不存在")
    return doc


async def _get_doc_for_user(db: AsyncSession, doc_id: uuid.UUID, user: User) -> Document:
    """文档的一切读写都继承所属知识库的可见范围。"""
    doc = await _get_doc(db, doc_id)
    kb = await db.get(KnowledgeBase, doc.kb_id)
    if kb is None or not can_view_kb(kb, user):
        raise ForbiddenError("无权访问该文档")
    return doc


@router.post("/knowledge-bases/{kb_id}/docs", response_model=DocumentOut, status_code=201)
async def upload_document(
    kb_id: uuid.UUID,
    file: UploadFile = File(...),
    version_no: str | None = Form(None, max_length=50),
    valid_from: date | None = Form(None),
    valid_to: date | None = Form(None),
    supersedes_doc_id: uuid.UUID | None = Form(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("doc:upload")),
) -> Document:
    settings = get_settings()
    kb = await get_visible_kb(db, kb_id, user)

    original_name = Path(file.filename or "untitled").name  # 防路径穿越
    try:
        file_type = file_type_from_name(original_name)
    except ValueError as exc:
        raise AppError(str(exc), code="UNSUPPORTED_FILE_TYPE", status_code=400) from exc

    data = await file.read()
    size_mb = settings.max_upload_size_mb * 1024 * 1024
    if len(data) > size_mb:
        raise AppError(
            f"文件超过大小限制 {settings.max_upload_size_mb}MB",
            code="FILE_TOO_LARGE", status_code=413,
        )

    if valid_from and valid_to and valid_from > valid_to:
        raise AppError("生效日期不能晚于失效日期", code="INVALID_DATE_RANGE", status_code=400)
    if supersedes_doc_id is not None:
        target = await db.get(Document, supersedes_doc_id)
        if target is None:
            raise AppError("替换目标文档不存在", code="INVALID_SUPERSEDES_TARGET", status_code=400)
        if target.kb_id != kb_id:
            raise AppError("替换目标必须在同一知识库", code="INVALID_SUPERSEDES_TARGET", status_code=400)
        if target.superseded_by is not None:
            raise AppError("替换目标已是废止文档", code="INVALID_SUPERSEDES_TARGET", status_code=400)

    doc = Document(
        kb_id=kb_id,
        filename=original_name,
        original_name=original_name,
        file_type=file_type,
        file_size=len(data),
        created_by=user.id,
        status="pending",
        version_no=version_no,
        valid_from=valid_from,
        valid_to=valid_to,
        supersedes_doc_id=supersedes_doc_id,
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
    active_only: bool = Query(default=False, description="只看现行文档（superseded_by 为空）"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("doc:read")),
):
    await ensure_kb_visible(db, kb_id, user)
    q = select(Document).where(Document.kb_id == kb_id)
    if active_only:
        q = q.where(Document.superseded_by.is_(None))
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
    user: User = Depends(require_permission("doc:read")),
):
    return await _get_doc_for_user(db, doc_id, user)


@router.post("/docs/{doc_id}/vectorize", status_code=202)
async def trigger_vectorize(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("doc:vectorize")),
):
    """手动触发向量化（小眼睛）。异步执行，前端轮询 GET /docs/{id} 看状态。"""
    doc = await _get_doc_for_user(db, doc_id, user)
    if doc.status == "processing":
        raise AppError("文档正在向量化中", code="ALREADY_PROCESSING", status_code=409)
    trigger_vectorization(doc_id)
    return {"doc_id": str(doc_id), "status": "processing"}


@router.get("/docs/{doc_id}/chunks", response_model=list[DocumentChunkOut])
async def preview_chunks(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("doc:read")),
):
    """解析 + 分块预览（不落库；向量化时才会持久化分块）。"""
    doc = await _get_doc_for_user(db, doc_id, user)
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


@router.put("/docs/{doc_id}", response_model=DocumentOut)
async def update_document(
    doc_id: uuid.UUID,
    body: DocumentUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("doc:update")),
):
    """更新时效/版本字段（局部）。更新后同步 ES metadata，零重新向量化。"""
    doc = await _get_doc_for_user(db, doc_id, user)
    # 区间校验按「合并后的生效值」算——只改一个字段也必须拦截坏区间
    new_from = body.valid_from if "valid_from" in body.model_fields_set else doc.valid_from
    new_to = body.valid_to if "valid_to" in body.model_fields_set else doc.valid_to
    if new_from is not None and new_to is not None and new_from > new_to:
        raise AppError("生效日期不能晚于失效日期", code="INVALID_DATE_RANGE", status_code=400)

    changed = {}
    for field in ("valid_from", "valid_to", "version_no"):
        if field in body.model_fields_set:
            setattr(doc, field, getattr(body, field))
            changed[field] = getattr(body, field)
    await db.commit()
    await db.refresh(doc)

    if changed:
        await _sync_es_metadata(doc)
    return doc


async def _sync_es_metadata(doc: Document) -> None:
    """把文档当前时效刷进 ES metadata（update_by_query，零 embedding）。幂等。"""
    from app.core.elasticsearch import get_es
    from app.core.config import get_settings

    params = {
        "valid_from": (doc.valid_from or (doc.created_at.date() if doc.created_at else date.today())).isoformat(),
        "valid_to": (doc.valid_to or date(9999, 12, 31)).isoformat(),
        "version_no": doc.version_no,
    }
    es = get_es()
    try:
        await es.update_by_query(
            index=get_settings().es_index,
            query={"term": {"doc_id": str(doc.id)}},
            script={
                "source": (
                    "ctx._source.metadata.valid_from = params.valid_from;"
                    "ctx._source.metadata.valid_to = params.valid_to;"
                    "ctx._source.metadata.version_no = params.version_no"
                ),
                "params": params,
            },
            refresh=True,
        )
    except Exception as exc:  # noqa: BLE001
        # PG 已 commit，时效以 PG 为准；ES 同步失败只告警，re-PUT 可重试
        logger.warning("doc %s ES metadata sync failed: %s", doc.id, exc, exc_info=True)


@router.delete("/docs/{doc_id}", status_code=204)
async def delete_document(
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_permission("doc:delete")),
):
    doc = await _get_doc_for_user(db, doc_id, user)
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
