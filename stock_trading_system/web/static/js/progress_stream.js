/**
 * ProgressStream — unified task progress subscription + rendering.
 *
 * 3 layouts: compact | detail | inline-badge
 * 5 states:  idle | connecting | streaming | stalled | disconnected
 *
 * Usage:
 *   const stream = new ProgressStream('#container', {
 *     taskIds: ['uuid'],
 *     layout: 'detail',
 *     onEvent: (env) => { ... },
 *     onComplete: (env) => { ... },
 *   });
 *   stream.subscribe('another-uuid');
 *   stream.destroy();
 */

class ProgressStream {
  constructor(selector, opts = {}) {
    this.container = typeof selector === 'string' ? document.querySelector(selector) : selector;
    this.opts = opts;
    this.taskIds = new Set(opts.taskIds || []);
    this.tasks = new Map();       // taskId → { events: [], lastSeq: 0, meta: {} }
    this.status = 'idle';
    this._stalledTimer = null;
    this._socket = null;
    this._eventHandler = null;

    if (this.taskIds.size > 0) this._connect();
    this._render();
  }

  static mount(selector, opts) {
    return new ProgressStream(selector, opts);
  }

  // ── Socket management ──────────────────────────────────────────

  _connect() {
    if (typeof io === 'undefined') return;
    this._socket = io;  // reuse global socket from app.js
    this._setStatus('connecting');

    // Listen for all events via catch-all pattern
    this._eventHandler = (event, data) => {
      if (!data || !data.task_id) return;
      if (!this.taskIds.has(data.task_id)) return;
      this._applyEvent(data);
    };

    // Subscribe to known event types
    const events = [
      'task_progress', 'task_completed', 'task_failed', 'task_cancelled',
      'guru_unit_done', 'batch_analysis_item',
      'roundtable_start', 'roundtable_done',
      'agent_stage_done', 'analysis_pipeline',
    ];
    events.forEach(evt => {
      socket.on(evt, (data) => {
        if (!data || !data.task_id) {
          // Legacy events without task_id envelope
          if (data && typeof data === 'object') {
            data.task_id = data.task_id || data.batch_task_id || '';
          }
        }
        if (this.taskIds.has(data.task_id)) {
          this._applyEvent({ ...data, event: evt });
        }
      });
    });

    socket.on('connect', () => this._onReconnect());
    socket.on('reconnect', () => this._onReconnect());

    // Initial catch-up
    this._onReconnect();
  }

  async _onReconnect() {
    this._setStatus('streaming');
    this._resetStalledTimer();

    for (const taskId of this.taskIds) {
      const lastSeq = this.tasks.get(taskId)?.lastSeq ?? 0;
      try {
        const resp = await fetch(`/api/tasks/events?task_id=${taskId}&since=${lastSeq}`);
        if (resp.ok) {
          const events = await resp.json();
          for (const env of events) this._applyEvent(env);
        }
      } catch (_) {}
    }
  }

  _applyEvent(env) {
    const taskId = env.task_id;
    if (!taskId) return;

    const entry = this.tasks.get(taskId) || { events: [], lastSeq: 0, meta: {} };
    const seq = env.seq || (entry.lastSeq + 1);

    if (seq <= entry.lastSeq) return; // idempotent

    entry.events.push(env);
    entry.lastSeq = seq;

    // Update meta from payload
    const p = env.payload || env;
    if (p.progress !== undefined) entry.meta.progress = p.progress;
    if (p.total !== undefined) entry.meta.total = p.total;
    if (p.stage) entry.meta.stage = p.stage;
    if (p.step) entry.meta.step = p.step;

    // Detect terminal states
    const evtType = env.event || env.type || '';
    if (['task_completed', 'task_failed', 'task_cancelled'].includes(evtType)) {
      entry.meta.terminal = evtType;
    }

    this.tasks.set(taskId, entry);
    this._resetStalledTimer();
    this._render();

    this.opts.onEvent?.(env);
    if (evtType === 'task_completed') this.opts.onComplete?.(env);
  }

  _setStatus(s) {
    this.status = s;
    this._render();
  }

  _resetStalledTimer() {
    clearTimeout(this._stalledTimer);
    this._stalledTimer = setTimeout(() => {
      if (this.status === 'streaming') this._setStatus('stalled');
    }, 10000);
  }

  // ── Public API ─────────────────────────────────────────────────

  subscribe(taskId) {
    this.taskIds.add(taskId);
    if (!this._socket) this._connect();
    else this._onReconnect();
  }

  unsubscribe(taskId) {
    this.taskIds.delete(taskId);
    this.tasks.delete(taskId);
    this._render();
  }

  destroy() {
    clearTimeout(this._stalledTimer);
    if (this.container) this.container.innerHTML = '';
  }

  // ── Rendering ──────────────────────────────────────────────────

  _render() {
    if (!this.container) return;
    const layout = this.opts.layout || 'compact';

    if (this.taskIds.size === 0) {
      this.container.innerHTML = '';
      return;
    }

    const parts = [];

    // Connection status indicator
    const statusDot = {
      idle: '',
      connecting: '<span class="ps-dot ps-connecting">⏳</span> 连接中...',
      streaming: '<span class="ps-dot ps-streaming">●</span> 实时流',
      stalled: '<span class="ps-dot ps-stalled">⚠️</span> 进度暂停',
      disconnected: '<span class="ps-dot ps-disconnected">✕</span> 连接断开',
    }[this.status] || '';

    if (statusDot) {
      parts.push(`<div class="ps-status" style="font-size:11px;color:var(--text-secondary);margin-bottom:8px;">${statusDot}</div>`);
    }

    for (const [taskId, entry] of this.tasks) {
      if (layout === 'compact') {
        parts.push(this._renderCompact(taskId, entry));
      } else if (layout === 'detail') {
        parts.push(this._renderDetail(taskId, entry));
      } else {
        parts.push(this._renderBadge(taskId, entry));
      }
    }

    this.container.innerHTML = parts.join('');
  }

