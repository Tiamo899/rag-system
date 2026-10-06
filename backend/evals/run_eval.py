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
    return parse_judge(await llm.generate(prompt, temperature=0.0))


def _load_cases(name: str) -> list[dict]:
    path = DATASET_DIR / f"{name}.jsonl"
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _rate(values: list[bool | None]) -> float | None:
    """None（裁判跳过或 case 失败）→ 剔除；全 None → None；否则按非 None 项求均值。"""
    valid = [v for v in values if v is not None]
    if not valid:
        return None
    return sum(1 for v in valid if v) / len(valid)


def _pct(v: float | None) -> str:
    """速率格式化；None（无可计样本）不炸报告输出。"""
    return f"{v:.2%}" if v is not None else "n/a"


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
        try:
            plan = await run_rag_flow(c["question"], kb_id)
            answer, sources = plan["answer"], plan["sources"]
        except Exception as exc:  # 单 case 失败不拖垮整轮，已跑结果保留
            hits.append(None)
            kws.append(None)
            judges.append(None)
            details.append(
                {
                    "id": c["id"],
                    "hit_at3": None,
                    "keyword": None,
                    "judge": None,
                    "sources": [],
                    "answer": "",
                    "error": str(exc),
                }
            )
            continue
        hit = hit_at3(sources, c["expect_docs"])
        kw = keyword_verdict(
            answer, c.get("expect_keywords", []), c.get("forbidden_keywords", [])
        )
        jd, err = None, None
        if use_judge:
            try:
                jd = await _judge(c["question"], c.get("expect_keywords", []), answer)
            except Exception as exc:
                jd, err = None, str(exc)
        hits.append(hit)
        kws.append(kw)
        judges.append(jd)
        row = {
            "id": c["id"],
            "hit_at3": hit,
            "keyword": kw,
            "judge": jd,
            "sources": [s.get("doc_name") for s in sources],
            "answer": answer[:300],
        }
        if err is not None:
            row["error"] = err
        details.append(row)
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
    mode: str = "independent",  # independent=Phase 0 基线语义 | history=传前轮
) -> dict:
    """多轮跑分。independent：每轮独立、不带历史（基线可复现，保持默认）；
    history：第 N 轮携带前 N-1 轮的 user/assistant 消息（Phase 1 验收用）。"""
    details = []
    hits, kws, judges = [], [], []
    for c in cases:
        turn_rows = []
        case_history: list[dict] = []  # 每个 case 重置
        for t in c["turns"]:
            # 传快照而非活引用：防止累积追加污染调用前的历史、
            # 也防止被调用方持有多条 turn 共享同一 list 对象
            history = list(case_history) if mode == "history" else []
            try:
                plan = await run_rag_flow(t["q"], kb_id, history=history)
                answer, sources = plan["answer"], plan["sources"]
            except Exception as exc:  # 单轮失败不拖垮整轮次序列
                hits.append(None)
                kws.append(None)
                judges.append(None)
                turn_rows.append(
                    {
                        "q": t["q"],
                        "hit_at3": None,
                        "keyword": None,
                        "judge": None,
                        "sources": [],
                        "answer": "",
                        "error": str(exc),
                    }
                )
                continue
            hit = hit_at3(sources, t.get("expect_docs", []))
            kw = keyword_verdict(
                answer, t.get("expect_keywords", []), t.get("forbidden_keywords", [])
            )
            jd, err = None, None
            if use_judge and t.get("expect_keywords"):
                try:
                    jd = await _judge(
                        t["q"], t.get("expect_keywords", []) or ["要点"], answer
                    )
                except Exception as exc:
                    jd, err = None, str(exc)
            hits.append(hit)
            kws.append(kw)
            judges.append(jd)
            row = {
                "q": t["q"],
                "hit_at3": hit,
                "keyword": kw,
                "judge": jd,
                "sources": [s.get("doc_name") for s in sources],
                "answer": answer[:300],
            }
            if err is not None:
                row["error"] = err
            turn_rows.append(row)
            case_history.append({"role": "user", "content": t["q"]})
            case_history.append({"role": "assistant", "content": answer})
        details.append({"id": c["id"], "turns": turn_rows})
    report = {
        "tag": tag,
        "dataset": "multi_turn",
        "date": date.today().isoformat(),
        "kb_id": kb_id,
        "multi_turn_mode": mode,
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
        else "跳过（无参考要点或 mock）"
    )
    lines = [
        f"# 评测报告 · {stem}",
        "",
        f"- tag: `{tag}`  dataset: `{name}`  date: {report['date']}",
        f"- kb_id: `{report['kb_id']}`",
        f"- Hit@3: **{_pct(report['hit_at3_rate'])}**",
        f"- 关键词: **{_pct(report['keyword_rate'])}**",
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
        settings = get_settings()
        r = client.post(
            "/api/v1/auth/login",
            json={
                "username": settings.default_admin_username,
                "password": settings.default_admin_password,
            },
        )
        assert r.status_code == 200
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
                cases, kb["id"], use_judge, results_dir, args.tag,
                mode=args.multi_turn_mode,
            )
        else:
            report = await run_single_cases(
                cases, kb["id"], use_judge, results_dir, args.tag,
                dataset_name=name,
            )
        print(
            f"[{name}] Hit@3={_pct(report['hit_at3_rate'])} "
            f"keyword={_pct(report['keyword_rate'])} "
            f"judge={report['judge_rate']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG 评测跑分")
    parser.add_argument("--tag", required=True, help="baseline/phase1/phase2…")
    parser.add_argument("--dataset", default="all",
                        choices=("all",) + DATASETS)
    parser.add_argument("--multi-turn-mode", default="independent",
                        choices=("independent", "history"),
                        help="多轮跑分是否携带前轮历史（默认 independent=基线语义）")
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR))
    args = parser.parse_args()
    asyncio.run(_amain(args))


if __name__ == "__main__":
    main()
