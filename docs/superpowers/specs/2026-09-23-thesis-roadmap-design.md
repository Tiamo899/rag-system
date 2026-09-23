# 毕设功能丰富路线设计（评测 · 多轮上下文 · 知识库治理）

日期：2026-09-23
状态：待评审

## 1. 背景与目标

本项目「高校教务与学生服务智能问答系统」已可正常运行（真实 LLM/Embedding 已接入），将作为本科毕业设计的系统成果。本设计定义从当前状态到毕设就绪的**功能丰富路线**，暂不涉及论文文档撰写。

**三条主线：**

1. **问答质量 → 多轮对话上下文**：实测唯一质量痛点，追问时无上下文、指代无法解析
2. **评测体系**：golden QA 数据集 + 自动跑分，为一切优化提供前后对比数据，构成实验章素材
3. **知识库治理**：同文档多版本、跨文档矛盾、更新残留、时效性——防止新旧文档互相打架

**约束：**

- 无近期硬节点，主要关口为答辩（约 2027 年中），按阶段推进
- mock 模式必须保持可用（现有测试与免 key 演示依赖）
- 现有 SSE 协议尽量不动（Phase 1 前端零改动）

**明确不做（YAGNI，留作论文展望）：** 重排序模型、自动跨文档矛盾消解（只提示不裁决）、检索命中/幻觉专项治理、功能广度扩展、工程化增强、论文文档。

## 2. 总体路线

| 阶段 | 内容 | 交付物 |
|------|------|--------|
| Phase 0 | 评测体系基线 | golden QA 数据集 + 跑分脚本 + 基线分数报告 |
| Phase 1 | 多轮上下文 | 查询改写接入 RAG 流程 + 前后对比分数 |
| Phase 2 | 知识库治理 | 版本链 + 时效过滤 + 替换清理 + 冲突提示 + 前后对比分数 |

每阶段收尾全量跑分，结果提交 git 留档。

**贯穿原则：**

1. **PG 存全量历史，ES 只存生效内容**：PostgreSQL 保留所有文档行与原文件（可审计）；Elasticsearch 只索引现行分块
2. **评测先于优化**：功能改完必须有前后分数对比，无数据不算完成
3. **fail-open**：查询改写失败、治理字段缺失、新文档向量化失败时降级为安全行为，不中断主流程
4. **mock 不破坏**：所有新增 LLM 调用在 mock 下透传，现有 pytest 全绿

## 3. Phase 0 · 评测体系

### 3.1 数据集

位置：`backend/evals/dataset/`，JSONL，随库提交。

| 文件 | 用例形态 | 度量目标 |
|------|----------|----------|
| `single_turn.jsonl` | `{id, question, expect_docs[], expect_keywords[]}` | 检索 Hit@3 + 答案关键词 |
| `multi_turn.jsonl` | `{id, turns: [{q, expect_keywords[]}]}`，追问含指代（「它/那这个呢」） | 多轮解析 |
| `governance.jsonl` | 新旧版本并存时以新版为准的问题 | 治理有效性 |

**版本冲突测试库**：Phase 0 构造——复制某演示政策文档为旧年份版，修改关键数字（如请假天数 3 天 → 5 天），两版并列入库。基线阶段系统预期会引用旧版数字，构成 Phase 2 的问题动机与对比数据。

### 3.2 跑分脚本

位置：`backend/evals/run_eval.py`，入口 `python -m evals.run_eval --dataset ... --tag ...`。

- **调用方式**：进程内调用 `run_rag_flow`（服务层直调，不走 HTTP、不碰鉴权）；需 PG + ES 运行
- **指标**（三层）：
  1. 检索 Hit@3：`expect_docs` 是否出现在 top-3 来源文档（`run_rag_flow` 的 `sources` 截取前 3，与生成实际上下文一致）
  2. 答案关键词命中率
  3. LLM 裁判 0/1 分：用当前配置的真实 LLM 裁判；**provider=mock 时跳过并在报告注明**
- **产出**：`backend/evals/results/<日期>-<标签>.{json,md}`，提交 git

## 4. Phase 1 · 多轮上下文（查询改写）

### 4.1 方案

检索前将「历史 + 最新问题」改写为独立问题，检索与相关性评估均使用改写后问句；生成时附带近几轮原文。

```
现状:  question ──────────────→ 检索 → 评估 → 生成
之后:  history + question → rewrite → standalone_query → 检索 → 评估
       history(近3轮) + standalone_query ──────────────→ 生成
```

### 4.2 改动点

1. **`state.py`**：`RAGState` 增 `history: list`、`standalone_query: str`
2. **新节点 `rewrite_node`**：
   - 无历史 / provider=mock / LLM 调用失败或返回空 → **透传原问题**（fail-open）
   - 有历史且 provider=openai → LLM 改写，提示词要求「结合对话历史改写为独立完整问题，只输出改写结果」