  _renderCompact(taskId, entry) {
    const m = entry.meta;
    const pct = m.progress !== undefined ? Math.round(m.progress * 100) : 0;
    const stage = m.step || m.stage || '';
    const terminal = m.terminal;
    const barColor = terminal === 'task_failed' ? 'var(--accent-red)' :
                     terminal === 'task_cancelled' ? 'var(--accent-yellow)' :
                     terminal === 'task_completed' ? 'var(--accent-green)' : 'var(--accent-blue)';

    return `<div class="m-card" style="margin-bottom:8px;">
      <div class="m-card-head" style="padding:8px 12px;">
        <span style="font-size:12px;font-weight:600;">${stage || taskId.substring(0, 8)}</span>
        <span style="font-size:11px;color:var(--text-secondary);">${pct}%</span>
      </div>
      <div style="height:4px;background:rgba(56,130,255,0.08);">
        <div style="height:100%;width:${pct}%;background:${barColor};border-radius:2px;transition:width 400ms ease-out;"></div>
      </div>
    </div>`;
  }

  _renderDetail(taskId, entry) {
    const m = entry.meta;
    const events = entry.events.slice(-15); // show last 15
    const total = m.total || events.length;
    const done = events.filter(e => {
      const t = e.event || e.type || '';
      return ['guru_unit_done', 'batch_analysis_item', 'agent_stage_done', 'step_done'].includes(t);
    }).length;
    const pct = total > 0 ? Math.round(done / total * 100) : 0;
    const terminal = m.terminal;

    const eventRows = events.map(e => {
      const evtType = e.event || e.type || '';
      const p = e.payload || e;
      let icon = '⏳', title = evtType, meta = '';

      if (evtType === 'guru_unit_done') {
        icon = p.signal === 'bullish' ? '🟢' : p.signal === 'bearish' ? '🔴' : '⚪';
        title = `${p.guru_display || p.guru || ''} × ${p.ticker || ''}`;
        meta = `${p.signal || ''} ${Math.round((p.confidence || 0) * 100)}%${p.cached ? ' [缓存]' : ''}`;
      } else if (evtType === 'batch_analysis_item') {
        icon = p.status === 'success' ? '✅' : p.status === 'skipped' ? '⏭️' : '❌';
        title = p.ticker || '';
        meta = p.signal || p.reason || '';
      } else if (evtType === 'task_completed') {
        icon = '✅'; title = '任务完成';
      } else if (evtType === 'task_failed') {
        icon = '❌'; title = '任务失败'; meta = (p.error || '').substring(0, 100);
      } else if (['step_done', 'agent_stage_done'].includes(evtType)) {
        icon = '✅'; title = p.label || p.step || evtType;
        meta = p.duration_ms ? `${(p.duration_ms/1000).toFixed(1)}s` : '';
      }

      return `<div class="m-card-row" style="font-size:12px;padding:4px 12px;">
        <span>${icon} ${title}</span><span style="color:var(--text-secondary);">${meta}</span>
      </div>`;
    }).join('');

    const barColor = terminal === 'task_failed' ? 'var(--accent-red)' :
                     terminal ? 'var(--accent-green)' : 'var(--accent-blue)';

    return `<div class="m-card" style="margin-bottom:12px;">
      <div class="m-card-head" style="padding:8px 12px;">
        <span style="font-size:12px;">已完成 ${done}/${total}</span>
        <span style="font-size:11px;color:var(--text-secondary);">${pct}%</span>
      </div>
      <div style="height:4px;background:rgba(56,130,255,0.08);">
        <div style="height:100%;width:${pct}%;background:${barColor};border-radius:2px;transition:width 400ms ease-out;"></div>
      </div>
      <div style="max-height:250px;overflow-y:auto;">
        ${eventRows}
      </div>
    </div>`;
  }

  _renderBadge(taskId, entry) {
    const m = entry.meta;
    const pct = m.progress !== undefined ? Math.round(m.progress * 100) : 0;
    const dots = '●'.repeat(Math.ceil(pct / 20)) + '○'.repeat(5 - Math.ceil(pct / 20));
    return `<span class="ps-badge" style="font-size:11px;color:var(--text-secondary);">[${dots} ${pct}%]</span>`;
  }
}

// CSS for status dots (injected once)
(function() {
  if (document.getElementById('ps-styles')) return;
  const style = document.createElement('style');
  style.id = 'ps-styles';
  style.textContent = `
    .ps-dot { display:inline-block; margin-right:4px; }
    .ps-streaming { color:var(--accent-green); animation:ps-pulse 2s infinite; }
    .ps-connecting { animation:ps-pulse 1s infinite; }
    .ps-stalled { color:var(--accent-yellow); }
    .ps-disconnected { color:var(--accent-red); }
    @keyframes ps-pulse { 0%,100%{opacity:1;} 50%{opacity:0.3;} }
  `;
  document.head.appendChild(style);
})();
