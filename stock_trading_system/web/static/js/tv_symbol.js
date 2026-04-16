/*
 * toTVSymbol — map system ticker → TradingView symbol.
 *
 * Pure function, no DOM/network dependencies, so it's unit-testable via
 * Node.js (see tests/frontend/test_tv_symbol.js).
 *
 * Rules (ARCHITECTURE_UPGRADE_PROPOSAL.md §4.7):
 *   6xxxxx            -> SSE:<ticker>        (Shanghai main board)
 *   0xxxxx / 3xxxxx   -> SZSE:<ticker>       (Shenzhen / ChiNext)
 *   8xxxxx / 4xxxxx   -> BSE:<ticker>        (Beijing Stock Exchange)
 *   HK xxxx / xxxxx   -> HKEX:<ticker>
 *   ticker in NYSE whitelist  -> NYSE:<ticker>
 *   AMEX whitelist            -> AMEX:<ticker>
 *   otherwise (US)            -> NASDAQ:<ticker>   (safe default)
 *
 * The exchange prefix matters because TradingView routes the data feed by
 * venue — guessing the wrong venue yields "invalid symbol" errors.
 */

// Common NYSE-listed US equities. Extend as encountered.
const NYSE_WHITELIST = new Set([
  // Mega-cap financials
  'JPM', 'BAC', 'GS', 'MS', 'C', 'WFC', 'BLK', 'SCHW',
  // Berkshire + insurance
  'BRK.A', 'BRK.B', 'TRV', 'MET', 'PRU', 'AIG',
  // Consumer / retail
  'KO', 'PEP', 'MCD', 'WMT', 'TGT', 'LOW', 'HD', 'DIS', 'NKE', 'PG', 'UL',
  // Industrials / energy
  'BA', 'CAT', 'MMM', 'GE', 'HON', 'LMT', 'RTX', 'DE',
  'XOM', 'CVX', 'COP', 'SLB',
  // Healthcare
  'JNJ', 'PFE', 'MRK', 'LLY', 'UNH', 'ABBV', 'BMY', 'ABT',
  // Telecom / media / utility
  'T', 'VZ', 'NEE', 'SO', 'D',
  // Transport / autos
  'UPS', 'FDX', 'F', 'GM',
  // Blue-chip tech on NYSE (not NASDAQ)
  'IBM', 'ORCL', 'CRM', 'NOW',
  // Commodities / materials
  'GLD', 'SLV', 'FCX', 'NEM',
  // Broad ETFs (SPY is NYSE ARCA)
  'SPY', 'VOO', 'VTI', 'IWM', 'DIA', 'EFA', 'EEM',
]);

const AMEX_WHITELIST = new Set([
  // Commonly mis-routed, explicit AMEX listings
  'IMO', 'AU',
]);

/**
 * Convert an internal ticker to a TradingView-qualified symbol.
 * @param {string} ticker
 * @returns {string} e.g. "NASDAQ:AAPL", "SSE:600519"
 */
function toTVSymbol(ticker) {
  if (!ticker || typeof ticker !== 'string') return '';
  const t = ticker.trim().toUpperCase();
  if (!t) return '';

  // HK: "0700.HK" or "00700.HK" style
  const hk = t.match(/^0*(\d{3,5})\.HK$/);
  if (hk) return `HKEX:${hk[1].padStart(4, '0')}`;

  // A-share (6 digits)
  if (/^\d{6}$/.test(t)) {
    const firstTwo = t.substring(0, 2);
    const first = t[0];
    // SSE: 600, 601, 603, 605, 688 (STAR), 900 (B-share)
    if (first === '6' || firstTwo === '90') return `SSE:${t}`;
    // SZSE: 000, 001, 002, 003, 300 (ChiNext), 200 (B-share)
    if (first === '0' || first === '3' || firstTwo === '20') return `SZSE:${t}`;
    // BSE: 8, 43, 83, 87, 88, 92
    if (first === '8' || first === '4') return `BSE:${t}`;
    // Fallback for other 6-digit patterns — default to SSE
    return `SSE:${t}`;
  }

  // Explicit venue prefix already supplied (user pasted "NYSE:JPM")
  const prefixed = t.match(/^(NYSE|NASDAQ|AMEX|HKEX|SSE|SZSE|BSE|OTC|TSX|LSE):.+/);
  if (prefixed) return t;

  // US equities — class share "BRK.B" is accepted as-is inside the whitelist
  if (NYSE_WHITELIST.has(t)) return `NYSE:${t}`;
  if (AMEX_WHITELIST.has(t)) return `AMEX:${t}`;

  // Default: most US common stocks trade on NASDAQ or can be found by it.
  // TradingView is forgiving when the fallback venue is close enough.
  return `NASDAQ:${t}`;
}

// Dual export so both <script> tag and Node can consume it.
if (typeof module !== 'undefined' && module.exports) {
  module.exports = { toTVSymbol, NYSE_WHITELIST, AMEX_WHITELIST };
} else if (typeof window !== 'undefined') {
  window.toTVSymbol = toTVSymbol;
}
