/* === Stock Trading System - Frontend === */

const socket = io();
let chartPnl = null;
let chartAllocation = null;
let chartKline = null;
let currentKlineTicker = null;
let currentKlineRange = '1mo';

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

function runAnalysis() {
    const ticker = document.getElementById('analyze-ticker').value.trim().toUpperCase();
    const date = document.getElementById('analyze-date').value;
    if (!ticker) { showToast('请输入股票代码', 'warning'); return; }

    // Load price chart + fundamentals + news immediately (fast preview)
    loadQuickData(ticker);

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

function renderSettingsConfig(s) {
    const box = document.getElementById('settings-config');
    if (!box || !s) return;
    const gemini = s.gemini || {};
    const qwen = s.qwen || {};
    const telegram = s.telegram || {};
    const email = s.email || {};
    const portfolio = s.portfolio || {};
    const rows = [
        ['Gemini 模型', gemini.model || '--'],
        ['Gemini 深度模型', gemini.deep_think_model || '--'],
        ['Gemini API Key', gemini.api_key_masked || '未配置'],
        ['Polygon API Key', (s.polygon && s.polygon.api_key_masked) || '未配置'],
        ['Qwen 状态', qwen.enabled ? '<span class="text-green">已启用</span>' : '<span class="text-muted">未启用</span>'],
        ['Qwen 模型', qwen.model || '--'],
        ['Qwen API Key', qwen.api_key_masked || '未配置'],
        ['Telegram Bot Token', telegram.bot_token_masked || '未配置'],
        ['Telegram Chat ID', telegram.chat_id || '未配置'],
        ['Email SMTP', email.smtp_host ? `${email.smtp_host}:${email.smtp_port}` : '未配置'],
        ['Email 用户', email.username || '未配置'],
        ['Email 收件人', email.to_address || '未配置'],
        ['持仓数据库', portfolio.db_path || '--'],
    ];
    box.innerHTML = rows.map(([k, v]) => `
        <div class="settings-row">
            <span class="label">${k}</span>
            <span class="value">${v}</span>
        </div>
    `).join('');
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

// ── Window resize ──────────────────────────────────────────────────────────

window.addEventListener('resize', () => {
    if (chartPnl) chartPnl.resize();
    if (chartAllocation) chartAllocation.resize();
    if (chartKline) chartKline.resize();
});

// ── Init ───────────────────────────────────────────────────────────────────

loadDashboard();
