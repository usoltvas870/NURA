// Tests for NURA PWA detectScenario (frontend/pwa-install.js)
// Run: node test_pwa_detect.mjs

import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert';

const __dirname = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(__dirname, 'pwa-install.js'), 'utf-8');

// Extract detectScenario function body
// The function signature: function detectScenario(nav) { ... }
const fnMatch = src.match(/function detectScenario\(nav\)\s*\{[\s\S]*?^\s{2}\}/m);
if (!fnMatch) {
  console.error('Could not extract detectScenario from pwa-install.js');
  process.exit(1);
}

let fnBody = fnMatch[0];
// Make it a standalone callable function with mockable window
const detectScenario = new Function('nav', 'window', fnBody + '\nreturn detectScenario(nav);');

// Mock window for node env
const mockWindow = {
  matchMedia: function () { return { matches: false }; },
  MSStream: undefined
};

// --- Test cases ---

const tests = [];

function addTest(label, nav, expected, notes) {
  tests.push({ label, nav, expected, notes });
}

// Chrome Desktop Win
addTest(
  'Chrome Desktop Windows',
  { userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36', standalone: false, userAgentData: null },
  'chromium',
  'beforeinstallprompt supported'
);

// Chrome Desktop Mac
addTest(
  'Chrome Desktop macOS',
  { userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36', standalone: false, userAgentData: null },
  'chromium',
  'beforeinstallprompt supported'
);

// Chrome Android
addTest(
  'Chrome Android',
  { userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36', standalone: false, userAgentData: null },
  'chromium',
  'beforeinstallprompt supported'
);

// Edge Desktop
addTest(
  'Edge Desktop Windows',
  { userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0', standalone: false, userAgentData: null },
  'chromium',
  'Chromium-based Edge, supports BIP'
);

// Opera Desktop
addTest(
  'Opera Desktop Windows',
  { userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 OPR/110.0.0.0', standalone: false, userAgentData: null },
  'opera',
  'Opera — no beforeinstallprompt'
);

// Opera Mobile Android
addTest(
  'Opera Mobile Android',
  { userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36 OPR/82.0.0.0', standalone: false, userAgentData: null },
  'opera',
  'Opera Mobile — no BIP'
);

// Opera Mini
addTest(
  'Opera Mini Android',
  { userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36 OPR/82.0.0.0', standalone: false, userAgentData: null },
  'opera',
  'Opera — no BIP'
);

// Brave Desktop
addTest(
  'Brave Desktop Windows',
  { userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36', standalone: false, userAgentData: null },
  'chromium',
  'Brave uses Chrome UA, detected as Chromium'
);

// iOS Safari
addTest(
  'iOS Safari iPhone',
  { userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1', standalone: false, userAgentData: null },
  'ios',
  'iOS Safari — custom modal'
);

// iOS Safari iPad
addTest(
  'iOS Safari iPad',
  { userAgent: 'Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1', standalone: false, userAgentData: null },
  'ios',
  'iPadOS Safari — custom modal'
);

// iOS Chrome (still iOS, no BIP — but chrome on iOS uses WebKit, not real Chrome)
addTest(
  'Chrome on iOS',
  { userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/125.0.6422.80 Mobile/15E148 Safari/604.1', standalone: false, userAgentData: null },
  'ios',
  'Chrome on iOS is actually WebKit, no BIP — treat as iOS'
);

// Firefox Desktop
addTest(
  'Firefox Desktop Windows',
  { userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0', standalone: false, userAgentData: null },
  'unknown',
  'Firefox — no beforeinstallprompt'
);

// Firefox Android
addTest(
  'Firefox Android',
  { userAgent: 'Mozilla/5.0 (Android 14; Mobile; rv:127.0) Gecko/127.0 Firefox/127.0', standalone: false, userAgentData: null },
  'unknown',
  'Firefox Android — no BIP'
);

// Samsung Internet
addTest(
  'Samsung Internet Android',
  { userAgent: 'Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/25.0 Chrome/125.0.6422.80 Mobile Safari/537.36', standalone: false, userAgentData: null },
  'chromium',
  'Samsung Internet is Chromium-based, supports BIP'
);

// Yandex Browser
addTest(
  'Yandex Browser Desktop',
  { userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.6422.80 YaBrowser/24.4.0.0 Safari/537.36', standalone: false, userAgentData: null },
  'chromium',
  'Yandex Browser is Chromium-based'
);

// Already installed — standalone mode
addTest(
  'Already installed (standalone true)',
  { userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36', standalone: true, userAgentData: null },
  'installed',
  'PWA already running'
);

// Already installed — display-mode matches
addTest(
  'Already installed (display-mode: standalone)',
  { userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36', standalone: false, userAgentData: null },
  'installed',
  'display-mode: standalone matched'
);

// userAgentData brands — Chrome
addTest(
  'userAgentData: Chrome',
  { userAgent: '', standalone: false, userAgentData: { brands: [{ brand: 'Google Chrome', version: '125' }, { brand: 'Chromium', version: '125' }, { brand: 'Not=A?Brand', version: '99' }] } },
  'chromium',
  'Detected via User-Agent Client Hints'
);

// userAgentData brands — Edge
addTest(
  'userAgentData: Edge',
  { userAgent: '', standalone: false, userAgentData: { brands: [{ brand: 'Microsoft Edge', version: '125' }, { brand: 'Chromium', version: '125' }, { brand: 'Not=A?Brand', version: '99' }] } },
  'chromium',
  'Edge detected via UA-CH'
);

// userAgentData brands — Opera
addTest(
  'userAgentData: Opera',
  { userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 OPR/110.0.0.0', standalone: false, userAgentData: { brands: [{ brand: 'Opera', version: '110' }, { brand: 'Chromium', version: '125' }, { brand: 'Not=A?Brand', version: '99' }] } },
  'opera',
  'Opera detected via UA string (checked before UA-CH)'
);

// --- Run ---

let passed = 0;
let failed = 0;

for (const t of tests) {
  let mockW = { ...mockWindow };
  if (t.expected === 'installed' && !t.nav.standalone) {
    // Simulate display-mode: standalone
    mockW.matchMedia = function () { return { matches: true }; };
  }
  const result = detectScenario(t.nav, mockW);
  if (result === t.expected) {
    passed++;
  } else {
    failed++;
    console.log(`FAIL: ${t.label}`);
    console.log(`  Expected: ${t.expected}, Got: ${result}`);
    console.log(`  Notes: ${t.notes || '—'}`);
    console.log(`  UA: ${(t.nav.userAgent || '(userAgentData)').substring(0, 120)}`);
  }
}

console.log(`\nResults: ${passed} passed, ${failed} failed, ${tests.length} total`);
if (failed > 0) process.exit(1);
