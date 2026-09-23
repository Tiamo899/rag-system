"""M1 角色管理 API 测试。需要 PG/ES 容器运行。"""
import uuid

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
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _roles(client, headers) -> dict[str, dict]:
    resp = client.get("/api/v1/roles", headers=headers)
    assert resp.status_code == 200, resp.text
    return {r["name"]: r for r in resp.json()}


def test_list_roles_has_builtin(client, admin_headers):
    roles = _roles(client, admin_headers)
    for name in ("admin", "editor", "viewer"):
        assert name in roles, f"缺少内置角色 {name}"
    assert roles["admin"]["user_count"] >= 1  # admin 账号至少 1 人


def test_list_permissions_catalog(client, admin_headers):
    resp = client.get("/api/v1/roles/permissions", headers=admin_headers)
    assert resp.status_code == 200
    catalog = resp.json()
    modules = [g["key"] for g in catalog]
    assert modules == ["kb", "doc", "chat", "system"]
    keys = {p["key"] for g in catalog for p in g["permissions"]}
    assert "user:manage" in keys and "role:manage" in keys and "system:config" in keys


def test_create_and_update_role(client, admin_headers):
    tag = uuid.uuid4().hex[:8]
    resp = client.post(
        "/api/v1/roles",
        json={"name": f"op_{tag}", "description": "运营", "permissions": ["kb:read", "doc:read"]},
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    role = resp.json()
    role_id = role["id"]

    # 更新权限
    resp = client.put(
        f"/api/v1/roles/{role_id}",
        json={"permissions": ["kb:read", "doc:read", "chat:use"]},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert set(resp.json()["permissions"]) == {"kb:read", "doc:read", "chat:use"}

    # 删除（无用户引用）
    resp = client.delete(f"/api/v1/roles/{role_id}", headers=admin_headers)
    assert resp.status_code == 204


def test_create_role_invalid_permission(client, admin_headers):
    resp = client.post(
        "/api/v1/roles",
        json={"name": f"bad_{uuid.uuid4().hex[:8]}", "permissions": ["hack:all"]},
        headers=admin_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_PERMISSION"


def test_create_role_duplicate_name(client, admin_headers):
    resp = client.post(
        "/api/v1/roles",
        json={"name": "viewer", "permissions": []},
        headers=admin_headers,
    )
    assert resp.status_code == 409


def test_builtin_role_only_description(client, admin_headers):
    editor_id = _roles(client, admin_headers)["editor"]["id"]
    resp = client.put(
        f"/api/v1/roles/{editor_id}",
        json={"description": "编辑者-新描述"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text

    resp = client.put(
        f"/api/v1/roles/{editor_id}",
        json={"permissions": ["kb:read"]},
        headers=admin_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "BUILTIN_ROLE_FROZEN"

    resp = client.put(
        f"/api/v1/roles/{editor_id}",
        json={"name": "editor_x"},
        headers=admin_headers,
    )
    assert resp.status_code == 400


def test_delete_builtin_role_forbidden(client, admin_headers):
    viewer_id = _roles(client, admin_headers)["viewer"]["id"]
    resp = client.delete(f"/api/v1/roles/{viewer_id}", headers=admin_headers)
    assert resp.status_code == 400


def test_viewer_cannot_access_roles(client):
    tag = uuid.uuid4().hex[:8]
    uname = f"vroles_{tag}"
    client.post(
        "/api/v1/auth/register",
        json={"username": uname, "email": f"{uname}@test.com", "password": "pass123456"},
    )
    login = client.post(
        "/api/v1/auth/login", json={"username": uname, "password": "pass123456"}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    resp = client.get("/api/v1/roles", headers=headers)
    assert resp.status_code == 403
