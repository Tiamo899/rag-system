"""M5 LangGraph 问答 + SSE 验收测试。需要 PG/ES 容器运行。"""
import json
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app

MARKDOWN = """# RAG 系统
RAG 全称是检索增强生成。

## FastAPI
后端使用 FastAPI 框架搭建。

## LangGraph
问答工作流用 LangGraph 编排。
"""


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


@pytest.fixture(scope="module")
def prepared_kb(client, admin_headers):
    """建库 + 上传 + 向量化，返回 kb_id。"""
    kb = client.post(
        "/api/v1/knowledge-bases",
        json={"name": "问答测试库", "chunk_size": 100},
        headers=admin_headers,
    ).json()
    kb_id = kb["id"]
    doc = client.post(
        f"/api/v1/knowledge-bases/{kb_id}/docs",
        headers=admin_headers,
        files={"file": ("rag.md", MARKDOWN.encode("utf-8"), "text/markdown")},
    ).json()
    client.post(f"/api/v1/docs/{doc['id']}/vectorize", headers=admin_headers)
    for _ in range(40):
        st = client.get(f"/api/v1/docs/{doc['id']}", headers=admin_headers).json()["status"]
        if st in ("completed", "failed"):
            break
        time.sleep(0.25)
    assert st == "completed"
    yield kb_id
    client.delete(f"/api/v1/knowledge-bases/{kb_id}", headers=admin_headers)


def _parse_sse(body: str) -> list[dict]:
    """解析 SSE 文本为 [{event, data}]。data 为已解码 JSON 对象。"""
    # 帧分隔符可能是 CRLF\r\n\r\n，统一转成 \n\n 再切
    body = body.replace("\r\n", "\n")
    events: list[dict] = []
    for frame in body.split("\n\n"):
        lines = frame.strip().splitlines()
        if not lines:
            continue
        ev = None
        data = ""
        for line in lines:
            if line.startswith("event:"):
                ev = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data += line.split(":", 1)[1].strip()
        if data:
            try:
                events.append({"event": ev, "data": json.loads(data)})
            except json.JSONDecodeError:
                events.append({"event": ev, "data": data})
    return events


def _accumulate_text(events: list[dict]) -> str:
    return "".join(e["data"].get("text", "") for e in events if e["event"] == "token")


def _done_event(events: list[dict]) -> dict:
    for e in events:
        if e["event"] == "done":
            return e["data"]
    raise AssertionError("SSE 缺少 done 事件")


def _send(client, headers, session_id, content):
    resp = client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": content},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text[:300]
    return _parse_sse(resp.text)


def test_chat_rag_citation_flow(client, admin_headers, prepared_kb):
    kb_id = prepared_kb
    sess = client.post(
        "/api/v1/chat/sessions",
        json={"title": "测试会话", "kb_id": kb_id},
        headers=admin_headers,
    ).json()
    sid = sess["id"]

    events = _send(client, admin_headers, sid, "FastAPI 是什么框架？")
    events_names = [e["event"] for e in events]
    assert "start" in events_names and "token" in events_names and "done" in events_names

    done = _done_event(events)
    assert done["answer"] and "[1]" in done["answer"], done["answer"]
    assert len(done["sources"]) > 0
    assert done["sources"][0]["doc_name"] == "rag.md"


def test_chat_greeting_direct(client, admin_headers, prepared_kb):
    sess = client.post(
        "/api/v1/chat/sessions",
        json={"title": "闲聊", "kb_id": prepared_kb},
        headers=admin_headers,
    ).json()
    events = _send(client, admin_headers, sess["id"], "你好")
    text = _accumulate_text(events)
    assert "知识库助手" in text or "知识库助手" in _done_event(events).get("answer", "")


def test_chat_fallback(client, admin_headers, prepared_kb):
    sess = client.post(
        "/api/v1/chat/sessions",
        json={"title": "兜底", "kb_id": prepared_kb},
        headers=admin_headers,
    ).json()
    events = _send(client, admin_headers, sess["id"], "公司的员工福利政策是什么？")
    text = _accumulate_text(events) + _done_event(events).get("answer", "")
    assert "未在知识库中找到相关内容" in text


def test_chat_history(client, admin_headers, prepared_kb):
    sess = client.post(
        "/api/v1/chat/sessions",
        json={"title": "历史", "kb_id": prepared_kb},
        headers=admin_headers,
    ).json()
    _send(client, admin_headers, sess["id"], "LangGraph 用来做什么？")
    detail = client.get(f"/api/v1/chat/sessions/{sess['id']}", headers=admin_headers).json()
    roles = [m["role"] for m in detail["messages"]]
    assert roles == ["user", "assistant"]
    assert detail["messages"][1]["sources"]


