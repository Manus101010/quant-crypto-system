/* QuantCore SPA router + shared utilities */

// ── Persistent state helpers ─────────────────────────────────────────────────
const _PERSIST_KEYS = ['macroResult', 'analystResults', 'scanResults', 'cryptoScanResults'];
const _STALE_MS     = 4 * 60 * 60 * 1000; // 4 hours — treat cached data as stale after this

function _loadPersisted() {
  const out = {};
  for (const key of _PERSIST_KEYS) {
    try {
      const raw = localStorage.getItem(`qc_${key}`);
      if (raw) {
        const { value, ts } = JSON.parse(raw);
        // Keep it even if stale — just flag it; user can re-run
        out[key] = value;
        out[`${key}_ts`] = ts;
      }
    } catch(e) {}
  }
  return out;
}

// In-memory freshness map. This is the source of truth for how fresh the
// CURRENTLY DISPLAYED data is: a fetch this session records here even if the
// localStorage write fails (quota). Without this, a failed persist left the
// macro label frozen at a days-old timestamp forever (the "12d old" bug).
const _fetchedAt = {};
// Large caches evicted first when localStorage is full so small critical
// state (macroResult) still persists.
const _EVICTABLE = ['cryptoScanResults', 'scanResults', 'analystResults'];

function _persist(key, value) {
  _fetchedAt[key] = Date.now();          // always record real fetch time
  const payload = JSON.stringify({ value, ts: _fetchedAt[key] });
  try {
    localStorage.setItem(`qc_${key}`, payload);
  } catch (e) {
    // Quota exceeded — evict big caches (except the one we're writing) and retry once.
    for (const ev of _EVICTABLE) {
      if (ev === key) continue;
      try { localStorage.removeItem(`qc_${ev}`); } catch (_) {}
    }
    try { localStorage.setItem(`qc_${key}`, payload); } catch (_) { /* give up; in-memory time still correct */ }
  }
}

function _tsFor(key) {
  // Prefer this session's real fetch time; fall back to persisted localStorage ts.
  if (_fetchedAt[key] != null) return _fetchedAt[key];
  try {
    const raw = localStorage.getItem(`qc_${key}`);
    if (!raw) return null;
    return JSON.parse(raw).ts ?? null;
  } catch (e) { return null; }
}

function _isStale(key) {
  const ts = _tsFor(key);
  return ts != null && (Date.now() - ts) > _STALE_MS;
}

function _ageLabel(key) {
  const ts = _tsFor(key);
  if (ts == null) return null;
  const mins = Math.round((Date.now() - ts) / 60000);
  if (mins < 1)   return 'just now';
  if (mins < 60)  return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24)   return `${hrs}h ago`;
  return `${Math.round(hrs/24)}d ago`;
}

// ── Global state ─────────────────────────────────────────────────────────────
const _persisted = _loadPersisted();
const State = {
  macroResult:          _persisted.macroResult       ?? null,
  analystResults:       _persisted.analystResults    ?? [],
  scanResults:          _persisted.scanResults       ?? [],
  cryptoScanResults:    _persisted.cryptoScanResults ?? [],
  currentPage:          'dashboard',
  activeStream:         null,   // live EventSource during analysis
  analysisRunning:      false,
  analysisDone:         0,
  analysisTotal:        0,
  analysisTicker:       '',
};

// ── Colour helpers ────────────────────────────────────────────────────────────
function scoreColor(s) {
  if (s >= 70) return '#4ade80';
  if (s >= 40) return '#facc15';
  return '#f87171';
}
function scoreBarClass(s) {
  if (s >= 70) return 'bar-teal';
  if (s >= 40) return 'bar-amber';
  return 'bar-red';
}
function regimeClass(regime) {
  if (!regime) return 'regime-cautious';
  const r = regime.toLowerCase();
  if (r.includes('aggressive')) return 'regime-aggressive';
  if (r.includes('moderate'))   return 'regime-moderate';
  if (r.includes('cautious'))   return 'regime-cautious';
  return 'regime-avoid';
}
function fmtNum(v, dec = 2) {
  if (v == null) return '—';
  return Number(v).toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec });
}
function fmtPct(v, dec = 1) {
  if (v == null) return '—';
  return (v * 100).toFixed(dec) + '%';
}

// ── Loading / error helpers ───────────────────────────────────────────────────
function loadingHTML(msg = 'Loading…') {
  return `<div class="loading-wrap"><div class="spinner"></div><div class="loading-text">${msg}</div></div>`;
}
function errorHTML(msg) {
  return `<div class="error-state">⚠ ${msg}</div>`;
}

