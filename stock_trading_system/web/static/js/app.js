/* === Stock Trading System - Frontend === */

const socket = io();
let chartPnl = null;
let chartAllocation = null;
let chartKline = null;
let currentKlineTicker = null;
let currentKlineRange = '1mo';
let dashPnlDays = 30;
let alertBadgeCount = 0;
let chartBacktest = null;
let _backtestStrategies = null;

function renderMd(text) {
    if (!text) return '<span class="text-muted">N/A</span>';
    if (typeof marked !== 'undefined') return marked.parse(String(text));
    return '<pre>' + String(text).replace(/</g, '&lt;') + '</pre>';
}

// ── Navigation ─────────────────────────────────────────────────────────────

function switchTab(page) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    const target = document.getElementById('page-' + page);
    if (!target) return;
    target.classList.add('active');

    // Highlight sidebar entries
    document.querySelectorAll('#sidebar .nav-link').forEach(l => {
        l.classList.toggle('active', l.dataset.page === page);
    });
    // Highlight mobile tabbar entries (5 primary items only)
    document.querySelectorAll('#mobile-tabbar .tabbar-item[data-page]').forEach(l => {
        l.classList.toggle('active', l.dataset.page === page);
    });
    // For secondary pages, activate the "More" tab
    const primaryPages = ['dashboard', 'analysis', 'screener', 'portfolio'];
    const moreBtn = document.getElementById('tabbar-more');
    if (moreBtn) moreBtn.classList.toggle('active', !primaryPages.includes(page));

    // Load page data
    if (page === 'dashboard') loadDashboard();
    if (page === 'portfolio') loadPortfolio();
    if (page === 'alerts') { loadAlerts(); clearAlertBadge(); }
    if (page === 'history') loadHistory();
    if (page === 'backtest') loadBacktestStrategies();
    if (page === 'paper') loadPaperTickers();
    if (page === 'settings') loadSettings();
    if (page === 'tasks') { loadTasks(); clearTaskBadge(); }
    if (page === 'screener') loadGurus();

    window.scrollTo({ top: 0, behavior: 'instant' in window ? 'instant' : 'auto' });
}

document.querySelectorAll('[data-page]').forEach(link => {
    link.addEventListener('click', e => {
        e.preventDefault();
        const page = link.dataset.page;
        if (page) switchTab(page);
    });
});

const sidebarToggleBtn = document.getElementById('sidebar-toggle');
if (sidebarToggleBtn) {
    sidebarToggleBtn.addEventListener('click', () => {
        document.getElementById('sidebar').classList.toggle('collapsed');
        document.getElementById('main-content').classList.toggle('expanded');
        setTimeout(() => {
            if (chartPnl) chartPnl.resize();
            if (chartAllocation) chartAllocation.resize();
            if (chartKline) chartKline.resize();
        }, 350);
    });
}

// ── Mobile "More" Sheet ────────────────────────────────────────────────────

function toggleMoreSheet() {
    const sheet = document.getElementById('more-sheet');
    const backdrop = document.getElementById('more-sheet-backdrop');
    if (!sheet || !backdrop) return;
    const open = !sheet.classList.contains('show');
    sheet.classList.toggle('show', open);
    backdrop.classList.toggle('show', open);
}

function closeMoreSheet() {
    document.getElementById('more-sheet').classList.remove('show');
    document.getElementById('more-sheet-backdrop').classList.remove('show');
}

// ── Global Search ──────────────────────────────────────────────────────────

let _searchTimer = null;
let _searchHighlight = -1;  // index in the flat result list for arrow-key nav
let _searchFlatResults = [];  // flat list of {type,id,ticker,action}

function _escapeHtml(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
}

function _highlightMatch(text, q) {
    if (!text || !q) return _escapeHtml(text);
    const i = text.toLowerCase().indexOf(q.toLowerCase());
    if (i < 0) return _escapeHtml(text);
    return _escapeHtml(text.slice(0, i))
        + '<mark>' + _escapeHtml(text.slice(i, i + q.length)) + '</mark>'
        + _escapeHtml(text.slice(i + q.length));
}

function _closeSearchPanel() {
    const panel = document.getElementById('global-search-panel');
    if (panel) panel.classList.remove('show');
    _searchHighlight = -1;
}

function _showSearchPanel() {
    const panel = document.getElementById('global-search-panel');
    if (panel) panel.classList.add('show');
}

function _renderSearchResults(data) {
    const panel = document.getElementById('global-search-panel');
    if (!panel) return;
    const q = data.q || '';
    const groups = [
        { key: 'positions',    label: '持仓',    icon: 'fa-briefcase' },
        { key: 'analyses',     label: '分析记录', icon: 'fa-brain' },
        { key: 'transactions', label: '交易',    icon: 'fa-exchange-alt' },
        { key: 'alerts',       label: '预警',    icon: 'fa-bell' },
    ];
    const total = groups.reduce((n, g) => n + (data[g.key] || []).length, 0);
    if (total === 0) {
        panel.innerHTML = `<div class="global-search-empty">没有找到 "${_escapeHtml(q)}" 的结果</div>`;
        _searchFlatResults = [];
        _showSearchPanel();
        return;
    }
    _searchFlatResults = [];
    let flatIdx = 0;
    const html = groups.map(g => {
        const items = data[g.key] || [];
        if (items.length === 0) return '';
        const rows = items.map(it => {
            const myIdx = flatIdx++;
            let subtitle = '';
            let payload = { type: g.key };
            if (g.key === 'positions') {
                subtitle = `${it.market || ''} · ${fmt(it.shares)} 股 @ ${fmt(it.avg_cost)}`;
                payload = { type: 'positions', ticker: it.ticker };
                _searchFlatResults.push(payload);
                return `<div class="gs-result" data-idx="${myIdx}" onclick="_onSearchResultClick(${myIdx})">
                    <div class="gs-result-main">
                        <span class="gs-result-ticker">${_highlightMatch(it.ticker, q)}</span>
                        <span class="gs-result-sub">${_escapeHtml(subtitle)}</span>
                    </div>
                </div>`;
            }
            if (g.key === 'analyses') {
                const sig = it.signal || '';
                const sigCls = getSignalClass(sig);
                subtitle = `${it.date || ''} · ${it.action || '--'} · ${it.model || ''}`;
                payload = { type: 'analyses', id: it.id, ticker: it.ticker };
                _searchFlatResults.push(payload);
                return `<div class="gs-result" data-idx="${myIdx}" onclick="_onSearchResultClick(${myIdx})">
                    <div class="gs-result-main">
                        <span class="gs-result-ticker">${_highlightMatch(it.ticker || '', q)}</span>
                        <span class="gs-result-sub">${_escapeHtml(subtitle)}</span>
                    </div>
                    <span class="gs-result-badge ${sigCls}">${_escapeHtml(sig)}</span>
                </div>`;
            }
            if (g.key === 'transactions') {
                const cls = it.action === 'buy' ? 'text-green' : 'text-red';
                subtitle = `${it.timestamp || ''} · ${fmt(it.shares)} @ ${fmt(it.price)}`;
                payload = { type: 'transactions', ticker: it.ticker };
                _searchFlatResults.push(payload);
                return `<div class="gs-result" data-idx="${myIdx}" onclick="_onSearchResultClick(${myIdx})">
                    <div class="gs-result-main">
                        <span class="gs-result-ticker">${_highlightMatch(it.ticker, q)}</span>
                        <span class="gs-result-sub">${_escapeHtml(subtitle)}</span>
                    </div>
                    <span class="gs-result-badge ${cls}">${(it.action || '').toUpperCase()}</span>
                </div>`;
            }
            if (g.key === 'alerts') {
                subtitle = `${it.condition || ''} · ${fmt(it.threshold)}`;
                payload = { type: 'alerts', id: it.id, ticker: it.ticker };
                _searchFlatResults.push(payload);
                return `<div class="gs-result" data-idx="${myIdx}" onclick="_onSearchResultClick(${myIdx})">
                    <div class="gs-result-main">
                        <span class="gs-result-ticker">${_highlightMatch(it.ticker, q)}</span>
                        <span class="gs-result-sub">${_escapeHtml(subtitle)}</span>
                    </div>
                </div>`;
            }
            return '';
        }).join('');
        return `<div class="gs-group">
            <div class="gs-group-head"><i class="fas ${g.icon}"></i> ${g.label} <span class="gs-group-count">${items.length}</span></div>
            ${rows}
        </div>`;
    }).join('');
    panel.innerHTML = html;
    _showSearchPanel();
}

function _onSearchResultClick(idx) {
    const r = _searchFlatResults[idx];
    if (!r) return;
    _closeSearchPanel();
    document.getElementById('global-search-input').blur();
    if (r.type === 'positions' || r.type === 'transactions') {
        switchTab('portfolio');
    } else if (r.type === 'analyses') {
        switchTab('history');
        // Open detail modal shortly after the page swap so the modal host exists.
        if (r.id) setTimeout(() => showHistoryDetail(r.id), 100);
    } else if (r.type === 'alerts') {
        switchTab('alerts');
    }
}

async function _runGlobalSearch(q) {
    if (!q) {
        _closeSearchPanel();
        return;
    }
    try {
        const data = await api('/api/search?q=' + encodeURIComponent(q));
        if (data) _renderSearchResults(data);
    } catch (e) { /* ignore */ }
}

(function initGlobalSearch() {
    const input = document.getElementById('global-search-input');
    const panel = document.getElementById('global-search-panel');
    if (!input || !panel) return;

    input.addEventListener('input', () => {
        const q = input.value.trim();
        clearTimeout(_searchTimer);
        if (!q) { _closeSearchPanel(); return; }
        // Debounce so we don't hammer the endpoint on every keystroke.
        _searchTimer = setTimeout(() => _runGlobalSearch(q), 200);
    });

    input.addEventListener('focus', () => {
        if (input.value.trim()) _showSearchPanel();
    });

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            _closeSearchPanel();
            input.blur();
            return;
        }
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            if (_searchFlatResults.length === 0) return;
            e.preventDefault();
            _searchHighlight += (e.key === 'ArrowDown' ? 1 : -1);
            if (_searchHighlight < 0) _searchHighlight = _searchFlatResults.length - 1;
            if (_searchHighlight >= _searchFlatResults.length) _searchHighlight = 0;
            panel.querySelectorAll('.gs-result').forEach((el, i) => {
                el.classList.toggle('highlighted', i === _searchHighlight);
                if (i === _searchHighlight) el.scrollIntoView({ block: 'nearest' });
            });
            return;
        }
        if (e.key === 'Enter') {
            if (_searchHighlight >= 0) {
                _onSearchResultClick(_searchHighlight);
                return;
            }
            // Enter with no selection → jump to analysis page with the ticker
            const q = input.value.trim().toUpperCase();
            if (q) {
                document.getElementById('analyze-ticker').value = q;
                switchTab('analysis');
                _closeSearchPanel();
                input.blur();
            }
        }
    });

    // Click outside panel closes it.
    document.addEventListener('click', (e) => {
        if (!e.target.closest('#global-search')) _closeSearchPanel();
    });

    // "/" keyboard shortcut to focus (skip if already typing in an input).
    document.addEventListener('keydown', (e) => {
        if (e.key !== '/') return;
        const tag = (e.target.tagName || '').toLowerCase();
        if (tag === 'input' || tag === 'textarea' || e.target.isContentEditable) return;
        e.preventDefault();
        input.focus();
        input.select();
    });
})();

// ── Clock ──────────────────────────────────────────────────────────────────

function updateClock() {
    const now = new Date();
    document.getElementById('clock').textContent = now.toLocaleString('zh-CN');
}
setInterval(updateClock, 1000);
updateClock();

// Set default analysis date to today
document.getElementById('analyze-date').valueAsDate = new Date();

// ── Helpers ────────────────────────────────────────────────────────────────

function fmt(v, decimals = 2) {
    if (v == null || isNaN(v)) return '--';
    return Number(v).toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function fmtPct(v) {
    if (v == null || isNaN(v)) return '--';
    const sign = v >= 0 ? '+' : '';
    return sign + fmt(v) + '%';
}

function fmtCurrency(v, market) {
    if (v == null || isNaN(v)) return '--';
    const prefix = market === 'cn' ? '¥' : '$';
    return prefix + fmt(v);
}

function pnlClass(v) {
    if (v > 0) return 'text-green';
    if (v < 0) return 'text-red';
    return '';
}

function getSignalClass(signal) {
    if (!signal) return '';
    const s = signal.toUpperCase().replace(/\s+/g, '');
    if (['BUY', 'STRONGBUY', 'STRONG_BUY', 'OVERWEIGHT'].includes(s)) return s.toLowerCase().replace(/_/g, '');
    if (['SELL', 'STRONGSELL', 'STRONG_SELL', 'UNDERWEIGHT'].includes(s)) return s.toLowerCase().replace(/_/g, '');
    if (s === 'HOLD') return 'hold';
    // Fallback: bullish → green, bearish → red
    if (s.includes('BUY') || s.includes('OVER') || s.includes('BULL')) return 'buy';
    if (s.includes('SELL') || s.includes('UNDER') || s.includes('BEAR')) return 'sell';
    return 'hold';
}

function getSignalBadgeClass(signal) {
    if (!signal) return 'sig-default';
    const s = signal.toUpperCase();
    if (s === 'ERROR') return 'sig-error';
    if (['BUY', 'STRONG BUY', 'STRONGBUY', 'OVERWEIGHT'].includes(s)) return 'sig-buy';
    if (['SELL', 'STRONG SELL', 'STRONGSELL', 'UNDERWEIGHT'].includes(s)) return 'sig-sell';
    if (s === 'HOLD') return 'sig-hold';
    if (s.includes('BUY') || s.includes('OVER') || s.includes('BULL')) return 'sig-buy';
    if (s.includes('SELL') || s.includes('UNDER') || s.includes('BEAR')) return 'sig-sell';
    return 'sig-default';
}

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const colors = { info: 'var(--accent-blue)', success: 'var(--accent-green)', error: 'var(--accent-red)', warning: 'var(--accent-yellow)' };
    const toast = document.createElement('div');
    toast.className = 'toast show';
    toast.setAttribute('role', 'alert');
    toast.style.borderLeft = `4px solid ${colors[type] || colors.info}`;
    toast.innerHTML = `<div class="toast-body" style="font-size:13px;">${message}</div>`;
    container.appendChild(toast);
    setTimeout(() => { toast.classList.remove('show'); setTimeout(() => toast.remove(), 300); }, 4000);
}

async function api(url, options = {}) {
    try {
        const resp = await fetch(url, {
            headers: { 'Content-Type': 'application/json' },
            ...options,
        });
        return await resp.json();
    } catch (e) {
        showToast('请求失败: ' + e.message, 'error');
        return null;
    }
}

// ── Dashboard ──────────────────────────────────────────────────────────────

async function loadDashboard() {
    const data = await api('/api/dashboard');
    if (!data) return;

    const pnl = data.pnl;
    document.getElementById('dash-total-value').textContent = '$' + fmt(pnl.total_value);
    document.getElementById('dash-total-pnl').textContent = '$' + fmt(pnl.total_pnl);
    document.getElementById('dash-total-pnl').className = 'stat-value ' + pnlClass(pnl.total_pnl);
    document.getElementById('dash-pnl-pct').textContent = fmtPct(pnl.total_pnl_pct);
    document.getElementById('dash-pnl-pct').className = 'stat-value ' + pnlClass(pnl.total_pnl_pct);
    document.getElementById('dash-alerts-count').textContent = data.alerts_count;

    // Holdings - desktop table
    const tbody = document.querySelector('#dash-holdings-table tbody');
    tbody.innerHTML = '';
    (data.holdings || []).forEach(h => {
        const cls = pnlClass(h.pnl);
        tbody.innerHTML += `<tr>
            <td><strong>${h.ticker}</strong></td>
            <td>${(h.market || '').toUpperCase()}</td>
            <td>${fmt(h.shares, 0)}</td>
            <td>${fmtCurrency(h.avg_cost, h.market)}</td>
            <td>${fmtCurrency(h.current_price, h.market)}</td>
            <td class="${cls}">${fmtCurrency(h.pnl, h.market)}</td>
            <td class="${cls}">${fmtPct(h.pnl_pct)}</td>
        </tr>`;
    });

    // Holdings - mobile cards
    renderHoldingsCards('dash-holdings-cards', data.holdings || []);

    // P&L Chart (use configurable days range)
    const history = await api('/api/portfolio/history?days=' + dashPnlDays);
    renderPnlChart(history || data.history);

    // Allocation Chart
    const alloc = await api('/api/portfolio/allocation');
    if (alloc) renderAllocationChart(alloc);
}

function renderHoldingsCards(containerId, holdings, withActions = false) {
    const container = document.getElementById(containerId);
    if (!container) return;
    if (!holdings || holdings.length === 0) {
        container.innerHTML = '<p class="text-muted" style="font-size:13px;">暂无持仓</p>';
        return;
    }
    container.innerHTML = holdings.map(h => {
        const cls = pnlClass(h.pnl);
        const actions = withActions ? `
            <div class="m-card-actions">
                <button class="btn btn-sm btn-outline-primary" onclick="analyzeFromScreen('${h.ticker}')"><i class="fas fa-brain"></i> 分析</button>
                <button class="btn btn-sm btn-outline-info" onclick="openUpdateCostModal('${h.ticker}', ${h.avg_cost})"><i class="fas fa-edit"></i> 修成本</button>
            </div>` : '';
        return `<div class="m-card">
            <div class="m-card-head">
                <div>
                    <span class="m-card-ticker">${h.ticker}</span>
                    <span class="m-card-sub" style="margin-left:6px;">${(h.market || '').toUpperCase()} · ${fmt(h.shares, 0)} 股</span>
                </div>
                <div class="${cls}" style="font-weight:600;">${fmtPct(h.pnl_pct)}</div>
            </div>
            <div class="m-card-row"><span>现价</span><span>${fmtCurrency(h.current_price, h.market)}</span></div>
            <div class="m-card-row"><span>成本</span><span>${fmtCurrency(h.avg_cost, h.market)}</span></div>
            <div class="m-card-row"><span>市值</span><span>${fmtCurrency(h.market_value, h.market)}</span></div>
            <div class="m-card-row"><span>盈亏</span><span class="${cls}">${fmtCurrency(h.pnl, h.market)}</span></div>
            ${actions}
        </div>`;
    }).join('');
}

function renderPnlChart(history) {
    if (!history || history.length === 0) {
        const el = document.getElementById('chart-pnl');
        el.innerHTML = '<p class="text-muted text-center" style="padding-top:120px;">暂无历史数据</p>';
        return;
    }
    if (!chartPnl) chartPnl = echarts.init(document.getElementById('chart-pnl'), 'dark');
    chartPnl.setOption({
        backgroundColor: 'transparent',
        tooltip: { trigger: 'axis' },
        xAxis: { type: 'category', data: history.map(h => h.date), axisLine: { lineStyle: { color: 'rgba(56,130,255,0.12)' } } },
        yAxis: { type: 'value', axisLine: { lineStyle: { color: 'rgba(56,130,255,0.12)' } }, splitLine: { lineStyle: { color: 'rgba(56,130,255,0.06)' } } },
        series: [
            { name: '总市值', type: 'line', data: history.map(h => h.total_value), smooth: true, lineStyle: { color: '#3882ff' }, areaStyle: { color: 'rgba(56,130,255,0.1)' } },
            { name: '盈亏', type: 'bar', data: history.map(h => h.pnl), itemStyle: { color: p => p.value >= 0 ? '#00ff88' : '#ff3860' } },
        ],
        grid: { left: 60, right: 20, top: 20, bottom: 30 },
    });
}

function renderAllocationChart(alloc) {
    if (!alloc || alloc.length === 0) {
        const el = document.getElementById('chart-allocation');
        el.innerHTML = '<p class="text-muted text-center" style="padding-top:120px;">暂无持仓</p>';
        return;
    }
    if (!chartAllocation) chartAllocation = echarts.init(document.getElementById('chart-allocation'), 'dark');
    chartAllocation.setOption({
        backgroundColor: 'transparent',
        color: ['#3882ff', '#00d4ff', '#a855f7', '#00ff88', '#ff8c00', '#ff3860', '#ffd000', '#bc8cff'],
        tooltip: { trigger: 'item', formatter: '{b}: {d}%' },
        series: [{
            type: 'pie', radius: ['40%', '70%'],
            data: alloc.map(a => ({ name: a.ticker, value: a.value })),
            label: { color: '#e8edf5', fontSize: 12, fontFamily: 'JetBrains Mono, monospace' },
            itemStyle: { borderColor: '#111a2e', borderWidth: 2 },
        }],
    });
}

// ── Analysis ───────────────────────────────────────────────────────────────

