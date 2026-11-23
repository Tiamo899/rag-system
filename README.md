# RAG Knowledge Base System

一个前后端分离的 RAG（检索增强生成）知识库系统：上传文档 → 解析分块 → 向量化 → 混合检索 → 基于大模型的流式智能问答。内置 RBAC 权限体系与管理后台，默认 mock 模型可免 key 演示，一行命令切换真实 LLM / Embedding。

## 功能

- **知识库管理**：多知识库，分块大小/重叠度可配
- **文档处理**：支持 pdf / docx / md / txt（≤20MB），按标题层级智能分块，手动触发向量化
- **混合检索**：Elasticsearch 向量 + 关键词混合检索（RRF 融合），余弦相似度二次验证兜底
- **智能问答**：会话管理，SSE 流式输出，答案附带来源引用，消息点赞/点踩
- **权限体系**：JWT 认证，admin / editor / viewer 角色，权限点 `模块:动作`，内置用户/角色管理护栏
- **知识库可见范围**：库级 `public` / `restricted`，按真实角色与指定用户授权，覆盖知识库、文档、会话与检索全链路
- **检索调试台**：展示向量/关键词各路召回、RRF 融合分数、余弦复核与最终上下文，便于定位检索质量问题
- **管理后台**：概览统计（ECharts）、系统配置（LLM/Embedding/分块参数）
- **双 Provider**：LLM 与 Embedding 均支持 `mock` / OpenAI 兼容接口，key 缺失明确报错不静默降级

## 技术栈

| 层 | 技术 |
|----|------|
| 前端 | Vite · React 18 · TypeScript · Ant Design · Zustand · ECharts |
| 后端 | FastAPI · SQLAlchemy (async) · Alembic · LangGraph |
| 存储 | PostgreSQL（业务数据） · Elasticsearch 8.13 + IK 分词（向量索引） · Redis |
| 部署 | Docker Compose（5 服务，健康检查编排启动顺序） |

## 快速开始

```bash
git clone https://github.com/Tiamo899/rag-system.git
cd rag-system
cp .env.example .env   # 可选：填入 LLM / Embedding Key；不配置则按 compose 默认 mock 演示
docker compose up -d --build
```

启动后访问 **http://localhost**，默认账号 `admin / admin123`。

本地开发（不走完整 Docker）：

```bash
# 依赖服务
docker compose up -d postgres elasticsearch redis

# 后端 :8000
cd backend
python -m venv .venv && source .venv/Scripts/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# 前端 :5173（/api 代理到 8000）
cd frontend
npm install
npm run dev
```

> Windows 下 ES 启动报 `vm.max_map_count` 等问题，见 [DEPLOY.md](DEPLOY.md) 的 Windows 章节。

## 接入真实模型

默认 mock 演示。把根目录 `.env.example` 复制为 `.env`，填入 Key 后重启后端即可：

- **LLM**：智谱 GLM（OpenAI 兼容），主模型 `glm-4-flash-250414`，限流时按 `LLM_FALLBACK_MODELS` 降级到 `glm-4.7-flash`
- **Embedding**：硅基流动 `BAAI/bge-m3`，1024 维

Key 只写入 `.env`，该文件已被忽略、不会进仓库。维度约束、索引重建等注意事项见 [DEPLOY.md](DEPLOY.md) 的「模型配置」章节。

## 项目结构

```
rag-system/
├── backend/                  # FastAPI 应用
│   ├── app/
│   │   ├── api/v1/           # 路由层（auth/kb/docs/search/chat/admin…）
│   │   ├── services/         # 业务层（解析/分块/向量化/检索/RAG/LLM）
│   │   ├── models/           # SQLAlchemy 模型
│   │   ├── schemas/          # Pydantic 校验
│   │   └── core/             # 配置、JWT、RBAC、ES 客户端
│   ├── alembic/              # 数据库迁移
│   └── tests/                # pytest 测试套件
├── frontend/                 # React 前端
│   └── src/
│       ├── pages/            # 登录/仪表盘/知识库/问答/管理
│       ├── api/              # 接口封装（含 SSE）
│       └── store/            # Zustand 状态
├── docker/                   # ES 定制镜像（IK 分词插件）
├── knowledge_base_docs_campus/  # 高校政策演示文档（20 份）
├── docker-compose.yml
├── API.md                    # 接口文档
└── DEPLOY.md                 # 部署与模型配置指南
```

## 文档

- [API.md](API.md) — 全部接口、权限点与错误码
- [DEPLOY.md](DEPLOY.md) — Docker 部署、本地开发、模型配置、Windows/国内网络注意事项

## 测试

```bash
cd backend
pytest
```

## License

MIT
