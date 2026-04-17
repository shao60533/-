# 架构升级测试用例 — Qwen 数据层 + TV 图表 + 异步任务系统

> **版本**: 1.0  
> **日期**: 2026-04-15  
> **依据**: [架构升级方案](ARCHITECTURE_UPGRADE_PROPOSAL.md)  
> **范围**: 本次升级涉及的新增/重构模块，**不重复** [TEST_CASES.md](TEST_CASES.md) 中已覆盖的原有功能测试

---

## 一、TaskManager 异步任务系统

### 1.1 TaskStore（任务持久化）

| ID | 用例 | 前置条件 | 步骤 | 预期结果 |
|----|------|---------|------|----------|
| TS-1.1.1 | 插入任务记录 | 空数据库 | 调用 `store.insert({id, type, title, params_json, status:"pending", ...})` | 记录写入成功，`get(id)` 能读回；`created_at` 自动填充 |
| TS-1.1.2 | 更新任务状态 | 已有 pending 任务 | `store.update(id, status="running", started_at=...)` | 记录状态更新，其他字段保留 |
| TS-1.1.3 | 按类型筛选 | 10 条任务（分 4 种 type） | `store.list(task_type="analysis")` | 只返回 `type=analysis` 的任务 |
| TS-1.1.4 | 按状态筛选 | 3 running + 5 success + 2 failed | `store.list(status="failed")` | 返回 2 条 failed 任务 |
| TS-1.1.5 | 分页查询 | 50 条任务 | `store.list(limit=10, offset=20)` | 返回第 21-30 条 |
| TS-1.1.6 | 时间倒序 | 多条任务 | `store.list()` | 按 `created_at DESC` 排序，最新在前 |
| TS-1.1.7 | 幂等查找命中 | 60s 内已有相同 `params_hash` 的 success 任务 | `store.find_recent_by_hash(hash, 60, ("pending","running","success"))` | 返回该任务 |
| TS-1.1.8 | 幂等查找超窗口未命中 | 2 小时前的同 hash 任务 | `store.find_recent_by_hash(hash, 60, ...)` | 返回 None |
| TS-1.1.9 | 幂等仅匹配指定状态 | 有 failed 任务 | `find_recent_by_hash(hash, 60, ("success",))` | 不匹配 failed，返回 None |
| TS-1.1.10 | 保存任务结果并记录 ref | 任务完成 | `store.save_result("analysis", task_id, result_dict)` | 写入 `analysis_history` 表，返回 `result_ref="analysis_history:42"` |
| TS-1.1.11 | 通过 result_ref 加载结果 | 已有 result_ref | `store.load_result("analysis_history:42")` | 返回完整结果 dict |
| TS-1.1.12 | 过期任务清理 | 31 天前的任务 | 执行 `cleanup_expired(days=30)` | 该记录被删除 |
| TS-1.1.13 | 状态索引生效 | 1000+ 任务 | `list(status="running")` 响应时间 | < 50ms |
| TS-1.1.14 | 特殊字符 params_json | title 含中文/emoji | 插入 + 读回 | 内容无损 |
| TS-1.1.15 | 并发写入不冲突 | 3 线程同时 insert | 全部成功 | 无 SQLite locked 错误 |

### 1.2 TaskManager 核心逻辑

