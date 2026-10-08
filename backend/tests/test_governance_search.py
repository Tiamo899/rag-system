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
