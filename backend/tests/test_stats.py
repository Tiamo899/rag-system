"""M4 概览统计接口测试。需要 PG/ES 容器运行。"""
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


def test_overview_structure(client, admin_headers):
    resp = client.get("/api/v1/stats/overview", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    for field in (
        "kb_total", "doc_total", "user_total", "today_chat_count",
        "recent_sessions", "kb_distribution", "doc_upload_trend",
    ):
        assert field in data, f"缺少字段 {field}"
    # trend 恒为 7 天
    assert len(data["doc_upload_trend"]) == 7
    # 时间格式 YYYY-MM-DD 且递增
    dates = [d["date"] for d in data["doc_upload_trend"]]
    assert dates == sorted(dates)
    assert all(len(d) == 10 for d in dates)
    # 至少存在一个知识库（用户数据）
    assert data["kb_total"] >= 1
    assert data["user_total"] >= 1


def test_viewer_can_view_overview(client):
    """概览对所有登录用户开放（kb:read 即可）。"""
    tag = uuid.uuid4().hex[:8]
    uname = f"vov_{tag}"
    client.post(
        "/api/v1/auth/register",
        json={"username": uname, "email": f"{uname}@test.com", "password": "pass123456"},
    )
    login = client.post("/api/v1/auth/login", json={"username": uname, "password": "pass123456"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    resp = client.get("/api/v1/stats/overview", headers=headers)
    assert resp.status_code == 200