| ID | 用例 | 前置条件 | 步骤 | 预期结果 |
|----|------|---------|------|----------|
| TM-1.2.1 | 注册 Worker | TaskManager 实例化 | `tm.register("analysis", worker_fn)` | 后续 `submit("analysis", ...)` 会路由到该函数 |
| TM-1.2.2 | 提交任务 | 已注册 analysis worker | `tm.submit("analysis", {"ticker":"AAPL"})` | 返回 `{id, type, status:"pending", title, ...}`；`tasks` 表新增记录 |
| TM-1.2.3 | 自动生成人类可读标题 | 不传 title | `tm.submit("analysis", {"ticker":"AAPL"})` | `title` 自动生成为 "AAPL 分析 · 2026-04-15 HH:MM" |
| TM-1.2.4 | 未知任务类型 | 未注册 "unknown" | `tm.submit("unknown", {})` | 立即标 `failed`，`error_message="Unknown task type"` |
| TM-1.2.5 | Worker 执行成功 | analysis worker 返回 result | 提交任务，等待完成 | status 依次变化：pending → running → success；`result_ref` 被填充 |
| TM-1.2.6 | Worker 抛异常 | analysis worker 抛 ValueError | 提交任务 | status 变为 failed；`error_message`、`error_trace` 填充完整 stack |
| TM-1.2.7 | 进度回调推送 | worker 中调用 `progress_cb(50, "中间步骤")` | 前端监听 `task_progress` 事件 | 收到 `{id, progress:50, step:"中间步骤"}` |
| TM-1.2.8 | `task_created` 事件 | 提交任务 | WS 监听 | 前端收到 `task_created` 含完整任务元数据 |
| TM-1.2.9 | `task_started` 事件 | Worker 开始执行 | WS 监听 | 收到 `{id}` |
| TM-1.2.10 | `task_completed` 事件 | Worker 成功返回 | WS 监听 | 收到 `{id, result_ref}` |
| TM-1.2.11 | `task_failed` 事件 | Worker 抛异常 | WS 监听 | 收到 `{id, error_message}` |
| TM-1.2.12 | 幂等窗口命中 | 60s 内已提交相同 params | 再次 `tm.submit("analysis", 相同 params)` | 返回已有 task，不创建新 worker 调用 |
| TM-1.2.13 | 幂等窗口外创建新任务 | 2 小时前完成 | 相同参数提交 | 新建任务 |
| TM-1.2.14 | 幂等窗口可关闭 | 用户强制重跑 | `tm.submit(..., idempotency_window=0)` | 强制新建 |
| TM-1.2.15 | 重试任务 | 有一个 failed 任务 | `tm.retry(old_id)` | 新任务创建；`retry_of=old_id` 指向原任务 |
| TM-1.2.16 | 重试不存在的任务 | 错误 task_id | `tm.retry("bogus")` | 抛 ValueError |
| TM-1.2.17 | 取消 pending 任务 | 线程池已满的 pending 任务 | `tm.cancel(id)` | 返回 True；status=cancelled |
| TM-1.2.18 | 无法取消已完成任务 | status=success | `tm.cancel(id)` | 返回 False |
| TM-1.2.19 | 参数哈希稳定 | 相同 dict 不同顺序 | 两次 `_hash_params` | 返回相同 hash（key 排序） |
| TM-1.2.20 | 并发提交 | 3 个线程同时提交不同任务 | 全部完成 | 3 个 task_id 独立，结果不串 |
| TM-1.2.21 | 线程池容量限制 | `max_workers=2`，提交 5 个任务 | 观察执行顺序 | 前 2 个立即 running，后 3 个 pending，完成一个派发一个 |
| TM-1.2.22 | 服务重启后挂起任务处理 | 重启前有 running 任务 | 重启 | 启动时 running 状态扫描并标记 `failed: "服务中断"` |

### 1.3 REST API

| ID | 用例 | 请求 | 预期结果 |
|----|------|------|----------|
| TA-1.3.1 | 提交任务 | `POST /api/tasks/submit {type:"analysis", params:{ticker:"AAPL"}}` | 200；返回完整任务对象 |
| TA-1.3.2 | 提交未注册类型 | `POST /api/tasks/submit {type:"invalid", params:{}}` | 400，`error` 字段明确 |
| TA-1.3.3 | 列出任务 | `GET /api/tasks` | 返回数组（<=50 条） |
| TA-1.3.4 | 按类型筛选 | `GET /api/tasks?type=analysis` | 只返回 analysis 类型 |
| TA-1.3.5 | 按状态筛选 | `GET /api/tasks?status=failed` | 只返回 failed |
| TA-1.3.6 | 分页 | `GET /api/tasks?limit=10&offset=20` | 返回第 21-30 条 |
| TA-1.3.7 | 任务详情 | `GET /api/tasks/<id>` | 含 params / error / progress / 时间字段 |
| TA-1.3.8 | 不存在的任务 | `GET /api/tasks/bogus-id` | 404 |
| TA-1.3.9 | 获取结果 | `GET /api/tasks/<id>/result` | 跳转业务表返回完整结果 |
| TA-1.3.10 | 未完成任务的结果 | pending 任务的 `/result` | 404 或返回 `{status:"pending"}` |
| TA-1.3.11 | 重试任务 | `POST /api/tasks/<id>/retry` | 新任务创建，返回新 task |
| TA-1.3.12 | 取消任务 | `POST /api/tasks/<id>/cancel` | success/failed 返回 200；否则 409 |
| TA-1.3.13 | 删除任务记录 | `DELETE /api/tasks/<id>` | 记录被删，结果表不动 |
| TA-1.3.14 | 鉴权（若启用） | 无 token | 401 |

