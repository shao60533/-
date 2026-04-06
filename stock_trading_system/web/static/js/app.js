/* === Stock Trading System - Frontend === */

const socket = io();
let chartPnl = null;
let chartAllocation = null;

// ── Navigation ─────────────────────────────────────────────────────────────

document.querySelectorAll('[data-page]').forEach(link => {
    link.addEventListener('click', e => {
        e.preventDefault();
        const page = link.dataset.page;
        document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
        document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
        document.getElementById('page-' + page).classList.add('active');
        link.classList.add('active');
        // Load page data
        if (page === 'dashboard') loadDashboard();
        if (page === 'portfolio') loadPortfolio();
        if (page === 'alerts') loadAlerts();
        if (page === 'history') loadHistory();
    });
});

document.getElementById('sidebar-toggle').addEventListener('click', () => {
    document.getElementById('sidebar').classList.toggle('collapsed');
    document.getElementById('main-content').classList.toggle('expanded');
    setTimeout(() => { if (chartPnl) chartPnl.resize(); if (chartAllocation) chartAllocation.resize(); }, 350);
});

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

    // Holdings table
    const tbody = document.querySelector('#dash-holdings-table tbody');
    tbody.innerHTML = '';
    data.holdings.forEach(h => {
        const cls = pnlClass(h.pnl);
        tbody.innerHTML += `<tr>
            <td><strong>${h.ticker}</strong></td>
            <td>${h.market.toUpperCase()}</td>
            <td>${fmt(h.shares, 0)}</td>
            <td>${fmtCurrency(h.avg_cost, h.market)}</td>
            <td>${fmtCurrency(h.current_price, h.market)}</td>
            <td class="${cls}">${fmtCurrency(h.pnl, h.market)}</td>
            <td class="${cls}">${fmtPct(h.pnl_pct)}</td>
        </tr>`;
    });

    // P&L Chart
    renderPnlChart(data.history);

    // Allocation Chart
    const alloc = await api('/api/portfolio/allocation');
    if (alloc) renderAllocationChart(alloc);
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

function runAnalysis() {
    const ticker = document.getElementById('analyze-ticker').value.trim();
    const date = document.getElementById('analyze-date').value;
    if (!ticker) { showToast('请输入股票代码', 'warning'); return; }

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

socket.on('analysis_status', data => {
    showToast(`${data.ticker} 分析中...`, 'info');
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

    const tbody = document.querySelector('#screen-table tbody');
    tbody.innerHTML = '';
    (data.results || []).forEach((s, i) => {
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
    showToast(`筛选完成，共 ${(data.results || []).length} 只`, 'success');
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

    // Holdings table
    const tbody = document.querySelector('#portfolio-table tbody');
    tbody.innerHTML = '';
    (holdings || []).forEach(h => {
        const cls = pnlClass(h.pnl);
        tbody.innerHTML += `<tr>
            <td><strong>${h.ticker}</strong></td>
            <td>${h.market.toUpperCase()}</td>
            <td>${fmt(h.shares, 0)}</td>
            <td>${fmtCurrency(h.avg_cost, h.market)}</td>
            <td>${fmtCurrency(h.current_price, h.market)}</td>
            <td>${fmtCurrency(h.market_value, h.market)}</td>
            <td class="${cls}">${fmtCurrency(h.pnl, h.market)}</td>
            <td class="${cls}">${fmtPct(h.pnl_pct)}</td>
            <td><button class="btn btn-sm btn-outline-primary" onclick="analyzeFromScreen('${h.ticker}')"><i class="fas fa-brain"></i></button></td>
        </tr>`;
    });

    // Transactions table
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

async function loadAlerts() {
    const alerts = await api('/api/alerts');
    const tbody = document.querySelector('#alerts-table tbody');
    tbody.innerHTML = '';

    const condLabels = {
        price_above: '价格高于', price_below: '价格低于',
        pct_change_above: '涨幅超过', pct_change_below: '跌幅超过',
        volume_spike: '成交量超过', stop_loss: '止损价', take_profit: '止盈价',
    };

    (alerts || []).forEach(a => {
        tbody.innerHTML += `<tr>
            <td>${a.id}</td>
            <td><strong>${a.ticker}</strong></td>
            <td>${condLabels[a.condition] || a.condition}</td>
            <td>${a.threshold}</td>
            <td>${a.created}</td>
            <td><button class="btn btn-sm btn-outline-danger" onclick="removeAlert(${a.id})"><i class="fas fa-trash"></i></button></td>
        </tr>`;
    });
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
        loadAlerts();
    }
}

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

function renderHistory(records) {
    const container = document.getElementById('history-list');
    if (!records || records.length === 0) {
        container.innerHTML = '<p class="text-muted">暂无分析记录</p>';
        return;
    }
    container.innerHTML = records.map(r => `
        <div class="history-item" onclick="showHistoryDetail(${r.id})">
            <div class="d-flex justify-content-between align-items-center">
                <div>
                    <span class="h-ticker">${r.ticker}</span>
                    <span class="h-signal ${getSignalBadgeClass(r.signal)}" style="margin-left:12px;">${r.signal}</span>
                </div>
                <div class="h-date">${r.created_at || r.date}</div>
            </div>
            <div class="mt-1" style="font-size:12px;color:var(--text-secondary);">
                分析日期: ${r.date}
            </div>
        </div>
    `).join('');
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

// ── WebSocket alert notifications ──────────────────────────────────────────

socket.on('alert_triggered', data => {
    showToast(`🚨 预警触发: ${data.ticker} ${data.condition} ${data.threshold}`, 'warning');
});

// ── Window resize ──────────────────────────────────────────────────────────

window.addEventListener('resize', () => {
    if (chartPnl) chartPnl.resize();
    if (chartAllocation) chartAllocation.resize();
});

// ── Init ───────────────────────────────────────────────────────────────────

loadDashboard();
