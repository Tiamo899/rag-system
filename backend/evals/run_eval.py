# backend/evals/run_eval.py
"""跑分脚本：进程内调 run_rag_flow，三层指标，结果写 results/。

用法（backend/ 目录下，需 PG+ES；--tag 标记本轮，如 baseline / phase1）：
    python -m evals.run_eval --tag baseline
    python -m evals.run_eval --tag phase1 --dataset multi_turn
"""
import argparse
import asyncio
import json
from datetime import date
from pathlib import Path

from app.core.config import get_settings
from app.services.rag.langgraph.graph import run_rag_flow
from evals.metrics import hit_at3, keyword_verdict, parse_judge

DATASET_DIR = Path(__file__).resolve().parent / "dataset"
DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent / "results"
DATASETS = ("single_turn", "multi_turn", "governance")

JUDGE_PROMPT = """你是严格的阅卷员。根据参考要点判断回答是否切题且覆盖要点。
只输出 1（通过）或 0（不通过），不要输出其他内容。

问题：{question}
参考要点：{keywords}
回答：{answer}
"""


def _judge_enabled() -> bool:
    return get_settings().llm_provider == "openai"


async def _judge(question: str, keywords: list[str], answer: str) -> int:
    from app.services.llm.factory import get_llm_provider

    llm = get_llm_provider()
    prompt = JUDGE_PROMPT.format(
        question=question, keywords="、".join(keywords), answer=answer[:2000]
    )
    return parse_judge(await llm.generate(prompt))


def _load_cases(name: str) -> list[dict]:
    path = DATASET_DIR / f"{name}.jsonl"
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _rate(values: list[bool | None]) -> float | None:
    """None（裁判跳过）全部 → None；否则按非 None 项求均值。"""
    valid = [v for v in values if v is not None]
    if not valid:
        return None
    return sum(1 for v in valid if v) / len(valid)


async def run_single_cases(
    cases: list[dict],
    kb_id: str,
    use_judge: bool,
    results_dir: Path,
    tag: str,
    dataset_name: str = "single_turn",
) -> dict:
    details = []
    hits, kws, judges = [], [], []
    for c in cases:
        plan = await run_rag_flow(c["question"], kb_id)
        answer, sources = plan["answer"], plan["sources"]
        hit = hit_at3(sources, c["expect_docs"])
        kw = keyword_verdict(
            answer, c.get("expect_keywords", []), c.get("forbidden_keywords", [])
        )
        jd = (
            await _judge(c["question"], c.get("expect_keywords", []), answer)
            if use_judge
            else None
        )
        hits.append(hit)
        kws.append(kw)
        judges.append(jd)
        details.append(
            {
                "id": c["id"],
                "hit_at3": hit,
                "keyword": kw,
                "judge": jd,
                "sources": [s.get("doc_name") for s in sources],
                "answer": answer[:300],
            }
        )
    report = {
        "tag": tag,
        "dataset": dataset_name,
        "date": date.today().isoformat(),
        "kb_id": kb_id,
        "hit_at3_rate": _rate(hits),
        "keyword_rate": _rate(kws),
        "judge_rate": _rate(judges) if use_judge else None,
        "cases": details,
    }
    _write_report(report, results_dir, tag, dataset_name)
    return report


