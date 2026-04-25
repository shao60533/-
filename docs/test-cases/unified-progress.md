# 测试用例：统一实时进度系统

| 项 | 值 |
|---|---|
| Feature | `unified-progress` |
| 版本 | v1.0 |
| 日期 | 2026-04-20 |
| 关联设计 | [../design/unified-progress.md](../design/unified-progress.md) |

## 汇总

| 分类 | 用例数 |
|---|---|
| 单元：emit_event 入口 | 8 |
| 单元：task_events DB 持久化 | 5 |
| 单元：ProgressStream 组件 | 12 |
| 集成：Per-user room 隔离 | 7 |
| 集成：断线续传 catch-up | 8 |
| 集成：11 种 task 统一发射 | 12 |
| 集成：5 页面统一挂载 | 10 |
| 前端：3 布局视觉 | 9 |
| 前端：5 态颜色/动画 | 6 |
| 前端：移动端断点 | 6 |
| 异常 & 边界 | 8 |
| 性能 | 5 |
| 回归（任务中心不崩）| 5 |
| **总计** | **101** |

---

## 1. 单元：`emit_event` 入口（8）

### TC-UP-U1：seq 对同 task 递增，不同 task 独立

```python
def test_seq_independent_per_task():
    emit_event("task-a", "task_progress", {"p": 0.1})
    emit_event("task-b", "task_progress", {"p": 0.1})
    emit_event("task-a", "task_progress", {"p": 0.2})
    evts_a = db.fetchall("SELECT seq FROM task_events WHERE task_id='task-a' ORDER BY seq")
    evts_b = db.fetchall("SELECT seq FROM task_events WHERE task_id='task-b' ORDER BY seq")
    assert [r["seq"] for r in evts_a] == [1, 2]
    assert [r["seq"] for r in evts_b] == [1]
```

### TC-UP-U2：envelope 包含 {task_id, user_id, seq, event, payload, emitted_at}

### TC-UP-U3：DB 写入失败 → 不 emit（避免前端收到未持久化事件）

### TC-UP-U4：socketio.emit 使用 `to=f"user:{uid}"` 参数（不是全局广播）

### TC-UP-U5：并发 10 线程对同一 task_id emit → seq 无重复（UNIQUE 约束 + 锁）

### TC-UP-U6：task 不存在时 emit_event 静默（不 raise）

### TC-UP-U7：user_id 从 task.created_by 取（正确对齐 multi-tenant）

### TC-UP-U8：envelope emitted_at 使用 UTC ISO 格式，毫秒级

---

## 2. 单元：`task_events` 表（5）

### TC-UP-U9：迁移脚本幂等（第二次执行无错）

### TC-UP-U10：`ix_task_events_user_seq` / `ix_task_events_task_seq` 索引创建

### TC-UP-U11：UNIQUE (task_id, seq) 约束生效

### TC-UP-U12：cleanup worker 删除 7 天前终态 task 的 events，保留活跃

### TC-UP-U13：cleanup 不删仍在 running 的 task events（即使 > 7 天）

---

## 3. 单元：`ProgressStream` 组件（12）

Jest / Playwright component-test。

### TC-UP-U14：mount 后 `status = 'connecting'`

### TC-UP-U15：socket connect 触发 `status = 'streaming'` 且调 catch-up

### TC-UP-U16：收到 envelope seq == lastSeq+1 → 应用事件

### TC-UP-U17：收到 envelope seq <= lastSeq → 忽略（幂等）

### TC-UP-U18：收到 envelope seq > lastSeq+1 → 触发再次 catch-up（补齐中间丢失）

### TC-UP-U19：subscribe(newTaskId) 立即拉 since=0

### TC-UP-U20：unsubscribe(taskId) 不再渲染该 task

### TC-UP-U21：destroy() 关闭 socket 且清空 DOM

### TC-UP-U22：onComplete 回调仅在 `task_completed` 事件触发

### TC-UP-U23：layout='compact' 渲染一行 + 进度条

### TC-UP-U24：layout='detail' 渲染完整事件流

### TC-UP-U25：layout='inline-badge' 渲染微型 badge

---

## 4. 集成：Per-user room 隔离（7）

### TC-UP-I1：未登录 WS 连接被拒绝

```python
@pytest.mark.integration
def test_ws_refuse_unauth(socketio_client):
    # 不设 session cookie
    connected = socketio_client.connect(namespace='/')
    assert not connected
```

### TC-UP-I2：alice 登录后 WS 连接成功，自动 join `user:<alice_id>` room

### TC-UP-I3：alice 的 task emit → 仅 alice 的 WS 收到

