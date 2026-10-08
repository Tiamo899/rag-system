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


def test_upload_version_no_too_long_422(client, admin_headers):
    """超长 version_no 被 422 拒绝，不落库不 500。"""
    kb_id = _mk_kb(client, admin_headers, "版本号边界测试库")
    try:
        r = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs",
            headers=admin_headers,
            data={"version_no": "x" * 51},
            files={"file": ("b.md", "# b\n版本边界土人参".encode(), "text/markdown")},
        )
        assert r.status_code == 422, r.status_code
    finally:
        client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=admin_headers)
