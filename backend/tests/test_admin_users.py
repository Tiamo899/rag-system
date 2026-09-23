"""M2 用户管理 API 测试。需要 PG/ES 容器运行。"""
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


def _viewer_role_id(client, headers) -> str:
    roles = client.get("/api/v1/roles", headers=headers).json()
    return next(r["id"] for r in roles if r["name"] == "viewer")


def test_user_crud_flow(client, admin_headers):
    tag = uuid.uuid4().hex[:8]
    uname = f"u_{tag}"
    email = f"{uname}@test.com"
    viewer_id = _viewer_role_id(client, admin_headers)

    # 创建（赋 viewer 角色）
    resp = client.post(
        "/api/v1/users",
        json={"username": uname, "email": email, "password": "pass123456",
              "role_ids": [viewer_id], "status": 1},
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    user = resp.json()
    user_id = user["id"]
    assert user["roles"] == ["viewer"]
    assert user["status"] == 1

    # 搜索命中
    resp = client.get(f"/api/v1/users?search={uname}", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1
    assert any(u["id"] == user_id for u in resp.json()["items"])

    # 局部更新：禁用
    resp = client.put(f"/api/v1/users/{user_id}", json={"status": 0}, headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == 0

    # 被禁用户再登录 → 401
    login = client.post("/api/v1/auth/login", json={"username": uname, "password": "pass123456"})
    assert login.status_code == 401

    # 重新启用 + 改密码
    resp = client.put(
        f"/api/v1/users/{user_id}",
        json={"status": 1, "password": "newpass789"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    login = client.post("/api/v1/auth/login", json={"username": uname, "password": "newpass789"})
    assert login.status_code == 200

    # 有用户引用的自定义角色禁止删除
    resp = client.post(
        "/api/v1/roles",
        json={"name": f"cust_{tag}", "permissions": ["kb:read"]},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    cust_role_id = resp.json()["id"]
    client.put(
        f"/api/v1/users/{user_id}",
        json={"role_ids": [viewer_id, cust_role_id]},
        headers=admin_headers,
    )
    resp = client.delete(f"/api/v1/roles/{cust_role_id}", headers=admin_headers)
    assert resp.status_code == 400
    assert resp.json()["code"] == "ROLE_IN_USE"

    # 删除用户后自定义角色可删
    resp = client.delete(f"/api/v1/users/{user_id}", headers=admin_headers)
    assert resp.status_code == 204
    resp = client.delete(f"/api/v1/roles/{cust_role_id}", headers=admin_headers)
    assert resp.status_code == 204


def test_create_user_duplicate(client, admin_headers):
    resp = client.post(
        "/api/v1/users",
        json={"username": "admin", "email": f"dup_{uuid.uuid4().hex[:8]}@test.com",
              "password": "pass123456", "role_ids": []},
        headers=admin_headers,
    )
    assert resp.status_code == 409


def test_cannot_disable_self(client, admin_headers):
    resp = client.get("/api/v1/users?search=admin&page_size=50", headers=admin_headers)
    admin_user = next(u for u in resp.json()["items"] if u["username"] == "admin")
    resp = client.put(
        f"/api/v1/users/{admin_user['id']}", json={"status": 0}, headers=admin_headers
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "SELF_DISABLE"


def test_cannot_delete_self_or_admin(client, admin_headers):
    resp = client.get("/api/v1/users?search=admin&page_size=50", headers=admin_headers)
    admin_user = next(u for u in resp.json()["items"] if u["username"] == "admin")
    resp = client.delete(f"/api/v1/users/{admin_user['id']}", headers=admin_headers)
    assert resp.status_code == 400
    assert resp.json()["code"] == "SELF_DELETE"


def test_non_admin_cannot_grant_admin_role(client, admin_headers):
    """拥有 user:manage 但无 *:* 的角色，授 admin 角色应被拒。"""
    tag = uuid.uuid4().hex[:8]
    # 建自定义角色 op（有 user:manage，无 *:*）
    resp = client.post(
        "/api/v1/roles",
        json={"name": f"op_{tag}", "permissions": ["user:manage"]},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    op_role_id = resp.json()["id"]
    admin_role_id = next(
        r["id"] for r in client.get("/api/v1/roles", headers=admin_headers).json()
        if r["name"] == "admin"
    )

    # 建 op 用户并赋 op 角色
    uname = f"opu_{tag}"
    resp = client.post(
        "/api/v1/users",
        json={"username": uname, "email": f"{uname}@test.com",
              "password": "pass123456", "role_ids": [op_role_id]},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    op_user_id = resp.json()["id"]

    # op 用户尝试授 admin 角色给新用户 → 403
    login = client.post("/api/v1/auth/login", json={"username": uname, "password": "pass123456"})
    op_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    resp = client.post(
        "/api/v1/users",
        json={"username": f"x_{tag}", "email": f"x_{tag}@test.com",
              "password": "pass123456", "role_ids": [admin_role_id]},
        headers=op_headers,
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "FORBIDDEN_ADMIN"

    # 清理
    client.delete(f"/api/v1/users/{op_user_id}", headers=admin_headers)
    client.delete(f"/api/v1/roles/{op_role_id}", headers=admin_headers)


def test_viewer_cannot_access_users(client):
    tag = uuid.uuid4().hex[:8]
    uname = f"vu_{tag}"
    client.post(
        "/api/v1/auth/register",
        json={"username": uname, "email": f"{uname}@test.com", "password": "pass123456"},
    )
    login = client.post("/api/v1/auth/login", json={"username": uname, "password": "pass123456"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    resp = client.get("/api/v1/users", headers=headers)
    assert resp.status_code == 403