3. **`nodes.py`**：`retrieve_node`、`evaluate_node`（余弦计算处）改用 `standalone_query`
4. **`graph.py`**：`prepare_rag(question, kb_id, history=None)`，流程中插入 rewrite 步骤
5. **`chat.py`**：`send_message` 从 DB 取本会话最近 6 条消息作为 history；生成 prompt 改为「近 3 轮对话 + 编号资料 + 独立化问题」，每轮截断限长

### 4.3 代价与验收

- 代价：有历史时每轮多一次 LLM 调用（追问延迟约 +0.3–1s），首轮零开销；SSE 协议与前端不变
- 验收：`multi_turn.jsonl` 基线分 vs 改后分对比入档

## 5. Phase 2 · 知识库治理

### 5.1 数据模型（Alembic 迁移 v6）

`documents` 表新增 4 个可空字段，不引入新状态枚举：

| 字段 | 类型 | 含义 |
|------|------|------|
| `valid_from` | date, null | 生效日期（空 = 默认上传日） |
| `valid_to` | date, null | 失效日期（空 = 长期有效） |
| `version_no` | str, null | 版本标识（如「2023 版」） |
| `superseded_by` | UUID FK → documents, null | 替代它的新文档；**空 = 现行，非空 = 已废止** |

「已废止 ⇔ `superseded_by` 非空」。与向量化状态 `status`（pending/processing/…）互不混用。

### 5.2 机制一：同名替换（场景 A 同文档多版本 + C 更新残留）

上传时同库存在同名且现行文档 → 前端询问「作为新版本替换？」并填 `version_no`/`valid_from`；后端亦接受显式 `supersedes_doc_id`。

**时序（关键）——替换在新文档向量化成功后才生效：**

```
上传新版 → 解析 → 向量化成功 → 原子操作：
   旧文档.superseded_by = 新文档.id
   旧分块从 ES 物理删除（PG 分块级联删；文档行 + 原文件保留）
向量化失败 → 旧文档保持现行，新版标 failed → 知识不断档（fail-open）
```

PG 分块为派生数据（可由原文件重新向量化），删除不违反「PG 存历史」原则。

### 5.3 机制二：时效过滤（场景 D + 异名多版本并存）

- **索引**：ES `metadata` 写入 `valid_from`/`valid_to`（缺省填上传日 / `9999-12-31`）
- **检索**：`hybrid_search` 的 knn `filter` 与 keyword `bool.filter` 同时追加 `valid_from ≤ today ≤ valid_to`，与 `kb_id` filter 合并
- **存量回填**：一次性脚本 `_update_by_query` 回填 metadata（**不重新向量化、零 embedding 费用**），幂等可重跑

### 5.4 机制三：跨文档矛盾——提示不裁决（场景 B）

1. context 行携带时效：`《学籍管理规定》(2023版, 生效2023-09-01)：…`
2. top-3 来自 ≥2 份不同文档时，prompt 追加：「资料来自多份文档，若规定不一致，指出差异并以生效日期较新者为准」

不做自动裁决，留作论文展望。

### 5.5 改动清单

- **后端**：迁移 v6；`documents` schema/API 增字段；替换事务逻辑；`hybrid_search` 时效过滤；context 构造；回填脚本；`API.md` 同步
- **前端（小改）**：文档列表「现行/已废止」徽章 + 有效期显示；上传弹窗版本字段；「只看现行」开关

### 5.6 验收

`governance.jsonl`：「引用旧版数字」失败案例归零；Hit@3 由旧版转移至新版。

## 6. 测试策略

| 层 | 内容 |
|----|------|
| 单元 | rewrite 透传/改写/失败降级；时效过滤器构造；替换状态机（向量化失败不 purge） |
| 集成 | 上传同名 → 向量化成功 → 断言 ES 旧 chunk 删除、`superseded_by` 已设（复用 conftest ES 环境） |
| 回归 | 每阶段全量 `pytest` 全绿，mock 测试不许破 |
| 实验 | 三数据集 × 三轮（基线/Phase1/Phase2）跑分结果 git 留档 |

## 7. 风险与开放问题

- **LLM 裁判稳定性**：裁判提示词固定、温度 0；若评分抖动明显，以关键词命中率为客观主指标、裁判分为辅
- **回填与替换的边界**：回填只处理存量缺字段文档；新文档索引时必写默认值，两路径不冲突
- **多版本并存 + 同名替换并用**：同名替换后旧 chunk 已物理删除，时效过滤只作用于仍并存的异名文档，二者互补不冲突
- **实施顺序**：严格 Phase 0 → 1 → 2，评测基线是后续一切对比的前提
