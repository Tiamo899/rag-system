"""M2 认证 + RBAC 验收测试。需要真实 PG/ES/Redis 容器运行。"""
import time

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.deps import require_permission
from app.main import app


@pytest.fixture(scope="module")
def client():
    # 挂载一个受保护探针路由到主 app，用于验证权限判定（须在 app 启动前添加）
    @app.get("/probe/doc-upload")
    def probe_route(_user=Depends(require_permission("doc:upload"))):
        return {"ok": True}

    with TestClient(app) as c:
        yield c


def test_login_admin_success(client):
    resp = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["access_token"] and data["refresh_token"]
    assert data["user"]["roles"] == ["admin"]


def test_me_without_token_401(client):
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401


def test_login_wrong_password_401(client):
    resp = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "wrong"}
    )
    assert resp.status_code == 401


def test_register_new_user_is_viewer(client):
    username = f"user_{int(time.time())}"
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@test.com",
            "password": "pass123456",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["user"]["roles"] == ["viewer"]
    return username


def test_refresh_token_flow(client):
    resp = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
    )
    refresh_token = resp.json()["refresh_token"]
    r2 = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert r2.status_code == 200
    assert r2.json()["access_token"]


def test_viewer_forbidden_doc_upload_403(client):
    username = f"user_{int(time.time())}"
    client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@test.com",
            "password": "pass123456",
        },
    )
    login = client.post(
        "/api/v1/auth/login", json={"username": username, "password": "pass123456"}
    )
    token = login.json()["access_token"]

    resp = client.get(
        "/probe/doc-upload", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 403

    # admin 有 *:*，应通过
    admin_login = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
    )
    admin_token = admin_login.json()["access_token"]
    resp_admin = client.get(
        "/probe/doc-upload", headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert resp_admin.status_code == 200
