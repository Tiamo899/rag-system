# backend/evals/setup_dataset.py
"""幂等建立评测库：20 份演示 docx + 2 份版本冲突 md，全部向量化。

用法（backend/ 目录下，需 PG+ES 运行、.env 已配真实模型）：
    python -m evals.setup_dataset
"""
import asyncio
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
EVAL_KB_NAME = "评测库"
EVAL_CHUNK_SIZE = 500

sys.path.insert(0, str(BACKEND_DIR))


def discover_corpus(base_dir: Path | None = None) -> list[Path]:
    """演示 docx（20）+ 冲突 md（2），排序稳定、去重。"""
    root = base_dir or PROJECT_DIR
    campus = root / "knowledge_base_docs_campus"
    eval_docs = root / "backend" / "evals" / "docs"
    files = sorted(list(campus.rglob("*.docx")) + list(eval_docs.glob("*.md")))
    seen: set[Path] = set()
    out = []
    for p in files:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def find_eval_kb(client, headers: dict) -> dict | None:
    # 列表接口无分页，直接返回全部（knowledge_bases.py: GET ""）
    r = client.get("/api/v1/knowledge-bases", headers=headers)
    for kb in r.json():
        if kb.get("name") == EVAL_KB_NAME:
            return kb
    return None


def _login(client) -> dict:
    from app.core.config import get_settings

    settings = get_settings()
    r = client.post(
        "/api/v1/auth/login",
        json={
            "username": settings.default_admin_username,
            "password": settings.default_admin_password,
        },
    )
    assert r.status_code == 200, f"登录失败: {r.text}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _wait_completed(client, headers, doc_id, timeout=120) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = client.get(f"/api/v1/docs/{doc_id}", headers=headers).json()["status"]
        if st in ("completed", "failed"):
            return st
        time.sleep(0.5)
    return "timeout"


def _upload_one(client, headers, kb_id, path: Path) -> str:
    """上传并等向量化完成，返回状态。已存在同名且 completed 则跳过。"""
    existing = client.get(
        f"/api/v1/knowledge-bases/{kb_id}/docs",
        params={"search": path.name, "page_size": 50},
        headers=headers,
    ).json()
    for d in existing:
        if d["original_name"] == path.name and d["status"] == "completed":
            return "completed"

    content_type = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if path.suffix == ".docx"
        else "text/markdown"
    )
    up = client.post(
        f"/api/v1/knowledge-bases/{kb_id}/docs",
        headers=headers,
        files={"file": (path.name, path.read_bytes(), content_type)},
    )
    assert up.status_code == 201, f"上传 {path.name} 失败: {up.text}"
    doc_id = up.json()["id"]
    r = client.post(f"/api/v1/docs/{doc_id}/vectorize", headers=headers)
    assert r.status_code == 202, f"触发向量化失败: {r.text}"
    return _wait_completed(client, headers, doc_id)


def main() -> int:
    corpus = discover_corpus()
    print(f"语料 {len(corpus)} 份")
    with TestClient(app=__import__("app.main", fromlist=["app"]).app) as client:
        headers = _login(client)
        kb = find_eval_kb(client, headers)
        if kb is None:
            r = client.post(
                "/api/v1/knowledge-bases",
                json={"name": EVAL_KB_NAME, "chunk_size": EVAL_CHUNK_SIZE},
                headers=headers,
            )
            assert r.status_code == 201, r.text
            kb = r.json()
            print(f"创建评测库 {kb['id']}")
        else:
            print(f"复用已有评测库 {kb['id']}")

        failed = []
        for i, path in enumerate(corpus, 1):
            st = _upload_one(client, headers, kb["id"], path)
            print(f"[{i}/{len(corpus)}] {path.name} -> {st}")
            if st != "completed":
                failed.append(path.name)

    if failed:
        print(f"失败: {failed}")
        return 1
    print(f"评测库就绪 kb_id={kb['id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