### TC-UP-I4：alice 的 task emit → bob 的 WS 不收到

### TC-UP-I5：alice 多标签页（多连接）都收到同一事件（broadcast 到 room）

### TC-UP-I6：alice 登出 WS 断开后，events 继续落库（不因无在线 socket 而丢失）

### TC-UP-I7：admin 看所有用户任务时（查询层），WS 推送仍按 room 隔离；admin 进 any-task 详情页后通过 HTTP 拉 events（不通过 WS 跨 room）

---

## 5. 集成：断线续传（8）

### TC-UP-I8：socket 断开 → 前端显示 "连接中断" banner（> 2s）

### TC-UP-I9：socket 重连 → 自动 GET `/api/tasks/events?since=<lastSeq>` 补齐

### TC-UP-I10：catch-up 事件按 seq 顺序应用

### TC-UP-I11：补齐完成后 banner 显示 "已恢复，补齐 N 个事件"，3s 后淡出

### TC-UP-I12：关浏览器 10 分钟后重开 → /api/tasks/running 返回 active tasks，自动订阅

### TC-UP-I13：7 天内任务的 events 全部可补齐

### TC-UP-I14：> 7 天老 task 的 events 已被 cleanup，/events?since=X 返回空列表（正常）

### TC-UP-I15：同时断连 + task 结束 → 重连后 task_completed 事件被补齐

---

## 6. 集成：11 种 task 统一发射（12）

每种 task 类型验证：emit_event 被调用、envelope 字段完整、无直接 socketio.emit。

- **TC-UP-I16**：analysis task emit `agent_stage_done`（每阶段完成）
- **TC-UP-I17**：batch_analysis emit `batch_analysis_item` 走 emit_event（不直接 socketio）
- **TC-UP-I18**：screen_v3 emit `guru_unit_done` 走 emit_event
- **TC-UP-I19**：screen_v3 emit `roundtable_start` / `roundtable_done`
- **TC-UP-I20**：backtest emit `task_progress` 5 次
- **TC-UP-I21**：report emit `task_progress` 3 次
- **TC-UP-I22**：qwen_fundamentals emit `task_progress`
- **TC-UP-I23**：qwen_news emit `task_progress`
- **TC-UP-I24**：paper_trade emit `task_progress` + `task_completed`
- **TC-UP-I25**：paper_backfill emit `task_progress`
- **TC-UP-I26**：agent_score_update / meta_evolution emit `task_progress`
- **TC-UP-I27**：全代码库 grep `socketio.emit` 在 `stock_trading_system/tasks/` 路径外无残留（硬断言）

---

## 7. 集成：5 页面统一挂载（10）

### TC-UP-I28：任务中心 每行挂 compact layout；10 个任务 10 个实例

### TC-UP-I29：任务中心切到"全部"tab（multi-tenant 场景）仍仅订阅 my tasks（不跨用户）

### TC-UP-I30：分析详情 触发后 detail layout 自动在结果区上方挂载

### TC-UP-I31：screener-v3 任务页 detail layout + custom guru item renderer

### TC-UP-I32：screener-v3 结果后 detail 组件自动切换 onComplete → 跳转结果抽屉

### TC-UP-I33：batch 持仓 detail layout，每 item 独立行展示分析状态

### TC-UP-I34：backtest compact layout，完成后跳结果 tab

### TC-UP-I35：所有页面的进度条视觉一致（color / height / transition）

### TC-UP-I36：所有页面的事件流行视觉一致（icon / color / layout）

### TC-UP-I37：原散落 handler 已删除，无重复渲染

---

## 8. 前端：3 布局视觉（9）

### TC-UP-F1：compact 高度 ≤ 56px，横向填满容器

### TC-UP-F2：compact 显示：title / progress bar / percentage / action button

### TC-UP-F3：detail 包含标题栏 + 阶段行 + 进度条 + 统计行 + 事件流 + 底部按钮

### TC-UP-F4：inline-badge 宽度 ≤ 100px，显示 5 级色块进度

### TC-UP-F5：detail 事件流超 10 条折叠"查看更早的 N 条"

### TC-UP-F6：进度条完成瞬间 `scaleX(1.02)` 弹性动画 200ms

### TC-UP-F7：失败瞬间进度条变红 + shake 400ms

### TC-UP-F8：不确定进度（total == null）显示扫光条纹

### TC-UP-F9：暗色主题下所有色彩对齐 CSS token（不硬编码 hex）

---

## 9. 前端：5 态颜色/动画（6）

