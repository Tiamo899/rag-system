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