// ── Terminal log ──────────────────────────────────────────────────────────────
let _logInterval = null;

async function refreshTerminal(elId = 'terminal-log') {
  const el = document.getElementById(elId);
  if (!el) return;
  try {
    const data = await API.getLogs(30);
    const icons = { ok: '✓', info: 'ℹ', warn: '⚠', err: '✗' };
    el.innerHTML = data.logs.map(l =>
      `<div class="log-line"><span class="log-ts">[${l.ts}]</span> ` +
      `<span class="log-${l.level}">${icons[l.level] || '·'} ${escHtml(l.message)}</span></div>`
    ).join('');
  } catch (_) { /* silent */ }
}

function startLogPoller(elId = 'terminal-log') {
  stopLogPoller();
  refreshTerminal(elId);
  _logInterval = setInterval(() => refreshTerminal(elId), 4000);
}

function stopLogPoller() {
  if (_logInterval) { clearInterval(_logInterval); _logInterval = null; }
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
// Safe for use inside HTML attribute values (also escapes " and ')
function attrEsc(s) {
  return escHtml(s).replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

// ── Topbar helpers ────────────────────────────────────────────────────────────
function setTopbar(title, actionsHTML = '', regime = null) {
  document.getElementById('page-title').textContent = title;
  document.getElementById('topbar-right').innerHTML = actionsHTML;
  const chip = document.getElementById('regime-chip');
  if (regime && State.macroResult) {
    chip.textContent = `⬡ ${State.macroResult.regime}`;
    chip.style.display = 'flex';
  } else {
    chip.style.display = 'none';
  }
}

// ── Plotly gauge ─────────────────────────────────────────────────────────────
function renderGauge(divId, score, label) {
  if (typeof Plotly === 'undefined') return;
  const color = scoreColor(score);
  Plotly.newPlot(divId, [{
    type: 'indicator', mode: 'gauge',
    value: score,
    gauge: {
      axis: { range: [0, 100], tickcolor: '#334155', tickfont: { color: '#334155', size: 9 }, nticks: 5 },
      bar:  { color, thickness: 0.28 },
      bgcolor: '#1e293b', bordercolor: '#1e293b',
      steps: [
        { range: [0, 40],   color: '#1a0a0a' },
        { range: [40, 70],  color: '#1a1500' },
        { range: [70, 100], color: '#061a0e' },
      ],
      threshold: { line: { color: '#475569', width: 1.5 }, thickness: 0.7, value: 60 },
    },
  }], {
    height: 120, paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
    margin: { l: 14, r: 14, t: 10, b: 0 },
    font: { color: '#94a3b8' },
  }, { displayModeBar: false, responsive: true });
}

// ── Plotly radar ──────────────────────────────────────────────────────────────
function renderRadar(divId, labels, values, maxVal = 100, color = '#00d4aa') {
  if (typeof Plotly === 'undefined') return;
  const L = [...labels, labels[0]];
  const V = [...values, values[0]];
  const mid = [...labels.map(() => maxVal * 0.5), maxVal * 0.5];
  Plotly.newPlot(divId, [
    {
      type: 'scatterpolar', r: V, theta: L, fill: 'toself',
      fillcolor: `${color}1a`,
      line: { color, width: 2 },
      name: 'Score',
    },
    {
      type: 'scatterpolar', r: mid, theta: L,
      line: { color: '#334155', width: 1, dash: 'dot' },
      name: 'Mid', showlegend: false,
    },
  ], {
    paper_bgcolor: 'transparent',
    polar: {
      bgcolor: '#0d1421',
      radialaxis: { range: [0, maxVal], tickfont: { color: '#334155', size: 9 }, gridcolor: '#1e293b', linecolor: '#1e293b' },
      angularaxis: { tickfont: { color: '#94a3b8', size: 10 }, gridcolor: '#1e293b', linecolor: '#1e293b' },
    },
    legend: { bgcolor: '#0d1421', bordercolor: '#1e293b', font: { color: '#94a3b8' } },
    height: 320, margin: { l: 50, r: 50, t: 30, b: 30 },
  }, { displayModeBar: false, responsive: true });
}

// ── Plotly line chart ─────────────────────────────────────────────────────────
function renderLine(divId, traces, layout = {}) {
  if (typeof Plotly === 'undefined') return;
  const base = {
    paper_bgcolor: 'transparent', plot_bgcolor: '#0d1421',
    font: { color: '#94a3b8', family: 'Space Grotesk' },
    xaxis: { gridcolor: '#1e293b', linecolor: '#1e293b', tickfont: { size: 10 } },
    yaxis: { gridcolor: '#1e293b', linecolor: '#1e293b', tickfont: { size: 10 } },
    legend: { bgcolor: '#111827', bordercolor: '#1e293b' },
    margin: { l: 48, r: 16, t: 20, b: 36 },
    ...layout,
  };
  Plotly.newPlot(divId, traces, base, { displayModeBar: false, responsive: true });
}

// ── Tooltip registry ──────────────────────────────────────────────────────────
// Store tip HTML in a Map; put only the key in data-tip to avoid HTML-attribute
// escaping issues (e.g. double-quotes breaking the attribute mid-string).
const _TIP_REGISTRY = new Map();
let   _TIP_SEQ      = 0;

function registerTip(html) {
  const key = 't' + (_TIP_SEQ++);
  _TIP_REGISTRY.set(key, html);
  return key;
}

// Convenience: wrap an element's inline content; returns data-tip="key" attribute string
function tipAttr(html) {
  return `data-tip="${registerTip(html)}"`;
}

// ── Global tooltip engine ─────────────────────────────────────────────────────
(function _initTooltip() {
  const TIP_OFFSET = 12;
  let _el  = null;
  let _raf = null;

  function _getEl() {
    if (!_el) _el = document.getElementById('qc-tooltip');
    return _el;
  }

  function _show(key, mouseX, mouseY) {
    const el = _getEl();
    if (!el) return;
    // Support both registry keys (e.g. "t0") and inline text (legacy inline data-tip="...")
    const html = _TIP_REGISTRY.get(key) || key;
    if (!html) return;
    el.innerHTML = html;
    el.classList.add('visible');
    _position(mouseX, mouseY);
  }

  function _position(mx, my) {
    const el = _getEl();
    if (!el) return;
    const vw = window.innerWidth, vh = window.innerHeight;
    const w  = el.offsetWidth  || 260;
    const h  = el.offsetHeight || 60;
    let left = mx + TIP_OFFSET;
    let top  = my + TIP_OFFSET;
    if (left + w > vw - 8)  left = mx - w - TIP_OFFSET;
    if (top  + h > vh - 8)  top  = my - h - TIP_OFFSET;
    el.style.left = left + 'px';
    el.style.top  = top  + 'px';
  }

  function _hide() {
    const el = _getEl();
    if (el) el.classList.remove('visible');
  }

  document.addEventListener('mouseover', function(e) {
    const target = e.target.closest('[data-tip]');
    if (!target) { _hide(); return; }
    const key = target.dataset.tip;
    if (!key) { _hide(); return; }
    _show(key, e.clientX, e.clientY);
  });

  document.addEventListener('mousemove', function(e) {
    const el = _getEl();
    if (!el || !el.classList.contains('visible')) return;
    if (_raf) cancelAnimationFrame(_raf);
    _raf = requestAnimationFrame(() => _position(e.clientX, e.clientY));
  });

  document.addEventListener('mouseout', function(e) {
    const target = e.target.closest('[data-tip]');
    if (!target) return;
    const related = e.relatedTarget;
    if (related && (related === target || target.contains(related))) return;
    _hide();
  });

  document.addEventListener('click', _hide);
  document.addEventListener('scroll', _hide, true);
})();

// ── Router ────────────────────────────────────────────────────────────────────
async function navigate(page) {
  stopLogPoller();
  State.currentPage = page;

  // Update active nav
  document.querySelectorAll('.nav-item').forEach(el => {
    el.classList.toggle('active', el.dataset.page === page);
  });

  const content = document.getElementById('page-content');
  content.innerHTML = loadingHTML('Loading page…');

  try {
    await Pages[page](content);
  } catch (err) {
    content.innerHTML = errorHTML(err.message || 'Page failed to load');
    console.error(err);
  }
}

// ── Boot ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.nav-item[data-page]').forEach(el => {
    el.addEventListener('click', e => { e.preventDefault(); navigate(el.dataset.page); });
  });

  // Check API key status
  API.getStatus().then(s => {
    const dot = document.querySelector('.status-dot');
    const txt = document.getElementById('status-text');
    if (!s.api_key_set) {
      dot.style.background = '#f59e0b';
      dot.style.boxShadow  = '0 0 6px #f59e0b';
      txt.textContent = 'No API Key';
    }
  }).catch(() => {});

  navigate('dashboard');
});