### 1.4 Workers 业务逻辑

| ID | 用例 | 步骤 | 预期结果 |
|----|------|------|----------|
| WK-1.4.1 | analysis worker 成功 | 提交有效 ticker | 7 Agent 全跑完，结果写 `analysis_history`，progress 步进 0→100 |
| WK-1.4.2 | analysis worker 进度粒度 | 提交 AAPL 分析 | 至少 7 次 progress 更新（每 Agent 一次） |
| WK-1.4.3 | analysis worker 异常 | 无效 ticker "ZZZZ" | 标 failed，error 信息清晰 |
| WK-1.4.4 | screen worker 成功 | 美股 growth 策略 | 三层筛选完成，结果写 `screen_results` |
| WK-1.4.5 | screen worker 进度 | 提交选股 | 3 次 progress 更新（每层一次） |
| WK-1.4.6 | backtest worker 成功 | SMA 策略 AAPL 1y | 结果写 `backtest_results`，含 equity_curve + trades + metrics |
| WK-1.4.7 | backtest 数据不足 | 1 天期间的回测 | failed，错误信息明确 |
| WK-1.4.8 | report worker 成功 | daily 报告 | 返回 Markdown 字符串 |
| WK-1.4.9 | qwen_fundamentals worker | AAPL | 返回 fundamentals dict，写 fundamentals_cache |
| WK-1.4.10 | qwen_news worker | AAPL | 返回 news 数组，写 news_cache |

---

## 二、LocalCache（SQLite 缓存层）

### 2.1 通用缓存行为

| ID | 用例 | 步骤 | 预期结果 |
|----|------|------|----------|
| LC-2.1.1 | 价格缓存写入 | `cache.set_price("AAPL", {"last":150})` | 记录写入，`fetched_at=now` |
| LC-2.1.2 | 价格缓存命中 | 写入后立即读 | 返回相同数据 |
| LC-2.1.3 | 价格缓存 TTL 过期 | 写入 > 60s 后读 | 返回 None（视为未命中） |
| LC-2.1.4 | 基本面缓存 TTL（24h） | 12h 后读 | 命中；25h 后读未命中 |
| LC-2.1.5 | 新闻缓存 TTL（1h） | 30min 后读 | 命中；70min 后读未命中 |
| LC-2.1.6 | 日线 K 线缓存 | 写入 + 12h 内读 | 命中 |
| LC-2.1.7 | 分钟线 TTL（5min） | 6min 后读 | 未命中 |
| LC-2.1.8 | 多键独立 | AAPL 和 TSLA 各自缓存 | 互不影响 |
| LC-2.1.9 | 覆盖写入 | 同 key 连续写 2 次 | 保留最新值 + 新 fetched_at |
| LC-2.1.10 | 大数据量（DataFrame） | 1 年日线 pickle 存储 | 读回等价 DataFrame |
| LC-2.1.11 | TTL 可配置 | 修改配置为 `daily_bars: 3600` | 1 小时后未命中 |
| LC-2.1.12 | 清理过期记录 | 执行 `cleanup()` | 过期记录被删除，未过期保留 |
| LC-2.1.13 | 缓存 miss 不抛异常 | 读不存在的 key | 返回 None |
| LC-2.1.14 | 并发读写安全 | 3 线程同时 get/set | 无数据损坏 |
| LC-2.1.15 | 缓存目录不存在自动创建 | 首次初始化 | 目录 + db 文件创建成功 |

### 2.2 缓存命中率

