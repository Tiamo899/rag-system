"""M3 系统配置 API 测试（只读展示）。需要 PG/ES 容器运行。"""
import uuid

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
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_list_real_configs(client, admin_headers):
    """GET 返回真实生效配置（来自 settings/.env），key 脱敏，含 .env 变量名。"""
    resp = client.get("/api/v1/system-configs", headers=admin_headers)
    assert resp.status_code == 200
    configs = {c["key"]: c for c in resp.json()}

    # 完整清单 12 项
    expected = {
        "llm.provider", "llm.api_key", "llm.base_url", "llm.model",
        "embedding.provider", "embedding.api_key", "embedding.base_url",
        "embedding.model", "embedding.dim", "relevance.threshold",
        "chunk.size", "chunk.overlap",
    }
    assert set(configs) == expected

    # 值来自 settings（conftest 强制 mock 环境）
    s = get_settings()
    assert configs["llm.model"]["value"] == s.llm_model
    assert configs["llm.provider"]["value"] == s.llm_provider
    assert configs["embedding.dim"]["value"] == str(s.embedding_dim)
    assert configs["relevance.threshold"]["value"] == str(s.relevance_threshold)

    # .env 变量名标注
    assert configs["llm.model"]["env_key"] == "LLM_MODEL"
    assert configs["embedding.dim"]["env_key"] == "EMBEDDING_DIM"
    assert configs["chunk.size"]["env_key"] is None
    assert configs["chunk.size"]["source"] == "default"

    # api_key 脱敏：conftest 下为空 → 未配置；绝不返回明文
    for k in ("llm.api_key", "embedding.api_key"):
        v = configs[k]["value"]
        assert "未配置" in v or "****" in v
        raw = s.llm_api_key if k == "llm.api_key" else s.embedding_api_key
        if raw:  # 空串不做成员判断（"" in v 恒为 True）
            assert raw not in v


def test_put_rejected(client, admin_headers):
    """PUT 一律 400：配置只读，引导到 .env。"""
    resp = client.put(
        "/api/v1/system-configs",
        json={"configs": [{"key": "llm.model", "value": "gpt-4o"}]},
        headers=admin_headers,
    )
    assert resp.status_code == 400
    assert "只读" in resp.json()["message"]


def test_viewer_cannot_access_configs(client):
    tag = uuid.uuid4().hex[:8]
    uname = f"vsc_{tag}"
    client.post(
        "/api/v1/auth/register",
        json={"username": uname, "email": f"{uname}@test.com", "password": "pass123456"},
    )
    login = client.post("/api/v1/auth/login", json={"username": uname, "password": "pass123456"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    resp = client.get("/api/v1/system-configs", headers=headers)
    assert resp.status_code == 403
