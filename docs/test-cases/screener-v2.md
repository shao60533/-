# 智能选股 V2 测试用例

> **版本**: 1.0
> **日期**: 2026-04-15
> **依据**: `SCREENER_V2_TECH_DESIGN.md`
> **范围**: 仅选股模块 V2，不覆盖其他模块

---

## 一、单元测试（后端）

### 1.1 Agent 基础设施

| ID | 用例 | 输入 | 预期 |
|----|------|------|------|
| U-1.1.1 | BaseAgent.to_grade 边界 | `score=94` | `"A+"` |
| U-1.1.2 | BaseAgent.to_grade 边界 | `score=87` | `"A"` |
| U-1.1.3 | BaseAgent.to_grade 边界 | `score=79.9` | `"B"` |
| U-1.1.4 | BaseAgent.to_grade 最低 | `score=0` | `"F"` |
| U-1.1.5 | AgentScore 序列化 | dataclass → dict | 含 score/grade/rationale/signals 四个 key |

### 1.2 MomentumAgent（Local Cache 数据）

| ID | 用例 | 输入 | 预期 |
|----|------|------|------|
| U-1.2.1 | 正常评分 - 上涨动能 | AAPL 近 12M +40% | score > 80，grade ≥ B+ |
| U-1.2.2 | 正常评分 - 下跌动能 | 假数据 12M -30% | score < 40，grade ≤ D+ |
| U-1.2.3 | 52W 新高接近度 | 当前价距 52W 高 < 5% | 加分 |
| U-1.2.4 | MA 排列正序 (10>50>200) | 多头排列 | 加分 |
| U-1.2.5 | 数据缺失容错 | Local cache 无 bars | 返回 score=0 + rationale 含"数据缺失" |
| U-1.2.6 | 批量评分 | tickers=["A","B","C"] | 返回 3 个 AgentScore |

### 1.3 QualityValueAgent（Qwen fundamentals）

| ID | 用例 | 输入 | 预期 |
|----|------|------|------|
| U-1.3.1 | 高质量企业 | ROE=25%, D/E=0.1, FCF_yield=4% | score > 85 |
| U-1.3.2 | 低质量企业 | ROE=3%, D/E=3.0 | score < 40 |
| U-1.3.3 | Qwen API 失败 | mock API 抛异常 | 返回 score=0 + rationale 含"数据源失败" |
| U-1.3.4 | 缓存命中 | 同一 ticker 5 分钟内二次调用 | 不再请求 Qwen（验证 local_cache 被调用） |

### 1.4 CatalystAgent（Qwen news）

| ID | 用例 | 输入 | 预期 |
|----|------|------|------|
| U-1.4.1 | 财报超预期催化 | mock Qwen 返回 "earnings beat" | score > 75，signals.primary_catalyst="earnings_beat" |
| U-1.4.2 | 无催化 | mock Qwen 返回空列表 | score < 50 |
| U-1.4.3 | 催化剂分类 | 输入新闻 "FDA approved" | primary_catalyst="fda" |
| U-1.4.4 | 多催化叠加 | 财报+回购同时 | score 高于单个催化 |

### 1.5 TechnicalAgent

| ID | 用例 | 输入 | 预期 |
|----|------|------|------|
| U-1.5.1 | 超卖反弹形态 | RSI<30 + 布林下轨 | signals.pattern="oversold_bounce" |
| U-1.5.2 | MACD 金叉 | MACD 上穿信号线 | 加分 |
| U-1.5.3 | 杯柄形态识别 | mock bars 形成 cup-handle | signals.pattern 含 "cup_handle" |
| U-1.5.4 | 放量突破 | 当日成交量 > 3× avg | signals.volume_surge=true |

### 1.6 RegimeRelativeAgent

| ID | 用例 | 输入 | 预期 |
|----|------|------|------|
| U-1.6.1 | 强于大盘 | 个股 +30% vs SPY +10% | score > 70 |
| U-1.6.2 | 弱于大盘 | 个股 +5% vs SPY +15% | score < 50 |
| U-1.6.3 | RRG 四象限 | 计算 RS-Ratio 和 RS-Momentum | 返回 象限 Leading/Improving/Lagging/Weakening |

### 1.7 RiskAgent