| ID | 用例 | 步骤 | 预期结果 |
|----|------|------|----------|
| LH-2.2.1 | 重复拉价格命中率 | 1 分钟内读 10 次 AAPL | 首次 miss，后续 9 次 hit（命中率 90%） |
| LH-2.2.2 | 仪表盘刷新性能 | 10 只持仓，60s 内连续刷 3 次 | 第 2、3 次 <2s |
| LH-2.2.3 | 基本面批量缓存 | 5 只股票依次读 → 重读 | 第二轮全部 hit |

---

## 三、DataRouter 路由层

### 3.1 路由决策

| ID | 用例 | 配置 | 步骤 | 预期结果 |
|----|------|------|------|----------|
| DR-3.1.1 | primary=qwen 时走 Qwen | `primary:"qwen"`, `qwen.enabled:true` | `get_price("AAPL")` | 先调 QwenProvider |
| DR-3.1.2 | Qwen 失败自动 fallback | Qwen 返回 None | `get_price("AAPL")` | 降级到 yfinance |
| DR-3.1.3 | primary=local 时跳过 Qwen | `primary:"local"` | `get_price("AAPL")` | 直接走 yfinance，不调 Qwen |
| DR-3.1.4 | A 股走 AkShare | ticker="600519" | `get_price("600519")` | 路由到 AkShare（如 primary=local）或 Qwen（primary=qwen） |
| DR-3.1.5 | 缓存命中时不调外部 | 60s 内第 2 次调用 | `get_price("AAPL")` | 不调 Qwen/yfinance，直接返回缓存 |
| DR-3.1.6 | 缓存 miss 时调用源并写回 | 首次调用 | `get_price("AAPL")` | 调用外部 + 写入缓存 |
| DR-3.1.7 | 禁用缓存时不读写 | `enable_cache:false` | 连续 2 次调用 | 都走外部源 |
| DR-3.1.8 | `get_history_for_backtest` 绝不走 Qwen | `primary:"qwen"` | 调用该方法 | 直接走 yfinance/AkShare，日志无 Qwen 调用 |
| DR-3.1.9 | `get_history_for_backtest` 命中缓存 | 12h 内重复调用 | 第二次调用 | 不调 yfinance，返回缓存 |
| DR-3.1.10 | Qwen 未启用时降级 | `qwen.enabled:false` + `primary:"qwen"` | `get_price` | 直接走 yfinance |
| DR-3.1.11 | IB/Polygon 禁用生效 | `ib_enabled:false, polygon_enabled:false` | `get_price` | 链路中跳过，直接 yfinance |

### 3.2 数据合理性校验

| ID | 用例 | Qwen 返回 | 预期结果 |
|----|------|-----------|----------|
| DV-3.2.1 | PE 极端值被过滤 | `pe_ratio: 999999` | 字段置空或整条记录被拒（按配置） |
| DV-3.2.2 | 负市值被过滤 | `market_cap: -1e9` | 字段置空 |
| DV-3.2.3 | ROE 越界 | `roe: 1500` (%)  | 字段置空（应在 -500~500 内） |
| DV-3.2.4 | 空 ticker 被拒 | `{ticker:""}` | 返回 None |
| DV-3.2.5 | 必填字段缺失 | 无 `last` 价格 | 返回 None |
| DV-3.2.6 | JSON 解析失败 | 模型返回非 JSON 文本 | 返回 None，降级到 fallback |

---

## 四、Qwen Provider 扩展

### 4.1 get_fundamentals

| ID | 用例 | 步骤 | 预期结果 |
|----|------|------|----------|
| QF-4.1.1 | 美股返回完整字段 | `get_fundamentals("AAPL")` | 返回含 market_cap/pe_ratio/pb_ratio/roe/... |
| QF-4.1.2 | A 股返回 | `get_fundamentals("600519")` | 返回基本面数据（贵州茅台） |
| QF-4.1.3 | 无效 ticker | `get_fundamentals("ZZZZ")` | 返回 None |
| QF-4.1.4 | 返回附带 `source` 和 `as_of` | 任意查询 | 字段非空 |
| QF-4.1.5 | 响应时间 | `get_fundamentals("AAPL")` | 3-10s |
| QF-4.1.6 | 缓存命中不调 Qwen | 24h 内重复查 | 第二次响应 <500ms |
| QF-4.1.7 | confidence 字段返回 | 若 prompt 要求 | 返回 `high|medium|low` |
| QF-4.1.8 | Qwen 未启用 | `enabled:false` | 立即返回 None |

