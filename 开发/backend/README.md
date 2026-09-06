# 后端工程（v0.4）

本目录按《后端开发文档 v0.1》分批实现 API。v0.3 在 v0.2 第一阶段的基础上完成一次核心一致性整改；v0.4 增加受控供应商连接、助手版本和预算账本的本地实现与验证入口。

当前状态：身份、工作空间、会话、删除受理与清理 Worker 的核心契约可运行。管理员可管理 OpenAI 兼容供应商连接、部署价格、助手草稿／启用／撤销／默认版本及预算策略；绑定启用助手的会话在派发前原子预留额度，在实际用量返回后结算账本。导出、末轮重试、版本迁移、对账修正、恢复验收及真实供应商接入仍待完成，不能据此视为 V1 完成或上线依据。

本页 `v0.4` 为工程交付记录版本，`pyproject.toml` 中 `0.1.0` 为当前 Python 包元数据版本，尚未同步发包；两者不视为同一发布标识。既有 v0.3 记录见[复验 v0.3](E:/ai-customer-service-plan/审计/后端核心整改复验记录-v0.3.md)。本轮的 SQLite、真实本地 HTTP 与 PostgreSQL 方言迁移检查不代替真实 PostgreSQL 实例、真实供应商、HTTP 故障或完整 V1 验收。

## 快速启动（开发环境）

```powershell
cd E:\ai-customer-service-plan\开发\backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.lock
pip install -e . --no-deps

# 本地开发配置；正式环境使用 PostgreSQL 与外部注入的随机密钥
$env:AI_CS_SECRET_KEY = "replace-with-a-local-random-string"
$env:AI_CS_BOOTSTRAP_ENABLED = "true"
$env:AI_CS_BOOTSTRAP_ADMIN_PASSWORD = "replace-with-a-strong-local-password"
$env:AI_CS_PROVIDER_ALLOWED_HOSTS = '["api.example.com"]'
$env:AI_CS_PROVIDER_KEY_ENCRYPTION_KEY = (& .\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
alembic -c migrations/business/alembic.ini upgrade head
alembic -c migrations/journal/alembic.ini upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# 另一个终端启动持久任务 Worker
ai-cs-worker
```

`AI_CS_AUTO_CREATE_SCHEMA=true` 只供一次性测试使用。常规开发及正式部署统一执行两组迁移；生产环境禁止自动建表和自动创建管理员。

供应商 Key 只在管理写入请求中接收，使用 Fernet 密文保存，读取接口只返回掩码。生产必须设置独立的 `AI_CS_PROVIDER_KEY_ENCRYPTION_KEY`，并将 `AI_CS_PROVIDER_ALLOWED_HOSTS` 限定为已批准的外部主机；默认拒绝所有供应商地址、明文 HTTP、内网地址与重定向。`AI_CS_PROVIDER_ALLOW_HTTP_FOR_LOCAL_TESTING=true` 只允许开发环境对明确允许的本地测试主机生效。

## 已包含的端点（v1）

- `GET /health`、`GET /health/ready`
- `/api/v1/auth/csrf`
- `/api/v1/auth/login`
- `/api/v1/auth/me`
- `/api/v1/auth/logout`
- `/api/v1/workspace`（GET、PATCH）
- `/api/v1/service-mode`（GET、PUT）
- `/api/v1/conversations`（持久幂等创建、分页、详情、更新、安全删除受理）
- `/api/v1/conversations/{conversation_id}/messages`（列表、发送）
- `/api/v1/conversations/{conversation_id}/messages:stream`（每段已持久化后发送 SSE，支持 JSON 重放）
- `/api/v1/conversations/{conversation_id}/submissions/{client_message_id}`
- `/api/v1/runs/{run_id}`、`/api/v1/runs/{run_id}/cancel`
- `/api/v1/jobs`、`/api/v1/jobs/{job_id}`
- `/api/v1/provider-connections`（脱敏连接、异步能力／小额调用测试）
- `/api/v1/assistants`、`/api/v1/assistant-versions`（草稿、启用、撤销与默认版本）
- `/api/v1/budget-policies/current`、`/api/v1/usage`（版本化限额、预留、结算与查询）
- 导出、末轮重试、会话版本迁移、对账修正和概览仍以 `501 Not Implemented` 形式保留

