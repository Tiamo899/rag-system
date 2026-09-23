"""M4 向量化 + 混合检索验收测试。需要 PG/ES 容器运行。"""
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app

MARKDOWN_SAMPLE = """# 第一章 RAG 介绍
检索增强生成（RAG）结合检索与生成。

## 1.1 FastAPI 后端
后端使用 FastAPI 框架，配合 LangGraph 工作流编排。

## 1.2 混合检索
系统支持向量检索与关键词检索，用 RRF 融合排序。

# 第二章 Elasticsearch
使用 Elasticsearch 存储向量与文本。
"""


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


def _wait_status(client, headers, doc_id, timeout=20) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get(
            f"/api/v1/docs/{doc_id}", headers=headers
        ).json()["status"]
        if status in ("completed", "failed"):
            return status
        time.sleep(0.25)
    return "timeout"


def test_vectorize_and_hybrid_search(client, admin_headers):
    # 1. 建库
    kb = client.post(
        "/api/v1/knowledge-bases",
        json={"name": "检索测试库", "chunk_size": 200, "chunk_overlap": 20},
        headers=admin_headers,
    ).json()
    kb_id = kb["id"]

    # 2. 上传并向量化
    up = client.post(
        f"/api/v1/knowledge-bases/{kb_id}/docs",
        headers=admin_headers,
        files={"file": ("rag.md", MARKDOWN_SAMPLE.encode("utf-8"), "text/markdown")},
    )
    assert up.status_code == 201, up.text
    doc_id = up.json()["id"]

    r = client.post(f"/api/v1/docs/{doc_id}/vectorize", headers=admin_headers)
    assert r.status_code == 202, r.text

    status = _wait_status(client, admin_headers, doc_id)
    assert status == "completed", f"向量化未完成: {status}"

    doc = client.get(f"/api/v1/docs/{doc_id}", headers=admin_headers).json()
    assert doc["chunk_count"] > 0
    assert doc["status"] == "completed"

    # 3. 混合检索：相关文档应排在前面
    q = client.post(
        "/api/v1/search",
        json={"query": "FastAPI 后端工作流", "kb_id": kb_id, "top_k": 5},
        headers=admin_headers,
    )
    assert q.status_code == 200, q.text
    results = q.json()
    assert len(results) > 0, "混合检索无结果"
    assert results[0]["doc_name"] == "rag.md"
    assert results[0]["score"] > 0
    assert any("FastAPI" in r["content"] for r in results)

    # 4. keyword / vector 两种模式
    kw = client.post(
        "/api/v1/search",
        json={"query": "Elasticsearch", "kb_id": kb_id, "search_type": "keyword"},
        headers=admin_headers,
    ).json()
    assert len(kw) > 0 and any("Elasticsearch" in r["content"] for r in kw)

    vec = client.post(
        "/api/v1/search",
        json={"query": "RAG 知识库", "kb_id": kb_id, "search_type": "vector"},
        headers=admin_headers,
    ).json()
    assert len(vec) > 0

    # 5. 删除文档后 ES 分块应清掉
    client.delete(f"/api/v1/docs/{doc_id}", headers=admin_headers)
    q2 = client.post(
        "/api/v1/search",
        json={"query": "FastAPI", "kb_id": kb_id, "top_k": 5},
        headers=admin_headers,
    ).json()
    assert len(q2) == 0, "删除文档后 ES 仍有残留"

    client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=admin_headers)