### 4.2 get_news

| ID | 用例 | 步骤 | 预期结果 |
|----|------|------|----------|
| QN-4.2.1 | 返回新闻列表 | `get_news("AAPL")` | 数组，每项 title/url/date/source/summary |
| QN-4.2.2 | 数量限制 | `get_news("AAPL", limit=5)` | 最多 5 条 |
| QN-4.2.3 | 中文新闻（A 股） | `get_news("600519")` | 中文 title + 中文 source |
| QN-4.2.4 | 缓存命中 | 1h 内重复查 | 不调 Qwen |
| QN-4.2.5 | 空结果 | 冷门股票 | 返回 `[]` 不抛错 |
| QN-4.2.6 | URL 有效 | 抽样 3 条 | URL 可访问（至少是 http/https 格式） |

### 4.3 不实现 get_history

| ID | 用例 | 步骤 | 预期结果 |
|----|------|------|----------|
| QH-4.3.1 | QwenProvider 无 get_history 方法 | 代码检查 | `hasattr(qwen, 'get_history')` 为 False |
| QH-4.3.2 | DataRouter 回测不调 Qwen | mock Qwen，调用 `get_history_for_backtest` | Qwen 未被调用 |

---

## 五、TradingView Widget 集成

### 5.1 前端渲染

| ID | 用例 | 步骤 | 预期结果 |
|----|------|------|----------|
| TV-5.1.1 | 美股 widget 加载 | 分析页输入 AAPL | TV Widget iframe 加载，显示 AAPL NASDAQ K 线 |
| TV-5.1.2 | A 股主板加载 | 输入 600519 | 显示 SSE 数据 |
| TV-5.1.3 | 深交所股票 | 输入 000001 | 显示 SZSE 数据 |
| TV-5.1.4 | 符号映射正确 | `toTVSymbol("AAPL")` | 返回 "NASDAQ:AAPL" |
| TV-5.1.5 | NYSE 白名单 | `toTVSymbol("JPM")` | 返回 "NYSE:JPM" |
| TV-5.1.6 | A 股 6xx | `toTVSymbol("600519")` | 返回 "SSE:600519" |
| TV-5.1.7 | A 股 00x/30x | `toTVSymbol("000001")` | 返回 "SZSE:000001" |
| TV-5.1.8 | 暗色主题 | 加载 Widget | theme:"dark"，与系统主题一致 |
| TV-5.1.9 | 默认叠加均线 + 成交量 | 加载 Widget | studies 列表含 MASimple + Volume |
| TV-5.1.10 | 切换 ticker 正确重载 | AAPL → TSLA | 前一个 Widget 销毁，新 Widget 加载 TSLA |
| TV-5.1.11 | 移动端适配 | 手机宽度查看 | Widget 自适应容器宽度 |
| TV-5.1.12 | 触摸缩放 | 手机上捏合 | Widget 正常缩放 |
| TV-5.1.13 | 保留 TV 署名 | 查看 Widget 右下角 | "Powered by TradingView" 可见 |

### 5.2 降级方案

| ID | 用例 | 步骤 | 预期结果 |
|----|------|------|----------|
| TV-5.2.1 | TV 不可用时降级 | 断网环境或 tv.js 404 | 加载失败 → 自动降级到 ECharts candlestick |
| TV-5.2.2 | 小盘股 TV 不支持 | 输入 ST 股票代码 | Widget 报错 → 降级 ECharts |
| TV-5.2.3 | 配置开关禁用 TV | `config.chart_provider="echarts"` | 直接用 ECharts，不加载 tv.js |

---

## 六、回测引擎

### 6.1 策略

| ID | 用例 | 步骤 | 预期结果 |
|----|------|------|----------|
| BT-6.1.1 | SMA 交叉策略 | AAPL 1y short=20 long=50 | 返回完整 BacktestResult（equity_curve + trades + metrics） |
| BT-6.1.2 | RSI 均值回归 | AAPL 1y period=14 | 返回结果 |
| BT-6.1.3 | 买入持有 | AAPL 1y | 交易次数 = 1（仅入场） |
| BT-6.1.4 | 策略列表 API | `GET /api/backtest/strategies` | 返回 3 种策略及参数说明 |

