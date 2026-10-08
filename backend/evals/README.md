# 评测体系使用说明

## 前置

- PG + ES 容器运行（`docker compose up -d postgres elasticsearch redis`）
- `backend/.env` 已配真实 LLM/Embedding（mock 下裁判自动跳过）

## 首次：建评测库（幂等，可重跑）

```bash
cd backend
python -m evals.setup_dataset
```

20 份演示 docx + 2 份版本冲突 md 全部向量化，库名「评测库」。

## 跑分

```bash
cd backend
python -m evals.run_eval --tag baseline            # 全量三数据集
python -m evals.run_eval --tag phase1 --dataset multi_turn   # 单数据集
```

结果写入 `results/<日期>-<tag>-<数据集>.{json,md}`，**提交 git**。

## 指标

| 指标 | 含义 |
|------|------|
| Hit@3 | top-3 来源命中期望文档 |
| 关键词 | 答案含任一 expect_keywords 且不含任何 forbidden_keywords；`expect_keywords` 为空的轮次恒判负（数据设计如此） |
| 裁判 | LLM 按参考要点打 0/1；mock provider 或该轮 `expect_keywords` 为空（无参考要点可对）时为 null |
| 多轮模式 | `--multi-turn-mode` 默认 `independent`（=基线语义，不带历史）；`history` 显式开启，第 N 轮携带前 N-1 轮消息 |

## 阶段对比

- 基线：`--tag baseline`
- Phase 1 后：`--tag phase1 --multi-turn-mode history`（对比 `multi_turn`：judge 50%→66.67%、keyword 100%→83.33%、Hit@3 持平 100%。keyword 破位为 mt-03 歧义指代消解失败，根因见对应结果 md 的「回归分析」注记——judge 与 keyword 两面并呈，不得只报提升）
- Phase 2 后：`--tag phase2`（对比 `governance`：场景 A 检索侧达标——2023 版零引用（基线 2 次→0）、gv-01 来源首位 2023→2024；keyword/judge 50%→50% 持平（n=2 无 case 翻转），根因是跨文档矛盾而非治理失效，见对应结果 md 的「验收分析」注记——两面并呈，不得只报检索侧达标）

对比 = 直接看两份 md 报告，或 `git diff` results 目录。
