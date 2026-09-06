# AI 智能客服系统工作区

项目根目录：`E:\ai-customer-service-plan`  
目录建立日期：2026-09-05

后续工作按以下 7 个目录组织。现有文档保留原路径，各目录 README 提供入口。文档更新可能改变行号，定位时以章节、编号与版本为准。

| 目录入口 | 用途 |
| --- | --- |
| [产品](E:/ai-customer-service-plan/产品/README.md) | 业务目标、产品需求、页面流程、交互稿、版本范围与验收标准 |
| [归档](E:/ai-customer-service-plan/归档/README.md) | 版本快照、修订记录、历史交付与已结束阶段的证据 |
| [架构](E:/ai-customer-service-plan/架构/README.md) | 技术设计、模块边界、接口协议、数据模型、状态机与架构决策 |
| [开发](E:/ai-customer-service-plan/开发/README.md) | 应用代码、数据库迁移、开发任务、自动化测试与本地开发说明 |
| [审计](E:/ai-customer-service-plan/审计/README.md) | 产品与技术审计、安全评审、问题清单及整改复验 |
| [拓扑蓝图](E:/ai-customer-service-plan/拓扑蓝图/README.md) | 系统关系图、部署拓扑、数据流、调用时序与网络边界 |
| [运维](E:/ai-customer-service-plan/运维/README.md) | 部署配置、运行手册、监控告警、备份恢复、故障处置与客服运营 |

## 当前主文档

- [产品需求文档 PRD](E:/ai-customer-service-plan/AI智能客服系统-产品需求文档PRD.md)
- [开发文档／技术设计](E:/ai-customer-service-plan/AI智能客服系统开发文档.md)
- [运营手册](E:/ai-customer-service-plan/AI智能客服系统-运营手册.md)
- [v1.3 修订记录](E:/ai-customer-service-plan/AI智能客服系统-v1.3修订记录.md)

后端实施入口：[后端开发文档 v0.1](E:/ai-customer-service-plan/开发/后端开发文档.md)、[后端工程 v0.4](E:/ai-customer-service-plan/开发/backend/README.md)与[核心整改复验记录 v0.3](E:/ai-customer-service-plan/审计/后端核心整改复验记录-v0.3.md)。当前已实现身份、工作空间、服务停用、会话核心契约、独立删除受理日志、连续投影恢复、删除 Worker，以及受控供应商连接、助手版本和预算账本的本地闭环；生产供应商、完整 PostgreSQL 验收、导出和完整恢复验收仍待完成。

当前主文档版本为 v1.3。[前端工作空间 v0.4](E:/ai-customer-service-plan/开发/frontend/README.md)已接入后端 v0.4 的认证、会话 SSE、供应商连接、助手版本、预算、任务和服务开关；真实浏览器联调覆盖登录到流式回复及刷新持久化。既有 [v0.3 冻结版本](E:/ai-customer-service-plan/归档/前端-v0.3-冻结记录-20260905.md)保持不变，并继续由 16 项状态测试和 22 项浏览器流程回归。生产 PostgreSQL、生产供应商、导出、完整恢复及 V1 AC／NF 尚未完成，因此当前联调版本仍不构成上线交付。

## 产品工作文档

“产品”目录已根据 v1.3 建立四份主题工作稿：[产品决策](E:/ai-customer-service-plan/产品/产品决策.md)、[产品需求](E:/ai-customer-service-plan/产品/产品需求.md)、[产品状态](E:/ai-customer-service-plan/产品/产品状态.md)、[验收标准](E:/ai-customer-service-plan/产品/验收标准.md)。它们用于决策与交付追踪，详细规格继续以原 PRD 和技术设计为依据。

## 后续存放规则

任务触发、按需阅读、资料更新、提交与冻结规则统一见 [AGENTS.md](E:/ai-customer-service-plan/AGENTS.md)，验证选择见[开发任务矩阵](E:/ai-customer-service-plan/开发/README.md)。本页只维护项目导航与当前交付入口。

既有 `versions` 目录由“归档”入口统一索引；本次建立目录与导航，未迁移或复制现有文档正文。