function switchReportTab(btn, panelId) {
    document.querySelectorAll('.report-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.report-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    const panel = document.getElementById(panelId);
    if (panel) panel.classList.add('active');
}

// Track active tasks by ticker so we can route task_* events back to UI.
const _activeAnalysisTasks = new Map();   // taskId -> ticker
const _activeScreenTasks = new Map();     // taskId -> {market, strategy}

// Pipeline steps mirror PIPELINE_STEPS in agents/analyzer.py so the UI can
// render all step cards up-front (before any WebSocket events arrive).
const PIPELINE_STEPS = [
    { id: 'market',       label: '技术面分析', icon: 'fa-chart-bar' },
    { id: 'social',       label: '情绪分析',   icon: 'fa-comments' },
    { id: 'news',         label: '新闻分析',   icon: 'fa-newspaper' },
    { id: 'fundamentals', label: '基本面分析', icon: 'fa-building' },
    { id: 'debate',       label: '多空辩论',   icon: 'fa-balance-scale' },
    { id: 'risk',         label: '风险评估',   icon: 'fa-shield-alt' },
    { id: 'decision',     label: '最终决策',   icon: 'fa-gavel' },
];
// Track live per-step state; keyed by step id.
let _pipelineState = {};
let _pipelineRunTicker = null;

function _pipelineStatusLabel(status) {
    if (status === 'done') return '完成';
    if (status === 'running') return '进行中';
    if (status === 'failed') return '失败';
    return '等待';
}

function _pipelineRender() {
    const host = document.getElementById('pipeline-dag');
    if (!host) return;
    const steps = PIPELINE_STEPS;
    const html = steps.map((s, idx) => {
        const st = _pipelineState[s.id] || { status: 'pending', duration_ms: 0 };
        const cls = `pipeline-step pipeline-step-${st.status}`;
        const dur = st.duration_ms ? `${(st.duration_ms / 1000).toFixed(1)}s` : '';
        const badge = _pipelineStatusLabel(st.status);
        const arrow = idx < steps.length - 1 ? '<div class="pipeline-arrow"><i class="fas fa-chevron-right"></i></div>' : '';
        return `
            <div class="${cls}" data-step="${s.id}">
                <div class="pipeline-step-head">
                    <i class="fas ${s.icon}"></i>
                    <span class="pipeline-step-label">${s.label}</span>
                </div>
                <div class="pipeline-step-meta">
                    <span class="pipeline-step-badge">${badge}</span>
                    ${dur ? `<span class="pipeline-step-dur">${dur}</span>` : ''}
                </div>
            </div>${arrow}`;
    }).join('');
    host.innerHTML = html;

    // Progress bar = done / total
    const done = steps.filter(s => (_pipelineState[s.id] || {}).status === 'done').length;
    const pct = Math.round((done / steps.length) * 100);
    const fill = document.getElementById('pipeline-progress-fill');
    if (fill) fill.style.width = pct + '%';

    const summary = document.getElementById('pipeline-summary');
    if (summary) {
        const running = steps.find(s => (_pipelineState[s.id] || {}).status === 'running');
        const failed = steps.find(s => (_pipelineState[s.id] || {}).status === 'failed');
        if (failed) summary.textContent = `失败于: ${failed.label}`;
        else if (done === steps.length) summary.textContent = `全部完成 (${done}/${steps.length})`;
        else if (running) summary.textContent = `${running.label} · ${done}/${steps.length}`;
        else summary.textContent = `${done}/${steps.length}`;
    }
}

function _pipelineReset() {
    _pipelineState = {};
    PIPELINE_STEPS.forEach(s => { _pipelineState[s.id] = { status: 'pending', duration_ms: 0 }; });
    const card = document.getElementById('pipeline-card');
    if (card) card.style.display = 'block';
    const rerun = document.getElementById('btn-rerun');
    if (rerun) rerun.style.display = 'none';
    _pipelineRender();
}

function runAnalysis() {
    const ticker = document.getElementById('analyze-ticker').value.trim().toUpperCase();
    const date = document.getElementById('analyze-date').value;
    if (!ticker) { showToast('请输入股票代码', 'warning'); return; }

    // Load price chart + fundamentals + news immediately (fast preview)
    loadQuickData(ticker);

    _pipelineRunTicker = ticker;
    _pipelineReset();
    document.getElementById('analysis-loading').style.display = 'block';
    document.getElementById('analysis-result').style.display = 'none';
    document.getElementById('btn-analyze').disabled = true;

    // Submit through the task system. Task center will track it; the
    // task_completed bridge below routes the result back to this page.
    api('/api/tasks/submit', {
        method: 'POST',
        body: JSON.stringify({
            type: 'analysis',
            params: { ticker, date: date || undefined },
            title: `${ticker} 分析`,
        }),
    }).then(task => {
        if (!task || task.error) {
            document.getElementById('analysis-loading').style.display = 'none';
            document.getElementById('btn-analyze').disabled = false;
            showToast(task?.error || '提交失败', 'error');
            return;
        }
        _activeAnalysisTasks.set(task.id, ticker);
        if (task.status === 'success') {
            // Idempotent hit — fetch existing result immediately.
            handleAnalysisTaskCompleted(task.id, ticker);
            showToast(`复用最近的 ${ticker} 分析结果`, 'info');
        } else {
            showToast(`分析已加入队列：${ticker}`, 'info');
        }
    });
}

async function handleAnalysisTaskCompleted(taskId, tickerHint) {
    try {
        const data = await api(`/api/tasks/${taskId}/result`);
        if (!data || data.error) return;
        const result = data.result;
        if (!result) return;
        // Result shape from analysis_history table — render as before.
        renderAnalysisResultPayload({
            ticker: result.ticker || tickerHint,
            signal: result.signal,
            market_report: result.market_report,
            sentiment_report: result.sentiment_report,
            news_report: result.news_report,
            fundamentals_report: result.fundamentals_report,
            investment_debate: result.investment_debate,
            risk_assessment: result.risk_assessment,
            trade_decision: result.trade_decision,
            advice: result.advice_json
                ? (typeof result.advice_json === 'string'
                    ? safeJsonParse(result.advice_json)
                    : result.advice_json)
                : (result.advice || null),
        });
    } catch (e) {
        console.error('failed to load analysis result', e);
    }
}

function safeJsonParse(s) {
    try { return JSON.parse(s); } catch (_) { return null; }
}

function rerunAnalysis() {
    // Re-submit the last ticker+date combination. We don't yet support
    // re-running a single failed step (that needs TradingAgents refactor);
    // for now "重跑" triggers a full fresh run.
    runAnalysis();
}

// ── Quick data (chart / fundamentals / news) ───────────────────────────────

function loadQuickData(ticker) {
    currentKlineTicker = ticker;
    document.getElementById('quick-chart-card').style.display = 'block';
    document.getElementById('side-data-row').style.display = 'flex';
    document.getElementById('quick-chart-ticker').textContent = ticker;
    loadQuote(ticker);
    mountPriceChart(ticker);  // TV Widget (primary) or ECharts (fallback)
    loadFundamentals(ticker);
    loadNews(ticker);
}

async function loadQuote(ticker) {
    const data = await api('/api/quote/' + encodeURIComponent(ticker));
    const box = document.getElementById('quick-quote');
    if (!data || data.error) { box.innerHTML = ''; return; }
    const p = data.price || {};
    const last = p.last || p.close || 0;
    const change = p.change != null ? p.change : (p.pct_change || 0);
    const changeCls = change >= 0 ? 'text-green' : 'text-red';
    const sign = change >= 0 ? '+' : '';
    box.innerHTML = `
        <div class="quote-row">
            <span class="quote-price">${fmtCurrency(last, data.market)}</span>
            ${change !== 0 ? `<span class="${changeCls}">${sign}${fmt(change)}</span>` : ''}
            ${p.volume ? `<span class="text-muted">成交量: ${fmt(p.volume, 0)}</span>` : ''}
            ${p.high ? `<span class="text-muted">高: ${fmt(p.high)}</span>` : ''}
            ${p.low ? `<span class="text-muted">低: ${fmt(p.low)}</span>` : ''}
        </div>`;
}

// ── TradingView Widget (primary) with ECharts fallback ─────────────────────
//
// Decision tree:
//   tv.js loaded OK + we can mount → TV Widget wins
//   tv.js failed to load (CDN blocked, offline) → ECharts fallback
//   TV widget reported an error event within 4s → ECharts fallback
//
// We never try to reach into TV's iframe (the CSP would block it anyway).

let _tvWidgetInstance = null;
let _tvWatchdog = null;
let _chartProvider = null;  // 'tv' | 'echarts' | null

function mountPriceChart(ticker) {
    const tvAvailable = typeof TradingView !== 'undefined'
        && TradingView && TradingView.widget
        && !window.__tvLoadFailed;

    const tvContainer = document.getElementById('tv-chart-container');
    const echartsContainer = document.getElementById('chart-kline');
    const switcher = document.getElementById('echarts-range-switcher');
    const badge = document.getElementById('chart-source-badge');

    if (tvAvailable) {
        // TV path: show TV container, hide ECharts + switcher.
        tvContainer.style.display = 'block';
        echartsContainer.style.display = 'none';
        if (switcher) switcher.style.display = 'none';
        if (badge) { badge.textContent = 'TradingView'; badge.title = 'Powered by TradingView'; }
        mountTradingViewWidget(ticker);
        _chartProvider = 'tv';
    } else {
        // ECharts fallback
        activateEchartsFallback(ticker, '(TradingView 不可用)');
    }
}

function mountTradingViewWidget(ticker) {
    const container = document.getElementById('tv-chart-container');
    if (!container) return;

    // Destroy any previous instance (TV Widget has no official destroy API;
    // clearing the container is the recommended reset pattern).
    container.innerHTML = '';
    _tvWidgetInstance = null;

    const tvSymbol = (typeof toTVSymbol === 'function')
        ? toTVSymbol(ticker)
        : ('NASDAQ:' + ticker.toUpperCase());

    // If for some reason symbol mapping returned empty, bail to ECharts.
    if (!tvSymbol) {
        activateEchartsFallback(ticker, '(符号解析失败)');
        return;
    }

    try {
        _tvWidgetInstance = new TradingView.widget({
            container_id: 'tv-chart-container',
            symbol: tvSymbol,
            interval: 'D',
            theme: 'dark',
            style: '1',              // candles
            locale: 'zh_CN',
            timezone: 'Asia/Shanghai',
            toolbar_bg: '#0d1117',
            enable_publishing: false,
            allow_symbol_change: true,
            hide_side_toolbar: false,
            studies: [
                'MASimple@tv-basicstudies',
                'Volume@tv-basicstudies',
            ],
            autosize: true,
        });
    } catch (err) {
        console.warn('TV widget instantiation failed:', err);
        activateEchartsFallback(ticker, '(TradingView 加载失败)');
        return;
    }

    // Watchdog: poll for the iframe up to 10s. TV Widget often needs 5-8s
    // on slower networks (tradingview.com data subdomains can be flaky).
    // As soon as the iframe appears we declare success and stop polling.
    clearInterval(_tvWatchdog);
    const watchdogStart = Date.now();
    const WATCHDOG_BUDGET_MS = 10000;
    _tvWatchdog = setInterval(() => {
        const iframe = document.querySelector('#tv-chart-container iframe');
        if (iframe) {
            clearInterval(_tvWatchdog);
            _tvWatchdog = null;
            return;
        }
        if (Date.now() - watchdogStart >= WATCHDOG_BUDGET_MS) {
            clearInterval(_tvWatchdog);
            _tvWatchdog = null;
            console.warn('TV widget iframe never appeared — falling back');
            activateEchartsFallback(ticker, '(TradingView 超时)');
        }
    }, 500);
}

function activateEchartsFallback(ticker, reason) {
    const tvContainer = document.getElementById('tv-chart-container');
    const echartsContainer = document.getElementById('chart-kline');
    const switcher = document.getElementById('echarts-range-switcher');
    const badge = document.getElementById('chart-source-badge');
    if (tvContainer) tvContainer.style.display = 'none';
    if (echartsContainer) echartsContainer.style.display = 'block';
    if (switcher) switcher.style.display = '';
    if (badge) {
        badge.textContent = 'ECharts ' + (reason || '');
        badge.style.background = 'rgba(107,107,107,0.15)';
        badge.style.color = '#8b949e';
    }
    _chartProvider = 'echarts';
    loadChart(ticker, currentKlineRange);
}

async function loadChart(ticker, period) {
    const data = await api(`/api/chart/${encodeURIComponent(ticker)}?period=${period}&interval=1d`);
    const el = document.getElementById('chart-kline');
    if (!data || data.error || !data.data || data.data.length === 0) {
        el.innerHTML = '<p class="text-muted text-center" style="padding-top:120px;">暂无K线数据</p>';
        if (chartKline) { chartKline.dispose(); chartKline = null; }
        return;
    }
    renderKlineChart(data.data);
}

function renderKlineChart(rows) {
    const el = document.getElementById('chart-kline');
    el.innerHTML = '';
    if (!chartKline) chartKline = echarts.init(el, 'dark');

    const dates = rows.map(r => r.date);
    const kdata = rows.map(r => [r.open, r.close, r.low, r.high]);
    const volumes = rows.map((r, i) => ({
        value: r.volume,
        itemStyle: { color: r.close >= r.open ? '#00ff88' : '#ff3860' },
    }));

    chartKline.setOption({
        backgroundColor: 'transparent',
        animation: false,
        legend: { data: ['K线'], textStyle: { color: '#e6edf3' }, top: 0 },
        tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'cross' },
            backgroundColor: '#1c2128',
            borderColor: 'rgba(56,130,255,0.12)',
            textStyle: { color: '#e6edf3' },
        },
        axisPointer: { link: [{ xAxisIndex: 'all' }] },
        grid: [
            { left: 50, right: 20, top: 30, height: '62%' },
            { left: 50, right: 20, top: '76%', height: '18%' },
        ],
        xAxis: [
            { type: 'category', data: dates, axisLine: { lineStyle: { color: 'rgba(56,130,255,0.12)' } }, axisLabel: { color: '#6b7a99' } },
            { type: 'category', gridIndex: 1, data: dates, axisLine: { lineStyle: { color: 'rgba(56,130,255,0.12)' } }, axisLabel: { show: false } },
        ],
        yAxis: [
            { scale: true, axisLine: { lineStyle: { color: 'rgba(56,130,255,0.12)' } }, axisLabel: { color: '#6b7a99' }, splitLine: { lineStyle: { color: 'rgba(56,130,255,0.06)' } } },
            { gridIndex: 1, axisLine: { lineStyle: { color: 'rgba(56,130,255,0.12)' } }, axisLabel: { color: '#6b7a99' }, splitLine: { show: false } },
        ],
        series: [
            {
                name: 'K线', type: 'candlestick', data: kdata,
                itemStyle: {
                    color: '#00ff88', color0: '#ff3860',
                    borderColor: '#00ff88', borderColor0: '#ff3860',
                },
            },
            { name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: volumes },
        ],
    });
}

async function loadFundamentals(ticker) {
    const box = document.getElementById('fundamentals-box');
    box.innerHTML = '<div class="text-muted" style="font-size:12px;">加载中...</div>';
    const data = await api('/api/fundamentals/' + encodeURIComponent(ticker));
    if (!data || data.error) {
        box.innerHTML = '<p class="text-muted" style="font-size:12px;">暂无基本面数据</p>';
        return;
    }
    // Render common metrics with fallback to empty
    const metrics = [
        ['市值', data.market_cap || data.marketCap],
        ['市盈率', data.pe_ratio || data.pe || data.trailingPE],
        ['市净率', data.pb_ratio || data.pb || data.priceToBook],
        ['ROE', data.roe || data.returnOnEquity],
        ['毛利率', data.gross_margin || data.grossMargins],
        ['净利率', data.net_margin || data.profitMargins],
        ['营收增长', data.revenue_growth || data.revenueGrowth],
        ['股息率', data.dividend_yield || data.dividendYield],
        ['Beta', data.beta],
        ['52周高', data.week_52_high || data.fiftyTwoWeekHigh],
        ['52周低', data.week_52_low || data.fiftyTwoWeekLow],
        ['EPS', data.eps || data.trailingEps],
    ];
    const html = metrics
        .filter(([_, v]) => v != null && v !== '')
        .map(([k, v]) => {
            let display = v;
            if (typeof v === 'number') {
                if (Math.abs(v) > 1e9) display = (v / 1e9).toFixed(2) + 'B';
                else if (Math.abs(v) > 1e6) display = (v / 1e6).toFixed(2) + 'M';
                else if (Math.abs(v) < 1 && v !== 0) display = (v * 100).toFixed(2) + '%';
                else display = fmt(v);
            }
            return `<div class="fund-item"><span class="label">${k}</span><span class="value">${display}</span></div>`;
        }).join('');
    box.innerHTML = html ? `<div class="fund-grid">${html}</div>` : '<p class="text-muted" style="font-size:12px;">暂无基本面数据</p>';
}

async function loadNews(ticker) {
    const box = document.getElementById('news-box');
    box.innerHTML = '<div class="text-muted" style="font-size:12px;">加载中...</div>';
    const data = await api('/api/news/' + encodeURIComponent(ticker));
    if (!data || !Array.isArray(data) || data.length === 0) {
        box.innerHTML = '<p class="text-muted" style="font-size:12px;">暂无新闻</p>';
        return;
    }
    box.innerHTML = data.slice(0, 8).map(n => {
        const title = n.title || n.headline || '(无标题)';
        const url = n.url || n.link || '#';
        const date = n.date || n.published || n.time || '';
        const src = n.source || n.publisher || '';
        return `<div class="news-item">
            <a class="news-title" href="${url}" target="_blank" rel="noopener">${title}</a>
            <div class="news-meta">${src} · ${date}</div>
        </div>`;
    }).join('');
}

// Range switcher for ECharts K-line fallback (TV Widget has its own controls).
document.addEventListener('click', e => {
    const btn = e.target.closest('#echarts-range-switcher .btn');
    if (!btn) return;
    const parent = btn.closest('.range-switcher');
    parent.querySelectorAll('.btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentKlineRange = btn.dataset.range;
    if (currentKlineTicker && _chartProvider === 'echarts') {
        loadChart(currentKlineTicker, currentKlineRange);
    }
});

socket.on('analysis_status', data => {
    showToast(`${data.ticker} 分析中...`, 'info');
    // Reset all pipeline steps to pending
    document.querySelectorAll('#pipeline-steps .pipeline-step').forEach(el => {
        el.classList.remove('active', 'done');
        el.querySelector('.pipeline-status').textContent = '⏳';
    });
    // Mark first step as active (analysis starts with market)
    const first = document.querySelector('#pipeline-steps .pipeline-step');
    if (first) { first.classList.add('active'); first.querySelector('.pipeline-status').textContent = '🔄'; }
});

socket.on('analysis_step', data => {
    const stepEl = document.querySelector(`#pipeline-steps .pipeline-step[data-step="${data.step}"]`);
    if (!stepEl) return;
    // Skip if already done (e.g. risk step fires 3x for aggressive/conservative/neutral)
    if (stepEl.classList.contains('done')) return;

    if (data.status === 'done') {
        // Remove active from ALL steps first (clean slate)
        document.querySelectorAll('#pipeline-steps .pipeline-step.active').forEach(el => {
            el.classList.remove('active');
            // If this active step is NOT the one being completed, leave it as pending
            if (el !== stepEl && !el.classList.contains('done')) {
                el.querySelector('.pipeline-status').textContent = '⏳';
            }
        });

        // Mark this step as done
        stepEl.classList.add('done');
        stepEl.querySelector('.pipeline-status').textContent = '✅';

        // Find the next undone step and mark it active
        let next = stepEl.nextElementSibling;
        while (next && !next.classList.contains('pipeline-step')) next = next.nextElementSibling;
        if (next && !next.classList.contains('done')) {
            next.classList.add('active');
            next.querySelector('.pipeline-status').textContent = '🔄';
        }
    }
});

// Live pipeline progress stream from StockAnalyzer.analyze() via the
// `progress_cb` callback in /api/analyze. Events:
//   pipeline_start / step_start / step_done / pipeline_done / pipeline_error
socket.on('analysis_pipeline', event => {
    // Ignore events that belong to a different (older) run.
    if (_pipelineRunTicker && event.ticker && event.ticker !== _pipelineRunTicker) return;
    const type = event.type;
    if (type === 'pipeline_start') {
        if (Array.isArray(event.steps)) {
            event.steps.forEach(s => { _pipelineState[s.id] = { status: s.status, duration_ms: s.duration_ms || 0 }; });
        }
        _pipelineRender();
    } else if (type === 'step_start') {
        if (event.step) _pipelineState[event.step] = { status: 'running', duration_ms: 0 };
        _pipelineRender();
    } else if (type === 'step_done') {
        if (event.step) _pipelineState[event.step] = { status: 'done', duration_ms: event.duration_ms || 0 };
        _pipelineRender();
    } else if (type === 'pipeline_done') {
        if (Array.isArray(event.steps)) {
            event.steps.forEach(s => { _pipelineState[s.id] = { status: s.status, duration_ms: s.duration_ms || 0 }; });
        }
        _pipelineRender();
    } else if (type === 'pipeline_error') {
        if (Array.isArray(event.steps)) {
            event.steps.forEach(s => { _pipelineState[s.id] = { status: s.status, duration_ms: s.duration_ms || 0 }; });
        }
        document.getElementById('btn-rerun').style.display = 'inline-block';
        _pipelineRender();
    }
});

socket.on('analysis_result', data => {
    renderAnalysisResultPayload(data);
});

function renderAnalysisResultPayload(data) {
    document.getElementById('analysis-loading').style.display = 'none';
    document.getElementById('analysis-result').style.display = 'block';
    document.getElementById('btn-analyze').disabled = false;

    // Signal
    const signalEl = document.getElementById('signal-value');
    signalEl.textContent = data.signal;
    signalEl.className = 'signal-value ' + getSignalClass(data.signal);
    document.getElementById('signal-ticker').textContent = data.ticker;

    // Reports (markdown rendered)
    document.getElementById('report-market').innerHTML = renderMd(data.market_report);
    document.getElementById('report-fundamentals').innerHTML = renderMd(data.fundamentals_report);
    document.getElementById('report-sentiment').innerHTML = renderMd(data.sentiment_report);
    document.getElementById('report-news').innerHTML = renderMd(data.news_report);
    document.getElementById('report-debate').innerHTML = renderMd(data.investment_debate);
    document.getElementById('report-risk').innerHTML = renderMd(data.risk_assessment);
    document.getElementById('report-decision').innerHTML = renderMd(data.trade_decision);

    // Confidence card
    if (data.advice && data.advice.confidence) {
        document.getElementById('confidence-card').style.display = '';
        document.getElementById('confidence-value').textContent = data.advice.confidence + '%';
        document.getElementById('confidence-action').textContent = (data.advice.action || '').toUpperCase();
    } else {
        document.getElementById('confidence-card').style.display = 'none';
    }

    // Strategy advice
    if (data.advice) {
        document.getElementById('advice-card-container').style.display = 'block';
        const a = data.advice;
        document.getElementById('advice-content').innerHTML = `
            <div class="row g-2" style="font-size:13px;">
                <div class="col-4"><strong>建议操作:</strong> <span class="${a.action === 'buy' ? 'text-green' : a.action === 'sell' ? 'text-red' : 'text-yellow'}">${a.action.toUpperCase()}</span></div>
                <div class="col-4"><strong>信心度:</strong> ${a.confidence}</div>
                <div class="col-4"><strong>建议仓位:</strong> ${fmt(a.suggested_position_pct)}%</div>
                ${a.entry_price_low ? `<div class="col-4"><strong>入场区间:</strong> ${fmt(a.entry_price_low)} - ${fmt(a.entry_price_high)}</div>` : ''}
                ${a.stop_loss ? `<div class="col-4"><strong>止损:</strong> <span class="text-red">${fmt(a.stop_loss)}</span></div>` : ''}
                ${a.take_profit ? `<div class="col-4"><strong>止盈:</strong> <span class="text-green">${fmt(a.take_profit)}</span></div>` : ''}
                <div class="col-12 mt-2"><strong>分析:</strong> ${a.reasoning}</div>
                ${a.risk_warning ? `<div class="col-12 text-yellow"><strong>风险提示:</strong> ${a.risk_warning}</div>` : ''}
            </div>`;
    } else {
        document.getElementById('advice-card-container').style.display = 'none';
    }

    showToast(`${data.ticker} 分析完成: ${data.signal}`, 'success');
}

socket.on('analysis_error', data => {
    document.getElementById('analysis-loading').style.display = 'none';
    document.getElementById('btn-analyze').disabled = false;
    // Surface the rerun button so the user doesn't have to retype everything.
    const rerunBtn = document.getElementById('btn-rerun');
    if (rerunBtn) rerunBtn.style.display = 'inline-block';
    showToast(`分析失败: ${data.error}`, 'error');
});

// ═════════════════════════════════════════════════════════════════════════
// SCREENER V2 — Agent + Guru driven
// ═════════════════════════════════════════════════════════════════════════

const SCREENER_V2 = {
    currentTaskId: null,
    gurus: [],
    enabled: new Set(['buffett', 'graham', 'lynch', 'oneil']),
    loaded: false,
};

const V2_AGENT_META = {
    momentum:        { icon: 'fa-rocket',         color: '#3882ff', tag: 'Local', tagClass: 'tag-local-v2', role: '动量专家' },
    quality_value:   { icon: 'fa-gem',            color: '#00ff88', tag: 'Qwen',  tagClass: 'tag-qwen-v2',  role: '质量价值' },
    catalyst:        { icon: 'fa-bolt',           color: '#a855f7', tag: 'Qwen',  tagClass: 'tag-qwen-v2',  role: '催化剂' },
    sentiment:       { icon: 'fa-face-smile',     color: '#ffd000', tag: 'Qwen',  tagClass: 'tag-qwen-v2',  role: '情绪分析' },
    technical:       { icon: 'fa-chart-bar',      color: '#00d4ff', tag: 'Local', tagClass: 'tag-local-v2', role: '技术指标' },
    regime_relative: { icon: 'fa-sitemap',        color: '#ff8c00', tag: 'yfin',  tagClass: 'tag-yf-v2',    role: '环境/相对' },
    guru:            { icon: 'fa-crown',          color: '#ffd700', tag: 'Qwen',  tagClass: 'tag-qwen-v2',  role: '大师哲学' },
    risk:            { icon: 'fa-shield-halved',  color: '#ff3860', tag: 'Local', tagClass: 'tag-local-v2', role: '风险识别' },
};

async function loadGurus() {
    if (SCREENER_V2.loaded) return;
    try {
        const data = await api('/api/screen/v2/gurus');
        if (!data) return;
        SCREENER_V2.gurus = data;
        SCREENER_V2.loaded = true;
        renderGuruGrid();
        renderAgentGrid();
    } catch (e) { console.error('loadGurus failed:', e); }
}

function renderGuruGrid() {
    const grid = document.getElementById('guru-grid');
    if (!grid) return;
    grid.innerHTML = SCREENER_V2.gurus.map(g => {
        const active = SCREENER_V2.enabled.has(g.name) && g.implemented;
        const disabledClass = g.implemented ? '' : 'placeholder';
        const checked = active ? 'checked' : '';
        return `
            <div class="guru-card ${active ? 'active' : ''} ${disabledClass}">
                <div class="guru-head">
                    <div class="guru-avatar" style="background:${g.avatar_color}">${g.avatar_initials}</div>
                    <div>
                        <div class="guru-name">${g.display_name}</div>
                        <div class="guru-tag">${g.philosophy}</div>
                    </div>
                    <label class="guru-switch">
                        <input type="checkbox" ${checked} ${g.implemented ? '' : 'disabled'} onchange="toggleGuru('${g.name}')">
                        <span class="slider"></span>
                    </label>
                </div>
                <div class="guru-principles">
                    ${(g.principles || []).map(p => `<span class="principle">${p}</span>`).join('')}
                </div>
                <div class="guru-motto">${g.motto || ''}</div>
                ${!g.implemented ? '<div style="font-size:9px;color:var(--accent-yellow);margin-top:4px;text-align:center;font-family:var(--font-mono);">即将上线</div>' : ''}
            </div>`;
    }).join('');
    updateGuruCount();
}

function toggleGuru(name) {
    const g = SCREENER_V2.gurus.find(x => x.name === name);
    if (!g || !g.implemented) return;
    if (SCREENER_V2.enabled.has(name)) SCREENER_V2.enabled.delete(name);
    else SCREENER_V2.enabled.add(name);
    renderGuruGrid();
}

function updateGuruCount() {
    const el = document.getElementById('guru-active-count');
    if (!el) return;
    const implemented = SCREENER_V2.gurus.filter(g => g.implemented).length;
    el.textContent = `已启用 ${SCREENER_V2.enabled.size} / ${implemented}`;
}

function renderAgentGrid() {
    const grid = document.getElementById('agent-grid-screener');
    if (!grid) return;
    grid.innerHTML = Object.entries(V2_AGENT_META).map(([name, m]) => `
        <div class="agent-card-v2 idle" data-agent="${name}">
            <div class="agent-head-v2">
                <div class="agent-icon-v2" style="background:${m.color}22;color:${m.color};">
                    <i class="fas ${m.icon}"></i>
                </div>
                <div>
                    <div class="agent-name-v2">${name}</div>
                    <div class="agent-role-v2">${m.role}</div>
                </div>
                <div class="agent-status-v2 idle">⏳</div>
            </div>
            <div class="agent-data-tag-v2 ${m.tagClass}"><i class="fas fa-database"></i> ${m.tag}</div>
        </div>
    `).join('');
}

function renderPipelineStages(regime, universeCount, finalCount) {
    const stages = document.getElementById('screen-stages');
    if (!stages) return;
    const items = [
        { icon: 'fa-satellite-dish', label: 'L1 市场环境', value: regime || 'Detecting...' },
        { icon: 'fa-flask',          label: 'L2 宇宙过滤', value: universeCount ?? '--' },
        { icon: 'fa-sort-amount-up', label: 'L3 Agent 评分', value: universeCount ?? '--' },
        { icon: 'fa-gavel',          label: 'L4 聚合排名', value: finalCount ?? '--' },
    ];
    stages.innerHTML = items.map(i => `
        <div class="ps-step-v2">
            <div class="ps-icon-v2"><i class="fas ${i.icon}"></i></div>
            <div style="flex:1;">
                <div class="ps-label-v2">${i.label}</div>
                <div class="ps-count-v2">${i.value}</div>
            </div>
        </div>
    `).join('');
}

async function runScreenV2() {
    const enabledGurus = Array.from(SCREENER_V2.enabled);
    if (enabledGurus.length === 0) {
        showToast('请至少启用一位投资大师', 'warning');
        return;
    }
    const btn = document.getElementById('btn-screen-v2');
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 提交中...';

    document.getElementById('screen-picks-card').style.display = 'none';
    document.getElementById('agent-pipeline-card').style.display = 'block';
    document.getElementById('screen-stages-card').style.display = 'block';
    renderPipelineStages(null, null, null);
    document.querySelectorAll('#agent-grid-screener .agent-card-v2').forEach(el => {
        el.classList.remove('running', 'done');
        el.classList.add('idle');
        const s = el.querySelector('.agent-status-v2');
        s.className = 'agent-status-v2 idle';
        s.textContent = '⏳';
    });

    const params = {
        market: document.getElementById('screen-market').value,
        strategy: document.getElementById('screen-strategy').value,
        enabled_gurus: enabledGurus,
        nl_query: (document.getElementById('screen-nl-query').value || '').trim() || null,
        final_count: 5,
        max_universe: 40,
    };

    try {
        const resp = await api('/api/screen/v2/submit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(params),
        });
        if (!resp || !resp.ok) {
            showToast('提交失败: ' + (resp?.error || '未知错误'), 'error');
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-bolt"></i> 开始筛选';
            return;
        }
        SCREENER_V2.currentTaskId = resp.task_id;
        showToast('已提交选股任务 · ' + resp.task_id.substring(0, 8), 'info');
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 筛选中...';
    } catch (e) {
        showToast('提交出错: ' + e.message, 'error');
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-bolt"></i> 开始筛选';
    }
}