async def run_multi_turn_cases(
    cases: list[dict],
    kb_id: str,
    use_judge: bool,
    results_dir: Path,
    tag: str,
) -> dict:
    """Phase 0 基线：每轮独立调用，不携带历史。Phase 1 计划将改为传历史。"""
    details = []
    hits, kws, judges = [], [], []
    for c in cases:
        turn_rows = []
        for t in c["turns"]:
            plan = await run_rag_flow(t["q"], kb_id)
            answer, sources = plan["answer"], plan["sources"]
            hit = hit_at3(sources, t.get("expect_docs", []))
            kw = keyword_verdict(
                answer, t.get("expect_keywords", []), t.get("forbidden_keywords", [])
            )
            jd = (
                await _judge(t["q"], t.get("expect_keywords", []) or ["要点"], answer)
                if use_judge and t.get("expect_keywords")
                else None
            )
            hits.append(hit)
            kws.append(kw)
            judges.append(jd)
            turn_rows.append(
                {
                    "q": t["q"],
                    "hit_at3": hit,
                    "keyword": kw,
                    "judge": jd,
                    "sources": [s.get("doc_name") for s in sources],
                    "answer": answer[:300],
                }
            )
        details.append({"id": c["id"], "turns": turn_rows})
    report = {
        "tag": tag,
        "dataset": "multi_turn",
        "date": date.today().isoformat(),
        "kb_id": kb_id,
        "hit_at3_rate": _rate(hits),
        "keyword_rate": _rate(kws),
        "judge_rate": _rate(judges) if use_judge else None,
        "cases": details,
    }
    _write_report(report, results_dir, tag, "multi_turn")
    return report


def _write_report(report: dict, results_dir: Path, tag: str, name: str) -> None:
    results_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{report['date']}-{tag}-{name}"
    (results_dir / f"{stem}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    judge_line = (
        f"{report['judge_rate']:.2%}"
        if report["judge_rate"] is not None
        else "跳过（mock provider）"
    )
    lines = [
        f"# 评测报告 · {stem}",
        "",
        f"- tag: `{tag}`  dataset: `{name}`  date: {report['date']}",
        f"- kb_id: `{report['kb_id']}`",
        f"- Hit@3: **{report['hit_at3_rate']:.2%}**",
        f"- 关键词: **{report['keyword_rate']:.2%}**",
        f"- 裁判: **{judge_line}**",
        "",
        "| id | Hit@3 | 关键词 | 裁判 | 来源 |",
        "|----|-------|--------|------|------|",
    ]
    for c in report["cases"]:
        if "turns" in c:
            for i, t in enumerate(c["turns"]):
                lines.append(
                    f"| {c['id']}-t{i + 1} | {t['hit_at3']} | {t['keyword']} "
                    f"| {t['judge']} | {', '.join(x or '' for x in t['sources'])} |"
                )
        else:
            lines.append(
                f"| {c['id']} | {c['hit_at3']} | {c['keyword']} "
                f"| {c['judge']} | {', '.join(x or '' for x in c['sources'])} |"
            )
    (results_dir / f"{stem}.md").write_text("\n".join(lines), encoding="utf-8")


async def _amain(args: argparse.Namespace) -> None:
    from evals.setup_dataset import EVAL_KB_NAME, find_eval_kb
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        r = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
        kb = find_eval_kb(client, headers)
    assert kb is not None, "评测库不存在，先运行 python -m evals.setup_dataset"

    use_judge = _judge_enabled()
    results_dir = Path(args.results_dir)
    targets = DATASETS if args.dataset == "all" else (args.dataset,)
    print(f"kb={kb['id']} judge={'on' if use_judge else 'off'} datasets={targets}")
    for name in targets:
        cases = _load_cases(name)
        if name == "multi_turn":
            report = await run_multi_turn_cases(
                cases, kb["id"], use_judge, results_dir, args.tag
            )
        else:
            report = await run_single_cases(
                cases, kb["id"], use_judge, results_dir, args.tag,
                dataset_name=name,
            )
        print(
            f"[{name}] Hit@3={report['hit_at3_rate']:.2%} "
            f"keyword={report['keyword_rate']:.2%} "
            f"judge={report['judge_rate']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG 评测跑分")
    parser.add_argument("--tag", required=True, help="baseline/phase1/phase2…")
    parser.add_argument("--dataset", default="all",
                        choices=("all",) + DATASETS)
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR))
    args = parser.parse_args()
    asyncio.run(_amain(args))


if __name__ == "__main__":
    main()
