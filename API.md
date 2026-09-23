# API 接口文档

所有业务接口前缀 `/api/v1`。除注册/登录外，均需请求头 `Authorization: Bearer <access_token>`。
统一错误响应：`{"code": "<错误码>", "message": "<中文说明>", "detail": null}`，常见状态码 400/401/403/404/409/413/422。

默认角色权限：`admin`（`*:*` 全部）、`editor`、`viewer`。权限点语法 `模块:动作`。

## 认证 auth

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/auth/register` | 公开 | 注册（默认 viewer 角色），返回 token + user |
| POST | `/auth/login` | 公开 | 登录，返回 token + user |
| POST | `/auth/refresh` | 公开 | 刷新 token |
| GET | `/auth/me` | 登录 | 当前用户信息（含 roles/role_ids） |

## 知识库 knowledge-bases

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/knowledge-bases` | `kb:read` | 列表 |
| POST | `/knowledge-bases` | `kb:create` | 创建（name/description/chunk_size/chunk_overlap） |
| GET | `/knowledge-bases/{id}` | `kb:read` | 详情 |
| PUT | `/knowledge-bases/{id}` | `kb:update` | 更新（局部） |
| DELETE | `/knowledge-bases/{id}` | `kb:delete` | 删除（级联文档/分块 + 清 ES） |

## 文档 documents

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/knowledge-bases/{kb_id}/docs` | `doc:upload` | 上传（pdf/docx/md/txt，≤20MB） |
| GET | `/knowledge-bases/{kb_id}/docs` | `doc:read` | 列表（分页 + search 按文件名） |
| GET | `/docs/{id}` | `doc:read` | 详情（含向量化状态） |
| POST | `/docs/{id}/vectorize` | `doc:vectorize` | 手动触发向量化（异步，前端轮询状态） |
| GET | `/docs/{id}/chunks` | `doc:read` | 分块预览（不落库） |
| DELETE | `/docs/{id}` | `doc:delete` | 删除（级联分块 + 清 ES） |

## 检索 search

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/search` | `kb:read` | 混合检索。body `{query, kb_id, top_k, search_type: hybrid\|vector\|keyword}`，返回结果含来源/分块/相似度 |

## 智能问答 chat

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/chat/sessions` | `chat:use` | 创建会话（title/kb_id） |
| GET | `/chat/sessions` | `chat:history` | 我的会话列表 |
| GET | `/chat/sessions/{id}` | `chat:history` | 会话详情（session + messages） |
| DELETE | `/chat/sessions/{id}` | `chat:history` | 删除会话（级联消息） |
| POST | `/chat/sessions/{id}/messages` | `chat:use` | 发送消息，**SSE 流式**。事件：`start`→`token`(每8字符)→`done{message_id, answer, sources, model}` 或 `error` |
| POST | `/chat/messages/{message_id}/feedback` | `chat:use` | 消息反馈。body `{feedback: "like"\|"dislike"\|null}`。切换语义：同值=取消、不同值=切换、null=清除。仅 assistant 消息可反馈；他人消息 403 |

## 用户管理 users（admin）

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/users` | `user:manage` | 列表（分页 + search username/email） |
| POST | `/users` | `user:manage` | 创建（username/email/password/role_ids/status） |
| PUT | `/users/{id}` | `user:manage` | 更新（局部：username/email/password/status/role_ids）。护栏：禁禁用/删除自己、禁授 admin（仅 `*:*` 可授） |
| DELETE | `/users/{id}` | `user:manage` | 删除。护栏：禁删自己/禁删 admin |

## 角色管理 roles（admin）

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/roles/permissions` | `role:manage` | 权限目录（按模块分组，前端权限树数据源） |
| GET | `/roles` | `role:manage` | 角色列表（含 user_count） |
| POST | `/roles` | `role:manage` | 创建（name/description/permissions，校验权限点合法性） |
| PUT | `/roles/{id}` | `role:manage` | 更新。内置角色仅允许改 description |
| DELETE | `/roles/{id}` | `role:manage` | 删除。内置角色/有用户引用的角色禁止删除 |

## 系统配置 system-configs（admin）

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/system-configs` | `system:config` | 全部配置（key/value/description） |
| PUT | `/system-configs` | `system:config` | 批量 upsert，body `{configs: [{key, value?, description?}]}`，支持部分 key |

配置当前仅存储，接入真实模型后生效。预置 key：`llm.provider/api_key/base_url/model`、`embedding.provider/model`、`chunk.size/overlap`。

## 概览统计 stats

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | `/stats/overview` | `kb:read` | 概览：kb_total/doc_total/user_total/today_chat_count + recent_sessions(10) + kb_distribution + doc_upload_trend(近7天) |

## 其他

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查（不在 /api/v1 下） |
| GET | `/docs` | Swagger UI |