socket.on('task_progress', data => {
    if (data.id !== SCREENER_V2.currentTaskId) return;
    const step = data.step || '';
    const statusEl = document.getElementById('agent-pipeline-status');
    if (statusEl) statusEl.textContent = `${data.progress}% · ${step}`;
    const m = step.match(/Agent 完成：(\w+)/);
    if (m) markAgentDone(m[1]);
    if (step.includes('8 Agent 并行')) {
        document.querySelectorAll('#agent-grid-screener .agent-card-v2').forEach(el => {
            if (!el.classList.contains('done')) {
                el.classList.remove('idle');
                el.classList.add('running');
                const s = el.querySelector('.agent-status-v2');
                s.className = 'agent-status-v2 running';
                s.textContent = '🔄';
            }
        });
    }
});

function markAgentDone(agentName) {
    const el = document.querySelector(`#agent-grid-screener .agent-card-v2[data-agent="${agentName}"]`);
    if (!el) return;
    el.classList.remove('idle', 'running');
    el.classList.add('done');
    const s = el.querySelector('.agent-status-v2');
    s.className = 'agent-status-v2 done';
    s.textContent = '✅';
}

socket.on('task_completed', async data => {
    if (data.id !== SCREENER_V2.currentTaskId) return;
    const btn = document.getElementById('btn-screen-v2');
    if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-bolt"></i> 开始筛选'; }
    document.querySelectorAll('#agent-grid-screener .agent-card-v2').forEach(el => {
        el.classList.remove('running', 'idle');
        el.classList.add('done');
        const s = el.querySelector('.agent-status-v2');
        s.className = 'agent-status-v2 done';
        s.textContent = '✅';
    });
    try {
        const resp = await api('/api/screen/v2/result/by_task/' + SCREENER_V2.currentTaskId);
        if (resp && resp.results) {
            renderScreenV2Results(resp.results);
            showToast('筛选完成 · ' + resp.results.picks.length + ' 只精选', 'success');
        }
    } catch (e) {
        showToast('获取结果失败: ' + e.message, 'error');
    }
});

socket.on('task_failed', data => {
    if (data.id !== SCREENER_V2.currentTaskId) return;
    const btn = document.getElementById('btn-screen-v2');
    if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-bolt"></i> 开始筛选'; }
    showToast('筛选失败: ' + (data.error_message || '未知'), 'error');
});

function renderScreenV2Results(result) {
    // AI intent summary banner (V1.1)
    const fs = result.filter_spec || {};
    const intentBanner = document.getElementById('intent-summary-banner');
    if (intentBanner && fs.intent_summary) {
        intentBanner.style.display = 'flex';
        document.getElementById('intent-summary-text').textContent = fs.intent_summary;
        const srcMap = { qwen: 'Qwen 搜索', heuristic: '本地启发', default: '默认列表' };
        const srcLabel = srcMap[result.universe_source] || result.universe_source || '--';
        document.getElementById('universe-source-tag').innerHTML =
            `<i class="fas fa-database"></i> 宇宙源: <strong>${srcLabel}</strong>`;
    }

    const regime = result.regime || {};
    const banner = document.getElementById('regime-banner');
    const regimeLabel = regime.label || 'sideways';
    const regimeName = { bull: 'Bull 牛市', bear: 'Bear 熊市', sideways: 'Sideways 震荡' }[regimeLabel] || regimeLabel;
    banner.className = 'regime-banner-v2 ' + regimeLabel;
    banner.style.display = 'flex';
    document.getElementById('regime-title').textContent = '当前市场环境：' + regimeName;
    const stats = regime.stats || {};
    const weights = result.weights || {};
    const topWeight = Object.entries(weights).sort((a, b) => b[1] - a[1])[0];
    document.getElementById('regime-desc').innerHTML =
        `VIX ${stats.vix ?? '--'} · 市场宽度 ${stats.breadth_pct ?? '--'}% · SPY ${stats.spy_current ?? '--'} · 权重偏向 <strong>${topWeight ? topWeight[0] : '--'}</strong>`;
    document.getElementById('regime-stats').innerHTML = `
        <span>置信 <strong>${((regime.confidence || 0) * 100).toFixed(0)}%</strong></span>
        <span>耗时 <strong>${((result.duration_ms || 0) / 1000).toFixed(1)}s</strong></span>
    `;

    renderPipelineStages(regimeName, result.universe_count, result.final_count);
    document.querySelectorAll('#screen-stages .ps-step-v2').forEach(s => s.classList.add('done'));

    const statusEl = document.getElementById('agent-pipeline-status');
    if (statusEl) statusEl.textContent = `✅ 完成 · ${((result.duration_ms || 0) / 1000).toFixed(1)}s`;

    const picksCard = document.getElementById('screen-picks-card');
    picksCard.style.display = 'block';
    document.getElementById('screen-picks-meta').textContent =
        `${result.picks.length} 只 · 按综合置信度排序`;
    document.getElementById('screen-picks-list').innerHTML =
        result.picks.map((p, idx) => renderPickCardV2(p, idx === 0)).join('');
}

function renderPickCardV2(pick, isTop) {
    const conv = pick.conviction || 0;
    const convColor = conv >= 80 ? '#00ff88' : conv >= 65 ? '#00d4ff' : conv >= 50 ? '#ffd000' : '#ff8c00';
    const dashoffset = 152 - (152 * (conv / 100));
    const gurus = pick.guru_matches || {};
    const guruBadges = Object.entries(gurus).slice(0, 5).map(([name, g]) => {
        const cls = g.fit ? 'fit' : 'unfit';
        const tag = g.fit ? '✓' : '✗';
        return `<span class="guru-badge ${cls}" title="${(g.reason || '').replace(/"/g, '&quot;')}">${tag} ${name} · ${Math.round(g.match_pct || 0)}%</span>`;
    }).join('');

    const agentOrder = ['momentum', 'quality_value', 'catalyst', 'sentiment', 'technical', 'regime_relative', 'guru', 'risk'];
    const shortNames = { momentum: 'Mom', quality_value: 'Qual', catalyst: 'Cat', sentiment: 'Sent', technical: 'Tech', regime_relative: 'Reg', guru: 'Guru', risk: 'Risk' };
    const gradeClass = g => !g ? 'grade-f' : (g === 'A+' || g === 'A' ? 'grade-a' : g.startsWith('B') ? 'grade-b' : g.startsWith('C') ? 'grade-c' : g.startsWith('D') ? 'grade-d' : 'grade-f');
    const agentCells = agentOrder.map(n => {
        const s = (pick.agent_scores || {})[n] || {};
        return `<div class="score-cell-v2">
            <div class="s-agent">${shortNames[n]}</div>
            <div class="s-grade ${gradeClass(s.grade)}">${s.grade || '-'}</div>
            <div class="s-num">${Math.round(s.score || 0)}</div>
        </div>`;
    }).join('');

    const horizon = { '1-3 个月': '1-3M', '3-6 个月': '3-6M', '6-12 个月': '6-12M' }[pick.horizon] || pick.horizon || '--';
    const riskColor = { low: 'var(--accent-green)', med: 'var(--accent-yellow)', high: 'var(--accent-red)' }[pick.risk_tag] || 'var(--text-secondary)';
    const riskLabel = { low: '低风险', med: '中风险', high: '高风险' }[pick.risk_tag] || pick.risk_tag || '--';

    return `
        <div class="pick-card-v2 ${isTop ? 'top' : ''}">
            <div class="pick-head-v2">
                <div class="pick-rank-v2">#${pick.rank}</div>
                <div style="flex:1;min-width:200px;">
                    <span class="pick-ticker-v2">${pick.ticker}</span>
                    <div class="pick-name-v2">${pick.name || ''}${pick.sector ? ' · ' + pick.sector : ''}</div>
                    <div class="pick-meta-v2">
                        <span class="meta-item"><i class="fas fa-clock"></i> ${horizon}</span>
                        <span class="meta-item" style="color:${riskColor};"><i class="fas fa-shield-halved"></i> ${riskLabel}</span>
                        <span class="meta-item"><i class="fas fa-users"></i> ${pick.bullish_agents || 0}/${pick.total_agents || 8} 看多</span>
                    </div>
                </div>
                <div class="pick-conviction-v2">
                    <div class="conv-ring-v2">
                        <svg viewBox="0 0 56 56"><circle class="bg" cx="28" cy="28" r="24"/><circle class="fg" cx="28" cy="28" r="24" stroke="${convColor}" stroke-dashoffset="${dashoffset}"/></svg>
                        <div class="conv-text-v2" style="color:${convColor};">${Math.round(conv)}</div>
                    </div>
                </div>
            </div>
            <div class="agent-scores-v2">${agentCells}</div>
            ${guruBadges ? `<div class="guru-matches-v2"><span class="guru-matches-label"><i class="fas fa-crown"></i> 大师匹配</span>${guruBadges}</div>` : ''}
            <div class="pick-thesis-v2">
                <div class="label"><i class="fas fa-lightbulb"></i> 综合观点</div>
                <div><strong style="color:var(--text-primary);">Bull：</strong>${pick.bull_thesis || '--'}</div>
                ${pick.bear_thesis ? `<div style="margin-top:4px;"><strong style="color:var(--accent-red);">Bear：</strong>${pick.bear_thesis}</div>` : ''}
            </div>
            <div class="trade-plan-v2">
                <div class="tp-item-v2"><div class="tp-label-v2">入场</div><div class="tp-value-v2 entry">${pick.entry_low ?? '--'} - ${pick.entry_high ?? '--'}</div></div>
                <div class="tp-item-v2"><div class="tp-label-v2">止损</div><div class="tp-value-v2 stop">${pick.stop ?? '--'}</div></div>
                <div class="tp-item-v2"><div class="tp-label-v2">目标</div><div class="tp-value-v2 target">${pick.target ?? '--'}</div></div>
                <div class="tp-item-v2"><div class="tp-label-v2">R/R</div><div class="tp-value-v2 rr">${pick.risk_reward ? '1 : ' + pick.risk_reward : '--'}</div></div>
            </div>
            <div class="pick-actions-v2">
                <button class="btn primary" onclick="analyzeFromScreen('${pick.ticker}')"><i class="fas fa-brain"></i> AI 分析</button>
                <button class="btn" onclick="buyFromScreen('${pick.ticker}', ${pick.entry_low || 0})"><i class="fas fa-plus"></i> 加入持仓</button>
            </div>
        </div>
    `;
}

// ── Screener V1 (legacy fallback, kept for compatibility) ──

function runScreen() {
    const market = document.getElementById('screen-market').value;
    const strategy = document.getElementById('screen-strategy').value;

    document.getElementById('screen-loading').style.display = 'block';
    document.getElementById('screen-results').style.display = 'none';
    document.getElementById('btn-screen').disabled = true;

    // Reset funnel state
    ['funnel-l1', 'funnel-l2', 'funnel-l3'].forEach(id => {
        const el = document.getElementById(id);
        if (el) { el.classList.remove('done', 'active'); el.querySelector('.funnel-count').textContent = '⏳'; }
    });
    const l1 = document.getElementById('funnel-l1');
    if (l1) l1.classList.add('active');

    api('/api/tasks/submit', {
        method: 'POST',
        body: JSON.stringify({
            type: 'screen',
            params: { market, strategy },
            title: `${market.toUpperCase()} ${strategy} 选股`,
        }),
    }).then(task => {
        if (!task || task.error) {
            document.getElementById('screen-loading').style.display = 'none';
            document.getElementById('btn-screen').disabled = false;
            showToast(task?.error || '提交失败', 'error');
            return;
        }
        _activeScreenTasks.set(task.id, { market, strategy });
        if (task.status === 'success') {
            handleScreenTaskCompleted(task.id);
            showToast('复用最近的选股结果', 'info');
        } else {
            showToast('选股已加入队列', 'info');
        }
    });
}

async function handleScreenTaskCompleted(taskId) {
    try {
        const data = await api(`/api/tasks/${taskId}/result`);
        if (!data || data.error) return;
        // screen_results table stores results_json as a JSON string
        const row = data.result;
        const results = (row && row.results_json)
            ? safeJsonParse(row.results_json) || []
            : (row && row.results) || [];
        renderScreenResultsPayload({ results });
    } catch (e) {
        console.error('failed to load screen result', e);
    }
}

socket.on('screen_status', () => {
    showToast('筛选进行中...', 'info');
});

socket.on('screen_result', data => {
    renderScreenResultsPayload(data);
});

function renderScreenResultsPayload(data) {
    // Update funnel to all-done state with result count
    const count = (data.results || []).length;
    ['funnel-l1', 'funnel-l2', 'funnel-l3'].forEach(id => {
        const el = document.getElementById(id);
        if (el) { el.classList.remove('active'); el.classList.add('done'); el.querySelector('.funnel-count').textContent = '✅'; }
    });
    const l3 = document.getElementById('funnel-l3');
    if (l3) l3.querySelector('.funnel-count').textContent = `✅ ${count}只`;

    document.getElementById('screen-loading').style.display = 'none';
    document.getElementById('screen-results').style.display = 'block';
    document.getElementById('btn-screen').disabled = false;

    const results = data.results || [];
    const tbody = document.querySelector('#screen-table tbody');
    tbody.innerHTML = '';
    results.forEach((s, i) => {
        const sigCls = s.signal === 'BUY' ? 'text-green' : s.signal === 'SELL' ? 'text-red' : 'text-yellow';
        tbody.innerHTML += `<tr>
            <td>${i + 1}</td>
            <td><strong>${s.ticker || ''}</strong></td>
            <td>${s.name || ''}</td>
            <td>${s.price || ''}</td>
            <td class="${sigCls}">${s.signal || ''}</td>
            <td>${s.summary || ''}</td>
            <td>
                <button class="btn btn-sm btn-outline-primary me-1" onclick="analyzeFromScreen('${s.ticker}')" title="AI分析"><i class="fas fa-brain"></i></button>
                <button class="btn btn-sm btn-outline-success" onclick="buyFromScreen('${s.ticker}', '${s.price || ''}')" title="加入持仓"><i class="fas fa-plus"></i></button>
            </td>
        </tr>`;
    });

    // Mobile cards
    const mobileContainer = document.getElementById('screen-cards');
    if (mobileContainer) {
        if (results.length === 0) {
            mobileContainer.innerHTML = '<p class="text-muted" style="font-size:13px;">无结果</p>';
        } else {
            mobileContainer.innerHTML = results.map((s, i) => {
                const sigCls = s.signal === 'BUY' ? 'text-green' : s.signal === 'SELL' ? 'text-red' : 'text-yellow';
                return `<div class="m-card">
                    <div class="m-card-head">
                        <div>
                            <span class="m-card-sub">#${i + 1}</span>
                            <span class="m-card-ticker" style="margin-left:6px;">${s.ticker || ''}</span>
                        </div>
                        <span class="${sigCls}" style="font-weight:600;">${s.signal || ''}</span>
                    </div>
                    ${s.name ? `<div class="m-card-row"><span>名称</span><span>${s.name}</span></div>` : ''}
                    ${s.price ? `<div class="m-card-row"><span>价格</span><span>${s.price}</span></div>` : ''}
                    ${s.summary ? `<div class="m-card-row"><span>摘要</span><span style="max-width:60%;text-align:right;">${s.summary}</span></div>` : ''}
                    <div class="m-card-actions">
                        <button class="btn btn-sm btn-outline-primary" onclick="analyzeFromScreen('${s.ticker}')"><i class="fas fa-brain"></i> 分析</button>
                        <button class="btn btn-sm btn-outline-success" onclick="buyFromScreen('${s.ticker}', '${s.price || ''}')"><i class="fas fa-plus"></i> 加入持仓</button>
                    </div>
                </div>`;
            }).join('');
        }
    }
    showToast(`筛选完成，共 ${results.length} 只`, 'success');
}

socket.on('screen_error', data => {
    document.getElementById('screen-loading').style.display = 'none';
    document.getElementById('btn-screen').disabled = false;
    showToast('筛选失败: ' + data.error, 'error');
});

function analyzeFromScreen(ticker) {
    document.getElementById('analyze-ticker').value = ticker;
    document.querySelector('[data-page="analysis"]').click();
    runAnalysis();
}

function buyFromScreen(ticker, price) {
    document.getElementById('buy-ticker').value = ticker;
    if (price) document.getElementById('buy-price').value = price;
    document.querySelector('[data-page="portfolio"]').click();
    document.getElementById('buy-shares').focus();
}

// ── Portfolio ──────────────────────────────────────────────────────────────

async function loadPortfolio() {
    const [holdings, transactions] = await Promise.all([
        api('/api/portfolio/holdings'),
        api('/api/portfolio/transactions'),
    ]);

    // Holdings - desktop table
    const tbody = document.querySelector('#portfolio-table tbody');
    tbody.innerHTML = '';
    (holdings || []).forEach(h => {
        const cls = pnlClass(h.pnl);
        tbody.innerHTML += `<tr>
            <td><strong>${h.ticker}</strong></td>
            <td>${(h.market || '').toUpperCase()}</td>
            <td>${fmt(h.shares, 0)}</td>
            <td>${fmtCurrency(h.avg_cost, h.market)}</td>
            <td>${fmtCurrency(h.current_price, h.market)}</td>
            <td>${fmtCurrency(h.market_value, h.market)}</td>
            <td class="${cls}">${fmtCurrency(h.pnl, h.market)}</td>
            <td class="${cls}">${fmtPct(h.pnl_pct)}</td>
            <td>
                <button class="btn btn-sm btn-outline-primary" onclick="analyzeFromScreen('${h.ticker}')" title="分析"><i class="fas fa-brain"></i></button>
                <button class="btn btn-sm btn-outline-info" onclick="openUpdateCostModal('${h.ticker}', ${h.avg_cost})" title="修正成本"><i class="fas fa-edit"></i></button>
            </td>
        </tr>`;
    });

    // Holdings - mobile cards (with actions)
    renderHoldingsCards('portfolio-cards', holdings || [], true);

    // Transactions - desktop table
    const txBody = document.querySelector('#txn-table tbody');
    txBody.innerHTML = '';
    (transactions || []).slice(0, 50).forEach(t => {
        const cls = t.action === 'buy' ? 'text-green' : 'text-yellow';
        txBody.innerHTML += `<tr>
            <td>${t.date}</td>
            <td class="${cls}">${t.action.toUpperCase()}</td>
            <td>${t.ticker}</td>
            <td>${fmt(t.shares, 0)}</td>
            <td>${fmt(t.price)}</td>
            <td>${t.notes || ''}</td>
        </tr>`;
    });

    // Transactions - mobile cards
    renderTxnCards('txn-cards', transactions || []);
}

function renderTxnCards(containerId, txns) {
    const container = document.getElementById(containerId);
    if (!container) return;
    if (!txns || txns.length === 0) {
        container.innerHTML = '<p class="text-muted" style="font-size:13px;">暂无交易记录</p>';
        return;
    }
    container.innerHTML = txns.slice(0, 50).map(t => {
        const cls = t.action === 'buy' ? 'text-green' : 'text-yellow';
        return `<div class="m-card">
            <div class="m-card-head">
                <div>
                    <span class="m-card-ticker">${t.ticker}</span>
                    <span class="${cls}" style="font-weight:600;margin-left:8px;">${t.action.toUpperCase()}</span>
                </div>
                <div class="m-card-sub">${t.date}</div>
            </div>
            <div class="m-card-row"><span>数量</span><span>${fmt(t.shares, 0)}</span></div>
            <div class="m-card-row"><span>价格</span><span>${fmt(t.price)}</span></div>
            ${t.notes ? `<div class="m-card-row"><span>备注</span><span>${t.notes}</span></div>` : ''}
        </div>`;
    }).join('');
}

// ── Update Cost Modal ──────────────────────────────────────────────────────

let _updateCostTicker = null;

function openUpdateCostModal(ticker, currentCost) {
    _updateCostTicker = ticker;
    document.getElementById('updateCostTicker').textContent = ticker;
    document.getElementById('updateCostInput').value = currentCost || '';
    new bootstrap.Modal(document.getElementById('updateCostModal')).show();
}

async function submitUpdateCost() {
    const avgCost = document.getElementById('updateCostInput').value;
    if (!avgCost || !_updateCostTicker) {
        showToast('请输入有效的成本价', 'warning'); return;
    }
    const data = await api('/api/portfolio/update_cost', {
        method: 'POST',
        body: JSON.stringify({ ticker: _updateCostTicker, avg_cost: avgCost }),
    });
    if (data && data.ok) {
        showToast(data.message || '已更新', 'success');
        bootstrap.Modal.getInstance(document.getElementById('updateCostModal')).hide();
        loadPortfolio();
    }
}

async function takeSnapshot() {
    const data = await api('/api/portfolio/snapshot', { method: 'POST' });
    if (data && data.ok) showToast(data.message || '快照已保存', 'success');
}

async function addPosition() {
    const ticker = document.getElementById('buy-ticker').value.trim();
    const shares = document.getElementById('buy-shares').value;
    const price = document.getElementById('buy-price').value;
    if (!ticker || !shares || !price) { showToast('请填写完整信息', 'warning'); return; }

    const data = await api('/api/portfolio/add', {
        method: 'POST',
        body: JSON.stringify({ ticker, shares, price }),
    });
    if (data && data.ok) {
        showToast(data.message, 'success');
        document.getElementById('buy-ticker').value = '';
        document.getElementById('buy-shares').value = '';
        document.getElementById('buy-price').value = '';
        loadPortfolio();
    }
}

async function sellPosition() {
    const ticker = document.getElementById('sell-ticker').value.trim();
    const shares = document.getElementById('sell-shares').value;
    const price = document.getElementById('sell-price').value;
    if (!ticker || !shares || !price) { showToast('请填写完整信息', 'warning'); return; }

    const data = await api('/api/portfolio/sell', {
        method: 'POST',
        body: JSON.stringify({ ticker, shares, price }),
    });
    if (data && data.ok) {
        showToast(data.message, 'success');
        document.getElementById('sell-ticker').value = '';
        document.getElementById('sell-shares').value = '';
        document.getElementById('sell-price').value = '';
        loadPortfolio();
    }
}

// ── Alerts ─────────────────────────────────────────────────────────────────

const ALERT_COND_LABELS = {
    price_above: '价格高于', price_below: '价格低于',
    pct_change_above: '涨幅超过', pct_change_below: '跌幅超过',
    volume_spike: '成交量超过', stop_loss: '止损价', take_profit: '止盈价',
};

async function loadAlerts() {
    const alerts = await api('/api/alerts');
    const tbody = document.querySelector('#alerts-table tbody');
    tbody.innerHTML = '';

    (alerts || []).forEach(a => {
        tbody.innerHTML += `<tr>
            <td>${a.id}</td>
            <td><strong>${a.ticker}</strong></td>
            <td>${ALERT_COND_LABELS[a.condition] || a.condition}</td>
            <td>${a.threshold}</td>
            <td>${a.created}</td>
            <td><button class="btn btn-sm btn-outline-danger" onclick="removeAlert(${a.id})"><i class="fas fa-trash"></i></button></td>
        </tr>`;
    });

    // Mobile cards
    const mobileContainer = document.getElementById('alerts-cards');
    if (mobileContainer) {
        if (!alerts || alerts.length === 0) {
            mobileContainer.innerHTML = '<p class="text-muted" style="font-size:13px;">暂无活跃预警</p>';
        } else {
            mobileContainer.innerHTML = alerts.map(a => `
                <div class="m-card">
                    <div class="m-card-head">
                        <div>
                            <span class="m-card-ticker">${a.ticker}</span>
                            <span class="m-card-sub" style="margin-left:6px;">#${a.id}</span>
                        </div>
                        <button class="btn btn-sm btn-outline-danger" onclick="removeAlert(${a.id})"><i class="fas fa-trash"></i></button>
                    </div>
                    <div class="m-card-row"><span>条件</span><span>${ALERT_COND_LABELS[a.condition] || a.condition}</span></div>
                    <div class="m-card-row"><span>阈值</span><span>${a.threshold}</span></div>
                    <div class="m-card-row"><span>创建时间</span><span>${a.created}</span></div>
                </div>
            `).join('');
        }
    }

    // Also load trigger history
    loadAlertHistory();
}