## 约定

- 统一响应含 `request_id`，错误使用 `error` 结构。
- 会话使用 HttpOnly Cookie（`cs_session`）并配合 CSRF token；登录后访问 `/auth/csrf` 返回当前会话 token，未登录时才签发预认证 token。
- 默认业务库和删除日志为两个独立 sqlite 文件，仅作本地兜底；正式环境必须分别设置 PostgreSQL URL、账号和权限。
- 所有写请求必须同时携带可信 `Origin` 与会话 CSRF token；创建、取消和删除按接口要求携带 `Idempotency-Key`。
- 会话列表默认排除未发送消息的空会话，按 `last_activity_at,id` 做服务端游标分页。
- 删除先提交业务侧 `intent_persisted` 和内容阻断，再追加独立日志；启动、Worker 和 readiness 都按 `applied_seq` 投影连续日志。日志存在而本地 intent 缺失时重建最小清理任务并继续阻断内容。
- Worker 领取记录 `claim_version`、30 秒租约、十秒心跳与最多五次退避；每次最终写入重新核对领取版本。
- 供应商连接测试由持久 Job 执行：先验证模型清单，再在当前预算策略内发出一次固定、最小输出的受控请求；配置 revision 改变后旧测试结果不可将新配置标为可用。
- 助手版本绑定会话后不可由消息请求替换；撤销会阻止尚未派发或发布的结果。供应商网络不确定结果保留预留，明确未派发才释放。
- `/health/ready` 同时检查两组 Alembic revision 和删除日志投影水位。

## 验证

按[开发任务矩阵](E:/ai-customer-service-plan/开发/README.md)选择以下命令，使用已安装锁定依赖的工程虚拟环境。只有首次准备环境或依赖变化时安装依赖，不逐次重建虚拟环境。

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app migrations tests
.\.venv\Scripts\python.exe -m mypy app
.\.venv\Scripts\python.exe -m alembic -c migrations/business/alembic.ini check
.\.venv\Scripts\python.exe -m alembic -c migrations/journal/alembic.ini check
```

`tests/test_provider_billing_contract.py` 使用实际 TCP 端口上的本地假供应商，覆盖密钥脱敏、连接 Job、助手草稿／启用／回退、受控生成、SSE 与账本结算；`tests/test_real_http.py` 分别启动 Uvicorn、一次性 Worker 与本地假供应商，经过实际 HTTP 验证登录、连接测试、助手启用、额度结算及流式调用。两者不调用外部供应商。

真实 PostgreSQL 验证使用两条专用测试 URL，不能指向开发或生产库。可在 Docker 引擎可用时执行：

```powershell
docker compose -f deploy/postgres-test.compose.yml up -d
$env:AI_CS_POSTGRES_TEST_URL = "postgresql+asyncpg://ai_cs_test:ai_cs_test_only@127.0.0.1:55432/ai_cs_business"
$env:AI_CS_POSTGRES_JOURNAL_TEST_URL = "postgresql+asyncpg://ai_cs_test:ai_cs_test_only@127.0.0.1:55432/ai_cs_journal"
.\.venv\Scripts\python.exe -m pytest tests/test_postgres_integration.py -q
docker compose -f deploy/postgres-test.compose.yml down -v
```

该用例升级两组迁移，并检查 PostgreSQL 的 `FOR UPDATE NOWAIT` 预算行锁。未提供两条专用 URL 时它会跳过，不能据此宣称 PostgreSQL 已通过。局部测试可给 pytest 指定测试文件或 `-k` 用例条件。`alembic check` 证明模型与迁移无待生成差异，不能单独证明数据回填、旧版本升级或故障恢复正确。
