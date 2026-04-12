/* === Stock Trading System - Frontend === */

const socket = io();
let chartPnl = null;
let chartAllocation = null;
let chartKline = null;
let currentKlineTicker = null;
let currentKlineRange = '1mo';
let chartBacktest = null;
let _backtestStrategies = null;

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
    if (page === 'alerts') loadAlerts();
    if (page === 'history') loadHistory();
    if (page === 'settings') loadSettings();
    if (page === 'backtest') loadBacktestStrategies();

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

    // P&L Chart
    renderPnlChart(data.history);

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
        xAxis: { type: 'category', data: history.map(h => h.date), axisLine: { lineStyle: { color: '#30363d' } } },
        yAxis: { type: 'value', axisLine: { lineStyle: { color: '#30363d' } }, splitLine: { lineStyle: { color: '#21262d' } } },
        series: [
            { name: '总市值', type: 'line', data: history.map(h => h.total_value), smooth: true, lineStyle: { color: '#58a6ff' }, areaStyle: { color: 'rgba(88,166,255,0.1)' } },
            { name: '盈亏', type: 'bar', data: history.map(h => h.pnl), itemStyle: { color: p => p.value >= 0 ? '#3fb950' : '#f85149' } },
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
        tooltip: { trigger: 'item', formatter: '{b}: {d}%' },
        series: [{
            type: 'pie', radius: ['40%', '70%'],
            data: alloc.map(a => ({ name: a.ticker, value: a.value })),
            label: { color: '#e6edf3', fontSize: 12 },
            itemStyle: { borderColor: '#1c2128', borderWidth: 2 },
        }],
    });
}