async function loadAlertHistory() {
    const history = await api('/api/alerts/history?limit=30');
    const tbody = document.querySelector('#alert-history-table tbody');
    if (tbody) {
        tbody.innerHTML = '';
        (history || []).forEach(h => {
            tbody.innerHTML += `<tr>
                <td><strong>${h.ticker}</strong></td>
                <td>${ALERT_COND_LABELS[h.condition] || h.condition}</td>
                <td>${h.threshold}</td>
                <td>${h.current_price != null ? fmt(h.current_price) : '--'}</td>
                <td>${h.triggered_at}</td>
            </tr>`;
        });
        if (!history || history.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="text-muted text-center">暂无触发记录</td></tr>';
        }
    }
    const cards = document.getElementById('alert-history-cards');
    if (cards) {
        if (!history || history.length === 0) {
            cards.innerHTML = '<p class="text-muted" style="font-size:13px;">暂无触发记录</p>';
        } else {
            cards.innerHTML = history.map(h => `
                <div class="m-card">
                    <div class="m-card-head">
                        <span class="m-card-ticker">${h.ticker}</span>
                        <span class="text-muted">${h.triggered_at}</span>
                    </div>
                    <div class="m-card-row"><span>条件</span><span>${ALERT_COND_LABELS[h.condition] || h.condition}</span></div>
                    <div class="m-card-row"><span>阈值</span><span>${h.threshold}</span></div>
                    <div class="m-card-row"><span>触发价</span><span>${h.current_price != null ? fmt(h.current_price) : '--'}</span></div>
                </div>
            `).join('');
        }
    }
}

// ── Alert Rule Editor ──────────────────────────────────────────────────────

// Live cache of the current price for the ticker typed in the rule editor.
// Used by threshold suggestion chips, rule preview, and test-rule.
let _rulePrice = null;    // numeric last price, or null
let _ruleMarket = null;   // "us" / "cn"
let _rulePriceTimer = null;

const CONDITION_LABELS = {
    price_above:      { verb: '达到或超过', unit: '价格',   desc: '当最新价 ≥ 阈值时触发' },
    price_below:      { verb: '跌至或低于', unit: '价格',   desc: '当最新价 ≤ 阈值时触发' },
    pct_change_above: { verb: '当日涨幅达到', unit: '%',    desc: '今收相对昨收涨幅 ≥ 阈值时触发' },
    pct_change_below: { verb: '当日跌幅达到', unit: '%',    desc: '今收相对昨收跌幅 ≥ 阈值时触发' },
    volume_spike:     { verb: '成交量达到', unit: '股',     desc: '当日成交量 ≥ 阈值时触发' },
    stop_loss:        { verb: '跌至止损位', unit: '价格',   desc: '当最新价 ≤ 阈值时触发（止损语义）' },
    take_profit:      { verb: '涨至止盈位', unit: '价格',   desc: '当最新价 ≥ 阈值时触发（止盈语义）' },
};

function _ruleThresholdKind(cond) {
    // Returns 'price' / 'pct' / 'volume' — drives suggestion chips.
    if (cond === 'pct_change_above' || cond === 'pct_change_below') return 'pct';
    if (cond === 'volume_spike') return 'volume';
    return 'price';
}

function _ruleCurrency(n) {
    if (n == null) return '--';
    if (_ruleMarket === 'cn') return '¥' + fmt(n);
    return '$' + fmt(n);
}

function _updateRuleConditionDesc() {
    const cond = document.getElementById('alert-condition').value;
    const info = CONDITION_LABELS[cond] || {};
    const el = document.getElementById('rule-condition-desc');
    if (el) el.textContent = info.desc || '';
}

function _updateRuleThresholdSuggestions() {
    const host = document.getElementById('rule-threshold-suggestions');
    if (!host) return;
    const cond = document.getElementById('alert-condition').value;
    const kind = _ruleThresholdKind(cond);
    let chips = [];
    if (kind === 'price' && _rulePrice != null) {
        // Offer common offsets from current price. Negative for downside
        // conditions, positive for upside.
        const neg = (cond === 'price_below' || cond === 'stop_loss');
        const offsets = neg ? [-3, -5, -10, -15] : [3, 5, 10, 15];
        chips = offsets.map(pct => {
            const v = +(_rulePrice * (1 + pct / 100)).toFixed(2);
            const sign = pct > 0 ? '+' : '';
            return { label: `${sign}${pct}% → ${_ruleCurrency(v)}`, value: v };
        });
    } else if (kind === 'pct') {
        chips = [3, 5, 8, 10].map(v => ({ label: `${v}%`, value: v }));
    } else if (kind === 'volume') {
        chips = [1e6, 5e6, 1e7, 5e7].map(v => ({
            label: (v / 1e6).toFixed(0) + 'M',
            value: v,
        }));
    }
    host.innerHTML = chips.map(c =>
        `<button type="button" class="rule-suggest-chip" data-val="${c.value}">${c.label}</button>`
    ).join('');
}

function _updateRulePreview() {
    const ticker = (document.getElementById('alert-ticker').value || '').trim().toUpperCase();
    const cond = document.getElementById('alert-condition').value;
    const thresholdRaw = document.getElementById('alert-threshold').value;
    const threshold = parseFloat(thresholdRaw);
    const preview = document.getElementById('rule-preview');
    const btn = document.getElementById('btn-add-alert');

    const valid = ticker && !isNaN(threshold) && threshold > 0;
    if (btn) btn.disabled = !valid;

    if (!preview) return;
    if (!ticker) {
        preview.className = 'rule-preview rule-preview-muted';
        preview.innerHTML = '<i class="fas fa-circle-info"></i> <span>请输入股票代码...</span>';
        return;
    }
    if (isNaN(threshold)) {
        preview.className = 'rule-preview rule-preview-muted';
        preview.innerHTML = '<i class="fas fa-circle-info"></i> <span>请输入阈值...</span>';
        return;
    }
    const info = CONDITION_LABELS[cond] || {};
    const kind = _ruleThresholdKind(cond);
    let displayThreshold;
    if (kind === 'price') displayThreshold = _ruleCurrency(threshold);
    else if (kind === 'pct') displayThreshold = fmt(threshold) + '%';
    else displayThreshold = fmt(threshold, 0) + ' 股';

    let distance = '';
    if (kind === 'price' && _rulePrice != null) {
        const pct = ((threshold / _rulePrice) - 1) * 100;
        const sign = pct >= 0 ? '+' : '';
        const cls = pct >= 0 ? 'text-green' : 'text-red';
        distance = `<span class="rule-preview-distance ${cls}">距现价 ${sign}${fmt(pct)}%</span>`;
    }

    preview.className = 'rule-preview rule-preview-ready';
    preview.innerHTML = `
        <i class="fas fa-bell"></i>
        <span>
            当 <strong>${ticker}</strong> ${info.verb || ''}
            <strong>${displayThreshold}</strong> 时触发预警
            ${distance}
        </span>`;
}

async function _fetchRulePrice(ticker) {
    if (!ticker) {
        _rulePrice = null;
        _ruleMarket = null;
        document.getElementById('rule-current-price').textContent = '';
        _updateRuleThresholdSuggestions();
        _updateRulePreview();
        return;
    }
    try {
        const data = await api('/api/quote/' + encodeURIComponent(ticker));
        if (data && data.price) {
            _rulePrice = data.price.last || data.price.close || null;
            _ruleMarket = data.market || null;
        } else {
            _rulePrice = null;
            _ruleMarket = null;
        }
    } catch (e) {
        _rulePrice = null;
        _ruleMarket = null;
    }
    const label = document.getElementById('rule-current-price');
    if (label) {
        label.textContent = _rulePrice != null
            ? `${ticker} 现价 ${_ruleCurrency(_rulePrice)}`
            : (ticker ? `${ticker} 暂无行情` : '');
    }
    _updateRuleThresholdSuggestions();
    _updateRulePreview();
}

function _applyPreset(preset) {
    const condSel = document.getElementById('alert-condition');
    const thrInput = document.getElementById('alert-threshold');
    // Presets map to (condition, threshold-generator). Price-based presets
    // need _rulePrice; percent-based don't.
    if (preset === 'breakout_up') {
        condSel.value = 'price_above';
        if (_rulePrice != null) thrInput.value = (_rulePrice * 1.05).toFixed(2);
    } else if (preset === 'breakout_down') {
        condSel.value = 'price_below';
        if (_rulePrice != null) thrInput.value = (_rulePrice * 0.95).toFixed(2);
    } else if (preset === 'stop_loss_10') {
        condSel.value = 'stop_loss';
        if (_rulePrice != null) thrInput.value = (_rulePrice * 0.90).toFixed(2);
    } else if (preset === 'take_profit_20') {
        condSel.value = 'take_profit';
        if (_rulePrice != null) thrInput.value = (_rulePrice * 1.20).toFixed(2);
    } else if (preset === 'pct_change_3') {
        condSel.value = 'pct_change_above';
        thrInput.value = 3;
    }
    if (_rulePrice == null && preset !== 'pct_change_3') {
        showToast('请先输入股票代码以加载行情', 'warning');
    }
    _updateRuleConditionDesc();
    _updateRuleThresholdSuggestions();
    _updateRulePreview();
}

function testRule() {
    const ticker = (document.getElementById('alert-ticker').value || '').trim().toUpperCase();
    const cond = document.getElementById('alert-condition').value;
    const threshold = parseFloat(document.getElementById('alert-threshold').value);
    if (!ticker || isNaN(threshold)) {
        showToast('请先填写完整的规则', 'warning');
        return;
    }
    if (_rulePrice == null) {
        showToast(`无法获取 ${ticker} 现价，无法测试`, 'warning');
        return;
    }
    // Reuse the same logic as AlertMonitor._evaluate_condition. We don't have
    // prev-close/volume client-side, so percent/volume conditions are reported
    // as "cannot evaluate without historical data".
    let triggered = null;
    if (cond === 'price_above' || cond === 'take_profit') {
        triggered = _rulePrice >= threshold;
    } else if (cond === 'price_below' || cond === 'stop_loss') {
        triggered = _rulePrice <= threshold;
    }
    if (triggered === null) {
        showToast('此条件需服务端数据，无法客户端模拟', 'info');
        return;
    }
    const msg = triggered
        ? `✅ 规则已触发 (${ticker} = ${_ruleCurrency(_rulePrice)})`
        : `⏸ 规则未触发 (${ticker} = ${_ruleCurrency(_rulePrice)})`;
    showToast(msg, triggered ? 'success' : 'info');
}

async function addAlert() {
    const ticker = document.getElementById('alert-ticker').value.trim();
    const condition = document.getElementById('alert-condition').value;
    const threshold = document.getElementById('alert-threshold').value;
    if (!ticker || !threshold) { showToast('请填写完整信息', 'warning'); return; }

    const data = await api('/api/alerts/add', {
        method: 'POST',
        body: JSON.stringify({ ticker, condition, threshold }),
    });
    if (data && data.ok) {
        showToast(data.message, 'success');
        document.getElementById('alert-ticker').value = '';
        document.getElementById('alert-threshold').value = '';
        _rulePrice = null;
        _ruleMarket = null;
        document.getElementById('rule-current-price').textContent = '';
        _updateRuleThresholdSuggestions();
        _updateRulePreview();
        loadAlerts();
    }
}

// Wire up the rule editor once on page load.
(function initRuleEditor() {
    const tickerInput = document.getElementById('alert-ticker');
    const thresholdInput = document.getElementById('alert-threshold');
    const condSel = document.getElementById('alert-condition');
    if (!tickerInput || !condSel) return;

    tickerInput.addEventListener('input', () => {
        clearTimeout(_rulePriceTimer);
        const t = tickerInput.value.trim().toUpperCase();
        if (!t) {
            _fetchRulePrice('');
            return;
        }
        // Debounce network calls.
        _rulePriceTimer = setTimeout(() => _fetchRulePrice(t), 400);
        _updateRulePreview();
    });

    condSel.addEventListener('change', () => {
        _updateRuleConditionDesc();
        _updateRuleThresholdSuggestions();
        _updateRulePreview();
    });

    thresholdInput.addEventListener('input', _updateRulePreview);

    document.getElementById('rule-presets').addEventListener('click', e => {
        const chip = e.target.closest('[data-preset]');
        if (!chip) return;
        document.querySelectorAll('.rule-preset-chip').forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
        _applyPreset(chip.dataset.preset);
    });

    document.getElementById('rule-threshold-suggestions').addEventListener('click', e => {
        const chip = e.target.closest('[data-val]');
        if (!chip) return;
        thresholdInput.value = chip.dataset.val;
        _updateRulePreview();
    });

    _updateRuleConditionDesc();
    _updateRuleThresholdSuggestions();
    _updateRulePreview();
})();

async function removeAlert(id) {
    const data = await api('/api/alerts/remove', {
        method: 'POST',
        body: JSON.stringify({ id }),
    });
    if (data && data.ok) {
        showToast('预警已删除', 'success');
        loadAlerts();
    }
}

async function checkAlerts() {
    const data = await api('/api/alerts/check', { method: 'POST' });
    if (data) {
        const count = (data.triggered || []).length;
        showToast(count > 0 ? `触发 ${count} 条预警！` : '无预警触发', count > 0 ? 'warning' : 'info');
    }
}

// ── Reports ────────────────────────────────────────────────────────────────

async function generateReport() {
    const reportType = document.getElementById('report-type').value;
    const ticker = document.getElementById('report-ticker').value.trim();

    if (reportType === 'stock' && !ticker) {
        showToast('个股报告需要输入股票代码', 'warning');
        return;
    }

    document.getElementById('report-content').innerHTML = '<div class="text-center py-5"><div class="spinner-border text-primary"></div><p class="mt-2">生成中...</p></div>';

    const data = await api('/api/report', {
        method: 'POST',
        body: JSON.stringify({ type: reportType, ticker }),
    });

    if (data && data.content) {
        document.getElementById('report-content').innerHTML = renderMd(data.content);
        showToast('报告生成完成', 'success');
    } else {
        document.getElementById('report-content').innerHTML = '<p class="text-red">报告生成失败</p>';
    }
}

// ── Analysis History ───────────────────────────────────────────────────────

let _historyData = [];
let _compareMode = false;
let _compareSelected = new Set();

async function loadHistory() {
    const data = await api('/api/history');
    if (!data) return;
    _historyData = data;
    renderHistory(data);
}

function filterHistory() {
    const q = document.getElementById('history-filter').value.trim().toUpperCase();
    if (!q) { renderHistory(_historyData); return; }
    renderHistory(_historyData.filter(h => h.ticker.includes(q)));
}

function toggleCompareMode() {
    _compareMode = !_compareMode;
    _compareSelected.clear();
    document.getElementById('compare-toggle-label').textContent = _compareMode ? '退出对比' : '对比模式';
    document.getElementById('btn-compare-toggle').classList.toggle('active', _compareMode);
    document.getElementById('compare-action-wrap').classList.toggle('d-none', !_compareMode);
    _syncCompareButton();
    renderHistory(_historyData);
}

function _syncCompareButton() {
    const btn = document.getElementById('btn-run-compare');
    const cnt = document.getElementById('compare-count');
    if (cnt) cnt.textContent = String(_compareSelected.size);
    if (btn) btn.disabled = _compareSelected.size < 2;
}

function toggleHistorySelect(id, event) {
    if (event) { event.stopPropagation(); }
    id = Number(id);
    if (_compareSelected.has(id)) {
        _compareSelected.delete(id);
    } else {
        if (_compareSelected.size >= 5) {
            showToast('最多只能选择 5 条记录对比', 'warning');
            return;
        }
        _compareSelected.add(id);
    }
    // Update only the affected item visually instead of full re-render
    const el = document.querySelector(`.history-item[data-id="${id}"]`);
    if (el) el.classList.toggle('selected', _compareSelected.has(id));
    const chk = document.querySelector(`.history-item[data-id="${id}"] .h-check i`);
    if (chk) chk.className = _compareSelected.has(id) ? 'fas fa-check-square' : 'far fa-square';
    _syncCompareButton();
}

function renderHistory(records) {
    const container = document.getElementById('history-list');
    if (!records || records.length === 0) {
        container.innerHTML = '<p class="text-muted">暂无分析记录</p>';
        return;
    }
    container.innerHTML = records.map(r => {
        const sel = _compareSelected.has(r.id);
        const checkBox = _compareMode
            ? `<span class="h-check me-2" style="cursor:pointer;"><i class="${sel ? 'fas fa-check-square text-info' : 'far fa-square text-muted'}"></i></span>`
            : '';
        const clickAttr = _compareMode
            ? `onclick="toggleHistorySelect(${r.id}, event)"`
            : `onclick="showHistoryDetail(${r.id})"`;
        const actionInfo = r.action ? `<span class="text-muted ms-2" style="font-size:12px;">${r.action}${r.confidence ? ' · ' + r.confidence : ''}</span>` : '';
        return `
        <div class="history-item ${sel ? 'selected' : ''}" data-id="${r.id}" ${clickAttr}>
            <div class="d-flex justify-content-between align-items-center">
                <div>
                    ${checkBox}<span class="h-ticker">${r.ticker}</span>
                    <span class="h-signal ${getSignalBadgeClass(r.signal)}" style="margin-left:12px;">${r.signal}</span>
                    ${actionInfo}
                </div>
                <div class="d-flex align-items-center gap-2">
                    <button class="btn btn-sm btn-outline-secondary" onclick="showTimeline('${r.ticker}', event)" title="查看该股票历史演变">
                        <i class="fas fa-stream"></i>
                    </button>
                    <div class="h-date">${r.created_at || r.date}</div>
                </div>
            </div>
            <div class="mt-1" style="font-size:12px;color:var(--text-secondary);">
                分析日期: ${r.date}
            </div>
        </div>
        `;
    }).join('');
}

async function runCompare() {
    if (_compareSelected.size < 2) return;
    const ids = Array.from(_compareSelected).join(',');
    const data = await api('/api/history/compare?ids=' + encodeURIComponent(ids));
    if (!data || !data.records) return;
    renderCompareModal(data.records);
    const modal = new bootstrap.Modal(document.getElementById('compareModal'));
    modal.show();
}

function renderCompareModal(records) {
    const body = document.getElementById('compareModalBody');
    if (!records || records.length === 0) {
        body.innerHTML = '<p class="text-muted">没有可对比的记录</p>';
        return;
    }
    const headers = records.map(r => `
        <th class="text-center">
            <div><strong>${r.ticker}</strong></div>
            <div style="font-size:11px;color:var(--text-secondary);">${(r.created_at || r.date || '').split(' ')[0]}</div>
        </th>`).join('');
    const valueRow = (label, getter, options={}) => {
        const vals = records.map(getter);
        const changed = options.driftHighlight && _hasDrift(vals);
        const cells = vals.map(v => `<td class="text-center">${v == null || v === '' ? '<span class="text-muted">--</span>' : v}</td>`).join('');
        return `<tr${changed ? ' class="drift-row"' : ''}><th scope="row" class="text-muted" style="font-weight:normal;">${label}</th>${cells}</tr>`;
    };
    const sigCell = r => `<span class="h-signal ${getSignalBadgeClass(r.signal)}">${r.signal || '--'}</span>`;
    body.innerHTML = `
        <div class="table-responsive">
            <table class="table table-sm compare-table">
                <thead><tr><th style="width:140px;">字段</th>${headers}</tr></thead>
                <tbody>
                    ${valueRow('信号', sigCell, {driftHighlight: true})}
                    ${valueRow('策略建议', r => r.action || '', {driftHighlight: true})}
                    ${valueRow('信心', r => r.confidence || '')}
                    ${valueRow('建议仓位', r => r.position_pct != null ? fmt(r.position_pct) + '%' : '')}
                    ${valueRow('入场低位', r => r.entry_low != null ? fmt(r.entry_low) : '')}
                    ${valueRow('入场高位', r => r.entry_high != null ? fmt(r.entry_high) : '')}
                    ${valueRow('止损', r => r.stop_loss != null ? fmt(r.stop_loss) : '')}
                    ${valueRow('止盈', r => r.take_profit != null ? fmt(r.take_profit) : '')}
                    ${valueRow('模型', r => r.model || '')}
                </tbody>
            </table>
        </div>
        <p class="text-muted mb-0" style="font-size:12px;">
            <i class="fas fa-info-circle"></i> 标黄行表示不同记录间信号/策略建议存在漂移。
        </p>
    `;
}

function _hasDrift(values) {
    const norm = values.map(v => {
        if (v == null || v === '') return '';
        // Strip HTML from signal cell to compare raw signal text
        if (typeof v === 'string' && v.includes('<')) {
            return v.replace(/<[^>]+>/g, '').trim();
        }
        return String(v).trim();
    });
    const nonEmpty = norm.filter(v => v !== '');
    if (nonEmpty.length < 2) return false;
    return !nonEmpty.every(v => v === nonEmpty[0]);
}

async function showTimeline(ticker, event) {
    if (event) { event.stopPropagation(); }
    const data = await api('/api/history/timeline/' + encodeURIComponent(ticker));
    if (!data) return;
    renderTimelineModal(ticker, data.records || []);
    const modal = new bootstrap.Modal(document.getElementById('timelineModal'));
    modal.show();
}

function renderTimelineModal(ticker, records) {
    document.getElementById('timelineModalTitle').innerHTML =
        `<i class="fas fa-stream"></i> ${ticker} 观点演变 <small class="text-muted">(${records.length} 条)</small>`;
    const body = document.getElementById('timelineModalBody');
    if (records.length === 0) {
        body.innerHTML = '<p class="text-muted">该股票暂无历史分析</p>';
        return;
    }
    // Render timeline cards + a small confidence / signal strip
    let prevSignal = null;
    const items = records.map(r => {
        const drift = prevSignal && r.signal && prevSignal !== r.signal;
        prevSignal = r.signal || prevSignal;
        const dt = (r.created_at || r.date || '').split(' ')[0] || r.date;
        const pos = r.position_pct != null ? fmt(r.position_pct) + '%' : '--';
        const sl = r.stop_loss != null ? fmt(r.stop_loss) : '--';
        const tp = r.take_profit != null ? fmt(r.take_profit) : '--';
        return `
        <div class="timeline-item ${drift ? 'drift' : ''}">
            <div class="timeline-dot ${getSignalBadgeClass(r.signal)}"></div>
            <div class="timeline-body">
                <div class="d-flex justify-content-between flex-wrap gap-2">
                    <div>
                        <span class="h-signal ${getSignalBadgeClass(r.signal)}">${r.signal || '--'}</span>
                        ${r.action ? `<span class="ms-2">${r.action}</span>` : ''}
                        ${r.confidence ? `<span class="text-muted ms-1" style="font-size:12px;">· ${r.confidence}</span>` : ''}
                        ${drift ? '<span class="badge bg-warning text-dark ms-2">观点漂移</span>' : ''}
                    </div>
                    <div class="text-muted" style="font-size:12px;">${dt}</div>
                </div>
                <div class="row g-2 mt-1" style="font-size:12px;color:var(--text-secondary);">
                    <div class="col-4">仓位: ${pos}</div>
                    <div class="col-4">止损: ${sl}</div>
                    <div class="col-4">止盈: ${tp}</div>
                </div>
                <div class="mt-1">
                    <a href="#" onclick="event.preventDefault();event.stopPropagation();showHistoryDetail(${r.id});" style="font-size:12px;">查看完整报告 →</a>
                </div>
            </div>
        </div>
        `;
    }).join('');
    body.innerHTML = `<div class="timeline-list">${items}</div>`;
}

// Cache raw report text for lazy rendering in history detail modal
let _historyDetailCache = null;

function closeHistoryDetail() {
    const ov = document.getElementById('historyOverlay');
    if (ov) ov.classList.remove('show');
    document.body.classList.remove('overlay-open');
    document.body.style.overflow = '';
}

function openHistoryOverlay() {
    document.getElementById('historyOverlay').classList.add('show');
    document.body.classList.add('overlay-open');
    document.body.style.overflow = 'hidden';
}

// Close overlay when clicking backdrop (outside panel) or pressing Esc
document.addEventListener('click', e => {
    const ov = document.getElementById('historyOverlay');
    if (ov && ov.classList.contains('show') && e.target === ov) closeHistoryDetail();
});
document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeHistoryDetail();
});

function _renderHistoryTab(key) {
    if (!_historyDetailCache) return;
    const target = document.getElementById('hist-tab-content');
    if (!target) return;
    const text = _historyDetailCache[key] || '';
    target.innerHTML = `<div class="report-content" style="max-height:none;">${renderMd(text)}</div>`;
    // Update active tab button
    document.querySelectorAll('#hist-tabs .report-tab').forEach(t => t.classList.remove('active'));
    const btn = document.querySelector(`#hist-tabs .report-tab[data-tab="${key}"]`);
    if (btn) btn.classList.add('active');
}