### TC-UP-F10：connecting 呼吸灯动画 CSS keyframe 工作

### TC-UP-F11：streaming 脉冲绿 `--accent-green` + 2s pulse

### TC-UP-F12：stalled（> 10s 无事件）切换到黄色 `--accent-yellow`

### TC-UP-F13：disconnected 红色 `--accent-red` + 文案"连接断开，自动重连中"

### TC-UP-F14：tab 非活跃时 socket 暂停但不报 stalled（用 visibilitychange 抑制）

### TC-UP-F15：5 态切换过渡 opacity 200ms（不硬切）

---

## 10. 前端：移动端断点（6）

### TC-UP-F16：≤575.98px detail 布局事件流默认折叠

### TC-UP-F17：≤575.98px 进度条高度 6px（比桌面 4px 粗）

### TC-UP-F18：移动端触达目标 ≥ 44×44

### TC-UP-F19：断线 banner 位 `position:fixed;top:0`，不被 tabbar 遮挡

### TC-UP-F20：375 / 414 / 768 三断点均无横滑

### TC-UP-F21：移动端 inline-badge 缩到 60px 宽仍可读

---

## 11. 异常 & 边界（8）

### TC-UP-X1：worker 抛未捕获异常 → emit task_failed + 完整 traceback

### TC-UP-X2：用户任务 params_json 损坏 → emit_event 打 warn，不 crash

### TC-UP-X3：task_events 表不存在（未迁移）→ emit_event 降级为纯广播 + 打 error

### TC-UP-X4：前端 ProgressStream 挂载但容器不存在 → 静默返回 null（不抛）

### TC-UP-X5：socket 立即重连失败 10 次 → 停止尝试 + 显示"连接失败，请刷新"

### TC-UP-X6：catch-up API 返回 500 → 前端指数退避重试 3 次

### TC-UP-X7：同一 seq 事件意外重复 emit → 前端幂等（忽略第二次）

### TC-UP-X8：Railway cold-start WS 降级 polling → 自动工作，仅延迟增加

---

## 12. 性能（5）

### TC-UP-P1：100 事件 / 任务的 catch-up API ≤ 200ms

### TC-UP-P2：单 emit_event 延迟 ≤ 20ms（DB 写 + 广播）

### TC-UP-P3：并发 10 task 同时 emit（100 events）无丢失

### TC-UP-P4：task_events 表 100K 行下查询 `WHERE task_id=? AND seq>?` ≤ 50ms

### TC-UP-P5：cleanup worker 删 10K 过期 events ≤ 2s

---

## 13. 回归（5）

### TC-UP-R1：原任务中心基础列表渲染无变化（仅新增实时更新）

### TC-UP-R2：原 `POST /api/tasks/submit` 所有类型依然可触发 + 完成

### TC-UP-R3：原 analysis / backtest / screen 结果 JSON 结构不变

### TC-UP-R4：SocketIO 原有 `connect` / `disconnect` 回调（若业务复用）兼容

### TC-UP-R5：[model-switch](../design/model-switch.md) / [multi-tenant](../design/multi-tenant.md) / [screener-v3](../design/screener-v3.md) / [paper-trade](../design/paper-trade.md) 5 个既有模块行为不回归

---

## 覆盖要求

| 模块 | 目标 |
|---|---|
| `tasks/manager.py` emit_event + seq | 100% |
| `web/app.py` 新增 2 routes + WS handler | ≥ 90% |
| `static/js/progress_stream.js` | ≥ 85% |
| `migrations/task_events_v1.py` | 100% |

### 运行命令

```bash
# 后端
pytest tests/tasks/test_emit_event.py tests/web/test_task_events_api.py \
       tests/integration/test_progress_isolation.py \
       --cov=stock_trading_system/tasks/manager.py \
       --cov=stock_trading_system/web/app.py \
       --cov-report=term-missing

# 前端组件
npm test progress_stream

# E2E 跨页面
npx playwright test tests/frontend/test_unified_progress_*.spec.js

# 禁残留硬断言
grep -rn "socketio.emit" stock_trading_system/tasks/ | grep -v "manager.py" && exit 1 || echo OK
```

## 版本历史

| 版本 | 日期 | 用例数 | 变更 |
|---|---|---|---|
| v1.0 | 2026-04-20 | 101 | 初版：emit_event 单元 8 + task_events 表 5 + ProgressStream 单元 12 + room 隔离 7 + 断线续传 8 + 11 task 发射 12 + 5 页面集成 10 + 3 布局 9 + 5 态 6 + 移动端 6 + 异常 8 + 性能 5 + 回归 5 |