def test_chat_feedback_toggle(client, admin_headers, prepared_kb):
    sess = client.post(
        "/api/v1/chat/sessions",
        json={"title": "反馈", "kb_id": prepared_kb},
        headers=admin_headers,
    ).json()
    events = _send(client, admin_headers, sess["id"], "LangGraph 用来做什么？")
    msg_id = _done_event(events)["message_id"]
    url = f"/api/v1/chat/messages/{msg_id}/feedback"

    r = client.post(url, json={"feedback": "like"}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["feedback"] == "like"
    # 再点 like = 取消
    r = client.post(url, json={"feedback": "like"}, headers=admin_headers)
    assert r.json()["feedback"] is None
    # 点 dislike
    r = client.post(url, json={"feedback": "dislike"}, headers=admin_headers)
    assert r.json()["feedback"] == "dislike"
    # 再点 like = 切换
    r = client.post(url, json={"feedback": "like"}, headers=admin_headers)
    assert r.json()["feedback"] == "like"

    # 历史消息带 feedback 字段
    detail = client.get(f"/api/v1/chat/sessions/{sess['id']}", headers=admin_headers).json()
    assistant = [m for m in detail["messages"] if m["role"] == "assistant"]
    assert assistant[0]["feedback"] == "like"

    # 非法取值 → 422；不存在消息 → 404
    assert client.post(url, json={"feedback": "meh"}, headers=admin_headers).status_code == 422
    assert client.post(
        "/api/v1/chat/messages/00000000-0000-0000-0000-000000000000/feedback",
        json={"feedback": "like"}, headers=admin_headers,
    ).status_code == 404


def test_chat_feedback_ownership(client, admin_headers, prepared_kb):
    """他人消息 → 403。"""
    tag = str(time.time()).replace(".", "")
    uname = f"fbv_{tag}"
    client.post(
        "/api/v1/auth/register",
        json={"username": uname, "email": f"{uname}@test.com", "password": "pass123456"},
    )
    login = client.post(
        "/api/v1/auth/login", json={"username": uname, "password": "pass123456"}
    ).json()
    other_headers = {"Authorization": f"Bearer {login['access_token']}"}

    sess = client.post(
        "/api/v1/chat/sessions", json={"title": "归属", "kb_id": prepared_kb},
        headers=admin_headers,
    ).json()
    events = _send(client, admin_headers, sess["id"], "你好")
    msg_id = _done_event(events)["message_id"]
    r = client.post(
        f"/api/v1/chat/messages/{msg_id}/feedback",
        json={"feedback": "like"}, headers=other_headers,
    )
    assert r.status_code == 403


def test_chat_search_all_kbs(client, admin_headers, prepared_kb):
    """不选知识库（kb_id=None 全库检索）不应因 knn filter null 报错。"""
    sess = client.post(
        "/api/v1/chat/sessions", json={"title": "全库检索"}, headers=admin_headers
    ).json()
    events = _send(client, admin_headers, sess["id"], "FastAPI 是什么？")
    events_names = [e["event"] for e in events]
    assert "error" not in events_names, [e for e in events if e["event"] == "error"]
    done = _done_event(events)
    assert len(done["sources"]) > 0  # 全库检索能命中 prepared_kb 内容


def test_update_session_title(client, admin_headers, prepared_kb):
    sess = client.post(
        "/api/v1/chat/sessions",
        json={"title": "新对话", "kb_id": prepared_kb},
        headers=admin_headers,
    ).json()
    r = client.put(
        f"/api/v1/chat/sessions/{sess['id']}",
        json={"title": "报销单问题"},
        headers=admin_headers,
    )
    assert r.status_code == 200
    assert r.json()["title"] == "报销单问题"
    detail = client.get(f"/api/v1/chat/sessions/{sess['id']}", headers=admin_headers).json()
    assert detail["session"]["title"] == "报销单问题"


def test_chat_history_excludes_current_message(client, admin_headers, prepared_kb, monkeypatch):
    """history 只含本轮之前的消息：第一轮为空，第二轮恰为上一轮 user+assistant，
    绝不包含当前这条问题（否则改写拿到自指输入）。"""
    import app.api.v1.chat as chat_mod

    captured = []

    async def spy(question, kb_id, history=None):
        captured.append({"q": question, "history": history})
        return {"mode": "direct", "answer": "收到", "sources": [],
                "question": question, "prompt": ""}

    monkeypatch.setattr(chat_mod, "prepare_rag", spy)

    sess = client.post(
        "/api/v1/chat/sessions",
        json={"title": "历史传递", "kb_id": prepared_kb},
        headers=admin_headers,
    ).json()

    _send(client, admin_headers, sess["id"], "第一问")
    assert captured[0]["history"] == []          # 首轮无历史

    _send(client, admin_headers, sess["id"], "那这个呢？")
    h = captured[1]["history"]
    assert [m["role"] for m in h] == ["user", "assistant"]
    assert h[0]["content"] == "第一问"            # 上一轮问题
    assert h[1]["content"] == "收到"              # 上一轮回答（spy 的 direct 答案已落库）
    assert all(m["content"] != "那这个呢？" for m in h)  # 当前消息不在 history 里


def test_chat_sse_shape_unchanged_with_history(client, admin_headers, prepared_kb):
    """有历史的第二轮 SSE 帧序仍为 start/token/done——协议零改动。"""
    sess = client.post(
        "/api/v1/chat/sessions",
        json={"title": "协议回归", "kb_id": prepared_kb},
        headers=admin_headers,
    ).json()
    _send(client, admin_headers, sess["id"], "FastAPI 是什么框架？")  # 真实流程，产生历史
    events = _send(client, admin_headers, sess["id"], "那它是用来做什么的？")
    names = [e["event"] for e in events]
    assert names[0] == "start"
    assert "token" in names and "done" in names
    assert "error" not in names, [e for e in events if e["event"] == "error"]