async function showHistoryDetail(id) {
    const r = await api('/api/history/' + id);
    if (!r) return;

    const sigCls = getSignalBadgeClass(r.signal);
    const signalLabel = r.signal === 'ERROR' ? '❌ ERROR' : r.signal;
    document.getElementById('historyModalTitle').innerHTML =
        `${r.ticker} <span class="h-signal ${sigCls}" style="font-size:14px;">${signalLabel}</span> <small class="text-muted" style="font-size:13px;">${r.date}</small>`;

    const body = document.getElementById('historyModalBody');

    // ERROR records: simple error view
    if (r.signal === 'ERROR') {
        body.innerHTML = '<div class="alert" style="background:rgba(255,56,96,0.1);border:1px solid rgba(255,56,96,0.4);color:#ff3860;padding:12px;border-radius:6px;"><strong>分析失败详情</strong></div>';
        const pre = document.createElement('pre');
        pre.style.cssText = 'font-size:12px;color:#c9d1d9;white-space:pre-wrap;word-break:break-all;background:#0a0e1a;padding:12px;border-radius:6px;margin-top:8px;';
        pre.textContent = r.trade_decision || '（无错误详情）';
        body.appendChild(pre);
        openHistoryOverlay();
        return;
    }

    // Build advice card
    let adviceHtml = '';
    if (r.advice_json) {
        try {
            const a = JSON.parse(r.advice_json);
            adviceHtml = `
                <div style="background:rgba(56,130,255,0.06);border:1px solid var(--border);border-radius:8px;padding:14px 16px;margin-bottom:16px;">
                    <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;color:var(--accent-blue);font-weight:600;font-size:13px;"><i class="fas fa-lightbulb"></i> 策略建议</div>
                    <div class="row g-2" style="font-size:13px;">
                        <div class="col-md-3 col-6"><span style="color:var(--text-secondary);font-size:11px;">操作</span><div>${(a.action || '--').toUpperCase()}</div></div>
                        <div class="col-md-3 col-6"><span style="color:var(--text-secondary);font-size:11px;">信心度</span><div>${a.confidence || '--'}</div></div>
                        <div class="col-md-3 col-6"><span style="color:var(--text-secondary);font-size:11px;">仓位</span><div>${fmt(a.suggested_position_pct)}%</div></div>
                        ${a.stop_loss ? `<div class="col-md-3 col-6"><span style="color:var(--text-secondary);font-size:11px;">止损</span><div style="color:var(--accent-red);">${fmt(a.stop_loss)}</div></div>` : ''}
                        ${a.take_profit ? `<div class="col-md-3 col-6"><span style="color:var(--text-secondary);font-size:11px;">止盈</span><div style="color:var(--accent-green);">${fmt(a.take_profit)}</div></div>` : ''}
                        ${a.reasoning ? `<div class="col-12 mt-2" style="color:var(--text-secondary);"><strong style="color:var(--text-primary);">分析：</strong>${a.reasoning}</div>` : ''}
                        ${a.risk_warning ? `<div class="col-12" style="color:var(--accent-yellow);"><strong>⚠ 风险：</strong>${a.risk_warning}</div>` : ''}
                    </div>
                </div>`;
        } catch(e) {}
    }

    // Cache report text for lazy rendering
    _historyDetailCache = {
        market: r.market_report || '',
        fundamentals: r.fundamentals_report || '',
        sentiment: r.sentiment_report || '',
        news: r.news_report || '',
        debate: r.investment_debate || '',
        risk: r.risk_assessment || '',
        decision: r.trade_decision || '',
    };

    // Show modal with tab skeleton (NO markdown rendered yet — fast open)
    body.innerHTML = `
        ${adviceHtml}
        <div id="hist-tabs" class="report-tabs" style="display:flex;overflow-x:auto;border-bottom:1px solid var(--border);margin-bottom:16px;">
            <button class="report-tab active" data-tab="decision" onclick="_renderHistoryTab('decision')"><i class="fas fa-gavel"></i> 最终决策</button>
            <button class="report-tab" data-tab="market" onclick="_renderHistoryTab('market')"><i class="fas fa-chart-bar"></i> 技术面</button>
            <button class="report-tab" data-tab="fundamentals" onclick="_renderHistoryTab('fundamentals')"><i class="fas fa-building"></i> 基本面</button>
            <button class="report-tab" data-tab="sentiment" onclick="_renderHistoryTab('sentiment')"><i class="fas fa-comments"></i> 情绪</button>
            <button class="report-tab" data-tab="news" onclick="_renderHistoryTab('news')"><i class="fas fa-newspaper"></i> 新闻</button>
            <button class="report-tab" data-tab="debate" onclick="_renderHistoryTab('debate')"><i class="fas fa-scale-balanced"></i> 多空辩论</button>
            <button class="report-tab" data-tab="risk" onclick="_renderHistoryTab('risk')"><i class="fas fa-shield-halved"></i> 风险评估</button>
        </div>
        <div id="hist-tab-content"><div class="text-muted text-center py-3">加载中...</div></div>
        <div id="hist-timeline-slot"></div>
    `;

    openHistoryOverlay();

    // Render default tab (decision) async so modal opens instantly
    setTimeout(() => _renderHistoryTab('decision'), 50);

    // Load signal timeline async (doesn't block modal)
    setTimeout(async () => {
        try {
            const allHistory = await api('/api/history?ticker=' + encodeURIComponent(r.ticker));
            if (allHistory && allHistory.length > 1) {
                const slot = document.getElementById('hist-timeline-slot');
                if (slot) {
                    slot.innerHTML = '<div class="signal-timeline mt-3"><h6 style="color:#e6edf3;margin-bottom:8px;"><i class="fas fa-stream"></i> 信号变化时间线</h6><div class="timeline-track">' +
                        allHistory.slice().reverse().map(h => {
                            const cls = h.signal === 'BUY' ? 'tl-buy' : h.signal === 'SELL' ? 'tl-sell' : h.signal === 'ERROR' ? 'tl-error' : 'tl-hold';
                            const active = h.id === r.id ? ' tl-active' : '';
                            return `<div class="tl-point ${cls}${active}" title="${h.date} ${h.signal}">
                                <div class="tl-dot"></div>
                                <div class="tl-label">${h.signal}</div>
                                <div class="tl-date">${h.date}</div>
                            </div>`;
                        }).join('<div class="tl-line"></div>') +
                        '</div></div>';
                }
            }
        } catch(e) {}
    }, 100);
}

// ── Backtest ──────────────────────────────────────────────────────────────

// chartBacktest already declared at top level
let btStrategies = [];

async function loadBacktestStrategies() {
    btStrategies = await api('/api/backtest/strategies') || [];
    const sel = document.getElementById('bt-strategy');
    sel.innerHTML = btStrategies.map(s => `<option value="${s.id}">${s.name}</option>`).join('');
    sel.addEventListener('change', renderBtParams);
    renderBtParams();
}

function renderBtParams() {
    const sid = document.getElementById('bt-strategy').value;
    const strat = btStrategies.find(s => s.id === sid);
    const row = document.getElementById('bt-params-row');
    if (!strat || !strat.params || strat.params.length === 0) { row.innerHTML = ''; return; }
    row.innerHTML = strat.params.map(p => `
        <div class="col-4 col-md-2">
            <label class="form-label small">${p.label}</label>
            <input type="number" class="form-control bt-param" data-name="${p.name}" value="${p.default}">
        </div>
    `).join('');
}

// Track active backtest tasks so task_completed events can be routed back here.
const _activeBacktestTasks = new Map();   // taskId -> ticker

async function runBacktest() {
    const ticker = document.getElementById('bt-ticker').value.trim().toUpperCase();
    if (!ticker) { showToast('请输入股票代码', 'warning'); return; }
    const btn = document.getElementById('btn-backtest');
    btn.disabled = true;
    document.getElementById('bt-loading').style.display = 'block';
    document.getElementById('bt-result').style.display = 'none';

    const params = {};
    document.querySelectorAll('.bt-param').forEach(el => {
        params[el.dataset.name] = parseInt(el.value) || el.value;
    });

    const taskParams = {
        ticker,
        strategy_id: document.getElementById('bt-strategy').value,
        start_date: document.getElementById('bt-start').value,
        end_date: document.getElementById('bt-end').value,
        initial_capital: parseFloat(document.getElementById('bt-capital').value) || 100000,
        params,
    };

    const task = await api('/api/tasks/submit', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            type: 'backtest',
            params: taskParams,
            title: `${taskParams.strategy_id} 回测 ${ticker}`,
        }),
    });

    if (!task || task.error) {
        btn.disabled = false;
        document.getElementById('bt-loading').style.display = 'none';
        showToast(task?.error || '提交失败', 'error');
        return;
    }
    _activeBacktestTasks.set(task.id, ticker);

    if (task.status === 'success') {
        // Idempotent hit — load existing result immediately.
        handleBacktestTaskCompleted(task.id, ticker);
        showToast('复用最近的回测结果', 'info');
    } else {
        showToast(`回测已加入队列：${ticker}`, 'info');
    }
}

async function handleBacktestTaskCompleted(taskId, tickerHint) {
    try {
        const data = await api(`/api/tasks/${taskId}/result`);
        if (!data || data.error) return;
        const row = data.result;
        if (!row) return;
        // backtest_results table stores metrics/equity_curve/trades as JSON strings
        const metrics = (row.metrics_json && typeof row.metrics_json === 'string')
            ? safeJsonParse(row.metrics_json) || {}
            : (row.metrics || {});
        const equity = (row.equity_curve_json && typeof row.equity_curve_json === 'string')
            ? safeJsonParse(row.equity_curve_json) || []
            : (row.equity_curve || []);
        const trades = (row.trades_json && typeof row.trades_json === 'string')
            ? safeJsonParse(row.trades_json) || []
            : (row.trades || []);
        renderBacktestResultPayload({
            ticker: row.ticker || tickerHint,
            strategy_id: row.strategy_id,
            initial_capital: row.initial_capital,
            metrics, equity_curve: equity,
            benchmark_curve: row.benchmark_curve || [],  // not stored in V1 schema
            trades,
        });
    } catch (e) {
        console.error('failed to load backtest result', e);
    }
}

function renderBacktestResultPayload(payload) {
    const btn = document.getElementById('btn-backtest');
    btn.disabled = false;
    document.getElementById('bt-loading').style.display = 'none';
    document.getElementById('bt-result').style.display = 'block';

    const m = payload.metrics || {};
    const ticker = payload.ticker || '';

    // Metrics cards
    const totalReturn = m.total_return || 0;
    const annualized = m.annualized_return || 0;
    const maxDD = m.max_drawdown || 0;
    const winRate = m.win_rate || 0;
    const numTrades = m.num_trades != null ? m.num_trades : 0;
    const sharpe = m.sharpe_ratio != null ? m.sharpe_ratio : 0;

    const metrics = [
        { label: '总收益率', value: (totalReturn * 100).toFixed(2) + '%', cls: totalReturn >= 0 ? 'text-green' : 'text-red' },
        { label: '年化收益', value: (annualized * 100).toFixed(2) + '%', cls: annualized >= 0 ? 'text-green' : 'text-red' },
        { label: '最大回撤', value: (maxDD * 100).toFixed(2) + '%', cls: 'text-red' },
        { label: '胜率', value: (winRate * 100).toFixed(1) + '%', cls: winRate >= 0.5 ? 'text-green' : 'text-yellow' },
        { label: '交易次数', value: numTrades, cls: '' },
        { label: '夏普比率', value: sharpe, cls: sharpe >= 1 ? 'text-green' : 'text-yellow' },
    ];
    document.getElementById('bt-metrics').innerHTML = metrics.map(metric => `
        <div class="col-4 col-md-2">
            <div class="stat-card">
                <div class="stat-label">${metric.label}</div>
                <div class="stat-value ${metric.cls}" style="font-size:1.2rem;">${metric.value}</div>
            </div>
        </div>
    `).join('');

    renderBacktestChart(payload.equity_curve || [], payload.benchmark_curve || []);

    const trades = payload.trades || [];
    const tbody = document.querySelector('#bt-trades-table tbody');
    tbody.innerHTML = trades.map(t => `
        <tr>
            <td>${t.date}</td>
            <td><span class="${t.action === 'BUY' ? 'text-green' : 'text-red'}">${t.action === 'BUY' ? '买入' : '卖出'}</span></td>
            <td>${fmt(t.price)}</td>
            <td>${t.shares}</td>
            <td>$${fmt(t.value)}</td>
            <td class="${pnlClass(t.pnl || 0)}">${t.pnl != null ? '$' + fmt(t.pnl) : '--'}</td>
            <td>${t.hold_days != null ? t.hold_days + '天' : '--'}</td>
        </tr>
    `).join('');

    const cards = document.getElementById('bt-trades-cards');
    cards.innerHTML = trades.map(t => `
        <div class="m-card">
            <div class="m-card-head">
                <span class="${t.action === 'BUY' ? 'text-green' : 'text-red'}">${t.action === 'BUY' ? '买入' : '卖出'}</span>
                <span class="text-muted">${t.date}</span>
            </div>
            <div class="m-card-row"><span>价格</span><span>$${fmt(t.price)}</span></div>
            <div class="m-card-row"><span>数量</span><span>${t.shares} 股</span></div>
            ${t.pnl != null ? `<div class="m-card-row"><span>盈亏</span><span class="${pnlClass(t.pnl)}">$${fmt(t.pnl)}</span></div>` : ''}
        </div>
    `).join('');

    showToast(`回测完成: ${ticker} 收益 ${(totalReturn * 100).toFixed(2)}%`,
              totalReturn >= 0 ? 'success' : 'warning');
}

function renderBacktestChart(equity, benchmark) {
    if (!chartBacktest) chartBacktest = echarts.init(document.getElementById('chart-backtest'), 'dark');
    const series = [
        { name: '策略净值', type: 'line', data: equity.map(e => e.value), smooth: true, lineStyle: { color: '#3882ff', width: 2 }, areaStyle: { color: 'rgba(56,130,255,0.08)' } },
    ];
    if (benchmark && benchmark.length > 0) {
        series.push({ name: '买入持有', type: 'line', data: benchmark.map(e => e.value), smooth: true, lineStyle: { color: '#6b7a99', width: 1, type: 'dashed' } });
    }
    chartBacktest.setOption({
        backgroundColor: 'transparent',
        tooltip: { trigger: 'axis' },
        legend: { textStyle: { color: '#6b7a99' }, top: 0 },
        xAxis: { type: 'category', data: equity.map(e => e.date), axisLine: { lineStyle: { color: 'rgba(56,130,255,0.12)' } }, axisLabel: { fontSize: 10 } },
        yAxis: { type: 'value', axisLine: { lineStyle: { color: 'rgba(56,130,255,0.12)' } }, splitLine: { lineStyle: { color: 'rgba(56,130,255,0.06)' } } },
        series,
        grid: { left: 60, right: 20, top: 35, bottom: 30 },
    });
}

// ── Settings ───────────────────────────────────────────────────────────────

async function loadSettings() {
    const [settings, schedStatus] = await Promise.all([
        api('/api/settings'),
        api('/api/scheduler/status'),
    ]);
    renderSchedulerStatus(schedStatus);
    renderDataSourceStatus(settings);
    renderSettingsConfig(settings);
}

function renderSchedulerStatus(s) {
    const box = document.getElementById('scheduler-status');
    if (!box) return;
    if (!s) { box.innerHTML = '<span class="text-muted">无法获取状态</span>'; return; }
    const running = s.running;
    const dot = running ? '<span class="status-dot ok"></span>' : '<span class="status-dot idle"></span>';
    const label = running ? '<span class="text-green">运行中</span>' : '<span class="text-muted">已停止</span>';
    box.innerHTML = `
        <div class="settings-row">
            <span class="label">${dot}运行状态</span>
            <span class="value">${label}</span>
        </div>
        <div class="settings-row">
            <span class="label">预警检查间隔</span>
            <span class="value">${s.alert_interval || '--'} 秒</span>
        </div>`;
}

function renderDataSourceStatus(settings) {
    const box = document.getElementById('datasource-status');
    if (!box || !settings) return;
    const ds = settings.data_sources || {};
    const ib = settings.ib || {};
    const qwen = settings.qwen || {};
    const items = [
        { name: 'IB TWS (美股主)', ok: !!ds.ib_enabled, sub: ib.host ? `${ib.host}:${ib.port || ''}` : '未配置' },
        { name: 'Polygon.io (美股备用)', ok: !!ds.polygon_configured, sub: ds.polygon_configured ? '已配置' : '未配置 API Key' },
        { name: 'yfinance (美股兜底)', ok: true, sub: '无需 Key' },
        { name: 'AkShare (A股)', ok: !!ds.akshare, sub: '无需 Key' },
        { name: 'Qwen (LLM 最末兜底)', ok: !!ds.qwen_enabled, sub: ds.qwen_enabled ? (qwen.model || 'enabled') : '未启用' },
    ];
    box.innerHTML = items.map(it => `
        <div class="settings-row">
            <span class="label"><span class="status-dot ${it.ok ? 'ok' : 'fail'}"></span>${it.name}</span>
            <span class="value">${it.sub}</span>
        </div>
    `).join('');
}

// Settings editor state — origin's approach: the last full /api/settings
// response + edit mode, driven by the toolbar buttons in the header.
let _settingsData = null;
let _settingsEditMode = false;
let _settingsWritable = new Set();
// HEAD's legacy inline-edit dirty map is kept for backward compatibility with
// editSetting/commitSettingEdit flows but no longer drives the primary UI.
let settingsDirty = {};

// Definition of every editable row — label, dotted-path, input type,
// current-value accessor (reads from the /api/settings response), and
// optional hint. Rendered in both read and edit modes so the layout stays
// identical on toggle.
function _settingsFields(s) {
    const mask = v => v || '未配置';
    return [
        { group: 'Gemini (LLM)', rows: [
            { label: '快速模型', path: 'gemini.model', type: 'text',
              display: s.gemini?.model || '--' },
            { label: '深度模型', path: 'gemini.deep_think_model', type: 'text',
              display: s.gemini?.deep_think_model || '--' },
            { label: '思考等级', path: 'gemini.thinking_level', type: 'text',
              display: s.gemini?.thinking_level || '--' },
            { label: 'API Key', path: 'gemini.api_key', type: 'password',
              display: mask(s.gemini?.api_key_masked),
              placeholder: '粘贴新 Gemini API Key 以覆盖' },
        ]},
        { group: 'Polygon', rows: [
            { label: 'API Key', path: 'polygon.api_key', type: 'password',
              display: mask(s.polygon?.api_key_masked) },
        ]},
        { group: 'Qwen (DashScope 兜底)', rows: [
            { label: '启用', path: 'qwen.enabled', type: 'bool',
              display: s.qwen?.enabled ? '<span class="text-green">已启用</span>' : '<span class="text-muted">未启用</span>',
              valueBool: !!s.qwen?.enabled },
            { label: '模型', path: 'qwen.model', type: 'text',
              display: s.qwen?.model || '--' },
            { label: 'API Key', path: 'qwen.api_key', type: 'password',
              display: mask(s.qwen?.api_key_masked) },
        ]},
        { group: 'Interactive Brokers', rows: [
            { label: '启用', path: 'ib.enabled', type: 'bool',
              display: s.ib?.enabled ? '<span class="text-green">已启用</span>' : '<span class="text-muted">未启用</span>',
              valueBool: !!s.ib?.enabled },
            { label: 'Host', path: 'ib.host', type: 'text',
              display: s.ib?.host || '--' },
            { label: 'Port', path: 'ib.port', type: 'number',
              display: s.ib?.port || '--' },
            { label: 'Client ID', path: 'ib.client_id', type: 'number',
              display: s.ib?.client_id || '--' },
        ]},
        { group: 'Telegram Bot', rows: [
            { label: '启用', path: 'alerts.telegram.enabled', type: 'bool',
              display: s.telegram?.bot_token_masked ? '<span class="text-green">已配置</span>' : '<span class="text-muted">未配置</span>',
              valueBool: !!s.telegram?.bot_token_masked },
            { label: 'Bot Token', path: 'alerts.telegram.bot_token', type: 'password',
              display: mask(s.telegram?.bot_token_masked) },
            { label: 'Chat ID', path: 'alerts.telegram.chat_id', type: 'text',
              display: s.telegram?.chat_id || '--' },
        ]},
        { group: 'Email', rows: [
            { label: '启用', path: 'alerts.email.enabled', type: 'bool',
              display: s.email?.smtp_host ? '<span class="text-green">已配置</span>' : '<span class="text-muted">未配置</span>',
              valueBool: !!s.email?.smtp_host },
            { label: 'SMTP Host', path: 'alerts.email.smtp_host', type: 'text',
              display: s.email?.smtp_host || '--' },
            { label: 'SMTP Port', path: 'alerts.email.smtp_port', type: 'number',
              display: s.email?.smtp_port || '--' },
            { label: '用户名', path: 'alerts.email.username', type: 'text',
              display: s.email?.username || '--' },
            { label: '密码', path: 'alerts.email.password', type: 'password',
              display: mask(s.email?.password_masked) },
            { label: '收件人', path: 'alerts.email.to_address', type: 'text',
              display: s.email?.to_address || '--' },
        ]},
        { group: '运行时', rows: [
            { label: '预警检查间隔 (秒)', path: 'alerts.check_interval', type: 'number',
              display: (s.data_sources && s.alert_interval) || s.alert_interval || '--',
              valueFallback: s.alert_interval },
            { label: '持仓数据库', path: null, type: 'readonly',
              display: s.portfolio?.db_path || '--' },
        ]},
    ];
}

function renderSettingsConfig(s) {
    const box = document.getElementById('settings-config');
    if (!box || !s) return;
    // Sidebar LLM status indicator (HEAD feature — preserved here).
    const botStatusEl = document.getElementById('bot-status');
    if (botStatusEl) {
        const qwenOk = s.qwen && s.qwen.enabled;
        const geminiOk = s.gemini && s.gemini.api_key_masked && s.gemini.api_key_masked !== '';
        if (qwenOk) {
            botStatusEl.textContent = 'Qwen ' + ((s.qwen || {}).model || '') + ' · 在线';
        } else if (geminiOk) {
            botStatusEl.textContent = 'Gemini · 在线';
        } else {
            botStatusEl.textContent = 'LLM 未配置';
        }
    }
    _settingsData = s;
    _settingsWritable = new Set(s.writable_paths || []);
    const groups = _settingsFields(s);

    const html = groups.map(g => {
        const rowsHtml = g.rows.map(r => {
            // Hide rows that aren't writable in edit mode unless they're readonly-display.
            const writable = r.path && _settingsWritable.has(r.path);
            const editable = _settingsEditMode && writable;
            let valueHtml;
            if (editable) {
                if (r.type === 'bool') {
                    valueHtml = `<label class="form-check form-switch m-0">
                        <input class="form-check-input settings-input" type="checkbox"
                            data-path="${r.path}" ${r.valueBool ? 'checked' : ''}>
                    </label>`;
                } else {
                    const inputType = r.type === 'password' ? 'password' : (r.type === 'number' ? 'number' : 'text');
                    const placeholder = r.placeholder || '输入以覆盖当前值';
                    valueHtml = `<input type="${inputType}" class="form-control form-control-sm settings-input"
                        data-path="${r.path}" placeholder="${placeholder}" autocomplete="off">`;
                }
            } else {
                valueHtml = `<span class="value">${r.display}</span>`;
            }
            return `<div class="settings-row">
                <span class="label">${r.label}${writable && !_settingsEditMode ? '' : ''}</span>
                ${valueHtml}
            </div>`;
        }).join('');
        return `<div class="settings-group">
            <div class="settings-group-head">${g.group}</div>
            ${rowsHtml}
        </div>`;
    }).join('');
    box.innerHTML = html;
}

function toggleSettingsEdit(on) {
    _settingsEditMode = !!on;
    const editBtn = document.getElementById('btn-settings-edit');
    const saveBtn = document.getElementById('btn-settings-save');
    const cancelBtn = document.getElementById('btn-settings-cancel');
    if (editBtn) editBtn.classList.toggle('d-none', _settingsEditMode);
    if (saveBtn) saveBtn.classList.toggle('d-none', !_settingsEditMode);
    if (cancelBtn) cancelBtn.classList.toggle('d-none', !_settingsEditMode);
    if (_settingsData) renderSettingsConfig(_settingsData);
}

async function saveSettings() {
    // Collect non-empty inputs. Password fields that are left blank on
    // purpose don't get sent (so the existing key survives an accidental
    // edit-without-typing-anything save).
    const payload = {};
    document.querySelectorAll('.settings-input').forEach(el => {
        const path = el.dataset.path;
        if (!path) return;
        if (el.type === 'checkbox') {
            payload[path] = el.checked;
        } else {
            const v = el.value.trim();
            if (v !== '') payload[path] = v;
        }
    });
    if (Object.keys(payload).length === 0) {
        showToast('没有需要保存的改动', 'info');
        toggleSettingsEdit(false);
        return;
    }
    const data = await api('/api/settings', {
        method: 'POST',
        body: JSON.stringify(payload),
    });
    if (data && data.ok) {
        showToast(`已保存 ${data.count} 项设置`, 'success');
        toggleSettingsEdit(false);
        loadSettings();
    } else if (data && data.error) {
        showToast('保存失败: ' + data.error, 'error');
    }
}

function editSetting(el) {
    if (el.querySelector('input')) return;
    const key = el.dataset.key;
    const current = el.textContent.trim();
    const isMasked = current.includes('***') || current === '未配置';
    el.innerHTML = `<input type="text" class="form-control form-control-sm" style="max-width:300px;display:inline-block;" value="${isMasked ? '' : current}" placeholder="${isMasked ? '输入新值' : current}" data-key="${key}">`;
    const input = el.querySelector('input');
    input.focus();
    input.addEventListener('blur', () => commitSettingEdit(el, input));
    input.addEventListener('keydown', e => { if (e.key === 'Enter') input.blur(); if (e.key === 'Escape') { el.textContent = current; } });
}

function commitSettingEdit(el, input) {
    const key = input.dataset.key;
    const val = input.value.trim();
    if (val) {
        // Handle boolean/number conversions
        let parsed = val;
        if (val === '是' || val === 'true') parsed = true;
        else if (val === '否' || val === 'false') parsed = false;
        else if (/^\d+$/.test(val)) parsed = parseInt(val);
        settingsDirty[key] = parsed;
        el.innerHTML = `<span class="text-yellow">${val}</span> <small class="text-muted">(未保存)</small>`;
        document.getElementById('btn-save-settings').style.display = '';
    } else {
        el.textContent = input.placeholder || '--';
    }
}

async function saveSettings() {
    if (Object.keys(settingsDirty).length === 0) return;
    const btn = document.getElementById('btn-save-settings');
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 保存中...';
    const resp = await api('/api/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(settingsDirty) });
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-save"></i> 保存修改';
    if (resp && resp.ok) {
        showToast(`设置已保存 (${resp.updated.length} 项)`, 'success');
        settingsDirty = {};
        setTimeout(loadSettings, 500);
    } else {
        showToast('保存失败: ' + ((resp && resp.error) || '未知错误'), 'error');
    }
}

async function toggleScheduler(action) {
    const data = await api('/api/scheduler/' + action, { method: 'POST' });
    if (data && data.ok) {
        showToast(data.message || 'OK', 'success');
        setTimeout(loadSettings, 400);
    }
}

// ── WebSocket alert notifications ──────────────────────────────────────────

socket.on('alert_triggered', data => {
    showToast(`🚨 预警触发: ${data.ticker} ${data.condition} ${data.threshold}`, 'warning');
    alertBadgeCount++;
    updateAlertBadge();
});

function updateAlertBadge() {
    ['sidebar-alert-badge', 'mobile-alert-badge'].forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        if (alertBadgeCount > 0) {
            el.textContent = alertBadgeCount > 99 ? '99+' : alertBadgeCount;
            el.style.display = '';
        } else {
            el.style.display = 'none';
        }
    });
}