| ID | 用例 | 输入 | 预期 |
|----|------|------|------|
| U-1.7.1 | 低 Beta 股票 | Beta=0.5 | score 高（低风险） |
| U-1.7.2 | 高 Beta + 大回撤 | Beta=2.5, MDD=45% | score 低 |
| U-1.7.3 | 做空挤压预警 | short_interest>20%, days_to_cover>5 | signals.squeeze_risk=true |
| U-1.7.4 | 流动性不足 | 日均成交额<1M | score 极低 |

### 1.8 Guru 判断引擎

| Guru | 输入 | 预期 |
|------|------|------|
| **Buffett** (U-1.8.1) | ROE=20%, D/E=0.3, FCF_yield=5%, moat=8/10 | fit=true, match_pct>80 |
| Buffett (U-1.8.2) | P/E=80, 高增长但无护城河 | fit=false, match_pct<40 |
| **Graham** (U-1.8.3) | P/E=12, P/B=1.2, current_ratio=2.5 | fit=true, match_pct>75 |
| Graham (U-1.8.4) | P/E=35, P/B=5 | fit=false, match_pct<30 |
| **Lynch** (U-1.8.5) | PEG=0.7, revenue_growth=25% | fit=true |
| Lynch (U-1.8.6) | PEG=2.5 | fit=false |
| **O'Neil** (U-1.8.7) | CANSLIM 满足 5/7 | match_pct>70 |
| O'Neil (U-1.8.8) | 仅满足 2/7 | match_pct<40 |

### 1.9 Aggregator

| ID | 用例 | 输入 | 预期 |
|----|------|------|------|
| U-1.9.1 | 正常聚合 | 8 Agent 分 + 4 Guru 匹配 | conviction = 0.5*w + 0.15*c + 0.2*g + 0.15*d 公式正确 |
| U-1.9.2 | 共识度计算 | 所有 Agent 分数接近 | consensus 接近 1.0 |
| U-1.9.3 | 分歧大 | Agent 分数 stddev > 25 | consensus < 0.5 |
| U-1.9.4 | 大师一致性 | 3/4 Guru fit=true | guru_consistency = 0.75 |
| U-1.9.5 | 缺少辩论分 | L6 跳过 | 公式仅用前 3 项，加权归一化 |
| U-1.9.6 | 排序稳定性 | 置信度相同 | 按 ticker 字母序，不随机 |

### 1.10 RegimeDetector

| ID | 用例 | 输入 | 预期 |
|----|------|------|------|
| U-1.10.1 | 牛市识别 | SPY>200MA, VIX=15 | regime="bull", confidence>0.8 |
| U-1.10.2 | 熊市识别 | SPY<200MA, VIX=32 | regime="bear" |
| U-1.10.3 | 震荡识别 | SPY 围绕 200MA 震荡，VIX=22 | regime="sideways" |
| U-1.10.4 | 权重映射 | regime="bull" | weights.momentum=0.20 |
| U-1.10.5 | 数据源失败 | yfinance 不可用 | 回退 regime="sideways", confidence=0.5 |

### 1.11 Orchestrator

| ID | 用例 | 输入 | 预期 |
|----|------|------|------|
| U-1.11.1 | 完整流程 mock | mock 所有依赖 | 返回 dict 含 regime/weights/picks |
| U-1.11.2 | progress_cb 调用序列 | run() | 按顺序触发 5%→10%→20→85→90→95→100 |
| U-1.11.3 | 单 Agent 失败不影响整体 | mock CatalystAgent 抛异常 | 其他 7 Agent 仍正常，该 Agent 返回 score=0 + 错误 rationale |
| U-1.11.4 | enabled_gurus 生效 | 只启用 buffett/lynch | 只计算这 2 个 Guru，其他跳过 |
| U-1.11.5 | final_count 限制 | final_count=3 | picks 长度=3 |
| U-1.11.6 | skip_debate=true | 跳过 L6 | 耗时明显短于 false，aggregator 公式归一化 |

---

## 二、集成测试（API + DB）

### 2.1 API 端点