### 6.2 指标计算

| ID | 用例 | 步骤 | 预期结果 |
|----|------|------|----------|
| BM-6.2.1 | 总收益率正确 | 初始 100000，期末 120000 | `total_return ≈ 20%` |
| BM-6.2.2 | 最大回撤 | 已知回撤 10% 的序列 | `max_drawdown ≈ -10%` |
| BM-6.2.3 | 胜率 | 10 笔交易 6 盈 4 亏 | `win_rate = 60%` |
| BM-6.2.4 | 年化收益 | 2 年累计 21% | `annualized ≈ 10%` |
| BM-6.2.5 | 交易次数 | 策略产生 5 次完整进出 | `total_trades = 5` |

### 6.3 数据源与缓存

| ID | 用例 | 步骤 | 预期结果 |
|----|------|------|----------|
| BD-6.3.1 | 首次回测拉 yfinance | 冷启动 | yfinance 被调用，数据写入 bars_cache |
| BD-6.3.2 | 重复回测命中缓存 | 12h 内重跑相同参数 | 不调 yfinance，响应 <100ms |
| BD-6.3.3 | 回测结果持久化 | 完成一次回测 | `backtest_results` 表新增记录 |
| BD-6.3.4 | 回测不调 Qwen | 执行回测 | Qwen API 调用次数为 0 |
| BD-6.3.5 | 数据不足 | 请求 10 年但 yfinance 只返回 1 年 | 使用可用数据 + 日志提示 |
| BD-6.3.6 | 历史数据为空时 | 无效 ticker | 任务 failed + error "No data available" |

### 6.4 回测任务化

| ID | 用例 | 步骤 | 预期结果 |
|----|------|------|----------|
| BT-6.4.1 | 通过任务系统提交 | `POST /api/tasks/submit {type:"backtest", ...}` | 立即返回 task_id |
| BT-6.4.2 | WS 推送进度 | 回测进行中 | 收到 `task_progress` 事件（至少几次） |
| BT-6.4.3 | 回测完成后前端渲染 | 监听 `task_completed` | 调用 `/api/tasks/<id>/result` 拉完整结果渲染 |
| BT-6.4.4 | 幂等：相同参数复用 | 60s 内重复提交 | 返回已有 task，不重跑 |

---

## 七、任务中心前端页面

### 7.1 UI 与基础交互

| ID | 用例 | 步骤 | 预期结果 |
|----|------|------|----------|
| UT-7.1.1 | 页面入口 | 侧边栏 + 更多 Sheet | 均有"任务中心"入口 |
| UT-7.1.2 | 任务列表加载 | 进入页面 | 调 `/api/tasks`，渲染列表 |
| UT-7.1.3 | 状态 pill 过滤 | 点击"失败"标签 | 列表筛选为 failed 任务 |
| UT-7.1.4 | 空数据状态 | 无任务 | 显示空状态提示 |
| UT-7.1.5 | 时间倒序 | 列表 | 最新任务在顶部 |
| UT-7.1.6 | 加载更多 | 滚动到底 | 分页加载下一页 |
| UT-7.1.7 | 任务标题展示 | 列表项 | 显示 title + 耗时 + 状态 |
| UT-7.1.8 | 运行中任务实时进度 | 提交一个任务后停留在任务中心 | 进度条随 `task_progress` 事件更新 |

### 7.2 任务操作

| ID | 用例 | 步骤 | 预期结果 |
|----|------|------|----------|
| UT-7.2.1 | 查看详情 | 点击任务项 → 详情 | 展示 params / error_trace / 时间字段 |
| UT-7.2.2 | 查看结果 | 成功任务点击"查看结果" | 跳转到对应业务页（分析记录/回测/选股） |
| UT-7.2.3 | 重试失败任务 | 失败任务点击"重试" | 新任务创建，标注 retry_of |
| UT-7.2.4 | 取消运行中任务 | 点击"取消" | 状态变为 cancelled |
| UT-7.2.5 | 删除任务记录 | 点击"删除" | 列表移除，结果表不动 |
| UT-7.2.6 | 错误 trace 折叠 | 失败任务详情 | 默认折叠，点击展开显示完整 trace |