function clearAlertBadge() {
    alertBadgeCount = 0;
    updateAlertBadge();
}

// ── Backtest ───────────────────────────────────────────────────────────────

async function loadBacktestStrategies() {
    // Cache: only fetch once per session unless the dropdown is empty.
    const sel = document.getElementById('bt-strategy');
    if (!sel) return;
    if (_backtestStrategies) {
        _renderBacktestStrategyOptions();
        return;
    }
    const data = await api('/api/backtest/strategies');
    if (!data || !data.strategies) {
        sel.innerHTML = '<option value="">加载失败</option>';
        return;
    }
    _backtestStrategies = data.strategies;
    _renderBacktestStrategyOptions();
}

function _renderBacktestStrategyOptions() {
    const sel = document.getElementById('bt-strategy');
    if (!sel || !_backtestStrategies) return;
    sel.innerHTML = _backtestStrategies
        .map(s => `<option value="${s.id}">${s.label}</option>`)
        .join('');
    onBacktestStrategyChange();
}

function onBacktestStrategyChange() {
    const sel = document.getElementById('bt-strategy');
    const descEl = document.getElementById('bt-strategy-desc');
    const zone = document.getElementById('bt-params-zone');
    if (!sel || !_backtestStrategies) return;
    const strat = _backtestStrategies.find(s => s.id === sel.value);
    if (!strat) { zone.innerHTML = ''; descEl.textContent = ''; return; }
    descEl.textContent = strat.description || '';
    if (!strat.params || strat.params.length === 0) {
        zone.innerHTML = '<div class="col-12 text-muted" style="font-size:12px;">该策略无需额外参数</div>';
        return;
    }
    zone.innerHTML = strat.params.map(p => {
        const step = p.type === 'float' ? '0.1' : '1';
        return `<div class="col-6 col-md-3">
            <label class="form-label">${p.label}</label>
            <input type="number" class="form-control bt-param" data-name="${p.name}"
                value="${p.default}" min="${p.min ?? ''}" max="${p.max ?? ''}" step="${step}">
        </div>`;
    }).join('');
}

async function runBacktest() {
    const btn = document.getElementById('btn-run-backtest');
    const ticker = (document.getElementById('bt-ticker').value || '').trim().toUpperCase();
    const strategy = document.getElementById('bt-strategy').value;
    const period = document.getElementById('bt-period').value;
    const capital = parseFloat(document.getElementById('bt-capital').value || '100000');
    if (!ticker) { showToast('请输入股票代码', 'warning'); return; }
    if (!strategy) { showToast('请选择策略', 'warning'); return; }

    const params = {};
    document.querySelectorAll('#bt-params-zone .bt-param').forEach(inp => {
        const v = inp.value;
        if (v !== '' && !isNaN(Number(v))) params[inp.dataset.name] = Number(v);
    });

    btn.disabled = true;
    const originalHtml = btn.innerHTML;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> 运行中...';
    try {
        const data = await api('/api/backtest/run', {
            method: 'POST',
            body: JSON.stringify({
                ticker, strategy, period,
                initial_capital: capital,
                params,
            }),
        });
        if (!data || data.error) {
            showToast('回测失败: ' + (data && data.error ? data.error : '未知错误'), 'error');
            return;
        }
        renderBacktestResults(data);
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalHtml;
    }
}

function renderBacktestResults(r) {
    document.getElementById('bt-empty').classList.add('d-none');
    document.getElementById('bt-results').classList.remove('d-none');
    renderBacktestStats(r);
    renderBacktestEquity(r.equity_curve);
    renderBacktestTrades(r.trades);
}

function renderBacktestStats(r) {
    const row = document.getElementById('bt-stats-row');
    const totalCls = r.total_return_pct > 0 ? 'text-green' : (r.total_return_pct < 0 ? 'text-red' : '');
    const annCls = r.annualized_return_pct > 0 ? 'text-green' : (r.annualized_return_pct < 0 ? 'text-red' : '');
    const stats = [
        { label: '总收益率', value: fmtPct(r.total_return_pct), cls: totalCls },
        { label: '年化收益', value: fmtPct(r.annualized_return_pct), cls: annCls },
        { label: '最大回撤', value: '-' + fmt(r.max_drawdown_pct) + '%', cls: r.max_drawdown_pct > 0 ? 'text-red' : '' },
        { label: '胜率', value: fmt(r.win_rate * 100) + '%', cls: '' },
        { label: '交易次数', value: r.trade_count, cls: '' },
        { label: '最终净值', value: '$' + fmt(r.final_equity), cls: '' },
    ];
    row.innerHTML = stats.map(s => `
        <div class="col-6 col-md-2">
            <div class="stat-card">
                <div class="stat-label">${s.label}</div>
                <div class="stat-value ${s.cls}" style="font-size:20px;">${s.value}</div>
            </div>
        </div>
    `).join('');
    // Small caption below — initial capital / date range / strategy.
    const caption = `${r.ticker} · ${r.strategy} · ${r.start_date} ~ ${r.end_date} · 初始资金 $${fmt(r.initial_capital)}`;
    row.innerHTML += `<div class="col-12"><div class="text-muted" style="font-size:12px;">${caption}</div></div>`;
}

function renderBacktestEquity(curve) {
    const el = document.getElementById('bt-equity-chart');
    if (!el) return;
    if (!curve || curve.length === 0) {
        el.innerHTML = '<p class="text-muted text-center" style="padding-top:120px;">暂无数据</p>';
        return;
    }
    el.innerHTML = '';
    if (chartBacktest) { chartBacktest.dispose(); chartBacktest = null; }
    chartBacktest = echarts.init(el, 'dark');

    const dates = curve.map(p => p.date);
    const equity = curve.map(p => p.equity);
    const prices = curve.map(p => p.price);
    // Normalize price to a "buy-and-hold benchmark" starting at the same initial equity
    // so the two series share a comparable scale.
    const initEquity = equity[0] || 1;
    const firstPrice = prices[0] || 1;
    const benchmark = prices.map(p => initEquity * (p / firstPrice));

    chartBacktest.setOption({
        backgroundColor: 'transparent',
        animation: false,
        tooltip: {
            trigger: 'axis',
            backgroundColor: '#1c2128',
            borderColor: '#30363d',
            textStyle: { color: '#e6edf3' },
            valueFormatter: v => '$' + Number(v).toLocaleString('en-US', { maximumFractionDigits: 0 }),
        },
        legend: {
            data: ['策略净值', '买入并持有'],
            textStyle: { color: '#e6edf3' },
            top: 0,
        },
        grid: { left: 60, right: 20, top: 35, bottom: 40 },
        xAxis: {
            type: 'category', data: dates,
            axisLine: { lineStyle: { color: '#30363d' } },
            axisLabel: { color: '#8b949e' },
        },
        yAxis: {
            scale: true,
            axisLine: { lineStyle: { color: '#30363d' } },
            axisLabel: { color: '#8b949e', formatter: v => '$' + Math.round(v / 1000) + 'k' },
            splitLine: { lineStyle: { color: '#21262d' } },
        },
        series: [
            {
                name: '策略净值', type: 'line', data: equity, smooth: true, showSymbol: false,
                lineStyle: { color: '#58a6ff', width: 2 },
                areaStyle: { color: 'rgba(88, 166, 255, 0.15)' },
            },
            {
                name: '买入并持有', type: 'line', data: benchmark, smooth: true, showSymbol: false,
                lineStyle: { color: '#8b949e', width: 1, type: 'dashed' },
            },
        ],
    });
}

function renderBacktestTrades(trades) {
    const box = document.getElementById('bt-trades-body');
    if (!trades || trades.length === 0) {
        box.innerHTML = '<p class="text-muted text-center py-3 mb-0">该策略未产生交易</p>';
        return;
    }
    // Desktop: table layout
    const rows = trades.map((t, i) => {
        const pnlCls = t.pnl > 0 ? 'text-green' : (t.pnl < 0 ? 'text-red' : '');
        return `<tr>
            <td>${i + 1}</td>
            <td>${t.entry_date}</td>
            <td>$${fmt(t.entry_price, 2)}</td>
            <td>${t.exit_date}</td>
            <td>$${fmt(t.exit_price, 2)}</td>
            <td>${fmt(t.shares, 2)}</td>
            <td class="${pnlCls}">$${fmt(t.pnl, 2)}</td>
            <td class="${pnlCls}">${fmtPct(t.pnl_pct)}</td>
            <td class="text-muted" style="font-size:11px;">${t.reason || ''}</td>
        </tr>`;
    }).join('');
    // Mobile: card list layout
    const cards = trades.map((t, i) => {
        const pnlCls = t.pnl > 0 ? 'text-green' : (t.pnl < 0 ? 'text-red' : '');
        return `
        <div class="bt-trade-card">
            <div class="bt-trade-card-head">
                <span>#${i + 1} · ${fmt(t.shares, 2)} 股</span>
                <span class="${pnlCls}">${fmtPct(t.pnl_pct)}</span>
            </div>
            <div class="bt-trade-card-grid">
                <div><span class="label">买入</span> ${t.entry_date}</div>
                <div><span class="label">@</span> $${fmt(t.entry_price, 2)}</div>
                <div><span class="label">卖出</span> ${t.exit_date}</div>
                <div><span class="label">@</span> $${fmt(t.exit_price, 2)}</div>
                <div class="${pnlCls}" style="grid-column:1/-1;">
                    <span class="label">盈亏</span> $${fmt(t.pnl, 2)}
                </div>
                ${t.reason ? `<div class="text-muted" style="grid-column:1/-1;font-size:11px;">${t.reason}</div>` : ''}
            </div>
        </div>`;
    }).join('');
    box.innerHTML = `
        <div class="bt-trades-table-wrap">
            <div class="table-responsive">
                <table class="table table-sm mb-0 bt-trades-table">
                    <thead>
                        <tr>
                            <th>#</th><th>买入日期</th><th>买入价</th>
                            <th>卖出日期</th><th>卖出价</th><th>股数</th>
                            <th>盈亏</th><th>收益率</th><th>说明</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            </div>
        </div>
        <div class="bt-trades-cards p-2">${cards}</div>`;
}

// ── Window resize ──────────────────────────────────────────────────────────

window.addEventListener('resize', () => {
    if (chartPnl) chartPnl.resize();
    if (chartAllocation) chartAllocation.resize();
    if (chartKline) chartKline.resize();
    if (chartBacktest) chartBacktest.resize();
});

// ── Dashboard range switcher ──────────────────────────────────────────────

document.getElementById('dash-range-switcher')?.addEventListener('click', e => {
    const btn = e.target.closest('button[data-days]');
    if (!btn) return;
    document.querySelectorAll('#dash-range-switcher button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    dashPnlDays = parseInt(btn.dataset.days);
    api('/api/portfolio/history?days=' + dashPnlDays).then(history => {
        if (history) renderPnlChart(history);
    });
});

// ── Global Search ─────────────────────────────────────────────────────────

(function initGlobalSearch() {
    const input = document.getElementById('global-search');
    const dropdown = document.getElementById('search-dropdown');
    if (!input || !dropdown) return;

    let debounceTimer;
    input.addEventListener('input', () => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => doGlobalSearch(input.value.trim()), 300);
    });
    input.addEventListener('focus', () => { if (input.value.trim()) doGlobalSearch(input.value.trim()); });
    document.addEventListener('click', e => { if (!e.target.closest('.global-search-box')) dropdown.style.display = 'none'; });

    async function doGlobalSearch(q) {
        if (!q) { dropdown.style.display = 'none'; return; }
        const upper = q.toUpperCase();
        let html = '';

        // Search holdings
        const dash = await api('/api/dashboard');
        const holdings = (dash && dash.holdings || []).filter(h => h.ticker.includes(upper));
        if (holdings.length > 0) {
            html += '<div class="search-group">持仓</div>';
            holdings.forEach(h => {
                html += `<div class="search-item" onclick="switchTab('portfolio')">
                    <span><strong>${h.ticker}</strong> · ${fmt(h.shares, 0)} 股</span>
                    <span class="search-sub ${pnlClass(h.pnl)}">${fmtPct(h.pnl_pct)}</span>
                </div>`;
            });
        }

        // Search analysis history
        const history = await api('/api/history?ticker=' + encodeURIComponent(upper));
        if (history && history.length > 0) {
            html += '<div class="search-group">分析记录</div>';
            history.slice(0, 5).forEach(h => {
                html += `<div class="search-item" onclick="switchTab('history'); showHistoryDetail(${h.id})">
                    <span><strong>${h.ticker}</strong> · ${h.date}</span>
                    <span class="search-sub">${h.signal}</span>
                </div>`;
            });
        }

        // Search alerts
        const alerts = await api('/api/alerts');
        const matched = (alerts || []).filter(a => a.ticker.includes(upper));
        if (matched.length > 0) {
            html += '<div class="search-group">预警</div>';
            matched.forEach(a => {
                html += `<div class="search-item" onclick="switchTab('alerts')">
                    <span><strong>${a.ticker}</strong> · ${a.condition}</span>
                    <span class="search-sub">${a.threshold}</span>
                </div>`;
            });
        }

        // Quick action: analyze this ticker
        html += '<div class="search-group">快捷操作</div>';
        html += `<div class="search-item" onclick="document.getElementById('analyze-ticker').value='${upper}'; switchTab('analysis');">
            <span><i class="fas fa-brain"></i> AI 分析 <strong>${upper}</strong></span>
            <span class="search-sub">→</span>
        </div>`;

        dropdown.innerHTML = html;
        dropdown.style.display = html ? 'block' : 'none';
    }
})();

// ── PWA Service Worker ────────────────────────────────────────────────────

if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/static/sw.js').catch(() => {});
}

// ── Init ───────────────────────────────────────────────────────────────────

loadDashboard();

// ══════════════════════════════════════════════════════════════════════════
// Task Center — async task records
// ══════════════════════════════════════════════════════════════════════════

const TASK_PAGE_SIZE = 30;
let _taskFilter = '';
let _taskOffset = 0;
let _currentDetailTaskId = null;
let _pendingTaskCount = 0;

const TASK_TYPE_LABELS = {
    analysis: { icon: 'fa-brain', label: 'AI 分析', cls: 'analysis' },
    screen: { icon: 'fa-filter', label: '智能选股', cls: 'screen' },
    backtest: { icon: 'fa-flask', label: '策略回测', cls: 'backtest' },
    report: { icon: 'fa-file-lines', label: '报告生成', cls: 'report' },
    echo: { icon: 'fa-bolt', label: '测试', cls: 'echo' },
    qwen_fundamentals: { icon: 'fa-chart-column', label: '基本面', cls: 'analysis' },
    qwen_news: { icon: 'fa-newspaper', label: '新闻', cls: 'analysis' },
};

const TASK_STATUS_LABELS = {
    pending: '等待中',
    running: '运行中',
    success: '成功',
    failed: '失败',
    cancelled: '已取消',
};

function taskTypeInfo(type) {
    return TASK_TYPE_LABELS[type] || { icon: 'fa-cube', label: type, cls: 'generic' };
}

async function loadTasks() {
    _taskOffset = 0;
    await fetchAndRenderTasks(true);
}

async function loadMoreTasks() {
    _taskOffset += TASK_PAGE_SIZE;
    await fetchAndRenderTasks(false);
}

async function fetchAndRenderTasks(reset) {
    const q = new URLSearchParams({
        limit: String(TASK_PAGE_SIZE),
        offset: String(_taskOffset),
    });
    if (_taskFilter) q.set('status', _taskFilter);
    const data = await api(`/api/tasks?${q.toString()}`);
    const items = (data && data.items) || [];
    const listEl = document.getElementById('tasks-list');
    const emptyEl = document.getElementById('tasks-empty');
    const loadMoreWrap = document.getElementById('tasks-load-more-wrap');

    if (reset) listEl.innerHTML = '';

    if (items.length === 0 && _taskOffset === 0) {
        emptyEl.style.display = 'block';
        loadMoreWrap.style.display = 'none';
        return;
    }
    emptyEl.style.display = 'none';

    items.forEach(t => listEl.appendChild(renderTaskCard(t)));
    loadMoreWrap.style.display = items.length >= TASK_PAGE_SIZE ? 'block' : 'none';
}

function renderTaskCard(task) {
    const info = taskTypeInfo(task.type);
    const wrap = document.createElement('div');
    wrap.className = 'task-card';
    wrap.dataset.taskId = task.id;
    wrap.dataset.status = task.status;
    wrap.onclick = () => showTaskDetail(task.id);

    const created = task.created_at || '';
    const duration = task.duration_ms != null
        ? ' · 耗时 ' + formatDuration(task.duration_ms) : '';

    const progressBar = (task.status === 'running')
        ? `<div class="task-progress-bar"><div class="task-progress-fill" style="width:${task.progress || 0}%"></div></div>
           ${task.progress_step ? `<div class="task-progress-step">${escapeHtml(task.progress_step)}</div>` : ''}`
        : (task.status === 'success' || task.status === 'failed')
            ? `<div class="task-progress-bar"><div class="task-progress-fill ${task.status}" style="width:100%"></div></div>`
            : '';

    const errorLine = (task.status === 'failed' && task.error_message)
        ? `<div class="task-error-message"><i class="fas fa-triangle-exclamation"></i> ${escapeHtml(task.error_message)}</div>`
        : '';

    wrap.innerHTML = `
        <div class="task-icon ${info.cls}"><i class="fas ${info.icon}"></i></div>
        <div class="task-body">
            <div class="task-title">${escapeHtml(task.title || info.label)}</div>
            <div class="task-meta">
                <span>${escapeHtml(created)}</span>
                ${duration ? `<span>${duration}</span>` : ''}
                ${task.retry_of ? `<span><i class="fas fa-redo" style="font-size:10px;"></i> 重试</span>` : ''}
            </div>
            ${progressBar}
            ${errorLine}
        </div>
        <span class="task-status ${task.status}">${TASK_STATUS_LABELS[task.status] || task.status}</span>
    `;
    return wrap;
}

function updateTaskCardInPlace(task) {
    const existing = document.querySelector(`.task-card[data-task-id="${task.id}"]`);
    if (!existing) return false;
    const replaced = renderTaskCard(task);
    existing.replaceWith(replaced);
    return true;
}

function prependTaskCard(task) {
    const listEl = document.getElementById('tasks-list');
    const emptyEl = document.getElementById('tasks-empty');
    if (!listEl) return;
    emptyEl.style.display = 'none';
    listEl.insertBefore(renderTaskCard(task), listEl.firstChild);
}

function formatDuration(ms) {
    if (ms == null) return '';
    if (ms < 1000) return ms + 'ms';
    const s = ms / 1000;
    if (s < 60) return s.toFixed(1) + 's';
    return Math.floor(s / 60) + 'm ' + Math.round(s % 60) + 's';
}