| ID | 用例 | 请求 | 预期 |
|----|------|------|------|
| A-2.1.1 | Submit V2 选股 | `POST /api/screen/v2/submit {market:"us",strategy:"growth"}` | 200, `{task_id: "scr_v2_..."}`，tasks 表新增一行 status=pending |
| A-2.1.2 | Submit 幂等 | 60 秒内相同参数再次提交 | 返回相同 task_id（复用） |
| A-2.1.3 | Submit 带 NL query | `{nl_query:"AI 板块被低估"}` | 200, 进入队列 |
| A-2.1.4 | 查询结果 by task_id | `GET /api/screen/v2/result/scr_v2_xxx` | 任务完成后返回 picks JSON |
| A-2.1.5 | 查询不存在的任务 | `GET /api/screen/v2/result/notexist` | 404 |
| A-2.1.6 | 历史列表 | `GET /api/screen/v2/history` | 返回数组，按 created_at DESC |
| A-2.1.7 | Gurus 元数据 | `GET /api/screen/v2/gurus` | 返回 8 位大师对象（name, philosophy, principles, motto） |

### 2.2 WebSocket 事件

| ID | 用例 | 触发 | 预期 |
|----|------|------|------|
| W-2.2.1 | task_created | Submit 后立即 | 收到事件，含 id/type="screen_v2"/title |
| W-2.2.2 | task_progress 序列 | 任务执行 | 至少收到 10 个 progress 事件，progress 单调递增 |
| W-2.2.3 | task_progress.step | 执行中 | step 字段含中文描述（"市场环境检测中"/"Agent 评分中"） |
| W-2.2.4 | task_completed | 完成 | 事件含 result_ref |
| W-2.2.5 | task_failed | 强制抛异常 | 事件含 error_message |

### 2.3 数据库

| ID | 用例 | 操作 | 预期 |
|----|------|------|------|
| D-2.3.1 | screen_results_v2 建表 | 启动服务首次 | 表存在 + 索引存在 |
| D-2.3.2 | 结果写入 | 完成一次选股 | 表新增一行，results_json 可解析 |
| D-2.3.3 | 关联 task_id | 查询 | `SELECT * FROM screen_results_v2 WHERE task_id=?` 有记录 |
| D-2.3.4 | 历史查询性能 | 1000 条记录 | `GET /api/screen/v2/history?limit=50` < 500ms |
| D-2.3.5 | 并发提交 | 同时 3 个任务 | 3 行独立记录，无数据竞争 |

### 2.4 缓存

| ID | 用例 | 操作 | 预期 |
|----|------|------|------|
| C-2.4.1 | Qwen fundamentals 缓存 | 同一 ticker 24h 内二次查询 | 第二次无 Qwen 请求（日志验证） |
| C-2.4.2 | Regime 缓存 30min | 30min 内多次选股 | regime_detector 只调用 1 次 |
| C-2.4.3 | 缓存过期重取 | 过 TTL 后 | 触发新的数据源请求 |

---

## 三、前端测试

### 3.1 页面渲染

| ID | 用例 | 步骤 | 预期 |
|----|------|------|------|
| F-3.1.1 | 选股页加载 | 进入 `/` 选股 | 显示自然语言搜索 + 8 Guru 面板 + 预设策略 chips |
| F-3.1.2 | Guru 面板加载 | 页面进入 | GET /api/screen/v2/gurus 成功，渲染 8 张卡 |
| F-3.1.3 | Guru 开关 | 点击 Buffett 开关 | 切换 active 样式，本地状态更新 |
| F-3.1.4 | 预设策略 chips | 点击"成长动能" | active 样式切换，策略值更新 |
| F-3.1.5 | NL 查询输入 | 输入 "AI 板块低估" | 输入框显示文字，字数统计可选 |

### 3.2 执行流程

| ID | 用例 | 步骤 | 预期 |
|----|------|------|------|
| F-3.2.1 | 点击开始筛选 | 配置好参数 → 点击 | 显示 "已提交，task_id: ..." toast |
| F-3.2.2 | Agent 卡片实时更新 | 任务运行中 | 8 个 Agent 卡从 idle → running → done，带动画 |
| F-3.2.3 | 管线进度条 | 任务运行中 | 4 层漏斗逐步点亮（宇宙→评分→聚合→辩论） |
| F-3.2.4 | Regime 横幅 | 任务完成 | 显示 "当前环境：Bull"，含 VIX/宽度数据 |
| F-3.2.5 | Pick 卡片渲染 | 任务完成 | 显示 5 个 pick，每个含置信度环/8 Agent 评分格/大师徽章/交易计划 |
| F-3.2.6 | 置信度环 SVG | 渲染 | ring 填充弧长与 conviction 值匹配 |

