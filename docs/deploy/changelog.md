# 部署文档变更记录

| 日期 | 文档 | 版本 | 变更内容 | 关联 Commit |
|------|------|------|---------|-------------|
| 2026-05-13 | [railway.md](railway.md) | v1.0 — addendum (P0 hardening) | **hardening-iteration-v1 P0 部署补丁**（不改 deploy 文档主体）：本次部署引入 3 处与运维相关的行为变更——(1) **新增依赖** `flask-limiter>=3.5`（已加入 requirements.txt），Railway 单 worker 默认走内存 storage 即可；多 worker 部署必须在 Variables 设 `RATELIMIT_STORAGE_URI=redis://...`（否则各 worker 限流计数器互不感知）；(2) `/api/diagnostics/providers` 改为 admin-only（@admin_required）—— 此前 deploy 文档 §6.2 的"必跑"步骤需要先以 admin 登录（multi-tenant 首启自动创建 admin@local，密码在 `to_multi_tenant.py` 输出日志中可见）；(3) `/api/settings` GET+POST 改为 admin-only，普通用户访问 `/settings` 页面会看到 LLM/OAuth API key 区块 403 但用户级 LoginMethodsSection 仍可读 —— 这是修复 C3 关键安全漏洞（普通用户可改全局 LLM API key）的必要副作用。**部署前置检查**：`flask-limiter` + `flask-wtf>=1.2`（已声明，未接入；本期接入 CSRFProtect）2 个依赖必装到位，`pip install -r requirements.txt` 一行解决。**Health check 不受影响**：`/api/health` 未变（200 OK + `{"status":"ok"}`），Railway healthcheck 流程零影响。**冷启动行为**：CSRFProtect / Limiter `init_app` 都是 O(1) 操作，对启动延迟无可测影响。 | — |
| 2026-04-15 | [railway.md](railway.md) | v1.0 | Railway PaaS 部署指南：环境变量、Volume 配置、数据源诊断、任务系统验证、FAQ | `fa3c653` |