### 7.3 跨页面集成

| ID | 用例 | 步骤 | 预期结果 |
|----|------|------|----------|
| UX-7.3.1 | 分析页提交 → 任务中心可见 | 分析页点"分析" | 任务中心立即出现该任务 |
| UX-7.3.2 | 关闭分析页后任务继续 | 切换到其他页面 | 任务仍在执行，完成时 Toast 通知 |
| UX-7.3.3 | 重连后状态同步 | 断开 Wi-Fi 30 秒 → 恢复 | 任务中心自动同步最新状态 |
| UX-7.3.4 | 分析页内 WS 完成事件自动渲染 | 停留在分析页 | 收到 `task_completed` → 自动加载并渲染结果 |
| UX-7.3.5 | 幂等提示 | 60s 内相同 ticker 重复点分析 | Toast 提示"已有任务进行中，跳转查看" |

---

## 八、WebSocket 事件统一

| ID | 用例 | 步骤 | 预期结果 |
|----|------|------|----------|
| WS-8.1 | 6 个 task_* 事件生效 | 提交任务全周期 | 依次收到 created/started/progress/completed |
| WS-8.2 | 事件 payload 结构 | 抓包 | 结构与方案 4.2.6 节一致 |
| WS-8.3 | 旧事件迁移 | 抓 `analysis_status` | 应已移除，改由 `task_*` 承担 |
| WS-8.4 | 断连重连 | 断网 → 恢复 | 自动重连，新提交事件仍可收到 |
| WS-8.5 | 重连后回放丢失事件 | 断网时完成的任务 | 重连后 fetch `GET /api/tasks/<id>` 补齐状态 |
| WS-8.6 | 多客户端广播 | 两个浏览器标签页打开 | 都收到事件 |

---

## 九、性能基准

按方案"第十二节"目标执行：

| ID | 场景 | 目标 | 测量方法 |
|----|------|------|---------|
| PF-9.1 | 首页打开（有缓存） | < 3s | Chrome DevTools Performance |
| PF-9.2 | 持仓列表刷新（10 只，有缓存） | < 2s | 浏览器时间戳 |
| PF-9.3 | 单只股票基本面（缓存命中） | < 500ms | API 响应时间 |
| PF-9.4 | AI 分析提交响应（异步） | < 500ms（返回 task_id） | API 响应时间 |
| PF-9.5 | 选股提交响应 | < 500ms | API 响应时间 |
| PF-9.6 | 回测首次 | 3-8s | API 响应时间 |
| PF-9.7 | 回测缓存命中 | < 100ms | API 响应时间 |
| PF-9.8 | 页面切换 | < 200ms | 浏览器时间戳 |
| PF-9.9 | WebSocket 事件延迟 | < 1s | 客户端接收时间 - 服务端发送时间 |
| PF-9.10 | 缓存命中率 | 价格>80%，基本面>90%，新闻>70% | 日志统计 |
| PF-9.11 | 并发 3 个任务不互相阻塞 | 总耗时 ≈ 最慢任务耗时 | 提交 3 个同时观察 |
| PF-9.12 | Qwen 调用单次 | 3-8s | Qwen 返回时间 |

---

## 十、幂等与重试

| ID | 用例 | 步骤 | 预期结果 |
|----|------|------|----------|
| ID-10.1 | 60s 内重复提交分析 | 连续 2 次提交 AAPL 分析 | 第 2 次返回第 1 次的 task_id |
| ID-10.2 | 超窗口后允许新建 | 2 小时后同参数提交 | 新任务创建 |
| ID-10.3 | 失败后重试覆盖幂等 | failed 后立即提交 | 失败任务不命中幂等（按配置可调） |
| ID-10.4 | 重试链路可追溯 | 对 task A 重试得到 B | B 的 `retry_of = A.id`，可通过 B 追回 A |
| ID-10.5 | 并发提交 3 次相同参数 | 同时 submit | 只创建 1 个任务；其他 2 个返回同一 id |