function escapeHtml(s) {
    if (s == null) return '';
    return String(s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// Filter buttons
document.addEventListener('click', e => {
    const btn = e.target.closest('.task-filter-btn');
    if (!btn) return;
    document.querySelectorAll('.task-filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    _taskFilter = btn.dataset.status || '';
    loadTasks();
});

// ── Task detail modal ──────────────────────────────────────────────────────

async function showTaskDetail(taskId) {
    _currentDetailTaskId = taskId;
    const task = await api(`/api/tasks/${taskId}`);
    if (!task || task.error) {
        showToast('任务不存在', 'error');
        return;
    }

    const body = document.getElementById('taskDetailBody');
    const titleEl = document.getElementById('taskDetailTitle');
    const info = taskTypeInfo(task.type);
    titleEl.innerHTML = `<i class="fas ${info.icon}"></i> ${escapeHtml(task.title)}`;

    let params = {};
    try { params = task.params_json ? JSON.parse(task.params_json) : {}; }
    catch (_) { params = { _raw: task.params_json }; }

    const sections = [];

    // Status + timing
    sections.push(`
        <div class="task-detail-section">
            <div class="task-detail-section-title">状态</div>
            <div><span class="task-status ${task.status}">${TASK_STATUS_LABELS[task.status] || task.status}</span></div>
            <div class="task-meta" style="margin-top:8px;">
                <span>创建：${escapeHtml(task.created_at || '')}</span>
                ${task.started_at ? `<span>开始：${escapeHtml(task.started_at)}</span>` : ''}
                ${task.completed_at ? `<span>完成：${escapeHtml(task.completed_at)}</span>` : ''}
                ${task.duration_ms != null ? `<span>耗时：${formatDuration(task.duration_ms)}</span>` : ''}
            </div>
            ${task.progress_step ? `<div class="task-progress-step" style="margin-top:6px;">${escapeHtml(task.progress_step)}</div>` : ''}
            ${task.status === 'running' ? `<div class="task-progress-bar" style="margin-top:8px;"><div class="task-progress-fill" style="width:${task.progress || 0}%"></div></div>` : ''}
        </div>`);

    // Params
    sections.push(`
        <div class="task-detail-section">
            <div class="task-detail-section-title">参数</div>
            <pre class="task-detail-pre">${escapeHtml(JSON.stringify(params, null, 2))}</pre>
        </div>`);

    // Error
    if (task.status === 'failed') {
        const traceId = 'task-trace-' + task.id;
        sections.push(`
            <div class="task-detail-section">
                <div class="task-detail-section-title" style="color:var(--accent-red);">错误</div>
                <div>${escapeHtml(task.error_message || '未知错误')}</div>
                ${task.error_trace ? `
                    <button class="task-trace-toggle mt-2" onclick="document.getElementById('${traceId}').style.display=(document.getElementById('${traceId}').style.display==='none'?'block':'none')">显示/隐藏 调用栈</button>
                    <pre id="${traceId}" class="task-detail-pre" style="display:none;margin-top:6px;">${escapeHtml(task.error_trace)}</pre>
                ` : ''}
            </div>`);
    }

    // Retry lineage
    if (task.retry_of) {
        sections.push(`
            <div class="task-detail-section">
                <div class="task-detail-section-title">重试来源</div>
                <div><a href="#" onclick="event.preventDefault(); showTaskDetail('${task.retry_of}')" style="color:var(--accent-blue);">查看原任务</a></div>
            </div>`);
    }

    body.innerHTML = sections.join('');

    // Footer buttons
    const retryBtn = document.getElementById('taskDetailRetryBtn');
    const cancelBtn = document.getElementById('taskDetailCancelBtn');
    const viewResultBtn = document.getElementById('taskDetailViewResultBtn');
    const deleteBtn = document.getElementById('taskDetailDeleteBtn');

    retryBtn.style.display = (task.status === 'failed') ? '' : 'none';
    cancelBtn.style.display = (task.status === 'pending' || task.status === 'running') ? '' : 'none';
    viewResultBtn.style.display = (task.status === 'success' && task.result_ref) ? '' : 'none';

    retryBtn.onclick = () => retryTask(task.id);
    cancelBtn.onclick = () => cancelTask(task.id);
    viewResultBtn.onclick = () => openTaskResult(task);
    deleteBtn.onclick = () => deleteTask(task.id);

    const modal = bootstrap.Modal.getOrCreateInstance(document.getElementById('taskDetailModal'));
    modal.show();
}

async function retryTask(taskId) {
    const newTask = await api(`/api/tasks/${taskId}/retry`, { method: 'POST' });
    if (newTask && !newTask.error) {
        showToast('已创建重试任务', 'success');
        bootstrap.Modal.getInstance(document.getElementById('taskDetailModal')).hide();
        loadTasks();
    } else {
        showToast(newTask?.error || '重试失败', 'error');
    }
}

async function cancelTask(taskId) {
    const resp = await api(`/api/tasks/${taskId}/cancel`, { method: 'POST' });
    if (resp && resp.ok) {
        showToast('已请求取消', 'info');
        loadTasks();
    } else {
        showToast(resp?.error || '取消失败', 'error');
    }
}

async function deleteTask(taskId) {
    if (!confirm('确认删除此任务记录？（结果数据不会被删除）')) return;
    const resp = await api(`/api/tasks/${taskId}`, { method: 'DELETE' });
    if (resp && resp.ok) {
        showToast('已删除', 'info');
        bootstrap.Modal.getInstance(document.getElementById('taskDetailModal')).hide();
        loadTasks();
    } else {
        showToast(resp?.error || '删除失败', 'error');
    }
}

function openTaskResult(task) {
    // Route to the matching business page based on task type.
    bootstrap.Modal.getInstance(document.getElementById('taskDetailModal')).hide();
    const ref = task.result_ref || '';
    const typeMap = {
        'analysis':         () => {
            if (ref.startsWith('analysis_history:')) {
                const id = ref.split(':')[1];
                switchTab('history');
                setTimeout(() => { if (typeof showAnalysisDetail === 'function') showAnalysisDetail(id); }, 300);
            } else {
                switchTab('history');
            }
        },
        'batch_analysis':   () => { switchTab('history'); },
        'screen':           () => { switchTab('screener'); },
        'screen_v2':        () => { switchTab('screener'); },
        'backtest':         () => { switchTab('backtest'); },
        'report':           () => { switchTab('reports'); },
        'paper_trade':      () => { switchTab('paper'); },
        'paper_backfill':   () => { switchTab('paper'); },
        'qwen_fundamentals':() => {
            // 基本面查询结果 — 跳到分析页展示
            const ticker = task.params?.ticker;
            if (ticker) {
                switchTab('analysis');
                document.getElementById('analyze-ticker').value = ticker;
            } else { switchTab('history'); }
        },
        'qwen_news':        () => { switchTab('history'); },
        'agent_score_update':() => { switchTab('settings'); showToast('Agent 评分已更新', 'success'); },
        'meta_evolution':   () => { switchTab('settings'); showToast('Meta Agent 进化结果已更新', 'success'); },
    };
    const handler = typeMap[task.type];
    if (handler) {
        handler();
    } else {
        showToast('该任务无独立结果页', 'info');
    }
}

// ── Task badge (pending count) ────────────────────────────────────────────

function incrementTaskBadge() {
    _pendingTaskCount += 1;
    renderTaskBadge();
}

function clearTaskBadge() {
    _pendingTaskCount = 0;
    renderTaskBadge();
}

function renderTaskBadge() {
    const sb = document.getElementById('sidebar-tasks-badge');
    const mb = document.getElementById('mobile-tasks-badge');
    const display = _pendingTaskCount > 0 ? 'inline-block' : 'none';
    const text = _pendingTaskCount > 99 ? '99+' : String(_pendingTaskCount);
    if (sb) { sb.style.display = display; sb.textContent = text; }
    if (mb) { mb.style.display = display; mb.textContent = text; }
}

// ── WebSocket event handlers ──────────────────────────────────────────────

if (typeof socket !== 'undefined' && socket) {
    socket.on('task_created', task => {
        // Only prepend if we're on the tasks page to avoid ghost cards
        if (document.getElementById('page-tasks')?.classList.contains('active')) {
            if (!_taskFilter || _taskFilter === task.status) prependTaskCard(task);
        }
        if (!document.getElementById('page-tasks')?.classList.contains('active')) {
            incrementTaskBadge();
        }
    });

    socket.on('task_started', payload => {
        fetchAndUpdateTask(payload.id);
    });

    socket.on('task_progress', payload => {
        // Patch progress bar in place without full re-render.
        const el = document.querySelector(`.task-card[data-task-id="${payload.id}"]`);
        if (el) {
            const fill = el.querySelector('.task-progress-fill');
            const step = el.querySelector('.task-progress-step');
            if (fill) fill.style.width = (payload.progress || 0) + '%';
            if (step && payload.step) step.textContent = payload.step;
        }
    });

    socket.on('task_completed', payload => {
        fetchAndUpdateTask(payload.id);
        // Bridge: route specific completed tasks to their business pages
        if (_activeAnalysisTasks.has(payload.id)) {
            const ticker = _activeAnalysisTasks.get(payload.id);
            _activeAnalysisTasks.delete(payload.id);
            handleAnalysisTaskCompleted(payload.id, ticker);
        }
        if (_activeScreenTasks.has(payload.id)) {
            _activeScreenTasks.delete(payload.id);
            handleScreenTaskCompleted(payload.id);
        }
        if (_activeBacktestTasks.has(payload.id)) {
            const ticker = _activeBacktestTasks.get(payload.id);
            _activeBacktestTasks.delete(payload.id);
            handleBacktestTaskCompleted(payload.id, ticker);
        }
    });

    socket.on('task_failed', payload => {
        fetchAndUpdateTask(payload.id);
        if (!document.getElementById('page-tasks')?.classList.contains('active')) {
            showToast('任务失败：' + (payload.error_message || '未知错误'), 'error');
        }
        // Reset analysis/screen/backtest UI if the failure belongs to one we kicked off
        if (_activeAnalysisTasks.has(payload.id)) {
            _activeAnalysisTasks.delete(payload.id);
            document.getElementById('analysis-loading').style.display = 'none';
            document.getElementById('btn-analyze').disabled = false;
        }
        if (_activeScreenTasks.has(payload.id)) {
            _activeScreenTasks.delete(payload.id);
            document.getElementById('screen-loading').style.display = 'none';
            document.getElementById('btn-screen').disabled = false;
        }
        if (_activeBacktestTasks.has(payload.id)) {
            _activeBacktestTasks.delete(payload.id);
            const btLoading = document.getElementById('bt-loading');
            const btBtn = document.getElementById('btn-backtest');
            if (btLoading) btLoading.style.display = 'none';
            if (btBtn) btBtn.disabled = false;
        }
    });

    socket.on('task_cancelled', payload => {
        fetchAndUpdateTask(payload.id);
        if (_activeAnalysisTasks.has(payload.id)) {
            _activeAnalysisTasks.delete(payload.id);
            document.getElementById('analysis-loading').style.display = 'none';
            document.getElementById('btn-analyze').disabled = false;
        }
        if (_activeScreenTasks.has(payload.id)) {
            _activeScreenTasks.delete(payload.id);
            document.getElementById('screen-loading').style.display = 'none';
            document.getElementById('btn-screen').disabled = false;
        }
        if (_activeBacktestTasks.has(payload.id)) {
            _activeBacktestTasks.delete(payload.id);
            const btLoading = document.getElementById('bt-loading');
            const btBtn = document.getElementById('btn-backtest');
            if (btLoading) btLoading.style.display = 'none';
            if (btBtn) btBtn.disabled = false;
        }
    });
}

async function fetchAndUpdateTask(taskId) {
    try {
        const fresh = await api(`/api/tasks/${taskId}`);
        if (fresh && !fresh.error) updateTaskCardInPlace(fresh);
    } catch (_) { /* ignore */ }
}

// ═══════════════════════════════════════════════════════════════════════════
// Paper Trade
// ═══════════════════════════════════════════════════════════════════════════

let _paperCurrentSessionId = null;
let _chartPaperEquity = null;
const _activePaperTasks = new Set();

function _fmtPct(v, digits = 2) {
    if (v === null || v === undefined) return '—';
    const n = Number(v);
    if (!isFinite(n)) return '—';
    const cls = n > 0 ? 'text-success' : n < 0 ? 'text-danger' : '';
    return `<span class="${cls}">${n >= 0 ? '+' : ''}${n.toFixed(digits)}%</span>`;
}

function _fmtNum(v, digits = 2) {
    if (v === null || v === undefined || isNaN(Number(v))) return '—';
    return Number(v).toFixed(digits);
}

async function loadPaperSessions() {
    const listEl = document.getElementById('paper-sessions-list');
    if (!listEl) return;
    listEl.innerHTML = '<div class="text-muted text-center py-3"><div class="spinner-border spinner-border-sm"></div> 加载中...</div>';
    const sessions = await api('/api/paper/sessions');
    if (!Array.isArray(sessions) || sessions.length === 0) {
        listEl.innerHTML = '<p class="text-muted text-center py-3">暂无会话。点击"新建会话"开始。</p>';
        return;
    }
    const rows = sessions.map(s => {
        const metrics = s.metrics || {};
        const ret = metrics.total_return_pct;
        const statusBadge = {
            pending: '<span class="badge bg-secondary">待运行</span>',
            running: '<span class="badge bg-info">运行中</span>',
            done: '<span class="badge bg-success">已完成</span>',
            failed: '<span class="badge bg-danger">失败</span>',
        }[s.status] || `<span class="badge bg-secondary">${s.status}</span>`;
        const sysTag = s.is_system ? '<span class="badge bg-warning text-dark ms-1">系统</span>' : '';
        const autoTag = s.auto_track ? '<span class="badge bg-primary ms-1">自动追踪</span>' : '';
        const delBtn = s.is_system
            ? ''
            : `<button class="btn btn-sm btn-outline-danger" onclick="event.stopPropagation();deletePaperSession(${s.id})"><i class="fas fa-trash"></i></button>`;
        return `
            <div class="paper-session-row" onclick="openPaperDetail(${s.id})">
                <div class="d-flex justify-content-between align-items-start flex-wrap gap-2">
                    <div>
                        <div><strong>${escapeHtml(s.name)}</strong> ${sysTag}${autoTag}</div>
                        <div class="text-muted small">
                            ${s.mode === 'replay' ? '回放' : '实时'} ·
                            ${s.start_date || '—'} ~ ${s.end_date || '进行中'} ·
                            初始 $${_fmtNum(s.start_capital, 0)}
                        </div>
                    </div>
                    <div class="text-end">
                        <div class="h6 mb-0">${ret !== undefined ? _fmtPct(ret) : '—'}</div>
                        <div>${statusBadge}</div>
                    </div>
                    <div class="d-flex gap-1 align-items-start">
                        <button class="btn btn-sm btn-outline-primary" onclick="event.stopPropagation();openPaperDetail(${s.id})">
                            <i class="fas fa-eye"></i>
                        </button>
                        ${delBtn}
                    </div>
                </div>
            </div>
        `;
    }).join('');
    listEl.innerHTML = rows;
}

function showPaperCreateForm() {
    document.getElementById('paper-create-card').style.display = 'block';
    document.getElementById('paper-list-card').style.display = 'none';
    // Default dates: past 3 months → today
    const today = new Date();
    const past = new Date();
    past.setMonth(past.getMonth() - 3);
    const iso = (d) => d.toISOString().split('T')[0];
    const startEl = document.getElementById('pt-start');
    const endEl = document.getElementById('pt-end');
    if (startEl && !startEl.value) startEl.value = iso(past);
    if (endEl && !endEl.value) endEl.value = iso(today);
}

function hidePaperCreateForm() {
    document.getElementById('paper-create-card').style.display = 'none';
    document.getElementById('paper-list-card').style.display = 'block';
}

async function createPaperSession() {
    const name = document.getElementById('pt-name').value.trim();
    const mode = document.getElementById('pt-mode').value;
    const capital = parseFloat(document.getElementById('pt-capital').value) || 100000;
    const start = document.getElementById('pt-start').value;
    const end = document.getElementById('pt-end').value;
    if (!start) { showToast('请选择开始日期', 'warning'); return; }
    if (mode === 'replay' && !end) { showToast('回放模式需要结束日期', 'warning'); return; }

    const tickersRaw = document.getElementById('pt-tickers').value.trim();
    const tickers = tickersRaw ? tickersRaw.split(',').map(s => s.trim().toUpperCase()).filter(Boolean) : [];
    const signals = Array.from(document.querySelectorAll('.pt-signal:checked')).map(e => e.value);

    const positionPct = parseFloat(document.getElementById('pt-position-pct').value) || 10;
    const stopPct = parseFloat(document.getElementById('pt-stop').value) || 8;
    const targetPct = parseFloat(document.getElementById('pt-target').value) || 20;
    const maxDays = parseInt(document.getElementById('pt-maxdays').value) || 60;
    const benchmark = document.getElementById('pt-benchmark').value.trim() || 'SPY';
    const autoTrack = document.getElementById('pt-auto-track').checked;

    const payload = {
        name: name || `会话 ${new Date().toLocaleString('zh-CN')}`,
        mode,
        start_capital: capital,
        start_date: start,
        end_date: end || null,
        auto_track: autoTrack,
        benchmark,
        filters: { tickers, signals },
        sizing: { type: 'advice', default_pct: positionPct / 100 },
        exit_rules: {
            stop_loss_pct: stopPct / 100,
            take_profit_pct: targetPct / 100,
            max_hold_days: maxDays,
            reverse_exit: true,
        },
        cost: { commission_bps: 5, slippage_bps: 10 },
    };

    const res = await api('/api/paper/sessions', {
        method: 'POST', body: JSON.stringify(payload),
    });
    if (!res || !res.ok) {
        showToast('创建失败: ' + (res?.error || 'unknown'), 'error');
        return;
    }
    showToast('会话已创建，提交运行中...', 'success');
    const sid = res.session_id;
    // auto-run
    const runRes = await api(`/api/paper/sessions/${sid}/run`, { method: 'POST' });
    if (runRes?.ok) {
        _activePaperTasks.add(runRes.task_id);
        showToast('运行任务已提交 (task: ' + runRes.task_id.slice(0, 8) + ')', 'info');
    }
    hidePaperCreateForm();
    openPaperDetail(sid);
}

async function deletePaperSession(sessionId) {
    if (!confirm('确定删除此会话？相关交易和追踪记录将被清除。')) return;
    const res = await api(`/api/paper/sessions/${sessionId}`, { method: 'DELETE' });
    if (res?.ok) {
        showToast('已删除', 'success');
        loadPaperSessions();
    } else {
        showToast('删除失败: ' + (res?.error || 'unknown'), 'error');
    }
}

async function openPaperDetail(sessionId) {
    _paperCurrentSessionId = sessionId;
    document.getElementById('paper-list-card').style.display = 'none';
    document.getElementById('paper-create-card').style.display = 'none';
    document.getElementById('paper-detail').style.display = 'block';
    await refreshPaperDetail();
}

function hidePaperDetail() {
    document.getElementById('paper-detail').style.display = 'none';
    document.getElementById('paper-list-card').style.display = 'block';
    _paperCurrentSessionId = null;
    loadPaperSessions();
}

async function runPaperSession() {
    if (!_paperCurrentSessionId) return;
    const btn = document.getElementById('pt-run-btn');
    if (btn) btn.disabled = true;
    const res = await api(`/api/paper/sessions/${_paperCurrentSessionId}/run`, { method: 'POST' });
    if (res?.ok) {
        _activePaperTasks.add(res.task_id);
        showToast('运行任务已提交', 'success');
    } else {
        showToast('提交失败: ' + (res?.error || 'unknown'), 'error');
        if (btn) btn.disabled = false;
    }
}

async function refreshPaperDetail() {
    if (!_paperCurrentSessionId) return;
    const sid = _paperCurrentSessionId;
    const [sess, equity, trades, tracked] = await Promise.all([
        api(`/api/paper/sessions/${sid}`),
        api(`/api/paper/sessions/${sid}/equity`),
        api(`/api/paper/sessions/${sid}/trades`),
        api(`/api/paper/sessions/${sid}/tracked`),
    ]);
    if (!sess) return;

    document.getElementById('pt-detail-name').textContent = sess.name;
    const meta = document.getElementById('pt-detail-meta');
    meta.innerHTML = `
        状态 <strong>${sess.status}</strong> ·
        模式 ${sess.mode === 'replay' ? '回放' : '实时'} ·
        ${sess.start_date || '—'} ~ ${sess.end_date || '进行中'} ·
        初始 $${_fmtNum(sess.start_capital, 0)}
        ${sess.is_system ? ' · <span class="badge bg-warning text-dark">系统默认</span>' : ''}
        ${sess.auto_track ? ' · <span class="badge bg-primary">自动追踪</span>' : ''}
    `;

    renderPaperMetrics(sess.metrics || {});
    renderPaperEquity(equity || []);
    renderPaperTrades(trades || []);
    renderPaperTracked(tracked || []);
    await loadPaperBreakdown(sid);
}

function renderPaperMetrics(m) {
    const box = document.getElementById('pt-metrics');
    if (!m || Object.keys(m).length === 0) {
        box.innerHTML = '<div class="col-12"><p class="text-muted mb-0">尚未运行。点击右上方"运行"开始回放。</p></div>';
        return;
    }
    const cards = [
        ['总收益率', _fmtPct(m.total_return_pct), 'fa-chart-line'],
        ['年化收益', _fmtPct(m.annualized_return_pct), 'fa-rocket'],
        ['胜率', (m.win_rate_pct ?? 0).toFixed(1) + '%', 'fa-trophy'],
        ['交易数', m.num_trades ?? 0, 'fa-exchange-alt'],
        ['最大回撤', _fmtPct(m.max_drawdown_pct), 'fa-arrow-trend-down'],
        ['夏普', _fmtNum(m.sharpe_ratio), 'fa-wave-square'],
        ['基准', m.benchmark_return_pct != null ? _fmtPct(m.benchmark_return_pct) : '—', 'fa-flag'],
        ['终值', '$' + _fmtNum(m.final_value, 0), 'fa-sack-dollar'],
    ];
    box.innerHTML = cards.map(([label, val, ico]) => `
        <div class="col-6 col-md-3">
            <div class="metric-card small">
                <div class="metric-label"><i class="fas ${ico}"></i> ${label}</div>
                <div class="metric-value">${val}</div>
            </div>
        </div>
    `).join('');
}

function renderPaperEquity(equity) {
    const el = document.getElementById('chart-paper-equity');
    if (!el) return;
    if (!_chartPaperEquity) _chartPaperEquity = echarts.init(el);
    if (!equity.length) {
        _chartPaperEquity.setOption({
            title: { text: '暂无权益数据', left: 'center', top: 'middle',
                    textStyle: { color: '#999', fontSize: 13 } },
        }, true);
        return;
    }
    const dates = equity.map(e => e.date);
    const values = equity.map(e => e.total_value);
    const bench = equity.map(e => e.benchmark_value);
    const hasBench = bench.some(v => v != null);
    const series = [{
        name: '策略',
        type: 'line', data: values, smooth: true,
        itemStyle: { color: '#3882ff' },
        areaStyle: { opacity: 0.15 },
    }];
    if (hasBench) series.push({
        name: '基准',
        type: 'line', data: bench, smooth: true,
        itemStyle: { color: '#888' },
        lineStyle: { type: 'dashed' },
    });
    _chartPaperEquity.setOption({
        tooltip: { trigger: 'axis' },
        legend: { top: 4 },
        grid: { left: 50, right: 20, top: 40, bottom: 30 },
        xAxis: { type: 'category', data: dates },
        yAxis: { type: 'value', scale: true },
        series,
    }, true);
}

function renderPaperTrades(trades) {
    const tbody = document.querySelector('#pt-trades-table tbody');
    const cards = document.getElementById('pt-trades-cards');
    if (!trades.length) {
        if (tbody) tbody.innerHTML = '<tr><td colspan="10" class="text-muted text-center">暂无交易</td></tr>';
        if (cards) cards.innerHTML = '<p class="text-muted text-center py-2">暂无交易</p>';
        return;
    }
    const rowHtml = t => `
        <tr>
            <td><strong>${escapeHtml(t.ticker)}</strong></td>
            <td><span class="badge bg-${t.signal === 'BUY' || t.signal === 'OVERWEIGHT' ? 'success' : 'danger'}">${t.signal || '—'}</span></td>
            <td>${t.entry_date || '—'}</td>
            <td>${_fmtNum(t.entry_price)}</td>
            <td>${t.exit_date || '持仓中'}</td>
            <td>${t.exit_price != null ? _fmtNum(t.exit_price) : '—'}</td>
            <td>${t.pnl != null ? _fmtNum(t.pnl) : '—'}</td>
            <td>${t.pnl_pct != null ? _fmtPct(t.pnl_pct) : '—'}</td>
            <td>${t.hold_days ?? '—'}</td>
            <td class="text-muted small">${t.exit_reason || ''}</td>
        </tr>
    `;
    if (tbody) tbody.innerHTML = trades.map(rowHtml).join('');

    const cardHtml = t => `
        <div class="trade-card">
            <div class="d-flex justify-content-between">
                <strong>${escapeHtml(t.ticker)}</strong>
                <span>${t.pnl_pct != null ? _fmtPct(t.pnl_pct) : '持仓中'}</span>
            </div>
            <div class="text-muted small">
                ${t.entry_date} @ ${_fmtNum(t.entry_price)} →
                ${t.exit_date || '—'} @ ${t.exit_price != null ? _fmtNum(t.exit_price) : '—'}
                · ${t.hold_days ?? 0}天
                ${t.exit_reason ? '· ' + t.exit_reason : ''}
            </div>
        </div>
    `;
    if (cards) cards.innerHTML = trades.map(cardHtml).join('');
}

async function loadPaperBreakdown(sid) {
    const trades = await api(`/api/paper/sessions/${sid}/trades`);
    const tbody = document.querySelector('#pt-breakdown-table tbody');
    if (!tbody) return;
    // Client-side aggregate (server has metrics.ticker_breakdown but trades API already has all)
    const closed = (trades || []).filter(t => t.exit_date);
    const by = {};
    for (const t of closed) {
        const k = t.ticker;
        if (!by[k]) by[k] = { ticker: k, trades: 0, wins: 0, pnl: 0, pct: 0 };
        by[k].trades += 1;
        if ((t.pnl || 0) > 0) by[k].wins += 1;
        by[k].pnl += t.pnl || 0;
        by[k].pct += t.pnl_pct || 0;
    }
    const rows = Object.values(by).sort((a, b) => b.pnl - a.pnl);
    if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="5" class="text-muted text-center">暂无数据</td></tr>';
        return;
    }
    tbody.innerHTML = rows.map(r => `
        <tr>
            <td><strong>${escapeHtml(r.ticker)}</strong></td>
            <td>${r.trades}</td>
            <td>${(r.wins / r.trades * 100).toFixed(1)}%</td>
            <td>${_fmtPct((r.pct / r.trades))}</td>
            <td>${_fmtPct((r.pnl / 1))}</td>
        </tr>
    `).join('');
}

function renderPaperTracked(rows) {
    const tbody = document.querySelector('#pt-tracked-table tbody');
    if (!tbody) return;
    if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-muted text-center">暂无追踪记录</td></tr>';
        return;
    }
    const statusBadge = (s) => ({
        pending: '<span class="badge bg-secondary">待执行</span>',
        executed: '<span class="badge bg-success">已执行</span>',
        skipped: '<span class="badge bg-warning text-dark">跳过</span>',
        no_action: '<span class="badge bg-info">无动作</span>',
    }[s] || `<span class="badge bg-secondary">${s}</span>`);
    tbody.innerHTML = rows.map(r => `
        <tr>
            <td>${r.analysis_date || '—'}</td>
            <td><strong>${escapeHtml(r.ticker)}</strong></td>
            <td>${r.signal || '—'}</td>
            <td>${statusBadge(r.status)}</td>
            <td>${r.tracked_by === 'auto' ? '自动' : '手动'}</td>
            <td class="text-muted small">${escapeHtml(r.skip_reason || r.notes || '')}</td>
        </tr>
    `).join('');
}

// Hook into socket task_completed for paper trade refresh
if (typeof socket !== 'undefined' && socket) {
    socket.on('task_completed', (payload) => {
        if (_activePaperTasks.has(payload.id)) {
            _activePaperTasks.delete(payload.id);
            const btn = document.getElementById('pt-run-btn');
            if (btn) btn.disabled = false;
            if (_paperCurrentSessionId) refreshPaperDetail();
            showToast('纸面交易运行完成', 'success');
        }
    });
    socket.on('task_failed', (payload) => {
        if (_activePaperTasks.has(payload.id)) {
            _activePaperTasks.delete(payload.id);
            const btn = document.getElementById('pt-run-btn');
            if (btn) btn.disabled = false;
            showToast('纸面交易失败: ' + (payload.error || 'unknown'), 'error');
        }
    });
    socket.on('analysis_tracked', (payload) => {
        // Visual cue: show a badge on the analysis result area if matching
        const badge = document.getElementById('analysis-tracked-badge');
        if (badge && payload.ticker) {
            badge.style.display = 'inline-block';
            badge.textContent = '已自动追踪 → ' + (payload.tracked_ids?.length || 1) + ' 个会话';
        }
    });
}

// ═══════════════════════════════════════════════════════════════════════════
// Paper Trade V2 — Per-ticker card grid + 3-tab detail view
// ═══════════════════════════════════════════════════════════════════════════

let _ptvCurrentTicker = null;
let _chartPtvEquity = null;
let _activeBackfillTask = null;

async function loadPaperTickers() {
    const grid = document.getElementById('paper-ticker-grid');
    if (!grid) return;
    grid.innerHTML = '<div class="text-muted text-center py-4"><div class="spinner-border spinner-border-sm"></div> 加载中...</div>';
    const rows = await api('/api/paper/tickers');
    if (!Array.isArray(rows)) {
        grid.innerHTML = '<p class="text-muted">加载失败</p>';
        return;
    }
    if (rows.length === 0) {
        grid.innerHTML = '<div class="text-center py-5 text-muted">' +
            '<i class="fas fa-inbox fa-3x mb-3 opacity-50"></i><br>' +
            '暂无 ticker 会话<br>' +
            '<small>触发一次 AI 分析，或点击"从历史分析回填"</small>' +
            '</div>';
        return;
    }
    grid.innerHTML = rows.map(_renderTickerCard).join('');
}

function _renderTickerCard(r) {
    const pnlCls = (r.cum_pnl_pct || 0) > 0 ? 'text-success' : (r.cum_pnl_pct || 0) < 0 ? 'text-danger' : 'text-muted';
    const pnl = (r.cum_pnl_pct || 0).toFixed(2);
    const pnlSign = (r.cum_pnl_pct || 0) >= 0 ? '+' : '';
    const sig = r.current_signal || '—';
    const sigCls = {
        BUY: 'bg-success', OVERWEIGHT: 'bg-success',
        SELL: 'bg-danger', UNDERWEIGHT: 'bg-danger',
        HOLD: 'bg-secondary',
        STOP_LOSS: 'bg-warning text-dark', TAKE_PROFIT: 'bg-info',
        TIME_STOP: 'bg-secondary',
    }[sig] || 'bg-secondary';
    const act = r.current_action ? `<span class="text-muted small">${escapeHtml(r.current_action)}</span>` : '';
    const posLine = r.position_shares > 0
        ? `持仓 ${r.position_shares.toFixed(2)}股 @ ${(r.close_price || 0).toFixed(2)}`
        : '<span class="text-muted">空仓</span>';
    const hit = r.hit_pretty !== '—'
        ? `命中率 <strong>${r.hit_pretty}</strong>` + (r.hit_rate != null
            ? ` (${(r.hit_rate * 100).toFixed(0)}%)` : '')
        : '<span class="text-muted">命中率 —</span>';
    const spark = _renderSparkline(r.sparkline || [], r.cum_pnl_pct >= 0);
    return `
    <div class="ticker-card" onclick="openPaperTickerDetail('${r.ticker}')">
        <div class="tc-head">
            <strong class="tc-ticker">${escapeHtml(r.ticker)}</strong>
            <span class="badge ${sigCls}">${escapeHtml(sig)}</span>
            ${act}
        </div>
        <div class="tc-pnl ${pnlCls}">${pnlSign}${pnl}%</div>
        <div class="tc-pos">${posLine}</div>
        <div class="tc-meta">${r.num_events} 次策略事件 · ${hit}</div>
        <div class="tc-spark">${spark}</div>
    </div>`;
}

function _renderSparkline(values, positive) {
    if (!values || values.length < 2) return '<span class="text-muted small">暂无数据</span>';
    const w = 120, h = 28;
    const min = Math.min(...values), max = Math.max(...values);
    const range = max - min || 1;
    const pts = values.map((v, i) => {
        const x = (i / (values.length - 1)) * w;
        const y = h - ((v - min) / range) * h;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
    const color = positive ? '#00c875' : '#ff5a5a';
    return `<svg width="${w}" height="${h}" class="tc-svg"><polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.6"/></svg>`;
}

async function openPaperTickerDetail(ticker) {
    _ptvCurrentTicker = ticker;
    document.getElementById('paper-ticker-view').style.display = 'none';
    document.getElementById('paper-ticker-detail').style.display = 'block';
    document.getElementById('ptv-ticker').textContent = ticker;
    switchPtvTab('strategy');
    await refreshPtv();
}

function closePaperTickerDetail() {
    document.getElementById('paper-ticker-detail').style.display = 'none';
    document.getElementById('paper-ticker-view').style.display = 'block';
    _ptvCurrentTicker = null;
    loadPaperTickers();
}

function switchPtvTab(tab) {
    document.querySelectorAll('#ptv-tabs .nav-link').forEach(l => {
        l.classList.toggle('active', l.dataset.tab === tab);
    });
    document.querySelectorAll('.ptv-tab').forEach(el => {
        el.style.display = el.id === `ptv-tab-${tab}` ? 'block' : 'none';
    });
    if (tab === 'daily' && _chartPtvEquity) {
        setTimeout(() => _chartPtvEquity.resize(), 50);
    }
}

async function refreshPtv() {
    if (!_ptvCurrentTicker) return;
    const data = await api(`/api/paper/tickers/${_ptvCurrentTicker}`);
    if (!data || data.error) {
        const el = document.getElementById('ptv-plan-summary');
        if (el) el.innerHTML = '<p class="text-muted">无数据</p>';
        return;
    }
    document.getElementById('ptv-status').textContent = data.session?.status || '—';

    _renderPtvStrategy(data);
    _renderPtvTimeline(data.events || []);
    _renderPtvDaily(data.dailies || [], data.session?.start_capital);
    _renderPtvHistory(data.plan_history || []);
}

function _renderPtvStrategy(data) {
    const plan = data.active_plan;
    const orders = data.active_orders || [];
    const sess = data.session || {};

    // 1. Plan summary card
    const sumEl = document.getElementById('ptv-plan-summary');
    const methodEl = document.getElementById('ptv-plan-method');
    if (!plan) {
        if (sumEl) sumEl.innerHTML = '<p class="text-muted">暂无活跃策略</p>';
        if (methodEl) methodEl.textContent = '—';
    } else {
        const ratingCls = plan.rating === 'BUY' ? 'bg-success' : plan.rating === 'SELL' ? 'bg-danger' : 'bg-secondary';
        const hmin = plan.holding_months_min, hmax = plan.holding_months_max;
        const holding = (hmin || hmax) ? `${hmin || '?'}-${hmax || '?'} 个月` : '';
        if (methodEl) methodEl.textContent = plan.parse_method || '—';
        sumEl.innerHTML = `
            <div class="mb-2">
                <span class="badge ${ratingCls} me-1">${escapeHtml(plan.rating || '—')}</span>
                <span class="text-muted small">创建于 ${plan.created_at} · 分析 #${plan.analysis_id}</span>
            </div>
            ${plan.thesis ? `<div class="mb-2"><strong>核心论点：</strong>${escapeHtml(plan.thesis)}</div>` : ''}
            ${holding ? `<div class="small mb-1"><i class="fas fa-clock"></i> 投资周期：<strong>${holding}</strong></div>` : ''}
            <div class="small text-muted">共 <strong>${orders.length}</strong> 档，
                ${orders.filter(o => o.status === 'triggered').length} 已执行，
                ${orders.filter(o => o.status === 'pending').length} 待触发</div>
        `;
    }

    // 2. Position card
    const lastDaily = (data.dailies || []).slice(-1)[0];
    const shares = lastDaily?.position_shares || 0;
    const posEl = document.getElementById('ptv-position');
    if (shares <= 0) {
        posEl.innerHTML = `<p class="text-muted mb-2">当前空仓</p>
            <div class="small">总值 <strong>$${(lastDaily?.total_value || sess.start_capital || 0).toFixed(2)}</strong></div>
            <div class="small text-muted">现金 $${(lastDaily?.cash || sess.start_capital || 0).toFixed(2)}</div>`;
    } else {
        const cost = lastDaily.avg_cost || 0;
        const mkt = lastDaily.close_price || 0;
        const pct = cost ? (mkt / cost - 1) * 100 : 0;
        const pctCls = pct >= 0 ? 'text-success' : 'text-danger';
        posEl.innerHTML = `
            <div class="h5">${shares.toFixed(2)} 股</div>
            <div class="small">成本 <strong>${cost.toFixed(2)}</strong> · 现价 <strong>${mkt.toFixed(2)}</strong></div>
            <div class="small">浮盈 <strong class="${pctCls}">${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%</strong></div>
            <hr class="my-2"/>
            <div class="small">市值 $${(lastDaily.position_value || 0).toFixed(2)}</div>
            <div class="small">现金 $${(lastDaily.cash || 0).toFixed(2)}</div>
            <div class="small">总值 <strong>$${(lastDaily.total_value || 0).toFixed(2)}</strong></div>
            <div class="small">持仓 ${lastDaily.days_held || 0} 天</div>
        `;
    }

    // 3. Ladder: each order as a row
    const ladderEl = document.getElementById('ptv-orders-ladder');
    if (!orders.length) {
        ladderEl.innerHTML = '<div class="text-muted text-center py-3">此策略无档位（HOLD 信号或解析失败）</div>';
    } else {
        ladderEl.innerHTML = '<div class="ladder-table">' +
            orders.map(_renderOrderRow).join('') + '</div>';
    }

    // 4. Raw summary
    const rawEl = document.getElementById('ptv-raw-summary');
    rawEl.textContent = plan?.raw_summary || data.latest_advice?.reasoning || '—';
}

function _renderOrderRow(o) {
    const statusBadge = {
        pending: '<span class="ladder-status status-pending">⏳ 待触发</span>',
        triggered: '<span class="ladder-status status-triggered">✓ 已执行</span>',
        cancelled: '<span class="ladder-status status-cancelled">✗ 已取消</span>',
        superseded: '<span class="ladder-status status-superseded">⊘ 已失效</span>',
    }[o.status] || o.status;
    const typeLabel = {
        entry_initial: '初始建仓',
        entry_add: '加仓档',
        exit_stop: '硬性止损',
        exit_target: '止盈档',
        exit_trailing: '跟踪止盈',
    }[o.order_type] || o.order_type;
    const trig = o.trigger || {};
    const triggerDesc = _describeTrigger(trig);
    const pct = o.pct_target_total != null
        ? `<span class="ladder-pct">目标 ${(o.pct_target_total * 100).toFixed(1)}%</span>`
        : '';
    const fill = o.triggered_date
        ? `<div class="ladder-fill"><i class="fas fa-check-circle text-success"></i> ${o.triggered_date} @ ${o.triggered_price?.toFixed(2) || '—'}</div>`
        : '';
    return `
        <div class="ladder-row status-${o.status}">
            <div class="ladder-seq">#${o.sequence}</div>
            <div class="ladder-type">${typeLabel}</div>
            <div class="ladder-pct-cell">${pct}</div>
            <div class="ladder-trigger">
                <div class="text-muted small">触发条件</div>
                <div>${triggerDesc}</div>
            </div>
            <div class="ladder-desc">${escapeHtml(o.description || '')}</div>
            <div class="ladder-status-cell">${statusBadge}${fill}</div>
        </div>`;
}

function _describeTrigger(trig) {
    const k = trig.kind;
    if (k === 'immediate') return '<strong>立即</strong>';
    if (k === 'price_above') return `价格 <strong>≥ $${trig.price}</strong>`;
    if (k === 'price_below') return `价格 <strong>≤ $${trig.price}</strong>`;
    if (k === 'breakout_retest') return `突破 <strong>$${trig.zone_low}-$${trig.zone_high}</strong> 后回踩`;
    if (k === 'trailing_ma') return `收盘 <strong>&lt; MA${trig.period || 20}</strong>`;
    if (k === 'time_stop') return `持仓 <strong>${trig.months}个月</strong>`;
    return escapeHtml(k || '—');
}

function _renderPtvHistory(plans) {
    const el = document.getElementById('ptv-plan-history');
    if (!plans.length) {
        el.innerHTML = '<p class="text-muted">暂无策略记录</p>';
        return;
    }
    el.innerHTML = plans.map((p, i) => {
        const active = p.status === 'active';
        const orders = p.orders || [];
        const tExec = orders.filter(o => o.status === 'triggered').length;
        const tPend = orders.filter(o => o.status === 'pending').length;
        const tSupd = orders.filter(o => o.status === 'superseded').length;
        const ratingCls = p.rating === 'BUY' ? 'bg-success' : p.rating === 'SELL' ? 'bg-danger' : 'bg-secondary';
        return `
            <div class="plan-card ${active ? 'plan-active' : 'plan-old'}">
                <div class="plan-card-head">
                    <span class="badge ${ratingCls} me-2">${escapeHtml(p.rating || '—')}</span>
                    <span><strong>Plan #${p.id}</strong></span>
                    ${active
                        ? '<span class="badge bg-primary ms-2">当前</span>'
                        : `<span class="badge bg-secondary ms-2">已失效</span>`}
                    <span class="text-muted small ms-auto">${p.created_at}</span>
                </div>
                ${p.thesis ? `<div class="plan-card-thesis">${escapeHtml(p.thesis)}</div>` : ''}
                <div class="plan-card-meta small text-muted">
                    分析 #${p.analysis_id} · 解析 ${p.parse_method || '—'} ·
                    ${tExec} 执行 · ${tPend} 待触发 · ${tSupd} 已失效
                </div>
                <div class="plan-card-orders">
                    ${orders.map(o => _renderOrderRow(o)).join('')}
                </div>
            </div>
        `;
    }).join('');
}

function _renderPtvTimeline(events) {
    const el = document.getElementById('ptv-timeline');
    if (!events.length) {
        el.innerHTML = '<p class="text-muted">暂无事件</p>';
        return;
    }
    const items = events.map(e => {
        const sigCls = {
            BUY: 'signal-buy', OVERWEIGHT: 'signal-buy',
            SELL: 'signal-sell', UNDERWEIGHT: 'signal-sell',
            HOLD: 'signal-hold',
            STOP_LOSS: 'signal-stop', TAKE_PROFIT: 'signal-target',
            TIME_STOP: 'signal-hold',
        }[(e.new_signal || '').toUpperCase()] || 'signal-hold';
        const actCls = {
            open: 'action-open', add: 'action-open', reduce: 'action-reduce',
            close: 'action-close', reverse: 'action-close',
            hold: 'action-hold', skipped: 'action-skip', no_action: 'action-skip',
            stop_loss: 'action-close', take_profit: 'action-close', time_stop: 'action-close',
        }[e.action] || 'action-hold';
        return `
        <div class="ptv-event ${sigCls}">
            <div class="ptv-event-date">${e.event_date}</div>
            <div class="ptv-event-body">
                <div>
                    <span class="ptv-event-signal">${escapeHtml(e.new_signal || '—')}</span>
                    <span class="ptv-event-action ${actCls}">${escapeHtml(e.action)}</span>
                    ${e.shares_delta ? `<span class="ptv-event-delta">${e.shares_delta > 0 ? '+' : ''}${parseFloat(e.shares_delta).toFixed(2)} 股</span>` : ''}
                    ${e.price ? `<span class="text-muted small ms-2">@ ${parseFloat(e.price).toFixed(2)}</span>` : ''}
                </div>
                ${e.reasoning ? `<div class="small text-muted mt-1">${escapeHtml(e.reasoning)}</div>` : ''}
                ${e.skip_reason ? `<div class="small text-warning mt-1"><i class="fas fa-exclamation-triangle"></i> ${escapeHtml(e.skip_reason)}</div>` : ''}
            </div>
        </div>`;
    }).join('');
    el.innerHTML = items;
}

function _renderPtvDaily(dailies, startCapital) {
    // Equity chart
    const chartEl = document.getElementById('chart-ptv-equity');
    if (chartEl && !_chartPtvEquity) _chartPtvEquity = echarts.init(chartEl);
    if (!dailies.length) {
        if (_chartPtvEquity) _chartPtvEquity.setOption({
            title: { text: '暂无日度数据', left: 'center', top: 'middle',
                     textStyle: { color: '#999', fontSize: 13 } },
        }, true);
        document.querySelector('#ptv-daily-table tbody').innerHTML =
            '<tr><td colspan="10" class="text-muted text-center">暂无日度数据。触发"更新日度数据"拉取历史。</td></tr>';
        document.getElementById('ptv-metrics').innerHTML = '';
        return;
    }
    const dates = dailies.map(d => d.date);
    const totals = dailies.map(d => d.total_value);
    const pnls = dailies.map(d => d.daily_pnl);
    _chartPtvEquity.setOption({
        tooltip: { trigger: 'axis' },
        legend: { data: ['总价值', '当日盈亏'], top: 4 },
        grid: { left: 60, right: 60, top: 40, bottom: 30 },
        xAxis: { type: 'category', data: dates },
        yAxis: [
            { type: 'value', name: '总价值', scale: true },
            { type: 'value', name: '日盈亏', scale: true },
        ],
        series: [
            { name: '总价值', type: 'line', data: totals, smooth: true,
              itemStyle: { color: '#3882ff' }, areaStyle: { opacity: 0.1 } },
            { name: '当日盈亏', type: 'bar', yAxisIndex: 1, data: pnls,
              itemStyle: {
                  color: (p) => p.value >= 0 ? '#00c875' : '#ff5a5a',
              } },
        ],
    }, true);

    // Metrics summary
    const last = dailies[dailies.length - 1];
    const wins = dailies.filter(d => (d.daily_pnl || 0) > 0).length;
    const dayWinRate = dailies.length ? (wins / dailies.length * 100) : 0;
    const maxDd = Math.min(...dailies.map(d => d.drawdown_pct || 0));
    const strategyChanges = dailies.filter(d => d.strategy_changed).length;
    const metrics = [
        ['总收益', `${(last.cum_pnl_pct || 0) >= 0 ? '+' : ''}${(last.cum_pnl_pct || 0).toFixed(2)}%`, 'fa-chart-line'],
        ['最大回撤', `${(maxDd).toFixed(2)}%`, 'fa-arrow-trend-down'],
        ['日胜率', `${dayWinRate.toFixed(1)}%`, 'fa-percent'],
        ['交易日数', dailies.length, 'fa-calendar'],
        ['策略变更', strategyChanges, 'fa-sync'],
        ['当前总值', `$${(last.total_value || 0).toFixed(2)}`, 'fa-sack-dollar'],
    ];
    document.getElementById('ptv-metrics').innerHTML = metrics.map(([l, v, i]) => `
        <div class="col-6 col-md-2">
            <div class="metric-card small">
                <div class="metric-label"><i class="fas ${i}"></i> ${l}</div>
                <div class="metric-value">${v}</div>
            </div>
        </div>
    `).join('');

    // Daily table
    const tbody = document.querySelector('#ptv-daily-table tbody');
    tbody.innerHTML = dailies.slice().reverse().map(d => {
        const pnlCls = (d.daily_pnl || 0) > 0 ? 'text-success' : (d.daily_pnl || 0) < 0 ? 'text-danger' : '';
        return `<tr>
            <td>${d.date}</td>
            <td>${(d.close_price || 0).toFixed(2)}</td>
            <td>${(d.position_shares || 0).toFixed(2)}</td>
            <td>$${(d.position_value || 0).toFixed(2)}</td>
            <td>$${(d.cash || 0).toFixed(2)}</td>
            <td><strong>$${(d.total_value || 0).toFixed(2)}</strong></td>
            <td class="${pnlCls}">${(d.daily_pnl || 0) >= 0 ? '+' : ''}${(d.daily_pnl || 0).toFixed(2)}</td>
            <td class="${(d.cum_pnl_pct || 0) >= 0 ? 'text-success' : 'text-danger'}">${(d.cum_pnl_pct || 0) >= 0 ? '+' : ''}${(d.cum_pnl_pct || 0).toFixed(2)}%</td>
            <td class="text-danger">${(d.drawdown_pct || 0).toFixed(2)}%</td>
            <td>${d.active_signal ? `<span class="badge bg-secondary">${escapeHtml(d.active_signal)}</span>` : '—'}</td>
        </tr>`;
    }).join('');
}

async function runTickerEod() {
    if (!_ptvCurrentTicker) return;
    const res = await api(`/api/paper/tickers/${_ptvCurrentTicker}/eod`, { method: 'POST' });
    if (res?.ok) {
        showToast(`日度数据已更新 (+${res.new_rows} 条)`, 'success');
        refreshPtv();
    } else {
        showToast('更新失败: ' + (res?.error || 'unknown'), 'error');
    }
}

async function runAllPaperEod() {
    showToast('批量更新日度数据中...', 'info');
    const rows = await api('/api/paper/tickers');
    if (!Array.isArray(rows)) return;
    let ok = 0, total = rows.length;
    for (const r of rows) {
        const res = await api(`/api/paper/tickers/${r.ticker}/eod`, { method: 'POST' });
        if (res?.ok) ok++;
    }
    showToast(`批量更新完成 (${ok}/${total})`, 'success');
    loadPaperTickers();
}

async function runPaperBackfill() {
    if (!confirm('从 analysis_history 回填所有 ticker 会话？将重建每只股票的策略轨迹 + 日度数据。')) return;
    const res = await api('/api/paper/backfill', { method: 'POST' });
    if (res?.ok) {
        _activeBackfillTask = res.task_id;
        showToast('回填任务已提交 (task: ' + res.task_id.slice(0, 8) + ')', 'info');
    } else {
        showToast('提交失败: ' + (res?.error || 'unknown'), 'error');
    }
}

// Socket wiring: refresh when backfill completes or analysis routed
if (typeof socket !== 'undefined' && socket) {
    socket.on('task_completed', (payload) => {
        if (_activeBackfillTask && payload.id === _activeBackfillTask) {
            _activeBackfillTask = null;
            showToast('回填完成', 'success');
            loadPaperTickers();
        }
    });
    socket.on('analysis_tracked', (payload) => {
        // If user is viewing the affected ticker, refresh
        if (_ptvCurrentTicker && payload.ticker === _ptvCurrentTicker) {
            refreshPtv();
        }
    });
}

// ═══════════════════════════════════════════════════════════════════════════
// Batch Analysis — one-click all holdings
// ═══════════════════════════════════════════════════════════════════════════

let _batchTaskId = null;
let _batchItems = [];
let _batchTotal = 0;

async function showBatchAnalysisConfirm() {
    // Fetch holdings count for the confirm text
    const holdings = await api('/api/portfolio/holdings');
    const count = Array.isArray(holdings) ? holdings.filter(h => (h.shares || 0) > 0).length : 0;
    if (count === 0) {
        showToast('暂无持仓，请先添加持仓', 'warning');
        return;
    }
    const estMin = count * 2, estMax = count * 5;
    document.getElementById('batch-confirm-text').textContent =
        `当前持仓 ${count} 只股票，预计耗时 ${estMin}-${estMax} 分钟`;
    const modal = new bootstrap.Modal(document.getElementById('batchAnalysisModal'));
    modal.show();
}

async function runBatchAnalysis() {
    bootstrap.Modal.getInstance(document.getElementById('batchAnalysisModal'))?.hide();
    const skipCheck = document.getElementById('batch-skip-check').checked;
    const skipHours = skipCheck ? (parseInt(document.getElementById('batch-skip-hours').value) || 4) : 0;

    const resp = await api('/api/tasks/submit', {
        method: 'POST',
        body: JSON.stringify({
            type: 'batch_analysis',
            params: { skip_recent_hours: skipHours },
            title: '持仓全量分析',
        }),
    });
    if (!resp || resp.error) {
        showToast('提交失败: ' + (resp?.error || 'unknown'), 'error');
        return;
    }
    _batchTaskId = resp.id;
    _batchItems = [];
    _batchTotal = 0;
    showBatchPanel();
    document.getElementById('btn-batch-analyze').disabled = true;
    showToast('批量分析已提交', 'info');
}

function showBatchPanel() {
    document.getElementById('batch-panel').style.display = 'block';
    document.getElementById('batch-float-bar').style.display = 'none';
    document.getElementById('batch-items-list').innerHTML =
        '<div class="text-muted text-center py-3"><div class="spinner-border spinner-border-sm"></div> 准备中...</div>';
    updateBatchProgress(0, '准备中...');
}

function minimizeBatchPanel() {
    document.getElementById('batch-panel').style.display = 'none';
    document.getElementById('batch-float-bar').style.display = 'block';
}

function expandBatchPanel() {
    document.getElementById('batch-panel').style.display = 'block';
    document.getElementById('batch-float-bar').style.display = 'none';
}

function closeBatchPanel() {
    document.getElementById('batch-panel').style.display = 'none';
    document.getElementById('batch-float-bar').style.display = 'none';
    _batchTaskId = null;
    const btn = document.getElementById('btn-batch-analyze');
    if (btn) btn.disabled = false;
}

function updateBatchProgress(pct, label) {
    document.getElementById('batch-progress-bar').style.width = pct + '%';
    document.getElementById('batch-progress-pct').textContent = pct + '%';
    document.getElementById('batch-progress-label').textContent = label || '';
    document.getElementById('batch-float-fill').style.width = pct + '%';
    document.getElementById('batch-float-text').textContent = label || '分析中...';
}

function _batchItemHtml(item) {
    const sigCls = {
        BUY: 'text-success', OVERWEIGHT: 'text-success',
        SELL: 'text-danger', UNDERWEIGHT: 'text-danger',
        HOLD: 'text-warning',
    }[(item.signal || '').toUpperCase()] || '';
    if (item.status === 'success') {
        return `
            <div class="batch-item batch-item-done">
                <span class="batch-item-icon">✅</span>
                <strong>${escapeHtml(item.ticker)}</strong>
                <span class="badge ${sigCls ? 'bg-' + (sigCls === 'text-success' ? 'success' : sigCls === 'text-danger' ? 'danger' : 'warning') : 'bg-secondary'} ms-2">
                    ${escapeHtml(item.signal || '—')}
                </span>
                ${item.confidence != null ? `<span class="text-muted small ms-1">置信度 ${Math.round(item.confidence * 100)}%</span>` : ''}
                <button class="btn btn-sm btn-outline-primary ms-auto" onclick="viewBatchItemDetail(${item.analysis_id})">查看详情</button>
            </div>`;
    }
    if (item.status === 'failed') {
        return `
            <div class="batch-item batch-item-fail">
                <span class="batch-item-icon">❌</span>
                <strong>${escapeHtml(item.ticker)}</strong>
                <span class="text-danger small ms-2">${escapeHtml(item.error || '失败')}</span>
            </div>`;
    }
    if (item.status === 'skipped') {
        return `
            <div class="batch-item batch-item-skip">
                <span class="batch-item-icon">⏭️</span>
                <strong>${escapeHtml(item.ticker)}</strong>
                <span class="text-muted small ms-2">${escapeHtml(item.reason || '已跳过')}</span>
                ${item.last_signal ? `<span class="badge bg-secondary ms-1">${item.last_signal}</span>` : ''}
            </div>`;
    }
    if (item.status === 'running') {
        return `
            <div class="batch-item batch-item-running">
                <span class="batch-item-icon"><div class="spinner-border spinner-border-sm"></div></span>
                <strong>${escapeHtml(item.ticker)}</strong>
                <span class="text-muted small ms-2">分析中...</span>
            </div>`;
    }
    return `
        <div class="batch-item batch-item-pending">
            <span class="batch-item-icon">⏳</span>
            <strong>${escapeHtml(item.ticker)}</strong>
            <span class="text-muted small ms-2">等待中</span>
        </div>`;
}

function renderBatchItems() {
    const el = document.getElementById('batch-items-list');
    el.innerHTML = _batchItems.map(_batchItemHtml).join('');
}

function viewBatchItemDetail(analysisId) {
    if (typeof openHistoryDetail === 'function') {
        openHistoryDetail(analysisId);
    }
}

// Socket events for batch
if (typeof socket !== 'undefined' && socket) {
    socket.on('batch_analysis_item', (data) => {
        if (!_batchTaskId || data.batch_task_id !== _batchTaskId) return;
        _batchTotal = data.total || _batchTotal;
        // Update or insert item
        const idx = _batchItems.findIndex(i => i.ticker === data.ticker);
        if (idx >= 0) {
            _batchItems[idx] = { ..._batchItems[idx], ...data };
        } else {
            _batchItems.push(data);
        }
        renderBatchItems();
        const done = _batchItems.filter(i => i.status !== 'pending' && i.status !== 'running').length;
        updateBatchProgress(
            Math.round(done / _batchTotal * 100),
            `${done}/${_batchTotal} 完成`
        );
    });

    socket.on('task_progress', (data) => {
        if (!_batchTaskId || data.id !== _batchTaskId) return;
        updateBatchProgress(data.progress || 0, data.step || '');
    });

    socket.on('task_completed', (data) => {
        if (!_batchTaskId || data.id !== _batchTaskId) return;
        updateBatchProgress(100, '全部完成');
        const succ = _batchItems.filter(i => i.status === 'success').length;
        const fail = _batchItems.filter(i => i.status === 'failed').length;
        const skip = _batchItems.filter(i => i.status === 'skipped').length;
        showToast(`持仓分析完成：${succ} 成功 / ${fail} 失败 / ${skip} 跳过`, 'success');
        const btn = document.getElementById('btn-batch-analyze');
        if (btn) btn.disabled = false;
    });

    socket.on('task_failed', (data) => {
        if (!_batchTaskId || data.id !== _batchTaskId) return;
        updateBatchProgress(0, '失败: ' + (data.error_message || ''));
        showToast('批量分析失败: ' + (data.error_message || ''), 'error');
        const btn = document.getElementById('btn-batch-analyze');
        if (btn) btn.disabled = false;
    });
}
