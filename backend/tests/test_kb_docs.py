"""M3 知识库 + 文档解析验收测试。需要 PG/ES 容器运行。"""
from pathlib import Path

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


@pytest.fixture(scope="module")
def sample_dir(tmp_path_factory) -> Path:
    """生成 4 种格式的样本文件。"""
    d = tmp_path_factory.mktemp("samples")

    (d / "sample.md").write_text(
        "# 第一章 系统介绍\n企业级 RAG 知识库系统支持混合检索。\n\n"
        "## 1.1 架构\nFastAPI 后端 + LangGraph 工作流。\n\n"
        "# 第二章 使用\n上传文档后触发向量化。\n",
        encoding="utf-8",
    )
    (d / "sample.txt").write_text(
        "这是第一段文本。\n\n这是第二段文本。\n", encoding="utf-8"
    )

    import docx

    doc = docx.Document()
    doc.add_paragraph("Word 文档第一段内容。")
    doc.add_paragraph("Word 文档第二段内容。")
    doc.save(str(d / "sample.docx"))

    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=12)
    pdf.cell(0, 10, "Hello RAG Knowledge System")
    pdf.output(str(d / "sample.pdf"))

    return d


def _upload(client, headers, kb_id, path: Path):
    with open(path, "rb") as f:
        resp = client.post(
            f"/api/v1/knowledge-bases/{kb_id}/docs",
            headers=headers,
            files={"file": (path.name, f, "application/octet-stream")},
        )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_kb_and_docs_full_flow(client, admin_headers, sample_dir):
    # 1. 创建知识库
    resp = client.post(
        "/api/v1/knowledge-bases",
        json={"name": "测试知识库", "description": "M3 验收"},
        headers=admin_headers,
    )
    assert resp.status_code == 201, resp.text
    kb = resp.json()
    kb_id = kb["id"]
    assert kb["chunk_size"] == 500

    # 2. 上传 4 种格式
    docs = {}
    for fname in ["sample.md", "sample.txt", "sample.docx", "sample.pdf"]:
        doc = _upload(client, admin_headers, kb_id, sample_dir / fname)
        docs[fname] = doc
        assert doc["status"] == "pending", fname

    # 3. 列表
    lst = client.get(
        f"/api/v1/knowledge-bases/{kb_id}/docs", headers=admin_headers
    )
    assert lst.status_code == 200
    assert len(lst.json()) == 4

    # 4. 搜索按文件名
    lst = client.get(
        f"/api/v1/knowledge-bases/{kb_id}/docs?search=sample",
        headers=admin_headers,
    )
    assert len(lst.json()) == 4
    lst = client.get(
        f"/api/v1/knowledge-bases/{kb_id}/docs?search=pdf",
        headers=admin_headers,
    )
    assert len(lst.json()) == 1

    # 5. 分块预览：md/txt/docx 应能抽出中文文本
    for fname, doc in docs.items():
        chunks = client.get(
            f"/api/v1/docs/{doc['id']}/chunks", headers=admin_headers
        )
        assert chunks.status_code == 200, f"{fname}: {chunks.text}"
        items = chunks.json()
        assert len(items) > 0, f"{fname} 分块为空"

    # md 预览应含标题内容
    md_chunks = client.get(
        f"/api/v1/docs/{docs['sample.md']['id']}/chunks", headers=admin_headers
    ).json()
    joined = "".join(c["content"] for c in md_chunks)
    assert "混合检索" in joined or "架构" in joined

    # 6. 删除一个文档，列表应少一个
    del_resp = client.delete(
        f"/api/v1/docs/{docs['sample.txt']['id']}", headers=admin_headers
    )
    assert del_resp.status_code == 204
    lst = client.get(
        f"/api/v1/knowledge-bases/{kb_id}/docs", headers=admin_headers
    )
    assert len(lst.json()) == 3

    # 7. 删除知识库
    resp = client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=admin_headers)
    assert resp.status_code == 204


def test_viewer_cannot_create_kb(client):
    username = "viewer3_test"
    client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@test.com",
            "password": "pass123456",
        },
    )
    login = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "pass123456"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    resp = client.post(
        "/api/v1/knowledge-bases", json={"name": "越权测试"}, headers=headers
    )
    assert resp.status_code == 403
