/**
 * Screener V3 — config panel + estimate + trigger + streaming results.
 */

(function () {
  'use strict';

  const RECOMMENDED_GURUS = ['buffett', 'graham', 'munger', 'lynch'];
  const LS_KEY = 'screener_v3_config';
  let _allGurus = [];
  let _estimateTimer = null;
  let _activeTaskId = null;

  // ── Init ──────────────────────────────────────────────────────────

  async function initV3() {
    // First-use tooltip
    if (!localStorage.getItem('v3_tip_dismissed')) {
      const tip = document.getElementById('v3-first-use-tip');
      if (tip) tip.style.display = 'block';
    }

    // Load guru metadata
    try {
      const resp = await fetch('/api/screen/v3/gurus');
      const data = await resp.json();
      _allGurus = data.gurus || [];
      _renderGuruCheckboxes();
    } catch (e) {
      console.warn('Failed to load V3 gurus:', e);
    }

    // Restore saved config
    _restoreConfig();

    // Wire mode chips
    document.querySelectorAll('#v3-mode-chips .chip').forEach(chip => {
      chip.addEventListener('click', () => {
        document.querySelectorAll('#v3-mode-chips .chip').forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
        chip.querySelector('input').checked = true;
        _scheduleEstimate();
        _saveConfig();
      });
    });

    // Wire candidate chips
    document.querySelectorAll('#v3-candidate-chips .chip').forEach(chip => {
      chip.addEventListener('click', () => {
        document.querySelectorAll('#v3-candidate-chips .chip').forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
        _scheduleEstimate();
        _saveConfig();
      });
    });

    // Wire market select
    const marketSel = document.getElementById('v3-market');
    if (marketSel) marketSel.addEventListener('change', () => { _scheduleEstimate(); _saveConfig(); });

    // Wire NL input
    const nlInput = document.getElementById('screen-nl-query');
    if (nlInput) nlInput.addEventListener('input', () => _saveConfig());

    // Initial estimate
    _scheduleEstimate();
  }

  // ── Guru checkboxes ───────────────────────────────────────────────

  function _renderGuruCheckboxes() {
    const container = document.getElementById('v3-guru-checkboxes');
    if (!container) return;
    container.innerHTML = _allGurus.map(g => {
      const checked = RECOMMENDED_GURUS.includes(g.name) ? 'checked' : '';
      return `<label class="collapse-row-head" style="padding:6px 8px;min-height:36px;cursor:pointer;border:1px solid var(--border);border-radius:6px;gap:6px;margin:0;">
        <input type="checkbox" class="v3-guru-cb" value="${g.name}" ${checked} onchange="v3OnGuruChange()">
        <span style="font-weight:600;font-size:12px;">${g.avatar_initials}</span>
        <span style="font-size:11px;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${g.display_name}</span>
      </label>`;
    }).join('');
  }

  window.v3SelectGurus = function (mode) {
    const cbs = document.querySelectorAll('.v3-guru-cb');
    cbs.forEach(cb => {
      if (mode === 'all') cb.checked = true;
      else if (mode === 'none') cb.checked = false;
      else cb.checked = RECOMMENDED_GURUS.includes(cb.value);
    });
    _updateGuruCount();
    _scheduleEstimate();
    _saveConfig();
  };

  window.v3OnGuruChange = function () {
    _updateGuruCount();
    _scheduleEstimate();
    _saveConfig();
  };

  function _updateGuruCount() {
    const total = document.querySelectorAll('.v3-guru-cb').length;
    const checked = document.querySelectorAll('.v3-guru-cb:checked').length;
    const el = document.querySelector('#v3-config-panel .card-header span:last-child');
    if (el) el.textContent = `已启用 ${checked} / ${total}`;
  }

  function _getSelectedGurus() {
    return Array.from(document.querySelectorAll('.v3-guru-cb:checked')).map(cb => cb.value);
  }

  function _getMode() {
    const radio = document.querySelector('input[name="v3-mode"]:checked');
    return radio ? radio.value : 'agent';
  }

  function _getCandidateN() {
    const active = document.querySelector('#v3-candidate-chips .chip.active');
    return active ? parseInt(active.dataset.n) : 20;
  }

  // ── Estimate ──────────────────────────────────────────────────────

  function _scheduleEstimate() {
    if (_estimateTimer) clearTimeout(_estimateTimer);
    _estimateTimer = setTimeout(_fetchEstimate, 500);
  }

  async function _fetchEstimate() {
    const mode = _getMode();
    const gurus = _getSelectedGurus();
    const card = document.getElementById('v3-estimate-card');

    if (mode === 'classic' || gurus.length === 0) {
      if (card) card.style.display = 'none';
      return;
    }

    try {
      const resp = await fetch('/api/screen/v3/estimate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          candidate_n: _getCandidateN(),
          gurus: gurus,
          with_roundtable: mode === 'agent_with_roundtable',
        }),
      });
      const est = await resp.json();
      document.getElementById('v3-est-calls').textContent = est.llm_calls;
      document.getElementById('v3-est-duration').textContent = (est.duration_sec / 60).toFixed(1);
      document.getElementById('v3-est-cost').textContent = est.cost_cny;
      if (card) card.style.display = 'block';
    } catch (e) {
      if (card) card.style.display = 'none';
    }
  }

  // ── Trigger ───────────────────────────────────────────────────────

  window.runScreenV3 = async function () {
    const mode = _getMode();
    const gurus = _getSelectedGurus();
    const nlQuery = (document.getElementById('screen-nl-query')?.value || '').trim();
    const market = document.getElementById('v3-market')?.value || 'us';
    const candidateN = _getCandidateN();

    if (gurus.length === 0 && mode !== 'classic') {
      if (typeof showToast === 'function') showToast('请至少选择一位大师', 'warning');
      return;
    }

    const params = {
      nl_query: nlQuery,
      market: market,
      candidate_n: candidateN,
      gurus: gurus,
      mode: mode,
      with_roundtable: mode === 'agent_with_roundtable',
    };

    if (mode === 'classic') {
      // Classic mode: synchronous v2 path (kept for backward compat)
      if (typeof runScreenV2 === 'function') runScreenV2();
      return;
    }

    // Agent mode: async task
    try {
      const resp = await fetch('/api/screen/v3/trigger', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params),
      });
      const data = await resp.json();
      if (!resp.ok) {
        if (typeof showToast === 'function') showToast(data.error || '提交失败', 'error');
        return;
      }
      _activeTaskId = data.task_id;
      if (typeof showToast === 'function') showToast('V3 筛选任务已提交，请在任务中心查看进度', 'success');

      // Show progress card
      const progressCard = document.getElementById('v3-progress-card');
      if (progressCard) progressCard.style.display = 'block';
      const streamList = document.getElementById('v3-stream-list');
      if (streamList) streamList.innerHTML = '';

      // Subscribe to task events
      _subscribeToTask(data.task_id);
    } catch (e) {
      if (typeof showToast === 'function') showToast('网络错误', 'error');
    }
  };

  // ── Task streaming ────────────────────────────────────────────────

  function _subscribeToTask(taskId) {
    if (typeof socket === 'undefined') return;

    socket.on('task_progress', (data) => {
      if (data.task_id !== taskId) return;
      const bar = document.getElementById('v3-progress-bar');
      const text = document.getElementById('v3-progress-text');
      if (bar) bar.style.width = (data.percent || 0) + '%';
      if (text && data.step) text.textContent = data.step;
    });

    socket.on('guru_unit_done', (data) => {
      const list = document.getElementById('v3-stream-list');
      if (!list) return;
      const sigIcon = data.signal === 'bullish' ? '🟢' : data.signal === 'bearish' ? '🔴' : '⚪';
      const cached = data.cached ? ' (缓存)' : '';
      list.innerHTML += `<div style="padding:4px 0;border-bottom:1px solid var(--border);">
        ${sigIcon} <strong>${data.guru_display || data.guru}</strong> × ${data.ticker}
        — ${data.signal} ${(data.confidence * 100).toFixed(0)}%${cached}
      </div>`;
      list.scrollTop = list.scrollHeight;

      const text = document.getElementById('v3-progress-text');
      if (text) text.textContent = `${data.progress}/${data.total}`;
      const bar = document.getElementById('v3-progress-bar');
      if (bar && data.total) bar.style.width = (data.progress / data.total * 100) + '%';
    });

    socket.on('task_completed', (data) => {
      if (data.task_id !== taskId) return;
      _onTaskComplete(taskId);
    });
  }

  async function _onTaskComplete(taskId) {
    const progressCard = document.getElementById('v3-progress-card');
    if (progressCard) progressCard.style.display = 'none';

    // Fetch full result
    try {
      const resp = await fetch(`/api/tasks/${taskId}/result`);
      const result = await resp.json();
      if (result && result.results) {
        _renderV3Results(result);
      }
    } catch (e) {
      console.warn('Failed to fetch V3 result:', e);
    }
  }

  // ── Result rendering ──────────────────────────────────────────────

  function _renderV3Results(data) {
    const card = document.getElementById('v3-results-card');
    const list = document.getElementById('v3-results-list');
    const meta = document.getElementById('v3-results-meta');
    if (!card || !list) return;

    card.style.display = 'block';
    if (meta) {
      const m = data.metrics || {};
      meta.textContent = `${m.llm_calls || 0} 调用 · ${(m.duration_sec || 0).toFixed(0)}s · ¥${m.cost_cny || 0}`;
    }

    const results = data.results || [];
    if (!results.length) {
      list.innerHTML = '<p class="text-muted">无结果</p>';
      return;
    }

    list.innerHTML = results.slice(0, 10).map((r, i) => {
      const signals = (r.guru_signals || []);
      const signalBadges = signals.map(s => {
        const color = s.signal === 'bullish' ? 'var(--accent-green)' : s.signal === 'bearish' ? 'var(--accent-red)' : 'var(--text-secondary)';
        return `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${color};margin-right:2px;" title="${s.guru}: ${s.signal} ${(s.confidence * 100).toFixed(0)}%"></span>`;
      }).join('');

      const rt = r.roundtable;
      const rtHtml = rt ? `<div style="font-size:11px;margin-top:4px;color:var(--text-secondary);">共识: ${(rt.consensus || []).join(', ')} ${rt.dissent?.length ? '· 异议: ' + rt.dissent.join(', ') : ''}</div>` : '';

      return `<div class="history-item" style="cursor:pointer;" onclick="this.querySelector('.v3-detail').style.display = this.querySelector('.v3-detail').style.display === 'none' ? 'block' : 'none'">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <div>
            <span style="font-size:16px;font-weight:700;">#${i + 1} ${r.ticker}</span>
            <span style="margin-left:8px;">${signalBadges}</span>
          </div>
          <span class="num-responsive num-stat" style="font-size:18px;">${r.final_score?.toFixed(1) || '--'}</span>
        </div>
        ${rtHtml}
        <div class="v3-detail" style="display:none;margin-top:8px;border-top:1px solid var(--border);padding-top:8px;">
          ${signals.map(s => `
            <div style="margin-bottom:6px;">
              <div style="display:flex;justify-content:space-between;align-items:center;">
                <strong style="font-size:12px;">${s.guru}</strong>
                <span style="font-size:11px;color:${s.signal === 'bullish' ? 'var(--accent-green)' : s.signal === 'bearish' ? 'var(--accent-red)' : 'var(--text-secondary)'};">
                  ${s.signal} ${(s.confidence * 100).toFixed(0)}%
                </span>
              </div>
              <div style="height:3px;background:var(--border);border-radius:2px;margin:4px 0;">
                <div style="height:100%;width:${s.confidence * 100}%;background:var(--accent-blue);border-radius:2px;"></div>
              </div>
              <div style="font-size:11px;color:var(--text-secondary);max-height:60px;overflow:hidden;">${(s.reasoning || '').substring(0, 200)}...</div>
            </div>
          `).join('')}
        </div>
      </div>`;
    }).join('');
  }

  // ── Config persistence ────────────────────────────────────────────

  function _saveConfig() {
    try {
      localStorage.setItem(LS_KEY, JSON.stringify({
        gurus: _getSelectedGurus(),
        mode: _getMode(),
        candidateN: _getCandidateN(),
        market: document.getElementById('v3-market')?.value || 'us',
        nlQuery: document.getElementById('screen-nl-query')?.value || '',
      }));
    } catch (_) {}
  }

  function _restoreConfig() {
    try {
      const raw = localStorage.getItem(LS_KEY);
      if (!raw) return;
      const cfg = JSON.parse(raw);
      // Restore gurus
      if (cfg.gurus) {
        document.querySelectorAll('.v3-guru-cb').forEach(cb => {
          cb.checked = cfg.gurus.includes(cb.value);
        });
        _updateGuruCount();
      }
      // Restore mode
      if (cfg.mode) {
        document.querySelectorAll('#v3-mode-chips .chip').forEach(c => {
          const input = c.querySelector('input');
          if (input && input.value === cfg.mode) {
            c.classList.add('active');
            input.checked = true;
          } else {
            c.classList.remove('active');
          }
        });
      }
      // Restore candidate count
      if (cfg.candidateN) {
        document.querySelectorAll('#v3-candidate-chips .chip').forEach(c => {
          c.classList.toggle('active', parseInt(c.dataset.n) === cfg.candidateN);
        });
      }
      // Restore market
      if (cfg.market) {
        const sel = document.getElementById('v3-market');
        if (sel) sel.value = cfg.market;
      }
      // Restore NL query
      if (cfg.nlQuery) {
        const nl = document.getElementById('screen-nl-query');
        if (nl) nl.value = cfg.nlQuery;
      }
    } catch (_) {}
  }

  // ── Bootstrap ─────────────────────────────────────────────────────

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initV3);
  } else {
    initV3();
  }
})();