// ── Analysis ───────────────────────────────────────────────────────────────

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
    document.getElementById('pipeline-card').style.display = 'block';
    document.getElementById('btn-rerun').style.display = 'none';
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

    api('/api/analyze', {
        method: 'POST',
        body: JSON.stringify({ ticker, date }),
    }).then(data => {
        if (data && data.ok) showToast('分析已启动: ' + ticker, 'info');
    });
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
    loadChart(ticker, currentKlineRange);
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
        itemStyle: { color: r.close >= r.open ? '#3fb950' : '#f85149' },
    }));

    chartKline.setOption({
        backgroundColor: 'transparent',
        animation: false,
        legend: { data: ['K线'], textStyle: { color: '#e6edf3' }, top: 0 },
        tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'cross' },
            backgroundColor: '#1c2128',
            borderColor: '#30363d',
            textStyle: { color: '#e6edf3' },
        },
        axisPointer: { link: [{ xAxisIndex: 'all' }] },
        grid: [
            { left: 50, right: 20, top: 30, height: '62%' },
            { left: 50, right: 20, top: '76%', height: '18%' },
        ],
        xAxis: [
            { type: 'category', data: dates, axisLine: { lineStyle: { color: '#30363d' } }, axisLabel: { color: '#8b949e' } },
            { type: 'category', gridIndex: 1, data: dates, axisLine: { lineStyle: { color: '#30363d' } }, axisLabel: { show: false } },
        ],
        yAxis: [
            { scale: true, axisLine: { lineStyle: { color: '#30363d' } }, axisLabel: { color: '#8b949e' }, splitLine: { lineStyle: { color: '#21262d' } } },
            { gridIndex: 1, axisLine: { lineStyle: { color: '#30363d' } }, axisLabel: { color: '#8b949e' }, splitLine: { show: false } },
        ],
        series: [
            {
                name: 'K线', type: 'candlestick', data: kdata,
                itemStyle: {
                    color: '#3fb950', color0: '#f85149',
                    borderColor: '#3fb950', borderColor0: '#f85149',
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

// Range switcher for K-line
document.addEventListener('click', e => {
    const btn = e.target.closest('.range-switcher .btn');
    if (!btn) return;
    const parent = btn.closest('.range-switcher');
    parent.querySelectorAll('.btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentKlineRange = btn.dataset.range;
    if (currentKlineTicker) loadChart(currentKlineTicker, currentKlineRange);
});

socket.on('analysis_status', data => {
    showToast(`${data.ticker} 分析中...`, 'info');
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
    document.getElementById('analysis-loading').style.display = 'none';
    document.getElementById('analysis-result').style.display = 'block';
    document.getElementById('btn-analyze').disabled = false;

    // Signal
    const signalEl = document.getElementById('signal-value');
    signalEl.textContent = data.signal;
    signalEl.className = 'signal-value ' + getSignalClass(data.signal);
    document.getElementById('signal-ticker').textContent = data.ticker;

    // Reports
    document.getElementById('report-market').textContent = data.market_report || 'N/A';
    document.getElementById('report-fundamentals').textContent = data.fundamentals_report || 'N/A';
    document.getElementById('report-sentiment').textContent = data.sentiment_report || 'N/A';
    document.getElementById('report-news').textContent = data.news_report || 'N/A';
    document.getElementById('report-debate').textContent = data.investment_debate || 'N/A';
    document.getElementById('report-risk').textContent = data.risk_assessment || 'N/A';
    document.getElementById('report-decision').textContent = data.trade_decision || 'N/A';

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
});

socket.on('analysis_error', data => {
    document.getElementById('analysis-loading').style.display = 'none';
    document.getElementById('btn-analyze').disabled = false;
    // Surface the rerun button so the user doesn't have to retype everything.
    const rerunBtn = document.getElementById('btn-rerun');
    if (rerunBtn) rerunBtn.style.display = 'inline-block';
    showToast(`分析失败: ${data.error}`, 'error');
});

// ── Screener ───────────────────────────────────────────────────────────────

function runScreen() {
    const market = document.getElementById('screen-market').value;
    const strategy = document.getElementById('screen-strategy').value;

    document.getElementById('screen-loading').style.display = 'block';
    document.getElementById('screen-results').style.display = 'none';
    document.getElementById('btn-screen').disabled = true;

    api('/api/screen', {
        method: 'POST',
        body: JSON.stringify({ market, strategy }),
    }).then(data => {
        if (data && data.ok) showToast('选股已启动', 'info');
    });
}

socket.on('screen_status', () => { showToast('筛选进行中...', 'info'); });

socket.on('screen_result', data => {
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
            <td><button class="btn btn-sm btn-outline-primary" onclick="analyzeFromScreen('${s.ticker}')"><i class="fas fa-brain"></i></button></td>
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
                    </div>
                </div>`;
            }).join('');
        }
    }
    showToast(`筛选完成，共 ${results.length} 只`, 'success');
});

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
        document.getElementById('report-content').textContent = data.content;
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

async function showHistoryDetail(id) {
    const r = await api('/api/history/' + id);
    if (!r) return;

    const sigCls = getSignalBadgeClass(r.signal);
    let adviceHtml = '';
    if (r.advice_json) {
        try {
            const a = JSON.parse(r.advice_json);
            adviceHtml = `
                <h6 style="color:#e6edf3;">策略建议</h6>
                <div class="row g-2 mb-3" style="font-size:13px;">
                    <div class="col-4"><strong>操作:</strong> ${a.action || '--'}</div>
                    <div class="col-4"><strong>信心:</strong> ${a.confidence || '--'}</div>
                    <div class="col-4"><strong>仓位:</strong> ${fmt(a.suggested_position_pct)}%</div>
                    ${a.stop_loss ? `<div class="col-4"><strong>止损:</strong> ${fmt(a.stop_loss)}</div>` : ''}
                    ${a.take_profit ? `<div class="col-4"><strong>止盈:</strong> ${fmt(a.take_profit)}</div>` : ''}
                    ${a.reasoning ? `<div class="col-12"><strong>分析:</strong> ${a.reasoning}</div>` : ''}
                    ${a.risk_warning ? `<div class="col-12" style="color:var(--accent-yellow);"><strong>风险:</strong> ${a.risk_warning}</div>` : ''}
                </div>
                <hr style="border-color:var(--border);">`;
        } catch(e) {}
    }

    document.getElementById('historyModalTitle').innerHTML =
        `${r.ticker} <span class="h-signal ${sigCls}" style="font-size:14px;">${r.signal}</span> <small class="text-muted" style="font-size:13px;">${r.date}</small>`;

    document.getElementById('historyModalBody').innerHTML = `
        ${adviceHtml}
        <div class="row g-3">
            <div class="col-md-6">
                <h6 style="color:#e6edf3;">技术面分析</h6>
                <div class="report-content">${r.market_report || 'N/A'}</div>
            </div>
            <div class="col-md-6">
                <h6 style="color:#e6edf3;">基本面分析</h6>
                <div class="report-content">${r.fundamentals_report || 'N/A'}</div>
            </div>
            <div class="col-md-6">
                <h6 style="color:#e6edf3;">情绪分析</h6>
                <div class="report-content">${r.sentiment_report || 'N/A'}</div>
            </div>
            <div class="col-md-6">
                <h6 style="color:#e6edf3;">新闻分析</h6>
                <div class="report-content">${r.news_report || 'N/A'}</div>
            </div>
            <div class="col-md-6">
                <h6 style="color:#e6edf3;">多空辩论</h6>
                <div class="report-content">${r.investment_debate || 'N/A'}</div>
            </div>
            <div class="col-md-6">
                <h6 style="color:#e6edf3;">风险评估</h6>
                <div class="report-content">${r.risk_assessment || 'N/A'}</div>
            </div>
            <div class="col-12">
                <h6 style="color:#e6edf3;">最终决策</h6>
                <div class="report-content">${r.trade_decision || 'N/A'}</div>
            </div>
        </div>`;

    new bootstrap.Modal(document.getElementById('historyModal')).show();
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

// Settings editor state — the last full /api/settings response + edit mode.
let _settingsData = null;
let _settingsEditMode = false;
let _settingsWritable = new Set();

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
    document.getElementById('btn-settings-edit').classList.toggle('d-none', _settingsEditMode);
    document.getElementById('btn-settings-save').classList.toggle('d-none', !_settingsEditMode);
    document.getElementById('btn-settings-cancel').classList.toggle('d-none', !_settingsEditMode);
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
});

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

// ── Init ───────────────────────────────────────────────────────────────────

loadDashboard();
