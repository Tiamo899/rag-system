"""知识库可见范围：接口权限 + 检索链路过滤。需要 PG/ES 容器运行。"""
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _login(client, username: str, password: str = "pass123456") -> dict:
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _make_user(client, admin_headers, role_name: str) -> tuple[str, dict]:
    tag = uuid.uuid4().hex[:8]
    uname = f"{role_name}_{tag}"
    role_id = next(
        r["id"]
        for r in client.get("/api/v1/roles", headers=admin_headers).json()
        if r["name"] == role_name
    )
    resp = client.post(
        "/api/v1/users",
        json={
            "username": uname,
            "email": f"{uname}@test.com",
            "password": "pass123456",
            "role_ids": [role_id],
            "status": 1,
        },
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"], _login(client, uname)


def _wait_indexed(client, headers, doc_id: str, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/api/v1/docs/{doc_id}", headers=headers)
        if resp.status_code == 200 and resp.json()["status"] in ("completed", "failed"):
            assert resp.json()["status"] == "completed", resp.text
            return
        time.sleep(0.5)
    raise AssertionError("文档向量化超时")


def test_kb_visibility_end_to_end(client):
    admin_headers = {
        "Authorization": "Bearer "
        + client.post(
            "/api/v1/auth/login", json={"username": "admin", "password": "admin123"}
        ).json()["access_token"]
    }
    viewer_id, viewer_headers = _make_user(client, admin_headers, "viewer")
    editor_id, editor_headers = _make_user(client, admin_headers, "editor")

    public_kb = client.post(
        "/api/v1/knowledge-bases",
        json={"name": f"公开库_{uuid.uuid4().hex[:6]}"},
        headers=admin_headers,
    ).json()
    restricted_kb = client.post(
        "/api/v1/knowledge-bases",
        json={
            "name": f"受限库_{uuid.uuid4().hex[:6]}",
            "visibility": "restricted",
            "allowed_roles": ["editor"],
        },
        headers=admin_headers,
    ).json()
    doc_id = None
    viewer_session_id = None
    scoped_kb_id = None
    try:
        # 1) 列表按可见范围过滤：viewer 看不到受限库，editor 能看到
        viewer_kbs = client.get("/api/v1/knowledge-bases", headers=viewer_headers).json()
        names = {k["name"] for k in viewer_kbs}
        assert public_kb["name"] in names
        assert restricted_kb["name"] not in names

        editor_kbs = client.get("/api/v1/knowledge-bases", headers=editor_headers).json()
        assert restricted_kb["name"] in {k["name"] for k in editor_kbs}

        admin_kbs = client.get("/api/v1/knowledge-bases", headers=admin_headers).json()
        assert restricted_kb["name"] in {k["name"] for k in admin_kbs}

        # 2) 直接访问受限库与非授权写入均被拒
        assert client.get(
            f"/api/v1/knowledge-bases/{restricted_kb['id']}", headers=viewer_headers
        ).status_code == 403
        resp = client.post(
            f"/api/v1/knowledge-bases/{restricted_kb['id']}/docs",
            headers=viewer_headers,
            files={"file": ("x.md", b"# t\ncontent", "text/markdown")},
        )
        assert resp.status_code == 403, resp.text

        # 3) 会话不能挂到无权知识库
        resp = client.post(
            "/api/v1/chat/sessions",
            json={"kb_id": restricted_kb["id"]},
            headers=viewer_headers,
        )
        assert resp.status_code == 403, resp.text

        # 3.5) 可见范围只接受真实角色/用户：手输脏数据直接 400
        resp = client.post(
            "/api/v1/knowledge-bases",
            json={"name": "脏角色库", "visibility": "restricted", "allowed_roles": ["不存在的角色"]},
            headers=editor_headers,
        )
        assert resp.status_code == 400 and resp.json()["code"] == "INVALID_ROLE", resp.text
        resp = client.post(
            "/api/v1/knowledge-bases",
            json={
                "name": "脏用户库",
                "visibility": "restricted",
                "allowed_users": ["00000000-0000-0000-0000-000000000000"],
            },
            headers=editor_headers,
        )
        assert resp.status_code == 400 and resp.json()["code"] == "INVALID_USER", resp.text

        # 3.6) 指定用户：viewer 被点名即可见，未被点名的 editor 反而不可见
        user_scoped_kb = client.post(
            "/api/v1/knowledge-bases",
            json={
                "name": f"点名库_{uuid.uuid4().hex[:6]}",
                "visibility": "restricted",
                "allowed_users": [viewer_id],
            },
            headers=admin_headers,
        ).json()
        scoped_ids = []
        scoped_kb_id = user_scoped_kb["id"]
        try:
            viewer_kbs = client.get("/api/v1/knowledge-bases", headers=viewer_headers).json()
            assert user_scoped_kb["id"] in {k["id"] for k in viewer_kbs}
            assert user_scoped_kb["id"] not in {
                k["id"] for k in client.get("/api/v1/knowledge-bases", headers=editor_headers).json()
            }
            assert client.get(
                f"/api/v1/knowledge-bases/{user_scoped_kb['id']}", headers=viewer_headers
            ).status_code == 200
            assert client.get(
                f"/api/v1/knowledge-bases/{user_scoped_kb['id']}", headers=editor_headers
            ).status_code == 403

            # 3.65) 设置可改且即时生效：viewer 无 kb:update 权限 → 403；
            # admin 把用户名额换成 editor 角色后，viewer 立刻失去访问，editor 获得访问
            assert client.put(
                f"/api/v1/knowledge-bases/{user_scoped_kb['id']}",
                json={"visibility": "restricted", "allowed_roles": ["editor"], "allowed_users": []},
                headers=viewer_headers,
            ).status_code == 403
            resp = client.put(
                f"/api/v1/knowledge-bases/{user_scoped_kb['id']}",
                json={"visibility": "restricted", "allowed_roles": ["editor"], "allowed_users": []},
                headers=admin_headers,
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["allowed_roles"] == ["editor"]
            assert resp.json()["allowed_users"] == []
            assert client.get(
                f"/api/v1/knowledge-bases/{user_scoped_kb['id']}", headers=viewer_headers
            ).status_code == 403
            assert client.get(
                f"/api/v1/knowledge-bases/{user_scoped_kb['id']}", headers=editor_headers
            ).status_code == 200
            # 再改回指定用户，验证双向切换
            resp = client.put(
                f"/api/v1/knowledge-bases/{user_scoped_kb['id']}",
                json={"visibility": "restricted", "allowed_roles": [], "allowed_users": [viewer_id]},
                headers=admin_headers,
            )
            assert resp.status_code == 200, resp.text
            assert client.get(
                f"/api/v1/knowledge-bases/{user_scoped_kb['id']}", headers=viewer_headers
            ).status_code == 200
        finally:
            scoped_ids.append(user_scoped_kb["id"])

        # 3.7) 可选项接口：角色人人可读；用户清单仅管理员下发
        viewer_opts = client.get(
            "/api/v1/knowledge-bases/access-options", headers=viewer_headers
        ).json()
        assert "admin" in viewer_opts["roles"] and viewer_opts["can_grant_users"] is False
        assert viewer_opts["users"] == []
        admin_opts = client.get(
            "/api/v1/knowledge-bases/access-options", headers=admin_headers
        ).json()
        assert admin_opts["can_grant_users"] is True and admin_opts["users"]

        # 4) 有权限的 editor 上传并向量化，作为检索过滤的真实数据
        token = f"VISIBILITY_ONLY_{uuid.uuid4().hex[:8]}"
        resp = client.post(
            f"/api/v1/knowledge-bases/{restricted_kb['id']}/docs",
            headers=editor_headers,
            files={
                "file": (
                    "受限制度.md",
                    f"# 受限制度\n\n{token} 仅限教务内部查阅。".encode(),
                    "text/markdown",
                )
            },
        )
        assert resp.status_code == 201, resp.text
        doc_id = resp.json()["id"]
        resp = client.post(f"/api/v1/docs/{doc_id}/vectorize", headers=admin_headers)
        assert resp.status_code == 202, resp.text
        _wait_indexed(client, admin_headers, doc_id)

        # 5) 检索过滤：viewer 查不到受限库内容，editor 查得到
        viewer_hits = client.post(
            "/api/v1/search", json={"query": token, "top_k": 5}, headers=viewer_headers
        ).json()
        assert all(token not in (h.get("content") or "") for h in viewer_hits)

        editor_hits = client.post(
            "/api/v1/search", json={"query": token, "top_k": 5}, headers=editor_headers
        ).json()
        assert any(token in (h.get("content") or "") for h in editor_hits)

        # 6) 问答链路同样不把受限内容送进上下文：viewer 应走兜底
        sid = client.post("/api/v1/chat/sessions", json={}, headers=viewer_headers).json()["id"]
        viewer_session_id = sid
        with client.stream(
            "POST",
            f"/api/v1/chat/sessions/{sid}/messages",
            json={"content": token},
            headers=viewer_headers,
        ) as stream:
            body = "".join(stream.iter_text())
        done_idx = body.rfind("event: done")
        assert done_idx != -1, body
        assert token not in body[done_idx:], body[done_idx:][:400]

        # 7) admin 不受限
        admin_hits = client.post(
            "/api/v1/search", json={"query": token, "top_k": 5}, headers=admin_headers
        ).json()
        assert any(token in (h.get("content") or "") for h in admin_hits)
    finally:
        if scoped_kb_id:
            client.delete(f"/api/v1/knowledge-bases/{scoped_kb_id}", headers=admin_headers)
        if viewer_session_id:
            client.delete(f"/api/v1/chat/sessions/{viewer_session_id}", headers=viewer_headers)
        if doc_id:
            client.delete(f"/api/v1/docs/{doc_id}", headers=admin_headers)
        client.delete(f"/api/v1/knowledge-bases/{restricted_kb['id']}", headers=admin_headers)
        client.delete(f"/api/v1/knowledge-bases/{public_kb['id']}", headers=admin_headers)
        for uid in (viewer_id, editor_id):
            client.delete(f"/api/v1/users/{uid}", headers=admin_headers)