---

## 十一、异常与边界

| ID | 用例 | 步骤 | 预期结果 |
|----|------|------|----------|
| EX-11.1 | Qwen API Key 失效 | 篡改 Key | `get_price` 降级到 yfinance，日志警告 |
| EX-11.2 | yfinance 超时 | 模拟网络慢 | 任务不无限卡住，60s 超时失败 |
| EX-11.3 | AkShare 在海外不可用 | Railway 环境 | A 股请求失败后 Qwen 兜底（若 primary=qwen） |
| EX-11.4 | SQLite 文件权限错误 | chmod 400 db 文件 | 启动时报明确错误，不静默 |
| EX-11.5 | TV.js CDN 加载失败 | 拦截 s3.tradingview.com | 前端降级 ECharts |
| EX-11.6 | 任务结果超大（10MB）写入 | 超长 result | 正常写入 SQLite BLOB |
| EX-11.7 | 同一 ticker 并发 10 个任务 | 压力测试 | 线程池排队，无数据竞争 |
| EX-11.8 | Worker 内 print 大量日志 | 大日志 | 不影响主流程，日志轮转 |
| EX-11.9 | 进度回调传超大 partial | 100KB payload | WS 正常推送 |
| EX-11.10 | 服务重启后任务可恢复 | 运行中任务 + 重启 | 标记 failed 并可重试 |

---

## 十二、回归测试（原有功能保持不受影响）

> 升级后需确保 [TEST_CASES.md](TEST_CASES.md) 中所有已通过用例**仍通过**。重点回归：

| ID | 回归范围 | 说明 |
|----|---------|------|
| REG-12.1 | 持仓 CRUD | 买入/卖出/修正成本不受数据层重构影响 |
| REG-12.2 | 预警 CRUD | 预警写入和触发逻辑不变 |
| REG-12.3 | 定时任务 | scheduler 启停不受影响 |
| REG-12.4 | 设置页展示 | 设置数据展示正常 |
| REG-12.5 | Dashboard 展示 | 统计卡 + 持仓列表 + 净值曲线仍正常 |
| REG-12.6 | 分析记录页 | 旧分析记录仍可查看（Schema 兼容） |
| REG-12.7 | 报告生成 | 日报/周报/月报/个股报告仍生成 |
| REG-12.8 | WebSocket 兼容 | 前端同时监听旧事件名时不报错（过渡期） |

---

## 附录 A：测试用例统计

| 类别 | 用例数 |
|------|--------|
| TaskStore | 15 |
| TaskManager | 22 |
| Task REST API | 14 |
| Workers | 10 |
| LocalCache | 15 + 3 |
| DataRouter | 11 + 6 |
| Qwen 扩展 | 14 + 2 |
| TradingView Widget | 13 + 3 |
| 回测引擎 | 16 |
| 任务中心 UI | 14 + 5 |
| WebSocket | 6 |
| 性能基准 | 12 |
| 幂等重试 | 5 |
| 异常边界 | 10 |
| 回归测试 | 8 |
| **总计** | **204** |

---

## 附录 B：测试执行优先级

### P0 — 合并到主干前必过
- TS-1.1.*（TaskStore 全部）
- TM-1.2.2/5/6/7/10/11/15/17（TaskManager 核心流程）
- LC-2.1.1/2/3/9/12（缓存基本行为）
- DR-3.1.1/2/8/9（路由主要路径 + 回测隔离）
- WS-8.1（任务事件链路）
- REG-12.*（原有功能不炸）

### P1 — 上线前完成
- TA-1.3.*（API 全部）
- WK-1.4.*（每个 worker）
- QF-4.1.* / QN-4.2.*（Qwen 扩展）
- TV-5.1.*（TV 主流 ticker 加载）
- BT-6.4.*（回测任务化）
- UT-7.*（任务中心 UI）
- PF-9.1~9.7（核心性能目标）

### P2 — 可延后
- TV-5.2.*（降级方案）
- EX-11.*（异常边界）
- ID-10.5（并发幂等）
- PF-9.10+（命中率统计）

---

*文档结束。Phase A 开工前请对 P0 用例对齐认知，避免实现后返工。*
