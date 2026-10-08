# Phase 2 知识库治理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消灭「新旧文档打架」——版本链 + 生效时间落库，同名替换在向量化成功后原子生效（旧分块物理清除），检索按时效过滤，跨文档矛盾在 prompt 中提示不裁决，governance 评测旧版引用归零。

**Architecture:** `documents` 表加 5 个可空列（spec §5.1 的 4 个 + `supersedes_doc_id` 存替换意图，见 Ruling）；ES `metadata` 显式映射 `valid_from/valid_to/version_no`，`hybrid_search` 用范围过滤（严格语义：缺字段即不命中），存量数据用一次性回填脚本补齐（零 embedding）；替换在 `_run_vectorize` 成功路径中应用（先清 ES 后改 PG）；机制三在 `evaluate_node` 构造 context 时附版本/时效并加多来源提示；前端加效力徽章、同名替换弹窗、「只看现行」开关。

**Tech Stack:** Python 3.10 · Alembic · Elasticsearch 8.13（range filter + update_by_query）· FastAPI Form · React/antd · pytest · npm run build（tsc）

**Spec:** `docs/superpowers/specs/2026-09-23-thesis-roadmap-design.md`（§2 原则、§5 Phase 2 全部）

**对 spec 的两处落地裁定（执行前已列入评审）：**
1. **第 5 列 `supersedes_doc_id`**（可空，存于新文档）：spec §5.1 字段表只有 4 个，但 §5.2 要求「上传时…后端亦接受显式 `supersedes_doc_id`」——意图必须在上传与向量化两次请求间持久化，无处可存。加一列自引用 FK 最忠于 spec 的 API 时序。
2. **开发库 schema 变更授权**：`alembic upgrade head` 将给共享开发库的 `documents` 表加 5 个**可空**列（向后兼容、不删不改既有列）。此红线操作已在计划评审时获得用户批准。

**Phase 0/1 既成事实（本计划的输入）：**
- 全量测试基线：**111 之前的 99 passed / 57 warnings**（本计划完成后 111）
- 迁移链头：`e23b6db22acb`（add_chat_message_feedback）
- `governance.jsonl` 基线（Phase 0）：keyword **50%**（gv-01 引用旧版「3天」）、judge 50%、Hit@3 100% 但来源首位是旧版
- 评测库存在：kb `评测库`，含 `请假管理办法_2023版.md` / `请假管理办法_2024版.md`（当前**都无时效字段、都现行**）
- `hybrid_search`/`evaluate_node`/`vectorizer`/`documents.py` 结构与 Phase 0 一致；`SearchResultOut` 无治理字段
- 前端 `KnowledgeBase.tsx`（347 行）上传为无弹窗直传；无前端测试基建，验证 = `npm run build`（tsc）

## Global Constraints

- **PG 存全量历史，ES 只存生效内容**：替换后旧文档行 + 原文件保留；旧分块（ES + PG）物理删除
- **替换时序**：`superseded_by` 标记与分块清除只在**新文档向量化成功后**执行；失败 → 旧文档保持现行（fail-open，知识不断档）
- **时效过滤严格语义**：`valid_from ≤ 今天 ≤ valid_to` 范围查询，**缺字段即不命中**——因此「写入必带默认值 + 存量必回填」是配套契约，索引侧缺省 `valid_from=上传日`、`valid_to=9999-12-31`
- **零 embedding 成本**：回填与 PUT 同步只改 metadata（`update_by_query`），绝不重新向量化
- **提示不裁决**：跨文档矛盾只在 context 加提示行，LLM 无自动裁决逻辑
- **mock 不破坏**：现有 99 测试全绿（治理单测不需要真实 key；集成测试需 PG+ES）
- **`API.md` 随接口改动同步**（T7 统一更新）
- **YAGNI**：不做版本树 UI/ diff 对比/文档编辑页/自动矛盾检测/前端有效期编辑（PUT 仅 API 可用）/ RBAC 变更

## Review Focus

1. **替换必须在向量化成功后才生效**——失败场景旧文档被误标废止 = 知识断档 → Task 4 `test_supersede_not_applied_when_vectorize_fails`
2. **旧分块必须物理清除**——过滤出来的「假现行」或残留检索 = 场景 C 复活 → Task 4 `test_supersede_purges_old_chunks_from_es_and_pg`
3. **严格时效过滤 + 存量缺字段 = 全库检索静默变空**——回填不跑/失败会让现有数据全部隐身 → Task 2 `test_expired_doc_excluded_and_fresh_doc_found` + live 回填验证步骤；回填脚本必须幂等
4. **`valid_from > valid_to` 等非法时效必须 400**——坏数据一旦入检索过滤行为不可预期 → Task 3 `test_put_rejects_invalid_range`
5. **同名替换的意图字段校验**——`supersedes_doc_id` 指向不存在/异库/已废止目标必须 400，不能带病入库 → Task 4 `test_upload_rejects_invalid_supersedes_target`

---

### Task 1: 迁移 v6 + 模型与输出字段

**Files:**
- Create: `backend/alembic/versions/a9c3e5f7b2d1_add_document_governance.py`
- Modify: `backend/app/models/document.py`（Document 类）
- Modify: `backend/app/schemas/document.py`（DocumentOut）
- Test: `backend/tests/test_doc_governance.py`（新建）

**Interfaces:**
- Consumes: 现有 `Document`/`DocumentOut`（字段见现状）
- Produces（后续任务依赖，逐字）:
  - `Document` 新列：`valid_from: Mapped[date | None]`、`valid_to: Mapped[date | None]`、`version_no: Mapped[str | None]`（String(50)）、`superseded_by: Mapped[uuid.UUID | None]`（FK documents.id, ondelete SET NULL, nullable）、`supersedes_doc_id: Mapped[uuid.UUID | None]`（FK documents.id, ondelete SET NULL, nullable）
  - `DocumentOut` 新字段：`valid_from: date | None`、`valid_to: date | None`、`version_no: str | None`、`superseded_by: uuid.UUID | None`、`supersedes_doc_id: uuid.UUID | None`
  - 迁移 revision id：`a9c3e5f7b2d1`，`down_revision = "e23b6db22acb"`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_doc_governance.py
"""Phase 2 治理：字段落库与输出。需要 PG（+ES 容器）。"""
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def admin_headers(client):
    resp = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _wait(client, headers, doc_id, timeout=20) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = client.get(f"/api/v1/docs/{doc_id}", headers=headers).json()["status"]
        if st in ("completed", "failed"):
            return st
        time.sleep(0.25)
    return "timeout"


def _mk_kb(client, headers, name):
    kb = client.post(
        "/api/v1/knowledge-bases", json={"name": name, "chunk_size": 100},
        headers=headers,
    ).json()
    return kb["id"]


GOV_FIELDS = ("valid_from", "valid_to", "version_no", "superseded_by", "supersedes_doc_id")


def test_upload_returns_governance_fields(client, admin_headers):
    """新字段随详情/列表输出，默认 None（DB 层可空，不设默认值）。"""
    kb_id = _mk_kb(client, admin_headers, "治理字段测试库")
    try:
        up = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs",
            headers=admin_headers,
            files={"file": ("g1.md", "# 标题\n治理字段默认值内容".encode(), "text/markdown")},
        )
        assert up.status_code == 201, up.text
        doc = up.json()
        for f in GOV_FIELDS:
            assert f in doc, f"缺字段 {f}"
            assert doc[f] is None
    finally:
        client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=admin_headers)


def test_upload_with_version_fields_persists(client, admin_headers):
    """上传时携带版本/时效字段 → 原样落库并回显。"""
    kb_id = _mk_kb(client, admin_headers, "治理版本字段测试库")
    try:
        up = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs",
            headers=admin_headers,
            data={"version_no": "2023 版", "valid_from": "2023-09-01",
                  "valid_to": "2025-08-31"},
            files={"file": ("g2.md", "# 旧版\n版本字段持久化内容".encode(), "text/markdown")},
        )
        assert up.status_code == 201, up.text
        doc = up.json()
        assert doc["version_no"] == "2023 版"
        assert doc["valid_from"] == "2023-09-01"
        assert doc["valid_to"] == "2025-08-31"
        got = client.get(f"/api/v1/docs/{doc['id']}", headers=admin_headers).json()
        assert got["version_no"] == "2023 版"
        assert got["superseded_by"] is None
    finally:
        client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=admin_headers)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/test_doc_governance.py -v`
Expected: FAIL — `assert 'valid_from' in doc`（字段不存在）

- [ ] **Step 3: 写迁移文件（先写，测试才能过）**

```python
# backend/alembic/versions/a9c3e5f7b2d1_add_document_governance.py
"""add document governance columns

Revision ID: a9c3e5f7b2d1
Revises: e23b6db22acb
Create Date: 2026-10-06

"""
from alembic import op
import sqlalchemy as sa


