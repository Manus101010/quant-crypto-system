/* QuantCore API client — all server calls centralised here */
const API = {
  base: '',

  async _get(path) {
    const r = await fetch(this.base + path);
    if (!r.ok) throw new Error(`API ${path} → ${r.status}`);
    return r.json();
  },

  async _post(path, body) {
    const r = await fetch(this.base + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(`API POST ${path} → ${r.status}`);
    return r.json();
  },

  async _delete(path) {
    const r = await fetch(this.base + path, { method: 'DELETE' });
    if (!r.ok) throw new Error(`API DELETE ${path} → ${r.status}`);
    return r.json();
  },

  // ── Macro ─────────────────────────────────────────────────────────────
  runMacro:    () => API._get('/api/macro/run'),
  latestMacro: () => API._get('/api/macro/latest'),

  // ── Analyst ───────────────────────────────────────────────────────────
  latestAnalyst: () => API._get('/api/analyst/latest'),
  analyzeStream(tickers, force = false, onEvent, onDone, onError) {
    const url = `/api/analyst/analyze/stream?tickers=${encodeURIComponent(tickers)}&force=${force}`;
    const es = new EventSource(url);
    es.onmessage = e => {
      try {
        const data = JSON.parse(e.data);
        if (data.status === 'complete') { es.close(); onDone(data.results); }
        else onEvent(data);
      } catch (err) { onError(err); }
    };
    es.onerror = err => { es.close(); onError(err); };
    return es;
  },

  // ── Scanner ───────────────────────────────────────────────────────────
  runScanner:       (params = '') => API._get('/api/scanner/run'        + (params ? '?' + params : '')),
  runCryptoScanner:  (params = '') => API._get('/api/scanner/run/crypto'   + (params ? '?' + params : '')),
  cryptoUniverse:   (size = 100)  => API._get(`/api/scanner/universe/crypto?size=${size}`),
  latestScanner:    ()            => API._get('/api/scanner/latest'),
  latestCrypto:     ()            => API._get('/api/scanner/latest/crypto'),

  // ── Journal ───────────────────────────────────────────────────────────
  getJournal:   (params = '') => API._get('/api/journal/entries' + (params ? '?' + params : '')),
  getJournalStats: ()         => API._get('/api/journal/stats'),
  addJournal:   body          => API._post('/api/journal/entries', body),
  deleteJournal: id           => API._delete(`/api/journal/entries/${id}`),

  // ── Paper Trades ──────────────────────────────────────────────────────
  getPaperTrades:    (status) => API._get(`/api/paper_trades${status ? '?status='+status : ''}`),
  getLivePrices:     ()       => API._get('/api/paper_trades/live'),
  openPaperTrade:    (body)   => API._post('/api/paper_trades', body),
  closePaperTrade:   (id, body) => API._put(`/api/paper_trades/${id}/close`, body),
  deletePaperTrade:  (id)     => API._delete(`/api/paper_trades/${id}`),
  checkPaperTrades:  ()       => API._post('/api/paper_trades/check', {}),
  getPaperStats:     ()       => API._get('/api/paper_trades/stats'),

  // ── Loop ──────────────────────────────────────────────────────────────
  runLoop:      (body) => API._post('/api/loop/run', body || {universe:'crypto',top_n:100}),
  checkLoop:    ()     => API._post('/api/loop/check', {}),
  getLoopStatus:()     => API._get('/api/loop/status'),
  pauseLoop:    ()     => API._post('/api/loop/pause', {}),
  resumeLoop:   ()     => API._post('/api/loop/resume', {}),

  // ── System ────────────────────────────────────────────────────────────
  getLogs:   (n = 30) => API._get(`/api/system/logs?n=${n}`),
  getStatus: ()       => API._get('/api/system/status'),
};
