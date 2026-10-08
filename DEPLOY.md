# 部署指南

## 一键 Docker 部署（推荐）

环境要求：Docker Desktop（WSL2 后端），Windows 用户需配置 ES 的 `vm.max_map_count`（见下）。

```bash
cp .env.example .env        # 可选：自定义 POSTGRES_USER/PASSWORD/DB 和 JWT_SECRET
docker compose up -d --build
```

启动后访问 **http://localhost** ，默认账号 `admin / admin123`。

启动顺序与依赖：
1. `postgres` / `elasticsearch` / `redis` 三个基础设施先起，各自 `service_healthy` 后
2. `backend` 容器执行 `alembic upgrade head`（自动迁移）再启动 uvicorn（:8000）
3. `frontend` 容器（nginx :80）等 backend healthy 后接管流量

> ⚠️ 完整栈占用 **80**（前端）和 **8000**（后端）端口；若本机端口被占，修改 `docker-compose.yml` 里的端口映射。

### 常用命令

```bash
docker compose ps                # 查看全部服务状态（应全 healthy）
docker compose logs -f backend   # 后端日志（含迁移输出）
docker compose logs -f frontend  # nginx 日志
docker compose down              # 停止（数据保留在命名卷）
docker compose up -d --build     # 代码变更后重新构建并启动
```

### 数据持久化

所有数据在 Docker 命名卷中，`docker compose down` 不会丢失：
- `pgdata`（PostgreSQL 业务数据）
- `esdata`（Elasticsearch 向量索引）
- `redisdata`（Redis）
- `uploads`（上传的原始文档，挂载到 `/app/data/uploads`）

如需彻底清除重建：`docker compose down -v`（⚠️ 会删数据）。

## 环境变量

根目录 `.env` 可覆盖（不配置则用 compose 默认值）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `rag` / `rag_dev_password` / `rag_knowledge` | PG 连接 |
| `JWT_SECRET` | `please-change-me-in-production` | **生产环境务必改为强随机值** |
| `RELEVANCE_THRESHOLD` | `0.02` | 检索相关度阈值。mock 向量相似度偏低，必须用 0.02（代码默认 0.30 仅对真实模型合理） |

后端其余配置（`JWT_*`、`EMBEDDING_PROVIDER`、`LLM_PROVIDER`、`RELEVANCE_THRESHOLD` 等）在 `backend/.env.example`，容器内由 compose 注入关键连接串，其余用代码默认值。

> 🔒 密钥不进镜像：Dockerfile 不 COPY `.env`，所有敏感配置靠 compose `environment` 注入。

## 模型配置（真实 LLM / Embedding）

默认 mock 演示。接真实模型在**根目录 `.env`** 配（容器走 compose 注入；本地开发走 `backend/.env`）：

```env
# LLM（OpenAI 兼容 chat completions）
LLM_PROVIDER=openai
LLM_API_KEY=<你的 key>
LLM_BASE_URL=https://api.siliconflow.cn/v1      # 硅基流动示例；DeepSeek 用 https://api.deepseek.com
LLM_MODEL=Qwen/Qwen2.5-7B-Instruct              # 硅基流动免费模型；DeepSeek 用 deepseek-v4-flash（deepseek-chat 已停用）

# Embedding（OpenAI 兼容 embeddings）
EMBEDDING_PROVIDER=openai
EMBEDDING_API_KEY=<你的 key>
EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_MODEL=BAAI/bge-m3                     # 1024 维
EMBEDDING_DIM=1024                              # 必须与 embedding 模型维度一致
```

要点：
- **维度**：`EMBEDDING_DIM` 必须等于 embedding 模型实际维度，且与 ES 索引 dims 一致。改维度需**删索引重建**（`curl -X DELETE localhost:9200/rag_chunks` → 重启后端自动重建 → 重新向量化文档），启动时 dims 不一致会拒绝启动。
- **provider=openai 但 key 为空**会明确报错（不静默降级 mock），保证不会"以为用真实模型实际是 mock"。
- 切换模型后**必须重启后端**（配置与 provider 都是进程内缓存）。

## 本地开发模式（不走 Docker）

```bash
# 1. 只起依赖
docker compose up -d postgres elasticsearch redis

# 2. 后端
cd backend
cp .env.example .env
python -m venv .venv && source .venv/Scripts/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# 3. 前端
cd frontend
npm install
npm run dev     # http://localhost:5173，/api 代理到 8000
```

## 升级流程

```bash
docker compose build   # 重新构建 backend/frontend 镜像
docker compose up -d   # 滚动更新，迁移由 entrypoint 自动执行
```

**升级到知识库治理版本后必跑一次时效回填**（存量文档缺 ES 时效字段，不回填会被严格过滤排除、检索结果为空；脚本幂等可重复执行，第二跑输出 `updated: 0`）：

```bash
docker compose exec backend python -m scripts.backfill_validity
```

本地开发（非容器）在 backend/ 下执行 `python -m scripts.backfill_validity`。

## ES 注意事项（Windows + Docker Desktop）

- ES 容器启动即退出报 `vm.max_map_count [65530] is too low`：编辑 `C:\Users\<你>\.wslconfig`：
  ```ini
  [wsl2]
  kernelCommandLine = "sysctl.vm.max_map_count=262144"
  ```
  然后 PowerShell 运行 `wsl --shutdown` 重启 Docker Desktop。
- ES 内存限制 512m（`ES_JAVA_OPTS`），向量化大文档时若 OOM 可适当调高。
- `EMBEDDING_DIM` 建索引后不可修改，换维度需删 ES 索引重建。

## 国内网络说明

- 基础设施与基础镜像走 `docker.1ms.run` 镜像加速器前缀（还原官方源只需去掉前缀）。
- 后端 pip 默认清华源、前端 npm 默认 npmmirror（均为 Dockerfile 中 `ARG`，可覆盖）。
- ES IK 插件从 `get.infini.cloud` 下载，失败降级路径见 `docker/es/Dockerfile` 注释。
