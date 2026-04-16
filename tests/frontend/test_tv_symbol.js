/*
 * toTVSymbol() unit tests — TV-5.1.4 ~ TV-5.1.7 and extensions.
 *
 * Run with: node tests/frontend/test_tv_symbol.js
 * Exit code 0 = all green. Non-zero = failure count.
 */

const path = require('path');
const { toTVSymbol } = require(
  path.join(__dirname, '..', '..', 'stock_trading_system', 'web', 'static', 'js', 'tv_symbol.js')
);

let passed = 0;
let failed = 0;
const failures = [];

function assertEq(actual, expected, label) {
  if (actual === expected) {
    passed++;
  } else {
    failed++;
    failures.push(`✗ ${label}\n    expected: ${JSON.stringify(expected)}\n    actual:   ${JSON.stringify(actual)}`);
  }
}

// ── TV-5.1.4 US NASDAQ default ─────────────────────────────────────────────
assertEq(toTVSymbol('AAPL'), 'NASDAQ:AAPL', 'AAPL -> NASDAQ:AAPL');
assertEq(toTVSymbol('TSLA'), 'NASDAQ:TSLA', 'TSLA -> NASDAQ:TSLA');
assertEq(toTVSymbol('NVDA'), 'NASDAQ:NVDA', 'NVDA -> NASDAQ:NVDA');
assertEq(toTVSymbol('MSFT'), 'NASDAQ:MSFT', 'MSFT -> NASDAQ:MSFT');

// ── TV-5.1.5 NYSE whitelist ───────────────────────────────────────────────
assertEq(toTVSymbol('JPM'), 'NYSE:JPM', 'JPM -> NYSE');
assertEq(toTVSymbol('BAC'), 'NYSE:BAC', 'BAC -> NYSE');
assertEq(toTVSymbol('BRK.B'), 'NYSE:BRK.B', 'BRK.B -> NYSE');
assertEq(toTVSymbol('KO'), 'NYSE:KO', 'KO -> NYSE');
assertEq(toTVSymbol('SPY'), 'NYSE:SPY', 'SPY ETF -> NYSE');
assertEq(toTVSymbol('JNJ'), 'NYSE:JNJ', 'JNJ -> NYSE');

// ── TV-5.1.6 Shanghai A-share ─────────────────────────────────────────────
assertEq(toTVSymbol('600519'), 'SSE:600519', '600519 -> SSE');   // Moutai
assertEq(toTVSymbol('601398'), 'SSE:601398', '601398 -> SSE');   // ICBC
assertEq(toTVSymbol('603288'), 'SSE:603288', '603288 -> SSE');   // Haitian
assertEq(toTVSymbol('688111'), 'SSE:688111', '688111 -> SSE (STAR)');
assertEq(toTVSymbol('900901'), 'SSE:900901', '900901 -> SSE (B-share)');

// ── TV-5.1.7 Shenzhen A-share (ChiNext / main) ────────────────────────────
assertEq(toTVSymbol('000001'), 'SZSE:000001', '000001 -> SZSE'); // PAB
assertEq(toTVSymbol('000002'), 'SZSE:000002', '000002 -> SZSE'); // Vanke
assertEq(toTVSymbol('002594'), 'SZSE:002594', '002594 -> SZSE'); // BYD
assertEq(toTVSymbol('300750'), 'SZSE:300750', '300750 -> SZSE (ChiNext)');
assertEq(toTVSymbol('200011'), 'SZSE:200011', '200011 -> SZSE (B-share)');

// ── Beijing Stock Exchange ────────────────────────────────────────────────
assertEq(toTVSymbol('830799'), 'BSE:830799', '830799 -> BSE');
assertEq(toTVSymbol('430139'), 'BSE:430139', '430139 -> BSE');

// ── Hong Kong ─────────────────────────────────────────────────────────────
assertEq(toTVSymbol('0700.HK'), 'HKEX:0700', '0700.HK -> HKEX:0700');
assertEq(toTVSymbol('00700.HK'), 'HKEX:0700', '00700.HK -> HKEX:0700 (normalized)');
assertEq(toTVSymbol('9988.HK'), 'HKEX:9988', '9988.HK -> HKEX:9988');

// ── Case / whitespace normalization ───────────────────────────────────────
assertEq(toTVSymbol('aapl'), 'NASDAQ:AAPL', 'lowercase upcased');
assertEq(toTVSymbol('  AAPL  '), 'NASDAQ:AAPL', 'trim whitespace');
assertEq(toTVSymbol('AaPl'), 'NASDAQ:AAPL', 'mixed case');

// ── Already-prefixed passes through ───────────────────────────────────────
assertEq(toTVSymbol('NYSE:JPM'), 'NYSE:JPM', 'NYSE:JPM passes through');
assertEq(toTVSymbol('HKEX:0700'), 'HKEX:0700', 'HKEX:0700 passes through');
assertEq(toTVSymbol('NASDAQ:AAPL'), 'NASDAQ:AAPL', 'NASDAQ:AAPL passes through');

// ── Edge cases ────────────────────────────────────────────────────────────
assertEq(toTVSymbol(''), '', 'empty -> empty');
assertEq(toTVSymbol(null), '', 'null -> empty');
assertEq(toTVSymbol(undefined), '', 'undefined -> empty');
assertEq(toTVSymbol(123), '', 'non-string -> empty');
assertEq(toTVSymbol('   '), '', 'whitespace only -> empty');

// ── Unknown US ticker defaults to NASDAQ ──────────────────────────────────
assertEq(toTVSymbol('ZZZZ'), 'NASDAQ:ZZZZ', 'unknown US -> NASDAQ default');
assertEq(toTVSymbol('AMZN'), 'NASDAQ:AMZN', 'AMZN -> NASDAQ');

// ── Report ────────────────────────────────────────────────────────────────
console.log(`\n${passed} passed, ${failed} failed (total ${passed + failed})`);
if (failed > 0) {
  console.log('\nFailures:');
  failures.forEach(f => console.log('  ' + f));
  process.exit(1);
}
