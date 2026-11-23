"""检索质量快速对比：固定 10 题，打印 Hit@3 / 上下文长度 / 来源多样性。

与 evals/run_eval.py 的区别：脚本走真实 HTTP 接口，覆盖多知识库联合检索，
适合「改完检索配置后一分钟看效果」；不调用 LLM，纯检索侧指标。

用法：
    python -m scripts.quick_eval                       # 默认 http://localhost:8000
    python -m scripts.quick_eval --base-url http://localhost --tag after-chunk
"""
import argparse
import json
import statistics
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

CASES = [
    ("挂科了还能评奖学金吗", "奖学金评定办法.docx"),
    ("国家助学金的申请条件是什么", "国家助学金评审办法.docx"),
    ("补考不及格还能拿到毕业证吗", "补考、重修与缓考管理办法.docx"),
    ("宿舍晚归会怎么处理", "学生宿舍管理办法.docx"),
    ("转专业需要满足什么条件", "转专业实施办法.docx"),
    ("勤工助学怎么申请", "勤工助学与助学贷款管理办法.docx"),
    ("课程考核不及格怎么办", "课程考核与成绩管理.docx"),
    ("学生请假超过三天需要谁批准", "学生考勤与请假管理办法.docx"),
    ("校园卡丢了怎么补办", "校园一卡通使用与管理.docx"),
    ("毕业需要满足什么条件", "毕业与学位授予工作细则.docx"),
]


def run(base_url: str, tag: str, username: str, password: str) -> dict:
    api = base_url.rstrip("/") + "/api/v1"
    with httpx.Client(timeout=120) as client:
        token = client.post(
            f"{api}/auth/login", json={"username": username, "password": password}
        ).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        rows = []
        for question, expect_doc in CASES:
            resp = client.post(
                f"{api}/search/debug", json={"query": question, "top_k": 5}, headers=headers
            )
            if resp.status_code != 200:
                rows.append({"q": question, "error": resp.text[:120]})
                continue
            data = resp.json()
            top3 = [i["doc_name"] for i in data["fusion"]["items"][:3]]
            meta = data.get("context_meta") or {}
            rows.append(
                {
                    "q": question,
                    "expect": expect_doc,
                    "top3": top3,
                    "hit": expect_doc in top3,
                    "ctx_chars": meta.get("chars", len(data.get("context") or "")),
                    "distinct_docs": len({d for d in top3 if d}),
                    "expanded": meta.get("expanded", 0),
                }
            )
    ok = sum(1 for r in rows if r.get("hit"))
    ctx = [r["ctx_chars"] for r in rows if r.get("ctx_chars")]
    summary = {
        "tag": tag,
        "date": date.today().isoformat(),
        "base_url": base_url,
        "hit_at3": f"{ok}/{len(rows)}",
        "avg_ctx_chars": int(statistics.mean(ctx)) if ctx else 0,
        "median_ctx_chars": int(statistics.median(ctx)) if ctx else 0,
        "multi_source_rate": f"{sum(1 for r in rows if r.get('distinct_docs', 0) >= 2)}/{len(rows)}",
    }
    return {"summary": summary, "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description="检索质量快速对比")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--tag", default="quick")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin123")
    parser.add_argument("--out", default=None, help="结果 JSON 输出路径")
    args = parser.parse_args()

    result = run(args.base_url, args.tag, args.username, args.password)
    for r in result["rows"]:
        if r.get("error"):
            print(f"[ERR] {r['q']} {r['error']}")
            continue
        flag = "OK " if r["hit"] else "MISS"
        print(
            f"{flag} {r['q'][:16]:<18} ctx={r['ctx_chars']:<5} docs={r['distinct_docs']} "
            f"top3={' / '.join(x or '-' for x in r['top3'])}"
        )
    s = result["summary"]
    print(
        f"\n[{s['tag']}] Hit@3={s['hit_at3']} 平均上下文={s['avg_ctx_chars']}字 "
        f"多来源占比={s['multi_source_rate']}"
    )
    if args.out:
        Path(args.out).write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"已写入 {args.out}")


if __name__ == "__main__":
    main()
