# 知应 AI · 前端工作空间

当前工程版本为 v0.4.0，依据总体技术设计 v1.3、后端开发文档 v0.1 和后端工程 v0.4 接入真实 API。默认运行模式使用后端身份、权限、会话、供应商连接、助手版本、预算账本、任务和服务开关。既有 [v0.3 冻结记录](E:/ai-customer-service-plan/归档/前端-v0.3-冻结记录-20260905.md)及冻结包保持不变；`VITE_DEMO_MODE=true` 只用于回归该冻结版的内存交互。

## 已接入能力

- 用户名密码登录、HttpOnly 会话 Cookie、预认证及会话 CSRF、退出登录和管理员路由。
- 工作空间名称、自动回复服务状态及配置修订冲突处理。
- 会话创建、列表、消息读取、安全删除受理、任务追踪；发送消息使用 SSE 流式协议，支持停止运行和刷新后恢复历史。
- OpenAI 兼容供应商连接、后端密钥保存、部署价格与 Token 上限、真实连接测试 Job。
- 助手元数据、草稿版本、启用、撤销及默认版本；版本绑定当前模型部署和预算策略。
- 当前预算策略、工作空间日／月限额、实际调用 Token、预算账户消费与预留汇总。

后端尚未开放的会话导出、末轮重试、版本迁移、对账修正和概览聚合不会在真实模式中模拟成功。概览由已接入的列表和账本数据组合显示。

## 本地运行

要求 Node.js 24.12.0 或更高、pnpm 11.19.0，并先按[后端工程说明](E:/ai-customer-service-plan/开发/backend/README.md)启动 API 和 Worker：

```powershell
Set-Location -LiteralPath 'E:\ai-customer-service-plan\开发\backend'
# 配置开发环境、完成两组迁移后：
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# 另一个终端：
.\.venv\Scripts\python.exe -m app.worker

Set-Location -LiteralPath 'E:\ai-customer-service-plan\开发\frontend'
pnpm install --frozen-lockfile
pnpm dev
```

打开 [登录页](http://127.0.0.1:5173/#/login)。Vite 将 `/api` 和 `/health` 代理到 `VITE_API_PROXY_TARGET`，默认是 `http://127.0.0.1:8000`。构建预览同样配置该代理；静态文件若交给其他 Web 服务器，需要由部署层把 `/api/v1` 转发到后端。

可复制 [.env.example](E:/ai-customer-service-plan/开发/frontend/.env.example)调整 API 路径和代理目标。不得把供应商 Key、会话密钥或其他机密写入 `VITE_*`；所有 `VITE_*` 值都会进入浏览器构建产物。

## 建议配置顺序

首次登录管理员账户后，按以下顺序完成真实对话配置：

1. 在“用量与预算”保存日／月预算策略。
2. 在“模型连接”填写 API 地址、模型、价格和 API Key，提交真实连接测试；后端 Worker 必须运行。
3. 在“助手配置”保存草稿，启用并设为默认版本。
4. 在“对话工作台”新建会话并发送消息。

连接或价格变化会递增连接 revision 并使旧测试结果失效；需重新测试并为助手创建绑定新 deployment 的版本。

## 构建与验证

```powershell
pnpm build
pnpm test
pnpm test:e2e
pnpm test:e2e:live
```

- `build`：执行 Vue/TypeScript 类型检查并生成 `dist`。
- `test`：运行 16 项冻结版状态边界回归。
- `test:e2e`：以 `VITE_DEMO_MODE=true` 运行 22 项冻结版页面回归，不需要后端。
- `test:e2e:live`：启动真实 Uvicorn、Vite、本地 OpenAI 兼容测试服务，并调用一次后端 Worker；验证登录、预算、连接测试、助手启用、SSE 回复及刷新后持久化。测试使用隔离的临时 SQLite 文件和本地假供应商，不调用外部模型。

真实 PostgreSQL、生产供应商、负载、备份恢复和全部 V1 AC／NF 仍按总体开发文档及后端说明单独验收。本地联调用例证明浏览器到现有后端契约的闭环，不等于生产上线验收。

## 目录

| 位置 | 职责 |
| --- | --- |
| `src/services/api.ts` | JSON 请求、错误映射、Cookie/CSRF 和 SSE 解析 |
| `src/stores/liveWorkspace.ts` | 后端 DTO 到页面状态的适配及实际业务操作 |
| `src/stores/workspace.ts` | v0.3 演示 store；环境开关选择 live/demo |
| `src/views` | 登录、聊天、历史、连接、助手、预算、任务及设置页面 |
| `playwright.live.config.ts`、`tests/live.spec.ts` | 隔离的真实前后端浏览器联调 |
| `public/space.html` | 保留的独立星球首页 |

页面范围和剩余能力见[前端功能模块](E:/ai-customer-service-plan/产品/前端功能模块.md)，后端接口与运行约定见[后端工程 README](E:/ai-customer-service-plan/开发/backend/README.md)。