revision = 'a9c3e5f7b2d1'
down_revision = 'e23b6db22acb'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('documents', sa.Column('valid_from', sa.Date(), nullable=True))
    op.add_column('documents', sa.Column('valid_to', sa.Date(), nullable=True))
    op.add_column('documents', sa.Column('version_no', sa.String(length=50), nullable=True))
    op.add_column('documents', sa.Column('superseded_by', sa.Uuid(), nullable=True))
    op.add_column('documents', sa.Column('supersedes_doc_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'fk_documents_superseded_by', 'documents', 'documents',
        ['superseded_by'], ['id'], ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_documents_supersedes_doc_id', 'documents', 'documents',
        ['supersedes_doc_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_documents_supersedes_doc_id', 'documents', type_='foreignkey')
    op.drop_constraint('fk_documents_superseded_by', 'documents', type_='foreignkey')
    op.drop_column('documents', 'supersedes_doc_id')
    op.drop_column('documents', 'superseded_by')
    op.drop_column('documents', 'version_no')
    op.drop_column('documents', 'valid_to')
    op.drop_column('documents', 'valid_from')
```

`backend/app/models/document.py` 的 `Document` 类末尾（`created_by` 之后）追加：

```python
    # 治理字段（Phase 2）：时效 + 版本链。superseded_by 非空 = 已废止；
    # supersedes_doc_id = 上传时登记的替换意图，向量化成功后才应用
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    version_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    supersedes_doc_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
```

（import 区补 `from datetime import date`；`Date` 从 sqlalchemy 导入，与既有 `DateTime` 并列。）

`backend/app/schemas/document.py` 的 `DocumentOut` 在 `created_at` 之前追加：

```python
    valid_from: date | None = None
    valid_to: date | None = None
    version_no: str | None = None
    superseded_by: uuid.UUID | None = None
    supersedes_doc_id: uuid.UUID | None = None
```

（文件头 `from datetime import datetime` 改为 `from datetime import date, datetime`。）

- [ ] **Step 4: 执行迁移（⚠️ 数据库 schema 变更——已获用户批准）**

Run: `cd backend && python -m alembic upgrade head`
Expected: `Running upgrade e23b6db22acb -> a9c3e5f7b2d1`；再跑 `python -m alembic current` 显示 `a9c3e5f7b2d1`

- [ ] **Step 5: 上传接口接受版本/时效表单字段**

`backend/app/api/v1/documents.py` 的 `upload_document` 签名改为（import 区补 `Form`）：

```python
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile

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
```

`Document(...)` 构造处补四个赋值（`supersedes_doc_id` 的目标校验留给 Task 4，本任务仅存储）：

```python
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
```

（`date` 从 `datetime` 模块导入：文件头已有 `from datetime import ...` 处按需补；若无则加 `from datetime import date`。）

- [ ] **Step 6: 跑测试确认通过**

Run: `cd backend && python -m pytest tests/test_doc_governance.py -v`
Expected: PASS（2 项全绿）

- [ ] **Step 7: 全量回归后提交**

Run: `cd backend && python -m pytest -q`
Expected: 101 passed（99 + 2）, 57 warnings

```bash
git add backend/alembic/versions/a9c3e5f7b2d1_add_document_governance.py \
        backend/app/models/document.py backend/app/schemas/document.py \
        backend/app/api/v1/documents.py backend/tests/test_doc_governance.py
git commit -m "feat(docs): governance columns via migration v6 with upload form fields"
```

---

### Task 2: ES 时效映射、索引写入与检索过滤 + 回填脚本

**Files:**
- Modify: `backend/app/services/search/es_index.py`（mapping + ensure_index put_mapping）
- Modify: `backend/app/services/vectorizer.py`（metadata 写入默认值）
- Modify: `backend/app/services/search/hybrid.py`（过滤构造与应用）
- Create: `backend/scripts/__init__.py`
- Create: `backend/scripts/backfill_validity.py`
- Test: `backend/tests/test_governance_search.py`（新建）

**Interfaces:**
- Consumes: Task 1 的 `Document.valid_from/valid_to/version_no/superseded_by`
- Produces（Task 3/4/5/7 依赖，逐字）:
  - `hybrid.build_validity_filters(today: str | None = None) -> list[dict]`——返回两条 range 子句（今天缺省 `date.today().isoformat()`）
  - ES `metadata` 显式子映射：`valid_from`/`valid_to`（`date`，`format: "yyyy-MM-dd||strict_date_optional_time"`）、`version_no`（`keyword`）
  - 索引 metadata 默认值：`valid_from = doc.valid_from or doc.created_at.date()` 的 isoformat；`valid_to = doc.valid_to or date(9999,12,31)` 的 isoformat；`version_no` 原样（None 就是 None）
  - 回填：`python -m scripts.backfill_validity`（backend/ 下运行，幂等；对 `superseded_by IS NULL` 的文档按上述默认值回填 ES metadata）

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_governance_search.py
"""Phase 2 时效过滤：非法日期检索不到、回填恢复存量。需要 PG+ES。"""
import asyncio
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def admin_headers(client):
    resp = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _wait(client, headers, doc_id, timeout=20) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = client.get(f"/api/v1/docs/{doc_id}", headers=headers).json()["status"]
        if st in ("completed", "failed"):
            return st
        time.sleep(0.25)
    return "timeout"


def _upload_and_vectorize(client, headers, kb_id, name, content, data=None):
    files = {"file": (name, content.encode("utf-8"), "text/markdown")}
    up = client.post(
        f"/api/v1/knowledge-bases/{kb_id}/docs",
        headers=headers, files=files, data=data or {},
    )
    assert up.status_code == 201, up.text
    doc_id = up.json()["id"]
    client.post(f"/api/v1/docs/{doc_id}/vectorize", headers=headers)
    assert _wait(client, headers, doc_id) == "completed"
    return doc_id


def test_expired_doc_excluded_and_fresh_doc_found(client, admin_headers):
    """过去失效的文档检索不到；有效期内的能找到（严格范围过滤生效）。"""
    kb = client.post(
        "/api/v1/knowledge-bases",
        json={"name": "时效过滤测试库", "chunk_size": 100},
        headers=admin_headers,
    ).json()
    kb_id = kb["id"]
    try:
        _upload_and_vectorize(
            client, admin_headers, kb_id, "expired.md",
            "# 过期\n时效过滤过期内容风铃草", {"valid_to": "2020-01-01"},
        )
        _upload_and_vectorize(
            client, admin_headers, kb_id, "fresh.md",
            "# 现行\n时效过滤现行内容风铃草", {"valid_from": "2020-01-01"},
        )
        hits = client.post(
            "/api/v1/search",
            json={"query": "时效过滤内容", "kb_id": kb_id, "top_k": 10},
            headers=admin_headers,
        ).json()
        names = [h["doc_name"] for h in hits]
        assert "expired.md" not in names, f"过期文档仍可检索: {names}"
        assert "fresh.md" in names, f"现行文档未命中: {names}"
    finally:
        client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=admin_headers)


def test_backfill_restores_legacy_chunks(client, admin_headers):
    """存量（缺时效字段）文档被严格过滤排除，回填后恢复——
    钉住「写入必带默认值 + 存量必回填」契约，防止全库检索静默变空。"""
    kb = client.post(
        "/api/v1/knowledge-bases",
        json={"name": "回填测试库", "chunk_size": 100},
        headers=admin_headers,
    ).json()
    kb_id = kb["id"]
    try:
        doc_id = _upload_and_vectorize(
            client, admin_headers, kb_id, "legacy.md",
            "# 存量\n回填恢复测试内容鹤望兰",
        )

        # 模拟存量：抹掉 metadata 时效字段。
        # 用独立 ES 客户端在独立事件循环内执行——不能复用模块级 get_es()
        # （其连接池绑定 TestClient 的事件循环，asyncio.run 会串环报错）。
        async def _strip():
            from elasticsearch import AsyncElasticsearch
            es2 = AsyncElasticsearch(get_settings().es_url)
            try:
                return await es2.update_by_query(
                    index=get_settings().es_index,
                    query={"term": {"doc_id": doc_id}},
                    script={
                        "source": (
                            "ctx._source.metadata.remove('valid_from');"
                            "ctx._source.metadata.remove('valid_to')"
                        )
                    },
                    refresh=True,
                )
            finally:
                await es2.close()

        resp = asyncio.run(_strip())
        assert resp.get("failed", 0) == 0

        hits = client.post(
            "/api/v1/search",
            json={"query": "回填恢复测试", "kb_id": kb_id, "top_k": 10},
            headers=admin_headers,
        ).json()
        assert not any(h["doc_name"] == "legacy.md" for h in hits), \
            "缺字段文档应被严格过滤排除"

        # 回填用子进程跑（脚本自带事件循环与连接池，天然隔离）
        backend_dir = Path(__file__).resolve().parents[1]
        proc = subprocess.run(
            [sys.executable, "-m", "scripts.backfill_validity"],
            capture_output=True, text=True, cwd=str(backend_dir),
            encoding="utf-8", errors="replace",
        )
        assert proc.returncode == 0, proc.stderr
        assert "backfill done" in (proc.stdout or ""), proc.stdout

        hits2 = client.post(
            "/api/v1/search",
            json={"query": "回填恢复测试", "kb_id": kb_id, "top_k": 10},
            headers=admin_headers,
        ).json()
        assert any(h["doc_name"] == "legacy.md" for h in hits2), \
            "回填后文档必须恢复可检索"
    finally:
        client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=admin_headers)


def test_build_validity_filters_shape():
    """纯函数：两条 range 子句、字段路径与日期格式固定。"""
    from app.services.search.hybrid import build_validity_filters as hv

    f = hv("2026-10-06")
    assert f == [
        {"range": {"metadata.valid_from": {"lte": "2026-10-06"}}},
        {"range": {"metadata.valid_to": {"gte": "2026-10-06"}}},
    ]
```

（测试文件头需 `import asyncio`。）

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/test_governance_search.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_validity_filters'`

- [ ] **Step 3: 实现**

`es_index.py` 的 `chunk_index_mapping()` 中 `metadata` 改为显式子映射：

```python
            "metadata": {
                "type": "object",
                "properties": {
                    "valid_from": {"type": "date", "format": "yyyy-MM-dd||strict_date_optional_time"},
                    "valid_to": {"type": "date", "format": "yyyy-MM-dd||strict_date_optional_time"},
                    "version_no": {"type": "keyword"},
                },
            },
```

`ensure_index` 索引已存在的分支在 dims 校验通过后追加（存量索引补子映射，幂等）：

```python
    # 存量索引补 metadata 子映射（幂等；与新建 mapping 保持一致）
    await es.indices.put_mapping(
        index=index,
        properties={"metadata": chunk_index_mapping()["properties"]["metadata"]},
    )
```

`vectorizer.py` `_do_vectorize` 构造 `operations` 的 `metadata` 改为（import 区补 `from datetime import date, datetime, timezone`——已有 `datetime, timezone` 则补 `date`）：

```python
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
```

`hybrid.py` 在 `_kb_filter` 之后加：

```python
def build_validity_filters(today: str | None = None) -> list[dict]:
    """时效过滤（严格语义：缺字段即不命中）。存量数据须先跑回填脚本。"""
    day = today or date.today().isoformat()
    return [
        {"range": {"metadata.valid_from": {"lte": day}}},
        {"range": {"metadata.valid_to": {"gte": day}}},
    ]
```

（import 区补 `from datetime import date`。）

`hybrid_search` 内两处应用（与既有 `kb_f` 合并）：

```python
    kb_f = _kb_filter(kb_id)  # 不变
    validity_f = build_validity_filters()

    # knn 分支：
        knn_filter = {"bool": {"filter": ([kb_f] if kb_f else []) + validity_f}}
        knn["filter"] = knn_filter
    # keyword 分支：
        bool_q["filter"] = ([kb_f] if kb_f else []) + validity_f
```

（注意保持「kb_id=None 时不传 knn.filter 键」的既有语义——`validity_f` 恒存在，所以 knn 的 filter 键从此恒有值；仅当 `kb_f` 为 None 时 filter 用 `{"bool": {"filter": validity_f}}`。）

`backend/scripts/__init__.py` 空文件。`backend/scripts/backfill_validity.py`：

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && python -m pytest tests/test_governance_search.py -v`
Expected: PASS（3 项全绿）

- [ ] **Step 5: 真实环境回填（需 PG+ES）**

Run: `cd backend && python -m scripts.backfill_validity`
Expected: `backfill done: {'updated': N, 'skipped': 0}`，N ≥ 评测库文档数；再跑一次 `updated: 0, skipped: N`（幂等）
随后验证存量可检索：
Run: `curl -s -X POST localhost:8000/api/v1/search -H "Content-Type: application/json" -H "Authorization: Bearer <token>" -d '{"query":"奖学金评定","top_k":5}'`（或用测试脚本调 `/search` 不带 kb_id）
Expected: 有结果（若 backend 容器跑的是旧镜像代码，本地开发以 `uvicorn --reload` 或单测验证为准——至少 `test_backfill_restores_legacy_chunks` 已证明契约）

- [ ] **Step 6: 全量回归后提交**

Run: `cd backend && python -m pytest -q`
Expected: 104 passed（101 + 3）, 57 warnings

```bash
git add backend/app/services/search/es_index.py backend/app/services/search/hybrid.py \
        backend/app/services/vectorizer.py backend/scripts \
        backend/tests/test_governance_search.py
git commit -m "feat(search): validity range filter with index-time defaults and backfill script"
```

---

### Task 3: 文档时效更新接口 PUT /docs/{id}

**Files:**
- Modify: `backend/app/api/v1/documents.py`（新增 PUT 路由）
- Modify: `backend/app/schemas/document.py`（DocumentUpdate）
- Test: `backend/tests/test_doc_governance.py`（追加 3 个测试）

**Interfaces:**
- Consumes: Task 1 字段；Task 2 的 metadata 契约（同步脚本写同一默认值）
- Produces: `PUT /api/v1/docs/{doc_id}`，body `{valid_from?, valid_to?, version_no?}`（局部更新，null=清除该字段）；权限 `doc:update`（**权限目录新增点**，见 Step 3）；更新后 ES metadata 同步（`update_by_query`，零 embedding）

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_doc_governance.py` 末尾追加：

```python
def test_put_updates_fields_and_syncs_es(client, admin_headers):
    """PUT 更新时效 → PG 回显 + ES metadata 同步（检索行为随之变化）。

    关键：文档必须先向量化进 ES，否则「检索不到」是平凡真理、测不出同步。
    """
    kb_id = _mk_kb(client, admin_headers, "PUT同步测试库")
    try:
        up = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs",
            headers=admin_headers,
            files={"file": ("put1.md", "# 内容\n时效同步测试松鹤".encode(), "text/markdown")},
        ).json()
        doc_id = up["id"]
        client.post(f"/api/v1/docs/{doc_id}/vectorize", headers=admin_headers)
        assert _wait(client, admin_headers, doc_id) == "completed"

        # 未设时效（默认长期有效）→ 可检索（证明已进 ES）
        hits0 = client.post(
            "/api/v1/search",
            json={"query": "时效同步测试", "kb_id": kb_id, "top_k": 10},
            headers=admin_headers,
        ).json()
        assert any(h["doc_name"] == "put1.md" for h in hits0), "前置：向量化后应可检索"

        # PUT 版本/时效 → PG 回显
        r = client.put(
            f"/api/v1/docs/{doc_id}",
            json={"version_no": "2024 版", "valid_from": "2024-09-01",
                  "valid_to": "2030-12-31"},
            headers=admin_headers,
        )
        assert r.status_code == 200, r.text
        got = client.get(f"/api/v1/docs/{doc_id}", headers=admin_headers).json()
        assert got["version_no"] == "2024 版"
        assert got["valid_to"] == "2030-12-31"

        # 显式清空 valid_from + 把 valid_to 改到过去 → 合法过期（合并口径下
        # 2024-09-01 > 2020-01-01 会 400，必须先清 from）→ ES 同步 → 检索排除。
        # 顺带钉住「显式 null = 清除」语义。
        client.put(
            f"/api/v1/docs/{doc_id}",
            json={"valid_from": None, "valid_to": "2020-01-01"},
            headers=admin_headers,
        )
        hits = client.post(
            "/api/v1/search",
            json={"query": "时效同步测试", "kb_id": kb_id, "top_k": 10},
            headers=admin_headers,
        ).json()
        assert not any(h["doc_name"] == "put1.md" for h in hits), \
            "valid_to 改为过去后 ES 应已同步、检索应排除"
        got2 = client.get(f"/api/v1/docs/{doc_id}", headers=admin_headers).json()
        assert got2["valid_from"] is None, "显式 null 应清除该字段"
    finally:
        client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=admin_headers)


def test_put_rejects_invalid_range(client, admin_headers):
    """valid_from > valid_to → 400，坏数据不入库。"""
    kb_id = _mk_kb(client, admin_headers, "PUT非法区间测试库")
    try:
        up = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs",
            headers=admin_headers,
            files={"file": ("put2.md", "# 内容\n非法区间斑鸠菊".encode(), "text/markdown")},
        ).json()
        r = client.put(
            f"/api/v1/docs/{up['id']}",
            json={"valid_from": "2025-01-01", "valid_to": "2024-01-01"},
            headers=admin_headers,
        )
        assert r.status_code == 400, r.text
        got = client.get(f"/api/v1/docs/{up['id']}", headers=admin_headers).json()
        assert got["valid_from"] is None  # 未入库
    finally:
        client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=admin_headers)


def test_put_not_found_404(client, admin_headers):
    r = client.put(
        "/api/v1/docs/00000000-0000-0000-0000-000000000000",
        json={"version_no": "x"}, headers=admin_headers,
    )
    assert r.status_code == 404
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/test_doc_governance.py -v`
Expected: 新增 3 项中 `test_put_updates_fields_and_syncs_es` 以 `405`（方法不允许）或 `404` 失败

- [ ] **Step 3: 实现 PUT 路由**

`backend/app/schemas/document.py` 追加：

```python
class DocumentUpdate(BaseModel):
    valid_from: date | None = None
    valid_to: date | None = None
    version_no: str | None = Field(default=None, max_length=50)
```

（import 区补 `from pydantic import BaseModel, Field`。max_length 与列 String(50) 对齐，防超长 500——与 Task 1 upload Form 同型修复。）

PUT 边界测试（追加到 `backend/tests/test_doc_governance.py` 末尾）：

```python
def test_put_version_no_too_long_422(client, admin_headers):
    """PUT 超长 version_no 被 422 拒绝，不 500。"""
    kb_id = _mk_kb(client, admin_headers, "PUT版本号边界测试库")
    try:
        up = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs",
            headers=admin_headers,
            files={"file": ("pb.md", "# pb\nPUT边界土人参".encode(), "text/markdown")},
        ).json()
        r = client.put(
            f"/api/v1/docs/{up['id']}",
            json={"version_no": "y" * 51},
            headers=admin_headers,
        )
        assert r.status_code == 422, r.status_code
    finally:
        client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=admin_headers)
```

（文件头已有 `date` import（Task 1 改过）。注意：三字段全 null 表示「不更新」还是「清除」——**约定：请求体里出现的键才更新**，用 `model_fields_set` 判断；`null` 显式出现 = 清除该字段。）

`backend/app/api/v1/documents.py` 在 `delete_document` 之前加路由（import 区补 `DocumentUpdate` 与 `date`）：

```python
@router.put("/docs/{doc_id}", response_model=DocumentOut)
async def update_document(
    doc_id: uuid.UUID,
    body: DocumentUpdate,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("doc:update")),
):
    """更新时效/版本字段（局部）。更新后同步 ES metadata，零重新向量化。"""
    doc = await _get_doc(db, doc_id)
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
```

**权限点**（两处修改 + 一次既有数据同步）：

1. `backend/app/core/security/rbac.py` 的 editor 角色集合（约第 13 行 `"doc:upload", "doc:read", ...`）追加 `"doc:update"`；
2. 同文件 `PERMISSIONS_CATALOG` 的 doc 模块 `permissions` 列表（约第 36-40 行）追加 `{"key": "doc:update", "label": "编辑时效"},`；
3. `seed.py` 只在角色缺失时创建、**不更新既有行**——既有开发库的 editor 角色需一次性同步（在本任务 Step 3 后执行，写进 `backend/tests` 之外的一次性命令）：

```bash
cd backend && python -c "
import asyncio
from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.models import Role

async def main():
    async with AsyncSessionLocal() as s:
        r = (await s.execute(select(Role).where(Role.name == 'editor'))).scalar_one()
        if 'doc:update' not in r.permissions:
            r.permissions = sorted(set(r.permissions) | {'doc:update'})
            await s.commit()
            print('editor synced')
        else:
            print('already has doc:update')

asyncio.run(main())
"
```

（admin 走 `*:*` 通配无需改；viewer 不授。）

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && python -m pytest tests/test_doc_governance.py -v`
Expected: PASS（7 项全绿：原 3 + 本任务 4——updates_sync / invalid_range / not_found / version_no 边界）

- [ ] **Step 5: 全量回归后提交**

Run: `cd backend && python -m pytest -q`
Expected: 109 passed（105 + 4）；warnings 实报（基线 64 + 新测试 jwt 既有类别若干，出现其他类别才上报）

```bash
git add backend/app/api/v1/documents.py backend/app/schemas/document.py \
        backend/app/core/security/rbac.py backend/tests/test_doc_governance.py
git commit -m "feat(docs): PUT validity/version update with ES metadata sync"
```

---

### Task 4: 同名替换（supersede）事务

**Files:**
- Modify: `backend/app/api/v1/documents.py`（上传校验 supersedes_doc_id）
- Modify: `backend/app/services/vectorizer.py`（成功路径应用替换）
- Test: `backend/tests/test_doc_governance.py`（追加 2 个测试）

**Interfaces:**
- Consumes: Task 1 的 `supersedes_doc_id`；Task 2 的 ES 清除能力（`delete_by_query` 模式与既有 delete_document 相同）
- Produces: 替换应用函数 `_apply_supersede(db, new_doc) -> None`（vectorizer 内部函数，无外部消费者，失败路径直接 return 不标记）；上传时目标校验 400 语义

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_doc_governance.py` 末尾追加：

```python
def test_supersede_purges_old_chunks_from_es_and_pg(client, admin_headers):
    """向量化成功 → 旧文档标记废止 + ES/PG 分块物理清除，文档行与文件保留。"""
    kb_id = _mk_kb(client, admin_headers, "替换测试库")
    try:
        # 旧版（含独有内容，便于检索断言）
        old_id = _upload_and_vectorize_doc(
            client, admin_headers, kb_id, "policy.md", "# 旧版\n旧版内容鹭鸶荷"
        )
        # 新版：显式替换意图
        up = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs",
            headers=admin_headers,
            data={"supersedes_doc_id": old_id, "version_no": "2024 版"},
            files={"file": ("policy.md", "# 新版\n新版内容鹭鸶荷".encode(), "text/markdown")},
        )
        assert up.status_code == 201, up.text
        new_id = up.json()["id"]
        assert up.json()["supersedes_doc_id"] == old_id
        client.post(f"/api/v1/docs/{new_id}/vectorize", headers=admin_headers)
        assert _wait(client, admin_headers, new_id) == "completed"

        old = client.get(f"/api/v1/docs/{old_id}", headers=admin_headers).json()
        assert old["superseded_by"] == new_id, "旧文档应标记废止"
        # 文档行保留（PG 历史）——经由详情端点可访问
        assert client.get(f"/api/v1/docs/{old_id}", headers=admin_headers).status_code == 200
        # （PG 分块清除不直接断言：同步测试里 asyncio.run 直连模块级引擎
        #   会串事件循环；ES 清除 + 标记 + 检索行为已覆盖 spec 测试策略要求）

        # ES：旧版内容检索不到，新版内容检索得到
        hits = client.post(
            "/api/v1/search",
            json={"query": "鹭鸶荷", "kb_id": kb_id, "top_k": 10},
            headers=admin_headers,
        ).json()
        names = {h["doc_name"] for h in hits}
        assert "policy.md" in names  # 新版在
        contents = " ".join(h["content"] for h in hits)
        assert "旧版内容" not in contents, "旧分块必须从 ES 物理清除"
    finally:
        client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=admin_headers)


def test_supersede_not_applied_when_vectorize_fails(client, admin_headers):
    """新文档向量化失败 → 旧文档保持现行（知识不断档）。"""
    kb_id = _mk_kb(client, admin_headers, "替换失败保护测试库")
    try:
        old_id = _upload_and_vectorize_doc(
            client, admin_headers, kb_id, "keep.md", "# 旧版\n保持现行秋石斛"
        )
        # 空内容 → 解析失败
        up = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs",
            headers=admin_headers,
            data={"supersedes_doc_id": old_id},
            files={"file": ("keep.md", b"", "text/markdown")},
        )
        new_id = up.json()["id"]
        client.post(f"/api/v1/docs/{new_id}/vectorize", headers=admin_headers)
        assert _wait(client, admin_headers, new_id) == "failed"

        old = client.get(f"/api/v1/docs/{old_id}", headers=admin_headers).json()
        assert old["superseded_by"] is None, "失败时旧文档不得标记废止"
        hits = client.post(
            "/api/v1/search",
            json={"query": "保持现行", "kb_id": kb_id, "top_k": 10},
            headers=admin_headers,
        ).json()
        assert any(h["doc_name"] == "keep.md" for h in hits), "旧文档必须仍可检索"
    finally:
        client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=admin_headers)


def test_upload_rejects_invalid_supersedes_target(client, admin_headers):
    """替换目标必须存在、同库且现行——400，不能带病入库。"""
    kb_a = _mk_kb(client, admin_headers, "替换校验库A")
    kb_b = _mk_kb(client, admin_headers, "替换校验库B")
    try:
        other = client.post(
            f"/api/v1/knowledge-bases/{kb_b}/docs",
            headers=admin_headers,
            files={"file": ("x.md", "# x\n异库目标雪见草".encode(), "text/markdown")},
        ).json()
        # 异库目标 → 400
        r = client.post(
            f"/api/v1/knowledge-bases/{kb_a}/docs",
            headers=admin_headers,
            data={"supersedes_doc_id": other["id"]},
            files={"file": ("y.md", "# y\n同名校验雪见草".encode(), "text/markdown")},
        )
        assert r.status_code == 400, r.text
        # 不存在目标 → 400
        r2 = client.post(
            f"/api/v1/knowledge-bases/{kb_a}/docs",
            headers=admin_headers,
            data={"supersedes_doc_id": "00000000-0000-0000-0000-000000000000"},
            files={"file": ("z.md", "# z\n不存在目标雪见草".encode(), "text/markdown")},
        )
        assert r2.status_code == 400, r2.text
        # 已废止目标 → 400（经真实替换流程造出废止状态，全 HTTP、不直连 DB）
        dead = _upload_and_vectorize_doc(
            client, admin_headers, kb_a, "dead.md", "# 旧\n废止目标雪见草"
        )
        live_up = client.post(
            f"/api/v1/knowledge-bases/{kb_a}/docs",
            headers=admin_headers,
            data={"supersedes_doc_id": dead},
            files={"file": ("live.md", "# 新\n现行目标雪见草".encode(), "text/markdown")},
        ).json()
        client.post(f"/api/v1/docs/{live_up['id']}/vectorize", headers=admin_headers)
        assert _wait(client, admin_headers, live_up["id"]) == "completed"
        dead_doc = client.get(f"/api/v1/docs/{dead}", headers=admin_headers).json()
        assert dead_doc["superseded_by"] is not None  # 前置成立
        r3 = client.post(
            f"/api/v1/knowledge-bases/{kb_a}/docs",
            headers=admin_headers,
            data={"supersedes_doc_id": dead},
            files={"file": ("w.md", "# w\n重复替换雪见草".encode(), "text/markdown")},
        )
        assert r3.status_code == 400, r3.text
    finally:
        client.delete(f"/api/v1/knowledge-bases/{kb_a}", headers=admin_headers)
        client.delete(f"/api/v1/knowledge-bases/{kb_b}", headers=admin_headers)
```

**辅助函数**（同文件顶部 fixtures 之后追加，Task 4 两个测试用）：

```python
def _upload_and_vectorize_doc(client, headers, kb_id, name, content) -> str:
    up = client.post(
        f"/api/v1/knowledge-bases/{kb_id}/docs",
        headers=headers,
        files={"file": (name, content.encode("utf-8"), "text/markdown")},
    )
    assert up.status_code == 201, up.text
    doc_id = up.json()["id"]
    client.post(f"/api/v1/docs/{doc_id}/vectorize", headers=headers)
    assert _wait(client, headers, doc_id) == "completed"
    return doc_id
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/test_doc_governance.py -v`
Expected: FAIL — `assert old["superseded_by"] == new_id`（None ≠ new_id）与 400 断言失败（当前不校验）

- [ ] **Step 3: 实现**

`backend/app/api/v1/documents.py` `upload_document` 中，`Document(...)` 构造**之前**加校验：

```python
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
```

`backend/app/services/vectorizer.py`：加应用函数（放在 `trigger_vectorization` 之后），并在 `_run_vectorize` 的 `_do_vectorize` 成功之后调用：

```python
async def _apply_supersede(db, new_doc: Document) -> None:
    """向量化成功后应用替换：清旧分块（先 ES 后 PG）→ 标记废止。

    任何一步失败都不标记（旧文档保持现行，fail-open）；ES 清理失败只告警不抛，
    因为此时旧内容仍可检索、知识未断档，重触发新版向量化可重试。
    """
    old = await db.get(Document, new_doc.supersedes_doc_id)
    if old is None or old.superseded_by is not None:
        logger.warning(
            "supersede target %s missing or already superseded, skip",
            new_doc.supersedes_doc_id,
        )
        return
    # 1) ES 物理清除旧分块
    try:
        es = get_es()
        await es.delete_by_query(
            index=_settings.es_index,
            query={"term": {"doc_id": str(old.id)}},
            refresh=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("supersede ES purge failed for %s: %s", old.id, exc)
        return
    # 2) PG 分块级联删 + 标记废止（同一事务）
    await db.execute(delete(DocumentChunk).where(DocumentChunk.doc_id == old.id))
    old.superseded_by = new_doc.id
    await db.commit()


# _run_vectorize 中，await _do_vectorize(db, doc) 成功之后、except 之前插入：
        try:
            await _do_vectorize(db, doc)
            if doc.supersedes_doc_id:
                await _apply_supersede(db, doc)
        except Exception as exc:
            ...（既有失败处理不动）
```

（`_run_vectorize` 现有结构是 `try: await _do_vectorize(...) except ...`——把 `if doc.superseded...` 那行放进 try 内 `_do_vectorize` 之后即可。`DocumentChunk`/`delete`/`get_es` 均已在该文件 import。
边界说明：若 `_apply_supersede` 抛异常，外层 except 会把新文档标为 failed——此时旧文档可能已被清除分块但未标记（或反之），重触发新版向量化即可自愈（`_do_vectorize` 幂等、`_apply_supersede` 对已标记目标跳过）；这是可恢复状态，不额外加事务。）

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && python -m pytest tests/test_doc_governance.py -v`
Expected: PASS（8 项全绿：原 5 + 本任务新增 3——purge / 失败保护 / 非法目标 400）

- [ ] **Step 5: 全量回归后提交**

Run: `cd backend && python -m pytest -q`
Expected: 110 passed（107 + 3）, 57 warnings

```bash
git add backend/app/api/v1/documents.py backend/app/services/vectorizer.py \
        backend/tests/test_doc_governance.py
git commit -m "feat(docs): atomic supersede on vectorize success with fail-open protection"
```

---

### Task 5: 机制三——context 时效标注与多来源提示

**Files:**
- Modify: `backend/app/services/rag/langgraph/nodes.py`（evaluate_node 的 context 构造）
- Modify: `backend/app/services/search/hybrid.py`（_hit_to_result 带出时效字段）
- Modify: `backend/app/schemas/document.py`（SearchResultOut 增字段）
- Test: `backend/tests/test_governance_prompt.py`（新建）

**Interfaces:**
- Consumes: Task 2 的 ES metadata（`valid_from`/`version_no` 经 `_hit_to_result` 到达 chunk dict）
- Produces: context 行格式 `……《名》（version_no，生效valid_from）：内容`（有字段才加）；`doc_count >= 2` 时 context 末尾追加提示行（常量 `MULTI_SOURCE_NOTICE`）

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_governance_prompt.py
"""机制三：context 时效标注与多来源提示。纯节点测试，无需容器。"""
import asyncio

from app.services.rag.langgraph import nodes


def _chunk(doc_id, doc_name, content, version_no=None, valid_from=None, score=0.95):
    # score 0.95：高于 relevance_threshold 的任何配置值（0.02/0.30），
    # 保证走 rrf_ok 分支、无需 embedding provider
    return {
        "doc_id": doc_id, "doc_name": doc_name, "title": None,
        "content": content, "score": score, "content_vector": None,
        "version_no": version_no, "valid_from": valid_from,
    }


def test_context_line_carries_version_and_validity():
    chunks = [_chunk("d1", "学籍管理规定.docx", "旧规内容",
                     version_no="2023 版", valid_from="2023-09-01")]
    state = {"question": "q", "retrieved_chunks": chunks}
    out = asyncio.run(nodes.evaluate_node(state))
    assert out["has_relevant_content"] is True
    line = out["context"]
    assert "《学籍管理规定.docx》" in line
    assert "2023 版" in line
    assert "生效2023-09-01" in line
    assert "旧规内容" in line


def test_context_without_meta_unchanged_format():
    chunks = [_chunk("d1", "单文档.md", "普通内容")]
    out = asyncio.run(nodes.evaluate_node(
        {"question": "q", "retrieved_chunks": chunks}
    ))
    assert out["context"] == "[1] 《单文档.md》：普通内容"
    assert "提示" not in out["context"]


def test_multi_source_notice_appended():
    chunks = [
        _chunk("d1", "A办法.docx", "甲规定"),
        _chunk("d2", "B办法.docx", "乙规定"),
    ]
    out = asyncio.run(nodes.evaluate_node(
        {"question": "q", "retrieved_chunks": chunks}
    ))
    assert "资料来自多份文档" in out["context"]
    assert "生效日期较新者为准" in out["context"]


def test_single_source_no_notice_even_with_two_chunks():
    chunks = [
        _chunk("d1", "同文档.md", "甲"),
        _chunk("d1", "同文档.md", "乙"),
    ]
    out = asyncio.run(nodes.evaluate_node(
        {"question": "q", "retrieved_chunks": chunks}
    ))
    assert "资料来自多份文档" not in out["context"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && python -m pytest tests/test_governance_prompt.py -v`
Expected: FAIL — `AssertionError: '2023 版' not in ...`（当前 context 无版本信息）

- [ ] **Step 3: 实现**

`hybrid.py` `_hit_to_result` 返回 dict 追加三个键（`score` 之前）：

```python
        "version_no": meta.get("version_no"),
        "valid_from": meta.get("valid_from"),
        "valid_to": meta.get("valid_to"),
```

`nodes.py` 模块常量区（`_GREETINGS` 附近）加：

```python
MULTI_SOURCE_NOTICE = (
    "\n[提示] 以上资料来自多份文档，若规定不一致，请指出差异并以生效日期较新者为准。"
)
```

`evaluate_node` 的 context 构造改为（保持 `query` 变量逻辑不动，只换 `context = ...` 段）：

```python
    def _fmt(i: int, c: dict) -> str:
        name = c.get("title") or c.get("doc_name") or "资料"
        meta_parts = []
        if c.get("version_no"):
            meta_parts.append(c["version_no"])
        if c.get("valid_from"):
            meta_parts.append(f"生效{c['valid_from']}")
        meta = f"（{'，'.join(meta_parts)}）" if meta_parts else ""
        return f"[{i + 1}] 《{name}》{meta}：{c['content']}"

    lines = [_fmt(i, c) for i, c in enumerate(chunks[:3])]
    doc_ids = {c.get("doc_id") for c in chunks[:3] if c.get("doc_id")}
    context = "\n".join(lines)
    if len(doc_ids) >= 2:
        context += MULTI_SOURCE_NOTICE
    return {"has_relevant_content": rrf_ok or cos_ok, "context": context}
```

（原代码用 `title or doc_name` 与 `enumerate(chunks[:3])`——`_fmt` 保持同一取名顺序；原 context 行格式 `《x》：content` 与 `test_context_without_meta_unchanged_format` 的期望逐字一致。）

`schemas/document.py` 的 `SearchResultOut` 追加：

```python
    version_no: str | None = None
    valid_from: str | None = None
    valid_to: str | None = None
```

- [ ] **Step 3b: Mock 行头契约适配（机制三在 mock provider 下必须可用）**

`backend/app/services/llm/mock.py` 两处：

1. 行头正则放宽为**可选 meta 段**（原：`》` 后紧跟冒号；新：允许 `》（…）：`）：
```python
_HEADER_RE = r"^\[\d+\]\s*《([^》]*)》(?:（[^）]*）)?[：:]\s?(.*)$"
```
2. `_parse_blocks` 逐行循环中，在行头匹配判断**之前**跳过提示行：
```python
            if line.startswith("[提示]"):
                continue  # 冲突提示行不是块头也不是引用内容，不进 mock 回答
```
（按 mock.py 实际循环结构落位——`line.startswith` 判断放在 `re.match(_HEADER_RE, line)` 之前即可。）

同步文案两处：mock.py 模块 docstring 中的行头示例、`openai_adapter.py` 内 prompt 说明（`[n] 《资料标题》：内容` → `[n] 《资料标题》（可选版本/生效标注）：内容`）。

追加测试到 `backend/tests/test_governance_prompt.py`：

```python
def test_mock_parses_meta_header_and_skips_notice():
    """机制三兼容 mock provider：标注行按块头解析、提示行不进回答。"""
    import asyncio as _a

    from app.services.llm.mock import MockLLM

    prompt = (
        "[1] 《学籍管理规定》（2023 版，生效2023-09-01）：旧规内容\n"
        "[2] 《B办法》：乙规定\n"
        "\n[提示] 以上资料来自多份文档，若规定不一致，请指出差异并以生效日期较新者为准。"
        "\n\n问题：测试问题"
    )
    answer = _a.run(MockLLM().generate(prompt))
    assert "[提示]" not in answer, "提示行不应被 mock 引用进回答"
    assert "（2023 版，生效2023-09-01）" not in answer, "原始标注行不应被当正文引用"
    assert "学籍管理规定" in answer, "标注后的标题应仍被识别为块头"
```

（若 `MockLLM().generate` 的既有签名/输出形状与上述断言冲突，以真实实现调整断言——但三条语义必须保住：提示行不进回答、标注行不被当正文、标题仍识别。）

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && python -m pytest tests/test_governance_prompt.py -v`
Expected: PASS（5 项全绿）

- [ ] **Step 5: 全量回归后提交（注意既有 prompt 断言）**

Run: `cd backend && python -m pytest -q`
Expected: 117 passed（116 + 1 mock 兼容测试）；warnings 实报（基线 71）
（若 `test_run_rag_flow_prompt_contains_history` 或 `test_chat` 中断言受影响立即报告——它们的 fake chunks 不带 version/valid 字段，输出格式不变，理论上全绿）

```bash
git add backend/app/services/rag/langgraph/nodes.py backend/app/services/search/hybrid.py \
        backend/app/schemas/document.py backend/app/services/llm/mock.py \
        backend/app/services/llm/openai_adapter.py backend/tests/test_governance_prompt.py
git commit -m "feat(rag): version/validity in context and multi-source conflict notice"
```

---

### Task 6: 前端——效力徽章、同名替换弹窗、只看现行

**Files:**
- Modify: `frontend/src/types.ts`（DocumentItem 增字段）
- Modify: `frontend/src/api/kb.ts`（uploadDocument 增选项、listDocuments 增 activeOnly）
- Modify: `frontend/src/pages/KnowledgeBase.tsx`
- Modify: `backend/app/api/v1/documents.py`（list 增 `active_only` 查询参数）

**Interfaces:**
- Consumes: Task 1 DocumentOut 字段、Task 3 PUT（本任务不调 PUT，仅展示）
- Produces: `GET /knowledge-bases/{kb_id}/docs?active_only=true`（过滤 `superseded_by IS NULL`）；`uploadDocument(kbId, file, opts?)` opts = `{version_no?, valid_from?, valid_to?, supersedes_doc_id?}`

- [ ] **Step 1: 后端 list 增 active_only（先做，可单测）**

`backend/app/api/v1/documents.py` `list_documents` 签名与查询：

```python
async def list_documents(
    kb_id: uuid.UUID,
    search: str | None = Query(default=None),
    active_only: bool = Query(default=False, description="只看现行文档（superseded_by 为空）"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_permission("doc:read")),
):
    q = select(Document).where(Document.kb_id == kb_id)
    if active_only:
        q = q.where(Document.superseded_by.is_(None))
    ...
```

测试（追加到 `backend/tests/test_doc_governance.py`）：

```python
def test_list_active_only_filter(client, admin_headers):
    """active_only=true 只返回现行文档（经真实替换流程造废止态，全 HTTP）。"""
    kb_id = _mk_kb(client, admin_headers, "只看现行测试库")
    try:
        a = _upload_and_vectorize_doc(
            client, admin_headers, kb_id, "a.md", "# a\n只看现行甲"
        )
        b_up = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs",
            headers=admin_headers,
            data={"supersedes_doc_id": a},
            files={"file": ("b.md", "# b\n只看现行乙".encode(), "text/markdown")},
        ).json()
        client.post(f"/api/v1/docs/{b_up['id']}/vectorize", headers=admin_headers)
        assert _wait(client, admin_headers, b_up["id"]) == "completed"
        b = b_up["id"]

        all_docs = client.get(
            f"/api/v1/knowledge-bases/{kb_id}/docs", headers=admin_headers
        ).json()
        active = client.get(
            f"/api/v1/knowledge-bases/{kb_id}/docs",
            params={"active_only": True}, headers=admin_headers,
        ).json()
        ids_all = {d["id"] for d in all_docs}
        ids_active = {d["id"] for d in active}
        assert a in ids_all and b in ids_all          # 默认列表两个都展示
        assert a not in ids_active and b in ids_active  # active_only 隐藏已废止的 a
    finally:
        client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=admin_headers)