### 3.3 交互

| ID | 用例 | 步骤 | 预期 |
|----|------|------|------|
| F-3.3.1 | AI 深度分析跳转 | 点击 pick 卡片的"AI 分析" | 切换到 analysis 页，ticker 预填 |
| F-3.3.2 | 加入持仓 | 点击"加入持仓" | 弹出买入 modal，ticker 预填 |
| F-3.3.3 | 设置预警 | 点击"设置预警" | 弹出预警 modal，ticker 预填 |
| F-3.3.4 | K 线图 | 点击"K线图" | 弹出 TradingView widget 或 ECharts K 线 |
| F-3.3.5 | 大师徽章 tooltip | 鼠标悬停 "O'Neil · 92%" | 显示具体 CANSLIM 原则匹配详情 |

### 3.4 边界与异常

| ID | 用例 | 步骤 | 预期 |
|----|------|------|------|
| F-3.4.1 | 任务失败显示 | 后端返回 task_failed | 显示红色错误 toast + 错误详情 |
| F-3.4.2 | 空结果 | picks=[] | 显示"暂无符合条件的股票"空状态 |
| F-3.4.3 | 网络中断 | 任务运行时断网 | 前端显示"连接中断，尝试恢复..." |
| F-3.4.4 | 重复点击提交 | 快速点击 3 次 | 只提交 1 次，按钮 disabled |
| F-3.4.5 | 历史页回看 | 进入选股历史 | 列表可按日期/策略筛选，点击进入历史结果 |

---

## 四、回归测试（确保不影响其他模块）

| ID | 用例 | 步骤 | 预期 |
|----|------|------|------|
| R-4.1 | AI 分析仍正常 | 分析 AAPL | 结果返回正常，与选股 V2 无关 |
| R-4.2 | 持仓管理仍正常 | 买入/卖出 AAPL | 持仓变更正常 |
| R-4.3 | 预警仍正常 | 添加价格预警 | 正常 |
| R-4.4 | V1 选股端点兼容 | `POST /api/screen` (旧) | 仍返回 V1 格式（如配置 version=v1） |
| R-4.5 | 现有 TaskManager | 其他任务（分析） | 不受 screen_v2 worker 注册影响 |
| R-4.6 | 其他页面样式 | 切换到 Dashboard/分析/持仓/预警 | 样式无破坏（CSS 新增仅作用于选股页 class） |
| R-4.7 | 数据库兼容 | 启动服务 | 已有表正常，新增 `screen_results_v2` 表独立 |
| R-4.8 | 现有 WS 事件 | `analysis_status` / `alert_triggered` | 正常推送，不受新 screen_v2 事件影响 |

---

## 五、性能基准

| ID | 场景 | 预期 |
|----|------|------|
| P-5.1 | 单次选股总耗时（skip_debate=true） | < 60 秒 |
| P-5.2 | 单次选股总耗时（L6 辩论） | < 5 分钟 |
| P-5.3 | L3 8 Agent 并行评分 200 只 | < 45 秒 |
| P-5.4 | L2 宇宙过滤 | < 10 秒 |
| P-5.5 | Regime 检测（缓存命中） | < 100ms |
| P-5.6 | WS progress 事件延迟 | < 500ms |
| P-5.7 | 前端 pick 卡片渲染（5 张） | < 200ms |
| P-5.8 | API /history?limit=50 | < 500ms |

---

## 六、验收标准（Definition of Done）

**后端**：
- [ ] 所有单元测试通过（覆盖率 ≥ 70%）
- [ ] 集成测试通过
- [ ] 性能基准达标
- [ ] 回归测试通过（其他模块功能正常）

**前端**：
- [ ] UI 与 `demo_screener_v2.html` 视觉一致
- [ ] 所有交互流程（F-3.1 ~ F-3.4）通过
- [ ] 响应式适配（桌面 + 手机）

**产品**：
- [ ] 选股结果可持久化留痕
- [ ] 支持任务中心查看历史
- [ ] 支持失败重试
- [ ] Regime 自动切换权重生效

---

## 七、用例总数

| 类别 | 用例数 |
|------|--------|
| 单元测试（后端） | 56 |
| 集成测试 | 18 |
| 前端测试 | 20 |
| 回归测试 | 8 |
| 性能基准 | 8 |
| **总计** | **110** |

---

*文档结束*