```

Run: `cd backend && python -m pytest tests/test_doc_governance.py::test_list_active_only_filter -v` → 先 FAIL（active_only 被忽略，a 出现在 active 列表）→ 实现 → PASS

- [ ] **Step 2: 前端类型与 API**

`frontend/src/types.ts` 的 `DocumentItem` 追加：

```ts
  valid_from?: string | null
  valid_to?: string | null
  version_no?: string | null
  superseded_by?: string | null
  supersedes_doc_id?: string | null
```

`frontend/src/api/kb.ts`：

```ts
export interface UploadDocOptions {
  version_no?: string
  valid_from?: string
  valid_to?: string
  supersedes_doc_id?: string
}

export async function listDocuments(
  kbId: string,
  search?: string,
  activeOnly?: boolean
): Promise<DocumentItem[]> {
  const res = await http.get<DocumentItem[]>(`/knowledge-bases/${kbId}/docs`, {
    params: { search, page_size: 100, active_only: activeOnly || undefined },
  })
  return res.data
}

export async function uploadDocument(
  kbId: string,
  file: File,
  opts?: UploadDocOptions
): Promise<DocumentItem> {
  const form = new FormData()
  form.append('file', file)
  if (opts?.version_no) form.append('version_no', opts.version_no)
  if (opts?.valid_from) form.append('valid_from', opts.valid_from)
  if (opts?.valid_to) form.append('valid_to', opts.valid_to)
  if (opts?.supersedes_doc_id) form.append('supersedes_doc_id', opts.supersedes_doc_id)
  const res = await http.post<DocumentItem>(`/knowledge-bases/${kbId}/docs`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return res.data
}
```

- [ ] **Step 3: KnowledgeBase.tsx 改动**

三处（全部给增量代码）：

**a) import 增**：`DatePicker`, `Switch`（antd）、`dayjs`：

```ts
import { /* 既有 import 列表中追加 */ Checkbox, DatePicker, Switch } from 'antd'
import dayjs from 'dayjs'
```

**b) 组件状态与处理函数**（`const [search, setSearch] = useState('')` 附近增）：

```ts
  const [activeOnly, setActiveOnly] = useState(false)
  const [versionModal, setVersionModal] = useState<{
    open: boolean
    file: File | null
    existing: DocumentItem | null
  }>({ open: false, file: null, existing: null })
  const [versionForm, setVersionForm] = useState({
    replace: true,
    version_no: '',
    valid_from: undefined as dayjs.Dayjs | undefined,
    valid_to: undefined as dayjs.Dayjs | undefined,
  })
```

`loadDocs` 增第三个参数并传 activeOnly：

```ts
  const loadDocs = useCallback(async (kbId: string, q?: string, active?: boolean) => {
    setLoading(true)
    try {
      const data = await listDocuments(kbId, q, active)
      setDocs(data)
    } catch (e) {
      message.error(getErrorMessage(e))
    } finally {
      setLoading(false)
    }
  }, [])
```

依赖它的调用点改为 `loadDocs(selectedKbId, search || undefined, activeOnly)`（两处：useEffect 与 search 回车）+ 新增：

```ts
  useEffect(() => {
    if (selectedKbId) loadDocs(selectedKbId, search || undefined, activeOnly)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedKbId, activeOnly])
```

`handleUpload` 改为同名检测 + 弹窗分流：

```ts
  const doUpload = async (file: File, opts?: UploadDocOptions) => {
    if (!selectedKbId) return
    try {
      await uploadDocument(selectedKbId, file, opts)
      message.success(`「${file.name}」上传成功`)
      loadDocs(selectedKbId, search || undefined, activeOnly)
    } catch (e) {
      message.error(getErrorMessage(e))
    }
  }

  const handleUpload = async (file: File) => {
    if (!selectedKbId) return false
    const existing = docs.find(
      (d) => d.original_name === file.name && !d.superseded_by
    )
    if (existing) {
      setVersionModal({ open: true, file, existing })
      return false
    }
    await doUpload(file)
    return false
  }

  const handleVersionOk = async () => {
    const { file, existing } = versionModal
    if (!file || !selectedKbId) { setVersionModal({ open: false, file: null, existing: null }); return }
    const opts: UploadDocOptions = {
      version_no: versionForm.version_no || undefined,
      valid_from: versionForm.valid_from ? versionForm.valid_from.format('YYYY-MM-DD') : undefined,
      valid_to: versionForm.valid_to ? versionForm.valid_to.format('YYYY-MM-DD') : undefined,
      supersedes_doc_id: versionForm.replace && existing ? existing.id : undefined,
    }
    await doUpload(file, opts)
    setVersionModal({ open: false, file: null, existing: null })
    setVersionForm({ replace: true, version_no: '', valid_from: undefined, valid_to: undefined })
  }
```

（`UploadDocOptions` 需从 `../api/kb` import。`handleUpload` 原 body 删除。）

**c) 表格列与开关**（`columns` 的「状态」列后插「效力」列；Card extra 的 Upload 按钮前插 Switch）：

```ts
    {
      title: '效力', key: 'governance', width: 210,
      render: (_: unknown, doc: DocumentItem) => (
        <Space direction="vertical" size={2}>
          {doc.superseded_by
            ? <Tag color="red">已废止</Tag>
            : <Tag color="green">现行</Tag>}
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {doc.version_no ? `${doc.version_no} · ` : ''}
            {doc.valid_from || doc.valid_to
              ? `${doc.valid_from ?? '…'} ~ ${doc.valid_to ?? '…'}`
              : '长期有效'}
          </Typography.Text>
        </Space>
      ),
    },
```

Card extra（Search Input 之前）：

```tsx
              <Space>
                <Switch
                  size="small"
                  checked={activeOnly}
                  onChange={(v) => { setActiveOnly(v); if (selectedKbId) loadDocs(selectedKbId, search || undefined, v) }}
                />
                <Typography.Text type="secondary">只看现行</Typography.Text>
              </Space>
```

文件末尾（`</Drawer>` 之后、`</Row>` 之前）加版本弹窗：

```tsx
      <Modal
        title={`检测到同名文档：${versionModal.existing?.original_name ?? ''}`}
        open={versionModal.open}
        onOk={handleVersionOk}
        onCancel={() => setVersionModal({ open: false, file: null, existing: null })}
        okText="上传"
      >
        <Form layout="vertical" style={{ marginTop: 12 }}>
          <Form.Item>
            <Typography.Paragraph type="secondary">
              知识库中已有同名且现行的文档。勾选替换后，新文档向量化成功时旧版将自动废止并清除其检索分块。
            </Typography.Paragraph>
          </Form.Item>
          <Form.Item label="版本信息">
            <Space.Compact block>
              <Checkbox
                checked={versionForm.replace}
                onChange={(e) => setVersionForm((f) => ({ ...f, replace: e.target.checked }))}
              >
                作为新版本替换旧文档
              </Checkbox>
            </Space.Compact>
          </Form.Item>
          <Form.Item label="版本号">
            <Input
              placeholder="如：2024 版"
              value={versionForm.version_no}
              onChange={(e) => setVersionForm((f) => ({ ...f, version_no: e.target.value }))}
            />
          </Form.Item>
          <Form.Item label="生效 / 失效日期（可选）">
            <Space.Compact block>
              <DatePicker
                style={{ width: '50%' }}
                value={versionForm.valid_from}
                onChange={(v) => setVersionForm((f) => ({ ...f, valid_from: v ?? undefined }))}
              />
              <DatePicker
                style={{ width: '50%' }}
                value={versionForm.valid_to}
                onChange={(v) => setVersionForm((f) => ({ ...f, valid_to: v ?? undefined }))}
              />
            </Space.Compact>
          </Form.Item>
        </Form>
      </Modal>
```

（antd `Checkbox` 需加入 import。`Space.Compact` 包 Checkbox 可简化为直接 `<Checkbox>`，实现时若样式冗余可去掉外层 Compact——语义不变。）

- [ ] **Step 4: 前端构建验证 + 后端回归**

Run: `cd frontend && npm run build`
Expected: tsc 零错误 + vite build 成功

Run: `cd backend && python -m pytest -q`
Expected: 115 passed（114 + 1）, 57 warnings

- [ ] **Step 5: Commit**

```bash
git add frontend/src/types.ts frontend/src/api/kb.ts frontend/src/pages/KnowledgeBase.tsx \
        backend/app/api/v1/documents.py backend/tests/test_doc_governance.py
git commit -m "feat(web): governance badges, same-name version dialog, active-only filter"
```

---

### Task 7: API.md 同步 + Phase 2 实跑验收

**Files:**
- Modify: `API.md`（documents/search 两节）
- Create: `backend/evals/results/<日期>-phase2-governance.{json,md}`（命令生成）

**Interfaces:**
- Consumes: Task 3 PUT、Task 1 上传字段、Task 6 active_only、既有 `python -m evals.run_eval`

- [ ] **Step 1: API.md 更新**

「文档 documents」表格：`POST /knowledge-bases/{kb_id}/docs` 行说明追加 `（可选 form 字段 version_no/valid_from/valid_to/supersedes_doc_id——同名替换意图）`；表格末尾加一行：

```markdown
| PUT | `/docs/{id}` | `doc:update` | 更新时效/版本（body: valid_from/valid_to/version_no，null=清除；非法区间 400；同步 ES metadata） |
```

「检索 search」行说明末尾追加：`；结果含 version_no/valid_from/valid_to，检索按文档时效过滤（valid_from ≤ 今天 ≤ valid_to，缺字段不命中）`

「GET `/knowledge-bases/{kb_id}/docs`」行说明追加：`；支持 active_only=true 只看现行`

- [ ] **Step 2: 数据准备——给 2023 版设置失效日期（评测场景构造，经由正式 API）**

Run（一次性脚本，backend/ 下执行）：

```bash
cd backend && PYTHONIOENCODING=utf-8 python -c "
from fastapi.testclient import TestClient
from app.main import app

with TestClient(app) as c:
    tok = c.post('/api/v1/auth/login', json={'username': 'admin', 'password': 'admin123'}).json()['access_token']
    h = {'Authorization': f'Bearer {tok}'}
    kbs = c.get('/api/v1/knowledge-bases', headers=h).json()
    kb_id = next(k['id'] for k in kbs if k['name'] == '评测库')
    docs = c.get(f'/api/v1/knowledge-bases/{kb_id}/docs', params={'search': '请假管理办法_2023版', 'page_size': 50}, headers=h).json()
    target = next(d for d in docs if d['original_name'] == '请假管理办法_2023版.md')
    r = c.put(f\"/api/v1/docs/{target['id']}\", json={'valid_to': '2026-10-05'}, headers=h)
    print(r.status_code, r.json())
    assert r.status_code == 200
    hits = c.post('/api/v1/search', json={'query': '学生请假最多能请几天', 'kb_id': kb_id, 'top_k': 5}, headers=h).json()
    names = [x['doc_name'] for x in hits]
    print('sources:', names)
    assert '请假管理办法_2023版.md' not in names, f'2023 版仍可检索: {names}'
    print('OK: 2023 版已失效且检索排除')
"
```

Expected: `200 {...}`、sources 不含 2023 版、末行 OK

- [ ] **Step 3: 回填确认 + 实跑 governance 对比（需 PG+ES+真实模型）**

Run: `cd backend && python -m scripts.backfill_validity`（幂等，updated 可为 0）
Run: `cd backend && PYTHONIOENCODING=utf-8 python -m evals.run_eval --tag phase2 --dataset governance`
Expected: 生成 `results/<日期>-phase2-governance.{json,md}`；`multi_turn_mode` 不适用（governance 无此字段，单轮数据集）

- [ ] **Step 4: 验收核对（spec §5.6）**

Run: `cat backend/evals/results/*-phase2-governance.md`
Expected（如实记录，不许调数据）:
- **keyword_rate：基线 50% → 期望 100%**（gv-01 不再引用「3天」）
- **Hit@3 的来源首位：旧版 → 新版**（2024 版）
- judge 若提升一并记录；未达期望 → 报告 BLOCKED 并给检索来源证据，不得重跑凑数

- [ ] **Step 5: 全量回归 + 前端构建后提交**

Run: `cd backend && python -m pytest -q` → 115 passed, 57 warnings
Run: `cd frontend && npm run build` → 成功

```bash
git add API.md backend/evals/results
git commit -m "feat(eval): Phase 2 governance comparison results and API docs"
```

---

## 完成定义

- [ ] 迁移 `a9c3e5f7b2d1` 已应用（alembic current 正确），`documents` 5 个可空列就位
- [ ] 上传带版本/时效字段、PUT 更新 + ES 同步、`active_only` 过滤均有测试
- [ ] 替换：成功 → 旧版废止+双库分块清除；失败 → 旧版保持现行（测试钉死）
- [ ] 严格时效过滤 + 回填脚本幂等（测试钉住「缺字段被排除、回填恢复」）
- [ ] context 带版本/时效，≥2 文档加冲突提示（测试钉死）；单文档格式逐字不变
- [ ] 前端：效力徽章、同名替换弹窗（含版本/日期/替换勾选）、只看现行开关；`npm run build` 零错误
- [ ] `governance` 实跑：keyword 50%→100%、来源首位旧版→新版（结果文件已 commit）；未达标按 BLOCKED 上报
- [ ] 全量 `pytest` 115 passed（99 基线 + 16 新增），`API.md` 已同步
