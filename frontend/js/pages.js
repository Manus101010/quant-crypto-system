/* QuantCore — all page render functions */

const Pages = {

  // ── Dashboard ─────────────────────────────────────────────────────────────
  async dashboard(container) {
    setTopbar('Dashboard',
      `<button class="btn btn-secondary btn-sm" onclick="navigate('macro')">▦ Macro Gate</button>
       <button class="btn btn-amber btn-sm" onclick="navigate('scanner')">⊞ Run Scanner</button>
       <button class="btn btn-primary btn-sm" onclick="navigate('analyst')">◉ Analyst</button>`
    );

    container.innerHTML = `
      <div class="metrics-row">
        <div class="metric-card" style="--card-top:#00d4aa">
          <div class="metric-label">Deployment Score</div>
          <div class="metric-value" id="m-deploy" style="color:#94a3b8">—</div>
          <div class="metric-sub" id="m-regime">Run Macro Gate to score</div>
        </div>
        <div class="metric-card" style="--card-top:#3b82f6">
          <div class="metric-label">Analyst Picks</div>
          <div class="metric-value" id="m-picks" style="color:#60a5fa">—</div>
          <div class="metric-sub" id="m-top-pick">Run analyst to populate</div>
        </div>
        <div class="metric-card" style="--card-top:#a855f7">
          <div class="metric-label">Setups Surfaced</div>
          <div class="metric-value" id="m-setups" style="color:#c084fc">—</div>
          <div class="metric-sub" id="m-scan-ts">Run scanner to populate</div>
        </div>
        <div class="metric-card" style="--card-top:#f59e0b">
          <div class="metric-label">Journal Win Rate</div>
          <div class="metric-value" id="m-winrate" style="color:#fbbf24">—</div>
          <div class="metric-sub" id="m-pnl">—</div>
        </div>
      </div>

      <div class="row-3">
        <!-- Scanner preview -->
        <div class="panel">
          <div class="panel-header">
            <div class="panel-title"><div class="panel-icon">⊞</div>Latest Scanner Results</div>
            <button class="btn btn-secondary btn-sm" onclick="navigate('scanner')">Full Scanner →</button>
          </div>
          <div id="dash-scanner-body">
            <div class="empty-state">Run scanner to see setups</div>
          </div>
        </div>

        <!-- Macro regime -->
        <div class="panel">
          <div class="panel-header">
            <div class="panel-title"><div class="panel-icon" style="background:rgba(245,158,11,0.1);color:#f59e0b">▦</div>Macro Regime</div>
            <button class="btn btn-secondary btn-sm" onclick="navigate('macro')">Details →</button>
          </div>
          <div class="panel-body" id="dash-macro-body">
            <div class="empty-state">Run Macro Gate first</div>
          </div>
        </div>
      </div>

      <!-- Terminal log -->
      <div class="panel" style="margin-bottom:0">
        <div class="panel-header">
          <div class="panel-title"><div class="panel-icon">◈</div>System Log</div>
          <button class="btn btn-secondary btn-sm" onclick="refreshTerminal()">↻ Refresh</button>
        </div>
        <div style="padding:12px 14px">
          <div class="terminal" id="terminal-log">
            <div class="log-line"><span class="log-ts">[—:—:—]</span> <span class="log-info">ℹ QuantCore v2.0 ready</span></div>
          </div>
        </div>
      </div>
    `;

    // Populate from cached state
    if (State.macroResult) _dashMacro(State.macroResult);
    if (State.scanResults.length) _dashScanner(State.scanResults);
    if (State.analystResults.length) {
      const top = State.analystResults[0];
      document.getElementById('m-picks').textContent  = State.analystResults.length;
      document.getElementById('m-picks').style.color  = '#60a5fa';
      document.getElementById('m-top-pick').textContent = `Top: ${top.ticker} (${top.blended_score})`;
    }

    // Journal stats
    try {
      const stats = await API.getJournalStats();
      document.getElementById('m-winrate').textContent = stats.total_trades > 0 ? stats.win_rate + '%' : '—';
      document.getElementById('m-winrate').style.color = stats.win_rate >= 50 ? '#4ade80' : '#f87171';
      document.getElementById('m-pnl').textContent =
        stats.total_trades > 0 ? `${stats.total_trades} trades · Total P&L ${stats.total_pnl > 0 ? '+' : ''}${stats.total_pnl.toFixed(1)}%` : 'No trades logged';
    } catch (_) {}

    startLogPoller('terminal-log');
  },

  // ── Scanner ───────────────────────────────────────────────────────────────
  async scanner(container) {
    setTopbar('Scanner',
      `<button class="btn btn-primary" id="scan-run-btn" onclick="window._runActiveScan && window._runActiveScan()">⊞ Scan Stocks</button>`
    );

    const _explainHTML = `
      <div style="background:rgba(0,212,170,0.05);border:1px solid rgba(0,212,170,0.15);border-radius:10px;padding:13px 16px;margin-bottom:16px;font-size:12px;color:#94a3b8;line-height:1.6">
        <span style="font-weight:700;color:#00d4aa">What is a scanner?</span>
        It automatically runs technical analysis rules across many tickers and surfaces only those that match your criteria — think of it as your first filter before you do deeper research.
        Results are <em>candidates to investigate</em>, not buy signals. Each card tells you exactly what pattern was detected and why.
      </div>`;

    container.innerHTML = `
      <div class="tab-bar" style="margin-bottom:18px">
        <div class="tab active" id="tab-scan-stocks" onclick="window._switchScanTab('stocks')">📈 Stocks</div>
        <div class="tab"        id="tab-scan-crypto" onclick="window._switchScanTab('crypto')">₿ Crypto</div>
      </div>

      <!-- ── Stocks panel ──────────────────────────────────────────────── -->
      <div id="scan-panel-stocks">
        ${_explainHTML}
        <div class="panel" style="margin-bottom:18px">
          <div class="panel-header"><div class="panel-title"><div class="panel-icon">⊞</div>Criteria — Stocks</div></div>
          <div class="panel-body">
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr 1fr;gap:12px;align-items:end">
              <div class="form-group">
                <label data-tip="How wide a net to cast. Default = ~90 curated large-caps (fast). S&P 500 = full index, institutional breadth (~503 names, ~40s scan). Custom tickers override this.">Universe</label>
                <select id="scan-universe" class="form-select">
                  <option value="default">Default (~90 large-caps)</option>
                  <option value="top">Top Stocks (megacap leaders)</option>
                  <option value="top_ai">Top AI Stocks</option>
                  <option value="top_tech">Top Tech Stocks</option>
                  <option value="sp500">S&P 500 (full index)</option>
                </select>
              </div>
              <div class="form-group">
                <label>Custom tickers (overrides universe)</label>
                <input id="scan-tickers" class="form-input" placeholder="AAPL,MSFT,NVDA…">
              </div>
              <div class="form-group">
                <label data-tip="The 200-day Simple Moving Average is the most-watched long-term trend line. Price above it = long-term uptrend. Filtering for this removes stocks in downtrends.">Must be above SMA200?</label>
                <select id="scan-sma200" class="form-select">
                  <option value="true">Yes — uptrends only</option>
                  <option value="false">No — show all</option>
                </select>
              </div>
              <div class="form-group">
                <label data-tip="RSI (Relative Strength Index) — 0-100 scale. Below 30 = oversold (may bounce). Above 70 = overbought (may pull back). 40-60 is a healthy trending range.">RSI Range</label>
                <div style="display:flex;gap:6px;align-items:center">
                  <input id="scan-rsi-min" class="form-input" type="number" value="0"   min="0" max="100" style="width:60px">
                  <span style="color:#475569;font-size:11px">to</span>
                  <input id="scan-rsi-max" class="form-input" type="number" value="100" min="0" max="100" style="width:60px">
                </div>
              </div>
              <div class="form-group">
                <label data-tip="3-month price return (%). Filters to stocks already showing positive momentum. E.g. enter 5 to only see stocks up 5%+ over 3 months.">Min 3M Momentum %</label>
                <input id="scan-mom" class="form-input" type="number" value="" placeholder="e.g. 5 (optional)">
              </div>
            </div>
          </div>
        </div>
        <div style="display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap" id="scan-stocks-strategy-bar" style="display:none">
          <button class="btn btn-secondary btn-sm scan-strat-btn active" data-strat="all"            onclick="window._filterScanResults('stocks','all')">All Setups</button>
          <button class="btn btn-secondary btn-sm scan-strat-btn"       data-strat="momentum"       onclick="window._filterScanResults('stocks','momentum')">🚀 Momentum Only</button>
          <button class="btn btn-secondary btn-sm scan-strat-btn"       data-strat="mean_reversion" onclick="window._filterScanResults('stocks','mean_reversion')">🎯 Mean Reversion Only</button>
        </div>
        <div id="scan-results-stocks">
          ${State.scanResults.length ? _scanCards(State.scanResults, 'stock') : '<div class="empty-state" style="padding:56px 0">Click ⊞ Scan Stocks to screen the market</div>'}
        </div>
      </div>

      <!-- ── Crypto panel ──────────────────────────────────────────────── -->
      <div id="scan-panel-crypto" style="display:none">
        ${_explainHTML}
        <div class="panel" style="margin-bottom:18px">
          <div class="panel-header"><div class="panel-title"><div class="panel-icon">₿</div>Criteria — Crypto</div></div>
          <div class="panel-body">
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:12px;align-items:end">
              <div class="form-group">
                <label data-tip="Choose how wide a net to cast. Top 50 = major coins, fast scan. Top 100/200 = broader market coverage but takes longer. Custom = paste your own tickers.">Universe to scan</label>
                <select id="scan-crypto-universe" class="form-select" onchange="window._onCryptoUniverseChange && window._onCryptoUniverseChange()">
                  <option value="50">Top 50 by Market Cap</option>
                  <option value="100" selected>Top 100 by Market Cap</option>
                  <option value="150">Top 150 by Market Cap</option>
                  <option value="200">Top 200 by Market Cap</option>
                  <option value="300">Top 300 by Market Cap</option>
                  <option value="400">Top 400 by Market Cap</option>
                  <option value="500">Top 500 by Market Cap</option>
                  <option value="custom">Custom tickers…</option>
                </select>
              </div>
              <div class="form-group" id="scan-crypto-custom-wrap" style="display:none">
                <label>Custom tickers</label>
                <input id="scan-crypto-tickers" class="form-input" placeholder="BTC-USD,ETH-USD,SOL-USD…">
              </div>
              <div class="form-group">
                <label data-tip="The 50-day SMA is crypto's key trend line. 'Show all' lets you see the full picture — each card shows whether a coin is above or below it so you decide.">SMA50 filter</label>
                <select id="scan-crypto-sma50" class="form-select">
                  <option value="false" selected>No — show all setups</option>
                  <option value="true">Yes — uptrends only</option>
                </select>
              </div>
              <div class="form-group">
                <label data-tip="Crypto RSI extremes are wider. Many traders use 25–80 for crypto vs 30–70 for stocks.">RSI Range</label>
                <div style="display:flex;gap:6px;align-items:center">
                  <input id="scan-crypto-rsi-min" class="form-input" type="number" value="0"   min="0" max="100" style="width:60px">
                  <span style="color:#475569;font-size:11px">to</span>
                  <input id="scan-crypto-rsi-max" class="form-input" type="number" value="100" min="0" max="100" style="width:60px">
                </div>
              </div>
              <div class="form-group">
                <label data-tip="Crypto 3-month moves of 20–50% are common in bull markets. Set a higher bar than for stocks.">Min 3M Momentum %</label>
                <input id="scan-crypto-mom" class="form-input" type="number" value="" placeholder="e.g. 10 (optional)">
              </div>
            </div>
            <div id="scan-crypto-universe-info" style="margin-top:10px;font-size:11px;color:#475569">
              Coins sourced live from CoinGecko by market cap. Stablecoins and wrapped tokens are automatically excluded.
            </div>
          </div>
        </div>
        <div style="display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap">
          <button class="btn btn-secondary btn-sm scan-strat-btn active" data-strat="all"            onclick="window._filterScanResults('crypto','all')">All Setups</button>
          <button class="btn btn-secondary btn-sm scan-strat-btn"       data-strat="momentum"       onclick="window._filterScanResults('crypto','momentum')">🚀 Momentum Only</button>
          <button class="btn btn-secondary btn-sm scan-strat-btn"       data-strat="mean_reversion" onclick="window._filterScanResults('crypto','mean_reversion')">🎯 Mean Reversion Only</button>
        </div>
        <div id="scan-results-crypto">
          ${State.cryptoScanResults?.length
            ? _scanCards(State.cryptoScanResults, 'crypto')
            : '<div class="empty-state" style="padding:56px 0">Click ₿ Scan Crypto to screen the market</div>'}
        </div>
      </div>
    `;

    // ── Tab switching ──────────────────────────────────────────────────────
    window._switchScanTab = (tab) => {
      document.getElementById('tab-scan-stocks').classList.toggle('active', tab === 'stocks');
      document.getElementById('tab-scan-crypto').classList.toggle('active', tab === 'crypto');
      document.getElementById('scan-panel-stocks').style.display = tab === 'stocks' ? '' : 'none';
      document.getElementById('scan-panel-crypto').style.display = tab === 'crypto' ? '' : 'none';
      const btn = document.getElementById('scan-run-btn');
      if (btn) btn.textContent = tab === 'stocks' ? '⊞ Scan Stocks' : '₿ Scan Crypto';
      window._activeScanTab = tab;
    };
    window._activeScanTab = 'stocks';

    // ── Dispatch to correct scanner ────────────────────────────────────────
    window._runActiveScan = () => {
      if (window._activeScanTab === 'crypto') _runCryptoScan();
      else _runStockScan();
    };

    // ── Stock scan ─────────────────────────────────────────────────────────
    const _runStockScan = async () => {
      const btn  = document.getElementById('scan-run-btn');
      const body = document.getElementById('scan-results-stocks');
      if (btn) { btn.disabled = true; btn.textContent = '⏳ Scanning…'; }
      body.innerHTML = loadingHTML('Scanning stocks — fetching 1 year of price data…');
      try {
        const mom = document.getElementById('scan-mom').value;
        const p = new URLSearchParams({
          tickers:      document.getElementById('scan-tickers').value || '',
          universe:     document.getElementById('scan-universe')?.value || 'default',
          above_sma200: document.getElementById('scan-sma200').value,
          min_rsi:      document.getElementById('scan-rsi-min').value,
          max_rsi:      document.getElementById('scan-rsi-max').value,
          ...(mom ? { min_momentum: mom } : {}),
        });
        if ((document.getElementById('scan-universe')?.value) === 'sp500' && !document.getElementById('scan-tickers').value) {
          body.innerHTML = loadingHTML('Scanning the full S&P 500 (~503 names) — chunked fetch, ~40s…');
        }
        const data = await API.runScanner(p.toString());
        State.scanResults = data.results || [];
        _persist('scanResults', State.scanResults);
        body.innerHTML = State.scanResults.length
          ? _scanCards(State.scanResults, 'stock', data.total_scanned)
          : '<div class="empty-state" style="padding:48px 0">No stocks met your criteria — try widening the RSI range or disabling the SMA200 filter.</div>';
      } catch (err) { body.innerHTML = errorHTML(err.message); }
      finally { if (btn) { btn.disabled = false; btn.textContent = '⊞ Scan Stocks'; } }
    };

    // ── Toggle custom ticker input ─────────────────────────────────────────
    window._onCryptoUniverseChange = () => {
      const val = document.getElementById('scan-crypto-universe')?.value;
      const customWrap = document.getElementById('scan-crypto-custom-wrap');
      const info = document.getElementById('scan-crypto-universe-info');
      if (customWrap) customWrap.style.display = val === 'custom' ? '' : 'none';
      if (info) {
        info.textContent = val === 'custom'
          ? 'Enter your own tickers in BTC-USD format. Separate with commas.'
          : `Will scan the live top-${val} coins by market cap from CoinGecko. Stablecoins excluded automatically.`;
      }
    };

    // ── Crypto scan ────────────────────────────────────────────────────────
    const _runCryptoScan = async () => {
      const btn  = document.getElementById('scan-run-btn');
      const body = document.getElementById('scan-results-crypto');
      const universeVal = document.getElementById('scan-crypto-universe')?.value || '100';

      const isMarketScan = universeVal !== 'custom';
      const marketSize   = isMarketScan ? parseInt(universeVal, 10) : 0;
      const customTickers = !isMarketScan ? (document.getElementById('scan-crypto-tickers')?.value || '') : '';

      if (btn) { btn.disabled = true; btn.textContent = '⏳ Scanning…'; }
      body.innerHTML = loadingHTML(
        isMarketScan
          ? `Fetching top-${marketSize} coins from CoinGecko, then scanning price data…`
          : 'Scanning your custom crypto tickers…'
      );

      try {
        const mom = document.getElementById('scan-crypto-mom').value;
        const p = new URLSearchParams({
          above_sma50: document.getElementById('scan-crypto-sma50').value,
          min_rsi:     document.getElementById('scan-crypto-rsi-min').value,
          max_rsi:     document.getElementById('scan-crypto-rsi-max').value,
          ...(isMarketScan ? { market_size: marketSize } : { tickers: customTickers }),
          ...(mom ? { min_momentum: mom } : {}),
        });
        const data = await API.runCryptoScanner(p.toString());
        const results = data.results || [];
        State.cryptoScanResults = results;
        _persist('cryptoScanResults', results);
        body.innerHTML = results.length
          ? _scanCards(results, 'crypto', data.total_scanned)
          : `<div class="empty-state" style="padding:48px 0">No crypto met your criteria from the ${isMarketScan ? `top-${marketSize}` : 'custom'} universe — try widening RSI range or disabling the SMA50 filter.</div>`;
      } catch (err) { body.innerHTML = errorHTML(err.message); }
      finally { if (btn) { btn.disabled = false; btn.textContent = '₿ Scan Crypto'; } }
    };

    // ── Journal helpers (defined on window so _scanCards onclick can call them) ──
    window.logScanIdea = async (btn, ticker, price, setupLabel, mom3m, rsi14) => {
      const macro = State.macroResult;
      try {
        await API.addJournal({
          entry_type:   'idea',
          ticker:       ticker,
          rationale:    `Scanner setup: ${setupLabel}. Price $${price}. RSI ${parseFloat(rsi14).toFixed(1)}. 3M momentum ${parseFloat(mom3m) >= 0 ? '+' : ''}${parseFloat(mom3m).toFixed(1)}%.`,
          tags:         'scanner,idea',
          deploy_score: macro?.deployment_score ?? null,
          regime:       macro?.regime ?? null,
        });
        btn.textContent = '✓ Logged';
        btn.disabled = true;
        btn.style.color = '#4ade80';
      } catch (e) { alert('Journal log failed: ' + e.message); }
    };

    // Strategy filter (client-side, no re-scan needed)
    window._filterScanResults = (tab, strat) => {
      const rows = window._lastScanRows || [];
      const filtered = strat === 'all' ? rows : rows.filter(r => r.setup_category === strat);
      const bodyId = tab === 'crypto' ? 'scan-results-crypto' : 'scan-results-stocks';
      const body = document.getElementById(bodyId);
      if (body) body.innerHTML = filtered.length
        ? _scanCards(filtered, tab, 0)
        : `<div class="empty-state" style="padding:40px 0">No ${strat === 'momentum' ? 'momentum' : 'mean reversion'} setups found in current scan results.</div>`;
      // Update active button
      document.querySelectorAll('.scan-strat-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.strat === strat);
      });
    };

    window.logAllScanIdeas = async (btn) => {
      const rows = window._lastScanRows || [];
      if (!rows.length) return;
      const macro = State.macroResult;
      let count = 0;
      btn.disabled = true;
      btn.textContent = '⏳ Logging…';
      for (const r of rows) {
        try {
          await API.addJournal({
            entry_type:   'idea',
            ticker:       r.ticker,
            rationale:    `Scanner: ${r.setup_label}. Price $${r.price}. RSI ${r.rsi_14?.toFixed(1)}. 3M momentum ${r.mom_3m_pct >= 0 ? '+' : ''}${r.mom_3m_pct?.toFixed(1)}%.`,
            tags:         'scanner,batch,idea',
            deploy_score: macro?.deployment_score ?? null,
            regime:       macro?.regime ?? null,
          });
          count++;
        } catch (_) {}
      }
      btn.textContent = `✓ Logged ${count}`;
      btn.style.color = '#4ade80';
    };
  },

  // ── Macro Gate ────────────────────────────────────────────────────────────
  async macro(container) {
    // Redraws the topbar (incl. the freshness label) so it reflects the CURRENT
    // localStorage timestamp — must be called again after every refresh, else the
    // label stays frozen at page-load state (the "keeps saying 12d old" bug).
    const _setMacroTopbar = () => {
      const age = _ageLabel('macroResult');
      const stale = _isStale('macroResult');
      setTopbar('Macro Gate',
        `<div style="display:flex;align-items:center;gap:10px">
          ${age ? `<span style="font-size:11px;color:${stale?'#f59e0b':'#475569'}">last run ${age}${stale?' ⚠ stale':''}</span>` : ''}
          <button class="btn btn-primary" id="macro-run-btn" onclick="runMacro()">⚡ Refresh Signals</button>
        </div>`
      );
    };
    _setMacroTopbar();

    container.innerHTML = `
      <div id="macro-body">
        ${State.macroResult ? _macroFull(State.macroResult) : loadingHTML('Fetching macro signals…')}
      </div>
    `;

    // Auto-fetch when there's no cached result OR the cached one is stale (>4h),
    // so the page self-heals instead of showing days-old data until a manual click.
    if (!State.macroResult || _isStale('macroResult')) {
      try {
        if (State.macroResult) {
          document.getElementById('macro-body').innerHTML =
            loadingHTML('Cached signals are stale — fetching fresh macro data…');
        }
        const result = await API.runMacro();
        State.macroResult = result;
        _persist('macroResult', result);
        _setMacroTopbar();
        document.getElementById('macro-body').innerHTML = _macroFull(result);
        _initMacroCharts(result);
        _initWhatIf(result);
      } catch (err) {
        document.getElementById('macro-body').innerHTML =
          State.macroResult ? _macroFull(State.macroResult) : errorHTML(err.message);
        if (State.macroResult) { _initMacroCharts(State.macroResult); _initWhatIf(State.macroResult); }
      }
    } else {
      _initMacroCharts(State.macroResult);
      _initWhatIf(State.macroResult);
    }

    window.runMacro = async () => {
      const btn = document.getElementById('macro-run-btn');
      if (btn) btn.disabled = true;
      document.getElementById('macro-body').innerHTML = loadingHTML('Refreshing signals…');
      try {
        const result = await API.runMacro();
        State.macroResult = result;
        _persist('macroResult', result);
        _setMacroTopbar();                 // redraw the freshness label → "just now"
        document.getElementById('macro-body').innerHTML = _macroFull(result);
        _initMacroCharts(result);
        _initWhatIf(result);
      } catch (err) {
        document.getElementById('macro-body').innerHTML = errorHTML(err.message);
      } finally {
        if (btn) btn.disabled = false;
      }
    };
  },

  // ── Analyst Rankings ──────────────────────────────────────────────────────
  async analyst(container) {
    setTopbar('Analyst Rankings',
      `<button class="btn btn-primary" id="analyst-run-btn" onclick="runAnalyst()">◉ Analyze</button>
       <label style="display:flex;align-items:center;gap:6px;font-size:12px;color:#94a3b8;cursor:pointer">
         <input type="checkbox" id="analyst-force"> Force refresh
       </label>`
    );

    // If analysis is running, show live progress; otherwise show results or empty
    const progressHTML = State.analysisRunning ? `
      <div style="font-size:11px;color:#94a3b8;font-family:var(--font-mono);margin-bottom:4px">
        Analyzing <span id="prog-ticker">${State.analysisTicker || '—'}</span> (${State.analysisTotal} total)…
      </div>
      <div class="progress-bar"><div class="progress-fill" id="prog-bar" style="width:${Math.round(State.analysisDone/Math.max(State.analysisTotal,1)*100)}%"></div></div>` : '';

    container.innerHTML = `
      <div class="panel" style="margin-bottom:18px">
        <div class="panel-header">
          <div class="panel-title"><div class="panel-icon">◉</div>Tickers to Analyze</div>
        </div>
        <div class="panel-body">
          <div style="display:flex;gap:10px;align-items:flex-end">
            <div class="form-group" style="flex:1">
              <label>Comma-separated tickers</label>
              <input id="analyst-tickers" class="form-input"
                value="AAPL,MSFT,NVDA,GOOGL,META,AMZN,TSLA,JPM,UNH,V">
            </div>
            <button class="btn btn-primary" onclick="runAnalyst()">◉ Analyze</button>
          </div>
          <div id="analyst-progress" style="margin-top:10px">${progressHTML}</div>
        </div>
      </div>

      <div id="analyst-results">
        ${State.analystResults.length ? _analystTable(State.analystResults) : '<div class="empty-state">Enter tickers and click Analyze</div>'}
      </div>
    `;

    if (State.analystResults.length) {
      _bindAnalystSelect();
    }

    window.runAnalyst = () => {
      const btn      = document.getElementById('analyst-run-btn');
      const tickers  = document.getElementById('analyst-tickers').value.trim();
      const force    = document.getElementById('analyst-force').checked;
      if (!tickers) return;

      // Cancel any in-flight stream
      if (State.activeStream) { State.activeStream.close(); State.activeStream = null; }

      if (btn) btn.disabled = true;
      const tickerList = tickers.split(',').map(t => t.trim().toUpperCase()).filter(Boolean);

      State.analysisRunning = true;
      State.analysisDone    = 0;
      State.analysisTotal   = tickerList.length;
      State.analysisTicker  = tickerList[0] || '—';

      const showProg = () => {
        const prog = document.getElementById('analyst-progress');
        if (!prog) return;
        prog.innerHTML = `
          <div style="font-size:11px;color:#94a3b8;font-family:var(--font-mono);margin-bottom:4px">
            Analyzing <span id="prog-ticker">${State.analysisTicker}</span> (${tickerList.length} total)…
          </div>
          <div class="progress-bar"><div class="progress-fill" id="prog-bar" style="width:${Math.round(State.analysisDone/tickerList.length*100)}%"></div></div>`;
        const res = document.getElementById('analyst-results');
        if (res) res.innerHTML = '';
      };
      showProg();

      State.activeStream = API.analyzeStream(
        tickers, force,
        ev => {
          if (ev.ticker) {
            State.analysisTicker = ev.ticker;
            const el = document.getElementById('prog-ticker');
            if (el) el.textContent = ev.ticker;
          }
          if (ev.status === 'done') {
            State.analysisDone++;
            const pct = Math.round(State.analysisDone / tickerList.length * 100);
            const bar = document.getElementById('prog-bar');
            if (bar) bar.style.width = pct + '%';
          }
        },
        ranked => {
          State.analystResults  = ranked;
          _persist('analystResults', ranked);
          State.analysisRunning = false;
          State.activeStream    = null;
          const prog    = document.getElementById('analyst-progress');
          const results = document.getElementById('analyst-results');
          const b       = document.getElementById('analyst-run-btn');
          if (prog)    prog.innerHTML    = '';
          if (results) results.innerHTML = _analystTable(ranked);
          if (b)       b.disabled        = false;
          _bindAnalystSelect();
        },
        err => {
          State.analysisRunning = false;
          State.activeStream    = null;
          const prog    = document.getElementById('analyst-progress');
          const results = document.getElementById('analyst-results');
          const b       = document.getElementById('analyst-run-btn');
          if (prog)    prog.innerHTML    = '';
          if (results) results.innerHTML = errorHTML('Analysis failed: ' + (err.message || err));
          if (b)       b.disabled        = false;
        }
      );
    };
  },

  // ── Rank Deltas ───────────────────────────────────────────────────────────
  async deltas(container) {
    setTopbar('Rank Deltas');
    const ranked = State.analystResults;

    const explainerHTML = `
      <div class="panel" style="margin-bottom:18px;border-color:rgba(168,85,247,0.25)">
        <div class="panel-header">
          <div class="panel-title"><div class="panel-icon" style="background:rgba(168,85,247,0.1);color:#a855f7">⬡</div>What is this tab?</div>
        </div>
        <div class="panel-body" style="display:grid;grid-template-columns:1fr 1fr;gap:18px">
          <div>
            <div style="font-size:13px;font-weight:600;color:#e2e8f0;margin-bottom:8px">Track how stocks move up &amp; down your rankings over time</div>
            <p style="font-size:12px;color:#94a3b8;line-height:1.6;margin:0">
              Every time you run <strong style="color:#e2e8f0">Analyst Rankings</strong>, each stock gets a rank (1 = best).
              This tab compares today's ranks to the <em>previous</em> run and flags anything that moved
              <strong style="color:#4ade80">up 3+ positions</strong> (upgrade) or
              <strong style="color:#f87171">down 3+ positions</strong> (downgrade).
            </p>
            <p style="font-size:12px;color:#94a3b8;line-height:1.6;margin:8px 0 0">
              <strong style="color:#e2e8f0">Example:</strong> AAPL was #7 last week. Today it scores #2.
              That is a <strong style="color:#4ade80">▲5 upgrade</strong> — something improved
              (earnings beat, margin expansion) and it is worth investigating why.
            </p>
          </div>
          <div>
            <div style="font-size:13px;font-weight:600;color:#e2e8f0;margin-bottom:8px">Why it matters</div>
            <ul style="font-size:12px;color:#94a3b8;line-height:1.9;margin:0;padding-left:16px">
              <li><strong style="color:#4ade80">Upgrades</strong> = improving fundamentals → potential buys</li>
              <li><strong style="color:#f87171">Downgrades</strong> = deteriorating signals → consider trimming</li>
              <li>Bar chart breaks scores into Quant vs AI so you see <em>what</em> changed</li>
              <li>Deltas appear after your <strong style="color:#e2e8f0">second run</strong> — first run sets the baseline</li>
            </ul>
          </div>
        </div>
      </div>`;

    if (!ranked.length) {
      container.innerHTML = explainerHTML + `<div class="empty-state" style="padding:60px 0">
        Run <strong>Analyst Rankings</strong> first to populate scores here.</div>`;
      return;
    }

    const upgrades   = ranked.filter(c => (c.rank_delta || 0) >= 3);
    const downgrades = ranked.filter(c => (c.rank_delta || 0) <= -3);
    const tickers    = ranked.map(c => c.ticker);
    const quant      = ranked.map(c => c.quant_score);
    const claude     = ranked.map(c => c.claude_norm);
    const blended    = ranked.map(c => c.blended_score);
    const hasPrev    = ranked.some(c => c.prev_rank);

    container.innerHTML = explainerHTML +
      (!hasPrev ? `<div style="background:rgba(245,158,11,0.08);border:1px solid rgba(245,158,11,0.25);border-radius:8px;padding:10px 14px;margin-bottom:14px;font-size:12px;color:#f59e0b">
        First run complete — this is your baseline. Run Analyst Rankings again to start seeing rank changes.
      </div>` : '') + `
      <div class="metrics-row" style="grid-template-columns:repeat(3,1fr)">
        <div class="metric-card" style="--card-top:#4ade80">
          <div class="metric-label">Upgrades ≥3</div>
          <div class="metric-value" style="color:#4ade80">${upgrades.length}</div>
        </div>
        <div class="metric-card" style="--card-top:#f87171">
          <div class="metric-label">Downgrades ≥3</div>
          <div class="metric-value" style="color:#f87171">${downgrades.length}</div>
        </div>
        <div class="metric-card" style="--card-top:#94a3b8">
          <div class="metric-label">Unchanged</div>
          <div class="metric-value" style="color:#94a3b8">${ranked.length - upgrades.length - downgrades.length}</div>
        </div>
      </div>

      <div class="row-2" style="margin-bottom:18px">
        <div>
          <div style="font-size:13px;font-weight:600;margin-bottom:10px;color:#4ade80">🟢 Upgraded</div>
          ${upgrades.length ? upgrades.sort((a,b) => b.rank_delta - a.rank_delta).map(c => `
            <div class="delta-card delta-up">
              <div style="display:flex;justify-content:space-between;align-items:center">
                <span class="delta-ticker" style="color:#4ade80">${c.ticker}</span>
                <span class="delta-arrow-pos">▲${Math.abs(c.rank_delta)} positions</span>
              </div>
              <div class="delta-detail">#${c.prev_rank||'—'} → #${c.rank} · Score: ${c.blended_score}</div>
            </div>`).join('') : '<div class="empty-state">No significant upgrades</div>'}
        </div>
        <div>
          <div style="font-size:13px;font-weight:600;margin-bottom:10px;color:#f87171">🔴 Downgraded</div>
          ${downgrades.length ? downgrades.sort((a,b) => a.rank_delta - b.rank_delta).map(c => `
            <div class="delta-card delta-down">
              <div style="display:flex;justify-content:space-between;align-items:center">
                <span class="delta-ticker" style="color:#f87171">${c.ticker}</span>
                <span class="delta-arrow-neg">▼${Math.abs(c.rank_delta)} positions</span>
              </div>
              <div class="delta-detail">#${c.prev_rank||'—'} → #${c.rank} · Score: ${c.blended_score}</div>
            </div>`).join('') : '<div class="empty-state">No significant downgrades</div>'}
        </div>
      </div>

      <div class="panel" style="margin-bottom:18px">
        <div class="panel-header">
          <div class="panel-title"><div class="panel-icon">◈</div>Score Breakdown — How Rankings Are Calculated</div>
        </div>
        <div style="padding:10px 16px 0;font-size:11.5px;line-height:1.65;border-bottom:1px solid #1e293b;margin-bottom:0;color:#64748b">
          Your final rank is a <strong style="color:#e2e8f0">blended score</strong> made up of two independent legs:
          &nbsp;<span style="color:#3b82f6;font-weight:600">Quant Score (60%)</span> — objective financial metrics anyone
          can calculate: P/E ratio, revenue growth, profit margins, 3-month price momentum. No opinion, pure data.&nbsp;&nbsp;
          <span style="color:#a855f7;font-weight:600">Claude AI Score (40%)</span> — qualitative analysis Claude performs
          after reading the fundamentals: competitive moat, management track record, sector tailwinds, narrative risks.
          Things numbers alone can't fully capture. The
          <span style="color:#00d4aa;font-weight:600">teal line (●)</span> is the blended result that sets the rank order.
          A stock can score high on Quant but low on Claude (or vice versa) — bars that diverge flag where the two disagree.
        </div>
        <div style="padding:14px"><div id="delta-chart" style="height:300px"></div></div>
      </div>

      <details style="margin-bottom:18px">
        <summary style="cursor:pointer;padding:10px 16px;background:#0d1421;border:1px solid #1e293b;border-radius:8px;font-size:12px;color:#475569;display:flex;align-items:center;gap:8px;list-style:none;-webkit-appearance:none;user-select:none">
          <span style="font-size:16px;color:#60a5fa">ⓘ</span>
          <span style="color:#94a3b8;font-weight:500">Full Data Table</span>
          <span style="color:#475569"> — exact scores and rank changes for all ${ranked.length} tickers</span>
          <span style="margin-left:auto;font-size:10px;color:#334155;font-family:var(--font-mono)">▾ click to expand</span>
        </summary>
        <div class="panel" style="margin-top:8px">
          <table class="data-table">
            <thead><tr><th>Rank</th><th>Ticker</th><th>Blended</th><th>Δ Rank</th><th>Prev</th><th>Sector</th></tr></thead>
            <tbody>
              ${ranked.map(c => {
                const d = c.rank_delta || 0;
                const dStr = d > 0 ? `<span style="color:#4ade80;font-weight:700">▲${d}</span>`
                           : d < 0 ? `<span style="color:#f87171;font-weight:700">▼${Math.abs(d)}</span>`
                           : '<span style="color:#475569">—</span>';
                return `<tr>
                  <td style="font-family:var(--font-mono)">${c.rank}</td>
                  <td><strong>${c.ticker}</strong></td>
                  <td style="color:${scoreColor(c.blended_score)};font-family:var(--font-mono);font-weight:700">${c.blended_score}</td>
                  <td>${dStr}</td>
                  <td style="font-family:var(--font-mono);color:#475569">${c.prev_rank||'—'}</td>
                  <td style="color:#94a3b8;font-size:11px">${c.sector||'—'}</td>
                </tr>`;
              }).join('')}
            </tbody>
          </table>
        </div>
      </details>
    `;

    // Bar chart
    setTimeout(() => {
      renderLine('delta-chart', [
        { x: tickers, y: quant,   type: 'bar', name: 'Quant (60%)',  marker: { color: '#3b82f6', opacity: 0.85 } },
        { x: tickers, y: claude,  type: 'bar', name: 'Claude (40%)', marker: { color: '#a855f7', opacity: 0.85 } },
        { x: tickers, y: blended, type: 'scatter', mode: 'lines+markers', name: 'Blended',
          line: { color: '#00d4aa', width: 2 }, marker: { color: '#00d4aa', size: 7 } },
      ], { barmode: 'group', height: 300, yaxis: { range: [0, 110] } });
    }, 50);
  },

  // ── Journal ───────────────────────────────────────────────────────────────
  async journal(container) {
    setTopbar('Journal',
      `<button class="btn btn-primary btn-sm" onclick="toggleJournalForm()">➕ New Entry</button>`
    );

    container.innerHTML = `
      <div id="journal-form-wrap" style="display:none;margin-bottom:18px">
        <div class="panel">
          <div class="panel-header"><div class="panel-title">New Journal Entry</div></div>
          <div class="panel-body">
            <div class="form-grid">
              <div class="form-group"><label>Type</label>
                <select id="j-type" class="form-select"><option>trade</option><option>idea</option><option>note</option><option>review</option></select>
              </div>
              <div class="form-group"><label>Ticker</label><input id="j-ticker" class="form-input" placeholder="AAPL"></div>
              <div class="form-group"><label>Direction</label>
                <select id="j-dir" class="form-select"><option value="">—</option><option>long</option><option>short</option><option>flat</option></select>
              </div>
              <div class="form-group"><label>Entry Price</label><input id="j-entry" class="form-input" type="number" step="0.01"></div>
              <div class="form-group"><label>Exit Price</label><input id="j-exit" class="form-input" type="number" step="0.01"></div>
              <div class="form-group"><label>Size %</label><input id="j-size" class="form-input" type="number" step="0.5"></div>
            </div>
            <div class="form-grid" style="grid-template-columns:1fr 1fr;margin-bottom:12px">
              <div class="form-group"><label>Tags</label><input id="j-tags" class="form-input" placeholder="momentum, earnings"></div>
              <div class="form-group"><label>Deploy Score</label>
                <input id="j-deploy" class="form-input" type="number" step="0.1"
                  value="${State.macroResult ? State.macroResult.deployment_score.toFixed(1) : 50}">
              </div>
            </div>
            <div class="form-group" style="margin-bottom:10px"><label>Rationale</label><textarea id="j-rat" class="form-textarea" rows="3"></textarea></div>
            <div class="form-group" style="margin-bottom:14px"><label>Outcome / Notes</label><textarea id="j-out" class="form-textarea" rows="2"></textarea></div>
            <div style="display:flex;gap:10px">
              <button class="btn btn-primary" onclick="saveJournalEntry()">💾 Save Entry</button>
              <button class="btn btn-secondary" onclick="toggleJournalForm()">Cancel</button>
            </div>
          </div>
        </div>
      </div>

      <div id="journal-stats" style="margin-bottom:18px"></div>
      <div id="journal-entries"></div>
    `;

    await _loadJournal();

    window.toggleJournalForm = () => {
      const el = document.getElementById('journal-form-wrap');
      el.style.display = el.style.display === 'none' ? 'block' : 'none';
    };

    window.saveJournalEntry = async () => {
      const body = {
        entry_type:  document.getElementById('j-type').value,
        ticker:      document.getElementById('j-ticker').value.toUpperCase() || null,
        direction:   document.getElementById('j-dir').value || null,
        entry_price: parseFloat(document.getElementById('j-entry').value) || null,
        exit_price:  parseFloat(document.getElementById('j-exit').value) || null,
        size_pct:    parseFloat(document.getElementById('j-size').value) || null,
        tags:        document.getElementById('j-tags').value || null,
        deploy_score:parseFloat(document.getElementById('j-deploy').value) || null,
        regime:      State.macroResult ? State.macroResult.regime : null,
        rationale:   document.getElementById('j-rat').value || null,
        outcome:     document.getElementById('j-out').value || null,
      };
      try {
        await API.addJournal(body);
        document.getElementById('journal-form-wrap').style.display = 'none';
        await _loadJournal();
      } catch (err) {
        alert('Save failed: ' + err.message);
      }
    };

    window.deleteJournalEntry = async (id) => {
      if (!confirm('Delete this entry?')) return;
      await API.deleteJournal(id);
      await _loadJournal();
    };
  },

  // ── Paper Trades ──────────────────────────────────────────────────────────
  async papertrades(container) {
    setTopbar('Paper Trades', `
      <div style="display:flex;gap:8px;align-items:center">
        <button class="btn btn-secondary" onclick="checkPaperTrades(this)" style="font-size:11px">⟳ Check Prices</button>
        <button class="btn btn-primary"   id="loop-run-btn" onclick="triggerLoop(this)" style="font-size:11px">▶ Run Loop Now</button>
        <button class="btn btn-secondary" id="loop-pause-btn" onclick="toggleLoopPause(this)" style="font-size:11px">⏸ Pause Auto</button>
      </div>
    `);

    container.innerHTML = loadingHTML('Loading paper trades…');

    const [liveRes, statsRes, loopStatus, allTradesRes] = await Promise.all([
      API.getLivePrices(),
      API.getPaperStats(),
      API.getLoopStatus(),
      API.getPaperTrades(),
    ]);

    // Open trades come from live endpoint (enriched with current price)
    // Closed trades from the full list
    const open      = liveRes.trades || [];
    const allTrades = allTradesRes.trades || [];
    const closed    = allTrades.filter(t => t.status !== 'open');
    const stats     = statsRes;
    const jobs      = loopStatus.jobs      || [];
    const sigStats  = loopStatus.signal_stats || [];
    const loopLog   = loopStatus.loop_log  || [];
    const paused    = !loopStatus.scheduler_running;

    const statusBadge = (s) => {
      const map = {
        open:         ['#f59e0b','rgba(245,158,11,0.1)','Open'],
        target_hit:   ['#4ade80','rgba(74,222,128,0.1)', 'Target Hit ✓'],
        stop_hit:     ['#f87171','rgba(248,113,113,0.1)','Stop Hit ✗'],
        manual_close: ['#60a5fa','rgba(96,165,250,0.1)', 'Closed'],
        expired:      ['#94a3b8','rgba(148,163,184,0.1)','Expired'],
      };
      const [c, bg, label] = map[s] || ['#94a3b8','rgba(148,163,184,0.1)', s];
      return `<span style="font-size:10px;font-weight:700;color:${c};background:${bg};padding:2px 8px;border-radius:4px">${label}</span>`;
    };

    const pnlColor = (pnl) => pnl == null ? '#94a3b8' : pnl > 0 ? '#4ade80' : '#f87171';

    // ── Open trade card (with live price progress) ───────────────────────────
    const openTradeCard = (t) => {
      const actionCol  = t.action === 'BUY' ? '#4ade80' : '#f87171';
      const hasPrices  = t.current_price != null;
      const pnl        = t.live_pnl_pct;
      const pnlCol     = pnlColor(pnl);
      const prog       = Math.min(Math.max(t.progress_pct ?? 0, 0), 100);  // clamp 0–100 for bar
      const rawProg    = t.progress_pct ?? 0;  // can exceed 100 if past target

      // Progress bar colour: green approaching target, red approaching stop
      const barCol = rawProg >= 70 ? '#4ade80' : rawProg >= 40 ? '#f59e0b' : '#f87171';

      return `
      <div style="background:#0d1421;border:1px solid ${hasPrices && pnl >= 0 ? 'rgba(74,222,128,0.2)' : hasPrices ? 'rgba(248,113,113,0.2)' : '#1e293b'};border-radius:10px;padding:14px;display:flex;flex-direction:column;gap:10px">

        <!-- Header row -->
        <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:6px">
          <div style="display:flex;align-items:center;gap:10px">
            <span style="font-size:15px;font-weight:800;font-family:var(--font-mono);color:#e2e8f0">${t.ticker}</span>
            <span style="font-size:11px;color:${actionCol};font-weight:700;background:${actionCol}18;padding:2px 8px;border-radius:4px">${t.action}</span>
            <span style="font-size:10px;color:#64748b">${t.setup_label}</span>
          </div>
          <div style="display:flex;align-items:center;gap:8px">
            ${hasPrices ? `<span style="font-size:20px;font-weight:800;font-family:var(--font-mono);color:${pnlCol}">${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}%</span>` : '<span style="color:#475569;font-size:12px">fetching…</span>'}
            <button class="btn btn-secondary btn-sm" style="font-size:10px;padding:3px 8px"
              onclick="manualCloseTrade(${t.id}, ${t.entry_price})">Close</button>
            <button class="btn btn-danger btn-sm btn-icon" style="font-size:10px"
              onclick="deletePaperTrade(${t.id})">✕</button>
          </div>
        </div>

        ${hasPrices ? `
        <!-- Live price strip -->
        <div style="display:flex;justify-content:space-between;align-items:center;font-size:11px;font-family:var(--font-mono)">
          <span style="color:#f87171" title="Stop loss">⬇ Stop ${_fmtPrice(t.stop_price)}</span>
          <span style="color:#94a3b8">Entry ${_fmtPrice(t.entry_price)}</span>
          <span style="color:#e2e8f0;font-weight:700">Now ${_fmtPrice(t.current_price)}</span>
          <span style="color:#4ade80" title="Target">Target ${_fmtPrice(t.target_price)} ⬆</span>
        </div>

        <!-- Progress bar: stop ←——[current]——→ target -->
        <div style="position:relative;height:10px;background:#1e293b;border-radius:99px;overflow:visible">
          <!-- Filled portion from left (stop) up to current position -->
          <div style="position:absolute;left:0;top:0;height:100%;width:${prog}%;background:${barCol};border-radius:99px;transition:width 0.5s"></div>
          <!-- Entry marker (50% of stop→target range) -->
          <div style="position:absolute;top:-3px;left:${Math.min(Math.max((t.entry_price - t.stop_price) / (t.target_price - t.stop_price) * 100, 2), 98)}%;transform:translateX(-50%);width:2px;height:16px;background:#94a3b8;border-radius:2px" title="Entry price"></div>
          <!-- Current price dot -->
          <div style="position:absolute;top:50%;left:${prog}%;transform:translate(-50%,-50%);width:14px;height:14px;background:${barCol};border:2px solid #0d1421;border-radius:50%;box-shadow:0 0 6px ${barCol}66" title="Current price"></div>
        </div>

        <!-- Distances row -->
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;font-size:11px">
          <div style="background:rgba(248,113,113,0.07);border:1px solid rgba(248,113,113,0.15);border-radius:6px;padding:7px 10px">
            <div style="color:#64748b;font-size:10px;margin-bottom:2px">To stop</div>
            <div style="color:#f87171;font-weight:700;font-family:var(--font-mono)">${t.pct_to_stop != null ? '-' + t.pct_to_stop.toFixed(2) + '%' : '–'}</div>
            <div style="color:#475569;font-size:10px">${_fmtPrice(t.stop_price)}</div>
          </div>
          <div style="background:rgba(148,163,184,0.05);border:1px solid #1e293b;border-radius:6px;padding:7px 10px;text-align:center">
            <div style="color:#64748b;font-size:10px;margin-bottom:2px">Days held</div>
            <div style="color:#94a3b8;font-weight:700">${t.days_held ?? '–'}</div>
            <div style="color:#475569;font-size:10px">Conv. ${t.conviction?.toFixed(0)}</div>
          </div>
          <div style="background:rgba(74,222,128,0.07);border:1px solid rgba(74,222,128,0.15);border-radius:6px;padding:7px 10px;text-align:right">
            <div style="color:#64748b;font-size:10px;margin-bottom:2px">To target</div>
            <div style="color:#4ade80;font-weight:700;font-family:var(--font-mono)">${t.pct_to_target != null ? '+' + t.pct_to_target.toFixed(2) + '%' : '–'}</div>
            <div style="color:#475569;font-size:10px">${_fmtPrice(t.target_price)}</div>
          </div>
        </div>

        ${t.predicted_rr ? `
        <div style="display:flex;gap:16px;font-size:10.5px;color:#64748b">
          <span>Predicted R:R <strong style="color:#94a3b8">${t.predicted_rr.toFixed(1)}:1</strong></span>
          <span>Progress <strong style="color:${barCol}">${rawProg.toFixed(0)}% of range</strong>${rawProg > 100 ? ' <span style="color:#4ade80">— past target!</span>' : ''}</span>
          <span>Since <strong style="color:#64748b">${t.entry_date}</strong></span>
        </div>` : ''}
        ` : `
        <!-- No price data yet -->
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;font-size:11px">
          <div><span style="color:#64748b">Entry </span><span style="color:#e2e8f0;font-family:var(--font-mono)">${_fmtPrice(t.entry_price)}</span></div>
          <div><span style="color:#4ade80">Target </span><span style="color:#e2e8f0;font-family:var(--font-mono)">${_fmtPrice(t.target_price)}</span></div>
          <div><span style="color:#f87171">Stop </span><span style="color:#e2e8f0;font-family:var(--font-mono)">${_fmtPrice(t.stop_price)}</span></div>
        </div>`}

        ${t.trade_note ? `<div style="font-size:10px;color:#475569;font-style:italic;border-top:1px solid #1e293b;padding-top:6px">${escHtml(t.trade_note)}</div>` : ''}
      </div>`;
    };

    // ── Closed trade row (compact) ────────────────────────────────────────────
    const tradeRow = (t, isOpen) => isOpen ? openTradeCard(t) : `
      <div style="background:#0d1421;border:1px solid #1e293b;border-radius:8px;padding:12px 14px;display:flex;flex-direction:column;gap:8px">
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px">
          <div style="display:flex;align-items:center;gap:10px">
            <span style="font-size:14px;font-weight:700;font-family:var(--font-mono);color:#e2e8f0">${t.ticker}</span>
            <span style="font-size:11px;color:${t.action==='BUY'?'#4ade80':'#f87171'};font-weight:700">${t.action}</span>
            ${statusBadge(t.status)}
            <span style="font-size:11px;color:#475569">${t.setup_label}</span>
          </div>
          <div style="display:flex;align-items:center;gap:10px">
            ${t.actual_pnl_pct != null
              ? `<span style="font-size:15px;font-weight:700;font-family:var(--font-mono);color:${pnlColor(t.actual_pnl_pct)}">${t.actual_pnl_pct>0?'+':''}${t.actual_pnl_pct.toFixed(2)}%</span>`
              : ''}
            ${t.actual_rr != null ? `<span style="font-size:11px;color:${t.actual_rr>0?'#4ade80':'#f87171'}">${t.actual_rr>0?'+':''}${t.actual_rr.toFixed(1)}R</span>` : ''}
            <button class="btn btn-danger btn-sm btn-icon" style="font-size:10px" onclick="deletePaperTrade(${t.id})">✕</button>
          </div>
        </div>
        <div style="display:flex;gap:16px;font-size:10.5px;color:#64748b;flex-wrap:wrap">
          <span>Entry <strong style="color:#94a3b8;font-family:var(--font-mono)">${_fmtPrice(t.entry_price)}</strong></span>
          <span>Exit <strong style="color:#94a3b8;font-family:var(--font-mono)">${_fmtPrice(t.exit_price)}</strong></span>
          <span>Pred R:R <strong style="color:#64748b">${t.predicted_rr?.toFixed(1) ?? '–'}:1</strong></span>
          ${t.bars_held != null ? `<span>Held <strong style="color:#64748b">${t.bars_held}d</strong></span>` : ''}
          <span>Opened <strong style="color:#475569">${t.entry_date}</strong></span>
        </div>
        ${t.trade_note ? `<div style="font-size:10px;color:#475569;font-style:italic">${escHtml(t.trade_note)}</div>` : ''}
      </div>`;

    // ── Performance stats ────────────────────────────────────────────────────
    const statsHTML = stats.total_closed > 0 ? `
      <div class="panel" style="margin-bottom:18px">
        <div class="panel-header"><div class="panel-title"><div class="panel-icon">◈</div>Performance Analytics</div></div>
        <div class="panel-body" style="display:flex;flex-direction:column;gap:18px">

          <!-- Summary metrics -->
          <div class="metrics-row" style="grid-template-columns:repeat(5,1fr)">
            <div class="metric-card" style="--card-top:#00d4aa">
              <div class="metric-label">Closed Trades</div>
              <div class="metric-value" style="color:#00d4aa">${stats.total_closed}</div>
            </div>
            <div class="metric-card" style="--card-top:${stats.win_rate>=50?'#4ade80':'#f87171'}">
              <div class="metric-label">Win Rate</div>
              <div class="metric-value" style="color:${stats.win_rate>=50?'#4ade80':'#f87171'}">${stats.win_rate}%</div>
            </div>
            <div class="metric-card" style="--card-top:${stats.avg_pnl>=0?'#4ade80':'#f87171'}">
              <div class="metric-label">Avg P&L</div>
              <div class="metric-value" style="color:${stats.avg_pnl>=0?'#4ade80':'#f87171'}">${stats.avg_pnl>=0?'+':''}${stats.avg_pnl}%</div>
            </div>
            <div class="metric-card" style="--card-top:#4ade80">
              <div class="metric-label">Avg Win</div>
              <div class="metric-value" style="color:#4ade80">+${stats.avg_win}%</div>
            </div>
            <div class="metric-card" style="--card-top:#f87171">
              <div class="metric-label">Avg Loss</div>
              <div class="metric-value" style="color:#f87171">${stats.avg_loss}%</div>
            </div>
          </div>

          <!-- By setup breakdown -->
          ${stats.by_setup?.length ? `
          <div>
            <div style="font-size:11px;font-weight:700;color:#94a3b8;margin-bottom:10px;text-transform:uppercase;letter-spacing:0.06em">Win Rate by Setup — is the model's setup classification working?</div>
            <div style="display:flex;flex-direction:column;gap:6px">
              ${stats.by_setup.map(s => {
                const wr = s.win_rate;
                const wrColor = wr >= 60 ? '#4ade80' : wr >= 40 ? '#f59e0b' : '#f87171';
                const rrDiff = s.avg_pred_rr && s.avg_actual_rr ? (s.avg_actual_rr - s.avg_pred_rr).toFixed(1) : null;
                return `<div style="display:grid;grid-template-columns:200px 60px 1fr 120px;gap:10px;align-items:center;font-size:11px">
                  <span style="color:#e2e8f0">${s.setup_label}</span>
                  <span style="color:#475569">${s.trades} trade${s.trades!==1?'s':''}</span>
                  <div style="height:6px;background:#1e293b;border-radius:99px;overflow:hidden">
                    <div style="height:100%;width:${wr}%;background:${wrColor};border-radius:99px;transition:width 0.6s"></div>
                  </div>
                  <div style="display:flex;gap:8px;align-items:center">
                    <span style="color:${wrColor};font-weight:700;font-family:var(--font-mono)">${wr}%</span>
                    ${rrDiff ? `<span style="color:${parseFloat(rrDiff)>=0?'#4ade80':'#f87171'};font-size:10px" title="Actual R:R vs predicted">(R:R ${parseFloat(rrDiff)>=0?'+':''}${rrDiff})</span>` : ''}
                  </div>
                </div>`;
              }).join('')}
            </div>
          </div>` : ''}

          <!-- Conviction calibration -->
          ${stats.conviction_calibration?.length ? `
          <div>
            <div style="font-size:11px;font-weight:700;color:#94a3b8;margin-bottom:10px;text-transform:uppercase;letter-spacing:0.06em">Conviction Score Calibration — does high conviction actually mean higher win rate?</div>
            <div style="display:flex;gap:12px;flex-wrap:wrap">
              ${stats.conviction_calibration.map(b => {
                const wr = b.win_rate;
                const c = wr >= 60 ? '#4ade80' : wr >= 40 ? '#f59e0b' : '#f87171';
                return `<div style="flex:1;min-width:140px;background:rgba(0,0,0,0.2);border:1px solid #1e293b;border-radius:8px;padding:12px;text-align:center">
                  <div style="font-size:11px;color:#64748b;margin-bottom:6px">${b.bucket}</div>
                  <div style="font-size:22px;font-weight:700;color:${c};font-family:var(--font-mono)">${wr}%</div>
                  <div style="font-size:10px;color:#475569;margin-top:4px">${b.trades} trades · avg ${b.avg_pnl>=0?'+':''}${b.avg_pnl}%</div>
                </div>`;
              }).join('')}
            </div>
          </div>` : ''}

        </div>
      </div>` : '';

    // ── Scheduler & learning panel ─────────────────────────────────────────
    const schedColor  = paused ? '#f87171' : '#4ade80';
    const schedLabel  = paused ? 'Paused' : 'Running';
    const checkJob    = jobs.find(j => j.id === 'check_positions');
    const dailyJob    = jobs.find(j => j.id === 'daily_loop');
    const fmtNext = (iso) => {
      if (!iso) return '–';
      const d = new Date(iso);
      return d.toLocaleString('en-GB', { day:'2-digit', month:'short', hour:'2-digit', minute:'2-digit', timeZone:'UTC' }) + ' UTC';
    };

    const automationHTML = `
      <div class="panel" style="margin-bottom:18px;border-color:${schedColor}33">
        <div class="panel-header">
          <div class="panel-title">
            <div class="panel-icon" style="background:${schedColor}18;color:${schedColor}">◎</div>
            Automation — <span style="color:${schedColor}">${schedLabel}</span>
          </div>
          <div style="display:flex;gap:18px;font-size:11px;color:#64748b;align-items:center">
            <span>Position check: <strong style="color:#94a3b8">${fmtNext(checkJob?.next_run)}</strong></span>
            <span>Daily scan: <strong style="color:#94a3b8">${fmtNext(dailyJob?.next_run)}</strong></span>
          </div>
        </div>
        <div class="panel-body">
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;font-size:11px;color:#64748b;margin-bottom:14px">
            <div style="background:rgba(0,0,0,0.2);border:1px solid #1e293b;border-radius:8px;padding:10px 14px">
              <div style="font-size:10px;text-transform:uppercase;letter-spacing:0.06em;color:#475569;margin-bottom:4px">Position Check</div>
              <div style="color:#e2e8f0;font-weight:600">Every hour</div>
              <div style="color:#64748b;margin-top:2px">Fetches current prices from Bybit/yfinance. Auto-closes trades that hit target or stop.</div>
            </div>
            <div style="background:rgba(0,0,0,0.2);border:1px solid #1e293b;border-radius:8px;padding:10px 14px">
              <div style="font-size:10px;text-transform:uppercase;letter-spacing:0.06em;color:#475569;margin-bottom:4px">Daily Scan</div>
              <div style="color:#e2e8f0;font-weight:600">08:00 UTC daily</div>
              <div style="color:#64748b;margin-top:2px">Runs scanner, opens top 3 high-conviction setups (conviction ≥65, vol >$1M) not already open.</div>
            </div>
          </div>

          <!-- Loop log -->
          ${loopLog.length ? `
          <div>
            <div style="font-size:10px;text-transform:uppercase;letter-spacing:0.06em;color:#475569;margin-bottom:8px">Recent Loop Runs</div>
            <div style="display:flex;flex-direction:column;gap:6px">
              ${loopLog.slice(0,5).map(l => {
                const r = l.result || {};
                const pos = r.positions || {};
                const scan = r.scan || {};
                return `<div style="display:flex;gap:12px;align-items:center;font-size:10.5px;padding:6px 10px;background:rgba(0,0,0,0.2);border-radius:6px;flex-wrap:wrap">
                  <span style="color:#475569;font-family:var(--font-mono)">${(l.run_at||'').slice(0,16).replace('T',' ')}</span>
                  <span style="color:#64748b">Checked <strong style="color:#94a3b8">${pos.checked??0}</strong> pos</span>
                  <span style="color:${(pos.resolved?.length||0)>0?'#4ade80':'#475569'}">Resolved <strong>${pos.resolved?.length??0}</strong></span>
                  <span style="color:#64748b">Scanned <strong style="color:#94a3b8">${scan.scan_count??0}</strong></span>
                  <span style="color:${(scan.opened?.length||0)>0?'#00d4aa':'#475569'}">Opened <strong>${scan.opened?.length??0}</strong> trades</span>
                </div>`;
              }).join('')}
            </div>
          </div>` : '<div style="font-size:11px;color:#475569">No loop runs yet — click ▶ Run Loop Now to start.</div>'}
        </div>
      </div>`;

    // ── Signal learning panel ──────────────────────────────────────────────
    const learningHTML = sigStats.length ? `
      <div class="panel" style="margin-bottom:18px">
        <div class="panel-header">
          <div class="panel-title"><div class="panel-icon" style="color:#a78bfa">◈</div>Signal Learning — how each setup is performing</div>
        </div>
        <div class="panel-body" style="display:flex;flex-direction:column;gap:10px">
          <div style="font-size:11px;color:#64748b;margin-bottom:4px">
            The loop tracks every trade outcome and adjusts each setup's <strong style="color:#e2e8f0">conviction multiplier</strong> automatically.
            High profit factor → multiplier rises (setup gets boosted). Edge decay detected → multiplier falls.
          </div>
          <div style="display:flex;flex-direction:column;gap:6px">
            ${sigStats.map(s => {
              const pf = s.profit_factor_20;
              const wr = s.win_rate_20;
              const mult = s.conviction_mult;
              const decay = s.edge_decay;
              const pfColor = pf == null ? '#475569' : pf >= 1.5 ? '#4ade80' : pf >= 1.0 ? '#f59e0b' : '#f87171';
              const multColor = mult >= 1.1 ? '#4ade80' : mult <= 0.85 ? '#f87171' : '#94a3b8';
              return `<div style="display:grid;grid-template-columns:180px 70px 90px 90px 80px 1fr;gap:8px;align-items:center;font-size:10.5px;padding:7px 10px;background:rgba(0,0,0,0.2);border-radius:6px;${decay?'border:1px solid rgba(248,113,113,0.25)':''}">
                <span style="color:#e2e8f0">${s.setup_label}</span>
                <span style="color:#475569">${s.trades_total} trades</span>
                <span>WR <strong style="color:${wr>=50?'#4ade80':'#f87171'}">${wr!=null?wr.toFixed(0)+'%':'–'}</strong></span>
                <span>PF <strong style="color:${pfColor}">${pf!=null?pf.toFixed(2):'–'}</strong></span>
                <span style="color:${multColor};font-weight:700;font-family:var(--font-mono)">×${mult.toFixed(2)}</span>
                ${decay ? `<span style="color:#f87171;font-size:10px;font-weight:600">⚠ Edge decay — conviction suppressed</span>` : '<span></span>'}
              </div>`;
            }).join('')}
          </div>
          <div style="font-size:10px;color:#475569;border-top:1px solid #1e293b;padding-top:8px;line-height:1.6">
            <strong style="color:#64748b">PF</strong> = Profit Factor (gross wins ÷ gross losses). Target >1.5.
            <strong style="color:#64748b">×mult</strong> = conviction score multiplier applied to scanner results.
            Edge decay fires when 20-trade win rate drops >15% below 90-day baseline.
          </div>
        </div>
      </div>` : '';

    container.innerHTML = `
      ${automationHTML}
      ${learningHTML}
      ${statsHTML}

      <!-- Open trades -->
      <div class="panel" style="margin-bottom:18px">
        <div class="panel-header">
          <div class="panel-title"><div class="panel-icon" style="color:#f59e0b">◎</div>Open Positions (${open.length})</div>
        </div>
        <div class="panel-body" style="display:flex;flex-direction:column;gap:10px">
          ${open.length
            ? open.map(t => tradeRow(t, true)).join('')
            : `<div class="empty-state">No open paper trades. Run the Scanner and click ◎ Paper Trade on any card.</div>`}
        </div>
      </div>

      <!-- Closed trades -->
      ${closed.length ? `
      <div class="panel">
        <div class="panel-header">
          <div class="panel-title"><div class="panel-icon">◈</div>Closed Trades (${closed.length})</div>
        </div>
        <div class="panel-body" style="display:flex;flex-direction:column;gap:10px">
          ${closed.map(t => tradeRow(t, false)).join('')}
        </div>
      </div>` : ''}
    `;

    // ── Handlers ───────────────────────────────────────────────────────────
    window.deletePaperTrade = async (id) => {
      if (!confirm('Delete this paper trade?')) return;
      await API.deletePaperTrade(id);
      await Pages.papertrades(container);
    };

    window.manualCloseTrade = async (id, entryPrice) => {
      const priceStr = prompt(`Close trade #${id}. Enter exit price (entry was ${entryPrice}):`);
      if (!priceStr) return;
      const exitPrice = parseFloat(priceStr);
      if (isNaN(exitPrice)) return alert('Invalid price');
      await API.closePaperTrade(id, { exit_price: exitPrice, status: 'manual_close' });
      await Pages.papertrades(container);
    };
  },
};

// ═══════════════════════════════════════════════════════════════════════════
// ── Private helpers ────────────────────────────────────────────────────────
// ═══════════════════════════════════════════════════════════════════════════

function _dashMacro(r) {
  const el = document.getElementById('dash-macro-body');
  if (!el) return;
  const color = scoreColor(r.deployment_score);
  el.innerHTML = `
    <div style="text-align:center;padding:10px 0 14px">
      <div style="font-size:44px;font-weight:800;color:${color};font-family:var(--font-mono);line-height:1">${r.deployment_score.toFixed(1)}</div>
      <div style="margin-top:8px">
        <span class="tag ${r.deployment_score>=70?'tag-teal':r.deployment_score>=40?'tag-amber':'tag-red'}">${r.regime}</span>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
      ${Object.values(r.signals).slice(0,4).map(s => `
        <div style="background:rgba(255,255,255,0.03);border:1px solid var(--border);border-radius:7px;padding:8px 10px">
          <div style="font-size:9.5px;color:var(--text-muted);font-family:var(--font-mono);text-transform:uppercase;margin-bottom:3px">${s.name.slice(0,14)}</div>
          <div style="font-size:16px;font-weight:700;font-family:var(--font-mono);color:${scoreColor(s.score)}">${s.score.toFixed(0)}</div>
        </div>`).join('')}
    </div>
  `;
  // Update topbar metric
  const m = document.getElementById('m-deploy');
  if (m) {
    m.textContent = r.deployment_score.toFixed(1);
    m.style.color = color;
    document.getElementById('m-regime').textContent = r.regime;
  }
}

function _dashScanner(results) {
  const el = document.getElementById('dash-scanner-body');
  if (!el || !results.length) return;
  el.innerHTML = _scanCards(results.slice(0, 6), 'stock');
  document.getElementById('m-setups').textContent = results.length;
  document.getElementById('m-setups').style.color = '#c084fc';
  document.getElementById('m-scan-ts').textContent = `${results.length} setups found`;
}

function _scanCards(rows, type = 'stock', totalScanned = 0) {
  if (!rows.length) return '<div class="empty-state">No setups found</div>';

  // Filter out tiles with no actionable trade (WAIT / "Watch — Below Key Levels")
  const actionable = rows.filter(r => !r.trade || r.trade.action !== 'WAIT');
  const waitCount  = rows.length - actionable.length;
  rows = actionable.length ? actionable : rows; // fall back to all if everything filtered

  // Store for "log all" action
  window._lastScanRows = rows;

  const _setupColor = {
    // Momentum
    'Momentum Runner':             '#4ade80',
    'Confirmed Uptrend':           '#00d4aa',
    'Overbought Runner':           '#f59e0b',
    'Pullback to SMA50':           '#3b82f6',
    'Building Base':               '#94a3b8',
    // Mean reversion
    'Deep Oversold':               '#818cf8',
    'BB Bounce Setup':             '#a78bfa',
    'Z-Score Extreme':             '#c084fc',
    'Williams %R Oversold':        '#e879f9',
    'Oversold in Uptrend':         '#60a5fa',
    'Overextended — Reversion Risk':'#fb923c',
    'Far Above 200-SMA':           '#fbbf24',
    // Neutral
    'Watch — Below Key Levels':    '#475569',
  };
  const _setupEmoji = {
    'Momentum Runner':             '🚀',
    'Confirmed Uptrend':           '📈',
    'Overbought Runner':           '⚡',
    'Pullback to SMA50':           '↩',
    'Building Base':               '🏗',
    'Deep Oversold':               '🎯',
    'BB Bounce Setup':             '🎯',
    'Z-Score Extreme':             '📊',
    'Williams %R Oversold':        '🎯',
    'Oversold in Uptrend':         '🔄',
    'Overextended — Reversion Risk':'⚠',
    'Far Above 200-SMA':           '⚠',
    'Watch — Below Key Levels':    '👀',
  };

  const cacheKey  = type === 'crypto' ? 'cryptoScanResults' : 'scanResults';
  const scanAge   = _ageLabel(cacheKey);
  const scanStale = _isStale(cacheKey);
  const header = `
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;flex-wrap:wrap;gap:10px">
      <div style="font-size:13px;color:#94a3b8">
        <strong style="color:#e2e8f0">${rows.length} actionable setup${rows.length !== 1 ? 's' : ''}</strong>
        ${totalScanned ? ` from ${totalScanned} ${type === 'crypto' ? 'coins' : 'stocks'} scanned` : ''}
        ${waitCount > 0 ? ` <span style="color:#475569">· ${waitCount} watch-only hidden</span>` : ''}
        ${scanAge ? ` <span style="color:${scanStale?'#f59e0b':'#475569'}">· ${scanAge}${scanStale?' ⚠ stale':''}</span>` : ''}
        <span style="color:#475569"> — sorted by conviction</span>
      </div>
      <button class="btn btn-secondary btn-sm" onclick="logAllScanIdeas(this)">
        📔 Log All ${rows.length} to Journal
      </button>
    </div>`;

  const cards = rows.map(r => {
    const color   = _setupColor[r.setup_label] || '#94a3b8';
    const emoji   = _setupEmoji[r.setup_label] || '📊';
    const rsiCol  = r.rsi_14 < 30 ? '#60a5fa' : r.rsi_14 > 70 ? '#f87171' : '#4ade80';
    const rsiLbl  = r.rsi_14 < 30 ? 'Oversold' : r.rsi_14 > 70 ? 'Overbought' : r.rsi_14 < 50 ? 'Neutral' : 'Healthy';
    const momCol  = r.mom_3m_pct >= 0 ? '#4ade80' : '#f87171';
    const priceStr = r.price_fmt || (r.price < 100 ? r.price.toFixed(2) : fmtNum(r.price));
    const volM    = r.vol_usd_m ?? r.avg_vol_m ?? 0;

    const conv = r.conviction ?? 0;
    const convColor = conv >= 80 ? '#4ade80' : conv >= 65 ? '#00d4aa' : conv >= 50 ? '#f59e0b' : '#64748b';
    const convLabel = conv >= 80 ? 'High' : conv >= 65 ? 'Good' : conv >= 50 ? 'Moderate' : 'Low';

    // ── build tooltip strings for this card ──────────────────────────────────
    const setupTips = {
      'Momentum Runner':              'Price is in a strong uptrend with above-average volume confirming the move. Trend-following setup — ride the momentum with tight trailing stops.',
      'Confirmed Uptrend':            'Price is above both the 50-day and 200-day moving averages, with the 50 above the 200 (bullish "golden cross" alignment). Lowest-risk long environment.',
      'Overbought Runner':            'Strong momentum but RSI is elevated (>70). Price can stay overbought in strong trends. Consider waiting for a brief pullback before entering.',
      'Pullback to SMA50':            'Price has pulled back to its 50-day moving average in an existing uptrend. This is a classic "buy the dip" level used by institutional traders.',
      'Building Base':                'Price is consolidating after a move, coiling energy. No actionable entry yet — watch for a volume breakout from the base to confirm direction.',
      'Deep Oversold':                'RSI has fallen below 30, entering extreme oversold territory. Mean reversion setups have historically high hit-rates here. Risk: stocks can stay oversold in downtrends.',
      'BB Bounce Setup':              'Price has touched or pierced the lower Bollinger Band (2 standard deviations below the 20-day mean). Statistically ~95% of prices stay inside the bands — a touch often precedes a bounce.',
      'Z-Score Extreme':              'Price is more than 2 standard deviations below its 20-day average — a statistical outlier. Prices tend to revert to the mean. The further the z-score, the stronger the expected snap-back.',
      'Williams %R Oversold':         'Williams %R is below -80, indicating price is near the bottom of its recent 14-day range. When combined with other oversold signals, this adds high-probability reversal evidence.',
      'Oversold in Uptrend':          'RSI < 40 but price is still above the 200-day SMA. Best of both worlds: mean reversion entry opportunity within a healthy longer-term uptrend. Lower risk than pure oversold plays.',
      'Overextended — Reversion Risk':'Price has run far above recent averages. While the trend may continue, risk/reward for new longs is poor. A short or fade setup for experienced traders.',
      'Far Above 200-SMA':            'Price is trading significantly above its 200-day moving average. Extended moves like this often precede consolidation or pullbacks.',
      'Watch — Below Key Levels':     'Price is below both its 50-day and 200-day moving averages. No setup yet — on watchlist for potential recovery signals.',
    };
    const setupTip = setupTips[r.setup_label] || 'Scanner-detected technical setup based on price, volume, and momentum signals.';

    const rsiTip = `<strong>RSI (Relative Strength Index) — ${r.rsi_14.toFixed(1)}</strong><br>Measures how overbought or oversold a stock is on a 0–100 scale. <strong>&lt;30 = Oversold</strong> (potential bounce), <strong>&gt;70 = Overbought</strong> (potential pullback), <strong>40–60 = Healthy/neutral</strong>.`;
    const momTip = `<strong>3-Month Price Momentum — ${r.mom_3m_pct >= 0 ? '+' : ''}${r.mom_3m_pct.toFixed(1)}%</strong><br>How much the price has moved over the last 3 months. Strong positive momentum is the single best predictor of continued outperformance (Jegadeesh & Titman, 1993). Negative = weakening trend.`;
    const convTip = `<strong>Conviction Score — ${conv.toFixed(0)}/100</strong><br>Composite quality score: <strong>base setup strength</strong> + <strong>signal extremity</strong> (how deep the oversold/overbought reading) + <strong>log-scale volume bonus</strong> (institutional participation). ≥80 = High, 65–79 = Good, 50–64 = Moderate.`;
    const sma200Tip = `<strong>200-Day SMA — ${r.above_sma200 ? 'Above ✓' : 'Below ✗'}</strong><br>The 200-day Simple Moving Average is the most-watched long-term trend line. <strong>Above</strong> = long-term uptrend, institutional buyers typically active. <strong>Below</strong> = long-term downtrend, higher risk for longs.`;
    const sma50Tip  = `<strong>50-Day SMA — ${r.above_sma50 ? 'Above ✓' : 'Below ✗'}</strong><br>Medium-term trend gauge. <strong>Above</strong> = intermediate uptrend intact. <strong>Below</strong> = intermediate breakdown — often a warning sign. Classic pullback-to-50-SMA setups occur when price dips here and bounces.`;
    const volTip    = `<strong>Daily Volume — $${volM.toFixed(0)}M</strong><br>Average daily dollar volume traded. Higher liquidity = easier to enter/exit without slippage. The scanner uses this to filter low-liquidity names and weight conviction scores. &gt;$100M/day = institutional-grade liquidity.`;
    const bbTip     = r.bb_pct != null ? `<strong>Bollinger Band %B — ${r.bb_pct.toFixed(3)}</strong><br>Where price sits within the Bollinger Bands (20-day, 2 std dev). <strong>0 = at lower band</strong> (oversold extreme), <strong>0.5 = at middle band</strong> (mean), <strong>1 = at upper band</strong> (overbought extreme). Below 0.1 = deep oversold signal.` : '';
    const zTip      = r.zscore_20 != null ? `<strong>Z-Score (20-day) — ${r.zscore_20 > 0 ? '+' : ''}${r.zscore_20.toFixed(2)}</strong><br>How many standard deviations price is from its 20-day mean. <strong>Below −2</strong> = statistical outlier (rare, ~2.5% of days) → strong mean reversion signal. <strong>Above +2</strong> = extended above mean → potential fade. Near 0 = average price territory.` : '';
    const wTip      = r.williams_r != null ? `<strong>Williams %R — ${r.williams_r.toFixed(0)}</strong><br>Momentum oscillator showing where price sits in its 14-day high-low range. Scale: <strong>0 = at the top</strong> (overbought), <strong>−100 = at the bottom</strong> (oversold). Below <strong>−80</strong> = oversold reversal zone. Above <strong>−20</strong> = overbought.` : '';
    const rrTip     = `<strong>Risk:Reward Ratio</strong><br>Ratio of potential profit to potential loss. <strong>R:R 2.0</strong> means you risk $1 to make $2. Professional traders typically require ≥1.5:1 minimum; 2:1 or better is considered high-quality. The higher this number, the more asymmetric the setup in your favour.`;
    const entryTip  = `<strong>Entry Price</strong><br>Suggested price level to initiate the position. For momentum setups this is near current price or a break above resistance. For mean reversion setups this is near the oversold extreme. Consider using limit orders within 0.5–1% of this level.`;
    const targetTip = `<strong>Target Price</strong><br>Price objective for the trade based on measured moves, prior resistance levels, or mean-reversion fair value. This is where you'd take partial or full profits. Not a guarantee — use it to size your position correctly via the R:R ratio.`;
    const stopTip   = `<strong>Stop Loss Price</strong><br>Maximum risk level. If price reaches this point, the trade idea is invalidated. Position size should be calculated so that a stop-out equals a fixed % of your portfolio (e.g. 0.5–1% per trade). Never skip the stop.`;
    const mrLongTip  = `<strong>Mean Reversion — LONG (upside)</strong><br>Price has fallen significantly below its historical average. The model expects a snap-back rally toward the mean. You're buying the dip with a defined stop below the oversold extreme.`;
    const mrShortTip = `<strong>Mean Reversion — SHORT (downside)</strong><br>Price has risen significantly above its historical average. The model expects a pullback toward the mean. You're selling the extension with a stop above the recent high.`;
    const momTagTip  = `<strong>Momentum Setup</strong><br>Trend-following strategy. Price is in a confirmed uptrend with strong relative strength. The edge comes from buying strength — momentum stocks tend to continue outperforming over the next 3–12 months.`;

    // ── direction: LONG / SHORT / NEUTRAL ────────────────────────────────────
    const isShort = r.trade && r.trade.action === 'SELL/EXIT';
    const isLong  = r.trade && r.trade.action === 'BUY';
    const dirLabel   = isLong  ? 'LONG'    : isShort ? 'SHORT'   : 'WATCH';
    const dirArrow   = isLong  ? '▲'       : isShort ? '▼'       : '◌';
    const dirColor   = isLong  ? '#4ade80' : isShort ? '#f87171' : '#64748b';
    const dirBg      = isLong  ? 'rgba(74,222,128,0.12)'  : isShort ? 'rgba(248,113,113,0.12)'  : 'rgba(100,116,139,0.08)';
    const dirBorder  = isLong  ? 'rgba(74,222,128,0.35)'  : isShort ? 'rgba(248,113,113,0.35)'  : 'rgba(100,116,139,0.2)';
    const leftBorder = isLong  ? '#4ade80' : isShort ? '#f87171' : '#475569';
    const cardBg     = isLong  ? 'rgba(74,222,128,0.03)'  : isShort ? 'rgba(248,113,113,0.03)'  : '#0d1421';

    // Register tips into the global registry (safe: no HTML-attribute escaping needed)
    const tSetup  = tipAttr(setupTip);
    const tMom    = tipAttr(momTip);
    const tConv   = tipAttr(convTip);
    const tRsi    = tipAttr(rsiTip);
    const tSma200 = tipAttr(sma200Tip);
    const tSma50  = tipAttr(sma50Tip);
    const tVol    = tipAttr(volTip);
    const tBb     = r.bb_pct    != null ? tipAttr(bbTip)  : '';
    const tZ      = r.zscore_20 != null ? tipAttr(zTip)   : '';
    const tW      = r.williams_r!= null ? tipAttr(wTip)   : '';
    const tMrL    = tipAttr(mrLongTip);
    const tMrS    = tipAttr(mrShortTip);
    const tMomTag = tipAttr(momTagTip);
    const tRr     = tipAttr(rrTip);
    const tEntry  = tipAttr(entryTip);
    const tTarget = tipAttr(targetTip);
    const tStop   = tipAttr(stopTip);

    return `
      <div style="background:${cardBg};border:1px solid ${dirBorder};border-top:2px solid ${color};border-left:4px solid ${leftBorder};border-radius:10px;padding:14px;display:flex;flex-direction:column;gap:10px">

        <!-- Direction badge row -->
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:-2px">
          <div style="display:flex;align-items:center;gap:8px">
            <div style="font-size:15px;font-weight:800;font-family:var(--font-mono);color:#e2e8f0;letter-spacing:0.03em">${r.ticker}</div>
            <div style="font-size:20px;font-weight:700;color:${color};font-family:var(--font-mono)">${type === 'crypto' ? '' : '$'}${priceStr}</div>
          </div>
          <div style="display:flex;align-items:center;gap:6px;background:${dirBg};border:1px solid ${dirBorder};border-radius:8px;padding:5px 10px;min-width:80px;justify-content:center">
            <span style="font-size:15px;color:${dirColor};line-height:1">${dirArrow}</span>
            <span style="font-size:12px;font-weight:800;color:${dirColor};font-family:var(--font-mono);letter-spacing:0.08em">${dirLabel}</span>
          </div>
        </div>

        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px">
          <div>
            <div class="no-underline" ${tSetup} style="font-size:11px;color:${color};font-weight:600;white-space:nowrap;cursor:help">${emoji} ${r.setup_label}</div>
            <div class="no-underline" ${tMom} style="font-size:11px;color:${momCol};font-family:var(--font-mono);margin-top:3px;font-weight:600;cursor:help">
              ${r.mom_3m_pct >= 0 ? '▲ +' : '▼ '}${r.mom_3m_pct.toFixed(1)}% / 3M
            </div>
          </div>
          <div style="text-align:right">
            <div class="no-underline" ${tConv} style="display:inline-flex;align-items:center;gap:4px;background:rgba(0,0,0,0.3);border:1px solid ${convColor}33;border-radius:6px;padding:2px 7px;cursor:help">
              <span style="font-size:10px;color:${convColor};font-weight:700;font-family:var(--font-mono)">${conv.toFixed(0)}</span>
              <span style="font-size:9px;color:${convColor};opacity:0.8">${convLabel}</span>
            </div>
          </div>
        </div>

        <div class="no-underline" ${tRsi} style="cursor:help">
          <div style="display:flex;justify-content:space-between;font-size:10px;color:#475569;margin-bottom:4px">
            <span>RSI ${r.rsi_14.toFixed(0)}</span>
            <span style="color:${rsiCol}">${rsiLbl}</span>
          </div>
          <div style="height:5px;background:#1e293b;border-radius:99px;overflow:hidden">
            <div style="height:100%;width:${r.rsi_14}%;background:${rsiCol};border-radius:99px"></div>
          </div>
        </div>

        <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">
          <span class="tag no-underline ${r.above_sma200 ? 'tag-teal' : 'tag-red'}" style="font-size:10px;cursor:help" ${tSma200}>${r.above_sma200 ? '✓' : '✗'} SMA200</span>
          <span class="tag no-underline ${r.above_sma50  ? 'tag-teal' : 'tag-amber'}" style="font-size:10px;cursor:help" ${tSma50}>${r.above_sma50  ? '✓' : '✗'} SMA50</span>
          ${r.bb_pct    != null ? `<span class="tag no-underline" style="background:rgba(167,139,250,0.1);color:#a78bfa;font-size:10px;cursor:help" ${tBb}>BB% ${r.bb_pct.toFixed(2)}</span>` : ''}
          ${r.zscore_20 != null ? `<span class="tag no-underline" style="background:rgba(192,132,252,0.1);color:${Math.abs(r.zscore_20)>2?'#e879f9':'#94a3b8'};font-size:10px;cursor:help" ${tZ}>Z ${r.zscore_20 > 0 ? '+' : ''}${r.zscore_20.toFixed(1)}</span>` : ''}
          ${r.williams_r!= null ? `<span class="tag no-underline" style="background:rgba(99,102,241,0.1);color:${r.williams_r<=-80?'#818cf8':'#64748b'};font-size:10px;cursor:help" ${tW}>%R ${r.williams_r.toFixed(0)}</span>` : ''}
          <span class="tag no-underline" style="background:rgba(148,163,184,0.08);color:#64748b;font-size:10px;cursor:help" ${tVol}>Vol $${volM.toFixed(0)}M/day</span>
          ${r.setup_category === 'mean_reversion'
              ? (r.trade && r.trade.action === 'SELL/EXIT'
                  ? `<span class="tag no-underline" style="background:rgba(248,113,113,0.15);color:#f87171;font-size:9px;font-weight:700;letter-spacing:0.05em;cursor:help" ${tMrS}>MR SHORT ↓</span>`
                  : `<span class="tag no-underline" style="background:rgba(167,139,250,0.15);color:#a78bfa;font-size:9px;font-weight:700;letter-spacing:0.05em;cursor:help" ${tMrL}>MR LONG ↑</span>`)
              : r.setup_category === 'momentum'
                  ? `<span class="tag no-underline" style="background:rgba(74,222,128,0.1);color:#4ade80;font-size:9px;font-weight:700;letter-spacing:0.05em;cursor:help" ${tMomTag}>MOMENTUM</span>`
                  : ''}
        </div>

        ${(() => {
          const t = r.trade;
          if (!t) return `<div style="font-size:10.5px;color:#475569;line-height:1.5;padding:8px 10px;background:rgba(255,255,255,0.02);border-radius:6px;border:1px solid #1e293b">${escHtml(r.setup_desc || '')}</div>`;
          const actionCol = t.action === 'BUY' ? '#4ade80' : t.action === 'SELL/EXIT' ? '#f87171' : '#f59e0b';
          const actionBg  = t.action === 'BUY' ? 'rgba(74,222,128,0.08)' : t.action === 'SELL/EXIT' ? 'rgba(248,113,113,0.08)' : 'rgba(245,158,11,0.08)';
          return `
          <div style="background:${actionBg};border:1px solid ${actionCol}22;border-radius:8px;padding:10px 12px;display:flex;flex-direction:column;gap:7px">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:2px">
              <span style="font-size:11px;font-weight:800;color:${actionCol};letter-spacing:0.08em;font-family:var(--font-mono)">${t.action}</span>
              ${t.rr ? `<span class="no-underline" ${tRr} style="font-size:10px;color:#94a3b8;background:rgba(0,0,0,0.3);padding:1px 7px;border-radius:4px;font-family:var(--font-mono);cursor:help">R:R ${t.rr}</span>` : ''}
            </div>
            <div style="display:grid;grid-template-columns:56px 1fr;gap:3px 8px;font-size:10.5px">
              <span class="no-underline" ${tEntry} style="color:#64748b;font-weight:600;cursor:help">Entry</span>
              <span style="color:#e2e8f0">${escHtml(t.entry)}</span>
              <span class="no-underline" ${tTarget} style="color:#4ade80;font-weight:600;cursor:help">Target</span>
              <span style="color:#e2e8f0">${escHtml(t.target)}</span>
              <span class="no-underline" ${tStop} style="color:#f87171;font-weight:600;cursor:help">Stop</span>
              <span style="color:#e2e8f0">${escHtml(t.stop)}</span>
            </div>
            <div style="font-size:10px;color:#64748b;border-top:1px solid rgba(255,255,255,0.05);padding-top:6px;line-height:1.5;font-style:italic">${escHtml(t.note)}</div>
          </div>`;
        })()}

        <div style="display:flex;gap:6px">
          <button class="btn btn-secondary btn-sm" style="flex:1;font-size:10.5px;padding:5px 10px"
            onclick="logScanIdea(this,'${r.ticker}','${priceStr}','${r.setup_label.replace(/'/g,'')}','${r.mom_3m_pct}','${r.rsi_14}')">
            📔 Journal
          </button>
          ${r.trade && r.trade.action !== 'WAIT' ? `<button class="btn btn-primary btn-sm" style="flex:1;font-size:10.5px;padding:5px 10px"
            onclick="openPaperTradeModal(${JSON.stringify(r).replace(/"/g,'&quot;')})">
            ◎ Paper Trade
          </button>` : ''}
        </div>
      </div>`;
  }).join('');

  return header + `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(270px,1fr));gap:14px">${cards}</div>`;
}

// ── Signal tooltips ───────────────────────────────────────────────────────────
const _SIGNAL_TIPS = {
  // Original 7
  vix_level:         'The CBOE Volatility Index — measures expected market turbulence. High VIX = fear/panic. Low VIX = calm. A HIGH score here means VIX is low (good for deploying capital).',
  vix_term_structure:'Ratio of near-term VIX to longer-term VIX3M. Below 1 = "contango" — markets expect vol to ease = bullish. Above 1 = "backwardation" — near-term fear spike priced in = bearish.',
  breadth:           '% of S&P 500 stocks trading above their 200-day moving average. HIGH score = most stocks in uptrends = healthy, broad rally. LOW score = most stocks weakening = fragile market.',
  credit_spreads:    'Extra yield investors demand for risky (high-yield) bonds vs safe Treasuries. TIGHT spreads = risk appetite high = good. WIDE spreads = credit stress, risk-off = bad.',
  put_call:          'Combines VIX 20-day rate-of-change + VIX9D/VIX ratio (9-day vs. 30-day implied vol). When near-term vol is calm relative to 30-day vol AND VIX is falling = strong bullish sentiment signal.',
  yield_curve:       '10-year minus 3-month Treasury yield spread. POSITIVE & widening = healthy growth expectations. NEGATIVE (inverted) = historically precedes recessions by 12–18 months = major warning.',
  momentum:          'Combines SPY golden cross (50>200 SMA), 3-month return, and 12-1 month return. HIGH = confirmed uptrend. LOW = trend deteriorating.',
  // New institutional signals (FRED-sourced)
  nfci:              'Chicago Fed National Financial Conditions Index — a composite of 105 indicators measuring credit, risk, and leverage. NEGATIVE value = loose conditions (capital is easy to deploy) = HIGH score. POSITIVE = tight, stressed conditions = LOW score. Used by institutional macro desks as a one-number financial-conditions gauge.',
  m2_growth:         'Year-over-year growth in M2 money supply (from the Federal Reserve via FRED). Rising M2 = more liquidity flowing into the economy and markets = HIGH score. Falling or negative M2 = liquidity draining (as seen in 2022-23, preceding the bear market) = LOW score. Used by Bridgewater and systematic macro funds as a leading liquidity indicator.',
  inflation:         '10-Year breakeven inflation rate from the TIPS market (FRED T10YIE) — what bond traders expect inflation to average over the next decade. The "Goldilocks" zone is 2.0–2.5%: equities handle moderate inflation well. Below 1.5% = deflation risk (bad for earnings). Above 3.5% = Fed forced to tighten hard, multiples compress = bad. Score peaks near 2.3% and falls at both extremes.',
};

const _DEPLOY_TIP = 'Weighted blend of all 7 signals (0–100). ≥70 = Aggressive Deploy. 50–69 = Moderate. 30–49 = Cautious. <30 = Avoid. Think of it as a "green light" meter for putting money to work.';
const _WHATIF_TIP = 'Drag the sliders to simulate how the Deployment Score would change if a signal were different. Useful for stress-testing: e.g. "what if VIX spiked to 30?" or "what if spreads widened?"';

// ── Signal plain-English interpretation ──────────────────────────────────────
function _signalInterp(key, s) {
  const sc = s.score, v = s.value;
  switch (key) {
    case 'vix_level':
      if (sc >= 75) return `VIX=${v?.toFixed(1)} is low → markets very calm. Strong green light.`;
      if (sc >= 55) return `VIX=${v?.toFixed(1)} is moderate → some uncertainty but manageable.`;
      if (sc >= 35) return `VIX=${v?.toFixed(1)} elevated → fear rising, reduce position size.`;
      return `VIX=${v?.toFixed(1)} is high → market fear, avoid new entries.`;
    case 'vix_term_structure':
      if (sc >= 65) return `Contango — near-term vol below long-term. Markets expect calm to continue.`;
      if (sc >= 45) return `Near-neutral — mixed vol expectations, no strong signal.`;
      return `Backwardation — near-term fear spike priced in. Risk elevated.`;
    case 'breadth':
      if (sc >= 75) return `${v?.toFixed(0)}% of market in uptrend → rally is broad-based and healthy.`;
      if (sc >= 50) return `Majority above 200-SMA but starting to diverge → watch closely.`;
      if (sc >= 30) return `Narrow market — fewer stocks participating, rally at risk.`;
      return `Most stocks in downtrend → avoid new longs, broad weakness.`;
    case 'credit_spreads':
      if (sc >= 75) return `Spreads tight → credit markets fully risk-on. Ideal for equities.`;
      if (sc >= 50) return `Spreads normal → no credit stress, cautiously constructive.`;
      if (sc >= 30) return `Spreads widening → credit markets signalling stress. Be careful.`;
      return `Wide spreads → credit crisis risk. Avoid equities entirely.`;
    case 'put_call':
      if (sc >= 65) return `VIX falling ${v != null ? '('+v.toFixed(1)+'% ROC)' : ''} → fear fading, mood turning bullish.`;
      if (sc >= 45) return `VIX roughly flat → neutral sentiment, no directional edge.`;
      return `VIX rising ${v != null ? '('+v.toFixed(1)+'% ROC)' : ''} → fear increasing. Reduce risk.`;
    case 'yield_curve':
      if (v != null && v < 0) return `Curve inverted (${v.toFixed(3)}) → historical recession warning. Hard penalty applied.`;
      if (sc >= 70) return `Curve positive & healthy → growth expectations intact, no recession signal.`;
      if (sc >= 45) return `Curve flat-to-positive → modest growth priced in, monitor for inversion.`;
      return `Curve flattening fast → growth concerns growing. Be cautious.`;
    case 'momentum':
      if (sc >= 80) return `Golden Cross active + strong trend → SPY in confirmed uptrend.`;
      if (sc >= 60) return `Positive momentum but moderating → trend intact, watch for stalls.`;
      if (sc >= 40) return `Weak momentum → mixed signals, no clear trend direction.`;
      return `Negative momentum → downtrend. Avoid new long positions.`;
    case 'nfci':
      if (sc >= 75) return `NFCI=${v?.toFixed(3)} — very loose conditions. Capital is cheap and accessible. Green light.`;
      if (sc >= 55) return `NFCI=${v?.toFixed(3)} — moderately loose. Credit flowing, constructive backdrop.`;
      if (sc >= 40) return `NFCI=${v?.toFixed(3)} — neutral to slightly tight. No red flag but conditions tightening.`;
      if (sc >= 25) return `NFCI=${v?.toFixed(3)} — tight conditions. Credit stress building, reduce equity exposure.`;
      return `NFCI=${v?.toFixed(3)} — very tight. Financial stress elevated — risk-off recommended.`;
    case 'm2_growth':
      if (sc >= 75) return `M2 growing +${v?.toFixed(1)}% YoY → ample liquidity. Capital flowing into markets.`;
      if (sc >= 55) return `M2 +${v?.toFixed(1)}% YoY → healthy growth. Liquidity supportive.`;
      if (sc >= 40) return `M2 ${v?.toFixed(1)}% YoY → slowing liquidity. Monitor closely.`;
      if (sc >= 25) return `M2 ${v?.toFixed(1)}% YoY → liquidity contracting. Historically precedes equity weakness.`;
      return `M2 ${v?.toFixed(1)}% YoY — significant liquidity drain. High caution zone.`;
    case 'inflation':
      if (v != null && v < 1.5) return `Breakeven ${v.toFixed(2)}% — deflation risk. Bad for earnings and growth expectations.`;
      if (v != null && v >= 1.5 && v < 2.0) return `Breakeven ${v.toFixed(2)}% — below Fed target. Growth concerns, but inflation not the problem.`;
      if (v != null && v >= 2.0 && v < 2.8) return `Breakeven ${v.toFixed(2)}% — Goldilocks zone. Equities can absorb this level of inflation.`;
      if (v != null && v >= 2.8 && v < 3.5) return `Breakeven ${v.toFixed(2)}% — elevated. Fed may need to tighten, watch for rate pressure on multiples.`;
      return `Breakeven ${v?.toFixed(2)}% — high inflation priced in. Multiple compression risk.`;
    default:
      if (sc >= 70) return `Bullish reading — conditions favor deployment.`;
      if (sc >= 50) return `Neutral — mixed conditions, proceed with care.`;
      return `Bearish — unfavorable, reduce exposure.`;
  }
}

function _macroFull(r) {
  const sigs = Object.entries(r.signals);
  const color = scoreColor(r.deployment_score);
  const rc = regimeClass(r.regime);
  return `
    <div class="deploy-score-block">
      <div class="deploy-score-label" data-tip="${attrEsc(_DEPLOY_TIP)}">Deployment Score</div>
      <div class="deploy-score-value" style="color:${color}">${r.deployment_score.toFixed(1)}</div>
      <div><span class="deploy-regime-badge ${rc}">${r.regime}</span></div>
      <div style="font-size:11px;color:var(--text-muted);margin-top:8px;font-family:var(--font-mono)">${r.elapsed_s}s fetch</div>
    </div>

    <div class="gauge-grid">
      ${sigs.map(([k, s]) => `
        <div class="gauge-card">
          <div class="gauge-name" data-tip="${attrEsc(_SIGNAL_TIPS[k] || '')}">${s.name}</div>
          <div class="gauge-score" style="color:${scoreColor(s.score)}">${s.score.toFixed(1)}</div>
          <div id="gauge-${k}"></div>
          ${s.value != null ? `<div style="font-size:10px;color:#475569;font-family:var(--font-mono);text-align:center;margin-top:2px">${fmtNum(s.value, s.value != null && Math.abs(s.value) < 10 ? 2 : 0)} ${escHtml(s.unit || '')}</div>` : ''}
          <div class="gauge-interp">${_signalInterp(k, s)}</div>
        </div>`).join('')}
    </div>

    <div class="row-2">
      <div class="panel">
        <div class="panel-header"><div class="panel-title"><div class="panel-icon">⬡</div>Signal Radar</div></div>
        <div style="padding:10px"><div id="macro-radar" class="radar-wrap"></div></div>
      </div>
      <div class="panel">
        <div class="panel-header"><div class="panel-title">Signal Details</div></div>
        <table class="data-table">
          <thead><tr><th>Signal</th><th>Score</th><th>Value</th><th>Wt</th></tr></thead>
          <tbody>
            ${sigs.map(([k, s]) => `
              <tr>
                <td data-tip="${attrEsc(_SIGNAL_TIPS[k] || '')}">${s.name}</td>
                <td style="color:${scoreColor(s.score)};font-family:var(--font-mono);font-weight:700">${s.score.toFixed(1)}</td>
                <td style="font-family:var(--font-mono);font-size:11px;color:#94a3b8">${s.value != null ? fmtNum(s.value, 3) + ' ' + (s.unit||'') : '—'}</td>
                <td style="font-family:var(--font-mono);color:#475569">${Math.round(getWeight(k)*100)}%</td>
              </tr>`).join('')}
          </tbody>
        </table>
      </div>
    </div>

    <div class="panel" style="margin-bottom:18px">
      <div class="panel-header"><div class="panel-title">What-If: Adjust Signal Scores</div></div>
      <div class="panel-body">
        <div class="slider-grid" id="whatif-sliders"></div>
        <div style="text-align:center;margin-top:14px">
          <span style="font-size:12px;color:var(--text-muted);font-family:var(--font-mono)" data-tip="${attrEsc(_WHATIF_TIP)}">What-If Score: </span>
          <span id="whatif-score" style="font-size:22px;font-weight:700;font-family:var(--font-mono);color:${color}">${r.deployment_score.toFixed(1)}</span>
        </div>
      </div>
    </div>
  `;
}

const _WEIGHTS = { vix_level:0.18, vix_term_structure:0.14, breadth:0.18, credit_spreads:0.16, put_call:0.12, yield_curve:0.12, momentum:0.10 };
function getWeight(k) { return _WEIGHTS[k] || 0.14; }

function _initMacroCharts(r) {
  const sigs = Object.entries(r.signals);
  // Gauges
  sigs.forEach(([k, s]) => {
    const el = document.getElementById(`gauge-${k}`);
    if (el) renderGauge(`gauge-${k}`, s.score, s.name);
  });
  // Radar
  renderRadar('macro-radar',
    sigs.map(([,s]) => s.name.slice(0, 14)),
    sigs.map(([,s]) => s.score),
    100
  );
}

function _initWhatIf(r) {
  const sigs = Object.entries(r.signals);
  const grid = document.getElementById('whatif-sliders');
  if (!grid) return;

  const manual = {};
  sigs.forEach(([k, s]) => { manual[k] = s.score; });

  grid.innerHTML = sigs.map(([k, s]) => `
    <div class="slider-item">
      <label>${s.name.slice(0, 16)}</label>
      <input type="range" min="0" max="100" step="5" value="${Math.round(s.score)}"
        id="wi-${k}" oninput="updateWhatIf()">
      <div class="slider-val" id="wi-val-${k}">${Math.round(s.score)}</div>
    </div>`).join('');

  window.updateWhatIf = () => {
    let total = 0, wSum = 0;
    sigs.forEach(([k]) => {
      const v = +document.getElementById(`wi-${k}`).value;
      document.getElementById(`wi-val-${k}`).textContent = v;
      total += v * getWeight(k);
      wSum  += getWeight(k);
    });
    const score = total / wSum;
    const el = document.getElementById('whatif-score');
    if (el) { el.textContent = score.toFixed(1); el.style.color = scoreColor(score); }
  };
}

function _analystTable(ranked) {
  if (!ranked.length) return '<div class="empty-state">No results</div>';
  return `
    <div class="panel" style="margin-bottom:18px">
      <div class="panel-header">
        <div class="panel-title">Rankings (60% Quant + 40% Claude)</div>
      </div>
      <table class="data-table">
        <thead>
          <tr><th>#</th><th>Δ</th><th>Ticker</th><th>Sector</th><th>Blended</th><th>Quant</th><th>Claude</th><th>Consist.</th></tr>
        </thead>
        <tbody>
          ${ranked.map(c => {
            const d = c.rank_delta || 0;
            const dStr = d >= 3 ? `<span style="color:#4ade80;font-weight:700">▲${d}</span>`
                       : d <= -3 ? `<span style="color:#f87171;font-weight:700">▼${Math.abs(d)}</span>`
                       : '<span style="color:#475569">—</span>';
            return `<tr class="analyst-row" data-ticker="${c.ticker}" style="cursor:pointer">
              <td style="font-family:var(--font-mono);color:#475569">${c.rank}</td>
              <td>${dStr}</td>
              <td><strong>${c.ticker}</strong><br><span style="font-size:10.5px;color:#475569">${(c.name||'').slice(0,18)}</span></td>
              <td style="font-size:11px;color:#94a3b8">${(c.sector||'').slice(0,16)}</td>
              <td style="color:${scoreColor(c.blended_score)};font-family:var(--font-mono);font-weight:700">${c.blended_score}</td>
              <td style="font-family:var(--font-mono);color:#60a5fa">${c.quant_score.toFixed(1)}</td>
              <td style="font-family:var(--font-mono);color:#c084fc">${(c.claude_norm||0).toFixed(1)}</td>
              <td><span class="tag ${c.consistency_rating==='High'?'tag-teal':c.consistency_rating==='Medium'?'tag-amber':'tag-red'}">${c.consistency_rating||'—'}</span></td>
            </tr>`;
          }).join('')}
        </tbody>
      </table>
    </div>

    <div id="analyst-deepdive"></div>
  `;
}

function _bindAnalystSelect() {
  document.querySelectorAll('.analyst-row').forEach(row => {
    row.addEventListener('click', () => {
      const ticker = row.dataset.ticker;
      const cand = State.analystResults.find(c => c.ticker === ticker);
      if (cand) _renderDeepDive(cand);
    });
  });
}

function _renderDeepDive(c) {
  const dd = document.getElementById('analyst-deepdive');
  if (!dd) return;
  const dims = c.dimension_scores || {};
  const dimKeys = Object.keys(dims);
  const dimVals = dimKeys.map(k => dims[k]);
  const peer = c.peer || {};
  const rankings = peer.rankings || {};

  dd.innerHTML = `
    <div class="panel">
      <div class="panel-header">
        <div class="panel-title"><div class="panel-icon">◉</div>${c.ticker} — ${(c.name||'').slice(0,28)} Deep Dive</div>
        <span style="font-size:11px;color:#475569">Click another row to switch</span>
      </div>
      <div class="panel-body">
        <div class="row-2">
          <div>
            <div style="margin-bottom:14px">
              ${dimKeys.map(k => `
                <div style="margin-bottom:8px">
                  <div style="display:flex;justify-content:space-between;margin-bottom:3px">
                    <span style="font-size:11px;color:#94a3b8">${k.replace(/_/g,' ').replace(/\b\w/g,l=>l.toUpperCase())}</span>
                    <span style="font-size:12px;font-weight:700;font-family:var(--font-mono);color:${scoreColor(dims[k]/10*100)}">${dims[k]}/10</span>
                  </div>
                  <div class="bar-track" style="height:6px">
                    <div class="bar-fill ${scoreBarClass(dims[k]/10*100)}" style="width:${dims[k]*10}%"></div>
                  </div>
                </div>`).join('')}
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:11.5px;margin-bottom:12px">
              <div><span style="color:#475569">Blended:</span> <strong style="color:${scoreColor(c.blended_score)}">${c.blended_score}</strong></div>
              <div><span style="color:#475569">Quant:</span> <strong style="color:#60a5fa">${c.quant_score.toFixed(1)}</strong></div>
              <div><span style="color:#475569">Claude:</span> <strong style="color:#c084fc">${(c.claude_norm||0).toFixed(1)}</strong></div>
              <div><span style="color:#475569">Consist.:</span> <span class="tag ${c.consistency_rating==='High'?'tag-teal':'tag-amber'}">${c.consistency_rating||'—'}</span></div>
            </div>
          </div>
          <div>
            <div id="dd-radar-${c.ticker}" style="height:280px"></div>
          </div>
        </div>

        <div class="row-2" style="margin-bottom:14px">
          <div>
            <div style="font-size:12px;font-weight:600;color:#4ade80;margin-bottom:6px">🟢 Bull Case</div>
            <div style="background:rgba(74,222,128,0.05);border:1px solid rgba(74,222,128,0.15);border-radius:8px;padding:12px;font-size:12.5px;color:#94a3b8;line-height:1.5">
              ${escHtml(c.bull_case || '—')}
            </div>
          </div>
          <div>
            <div style="font-size:12px;font-weight:600;color:#f87171;margin-bottom:6px">🔴 Bear Case</div>
            <div style="background:rgba(239,68,68,0.05);border:1px solid rgba(239,68,68,0.15);border-radius:8px;padding:12px;font-size:12.5px;color:#94a3b8;line-height:1.5">
              ${escHtml(c.bear_case || '—')}
            </div>
          </div>
        </div>

        ${c.key_risks && c.key_risks.length ? `
          <div style="margin-bottom:12px">
            <div style="font-size:12px;font-weight:600;margin-bottom:6px">⚠ Key Risks</div>
            ${c.key_risks.map(r => `<div style="font-size:12px;color:#94a3b8;margin-bottom:3px">· ${escHtml(r)}</div>`).join('')}
          </div>` : ''}

        ${c.reasoning_summary ? `
          <details>
            <summary style="cursor:pointer;font-size:12px;color:#60a5fa">Analyst Reasoning</summary>
            <div style="font-size:12px;color:#94a3b8;line-height:1.5;margin-top:8px;padding:10px;background:rgba(255,255,255,0.02);border-radius:6px">
              ${escHtml(c.reasoning_summary)}
            </div>
          </details>` : ''}

        ${Object.keys(rankings).length ? `
          <div style="margin-top:14px">
            <div style="font-size:12px;font-weight:600;margin-bottom:8px">Peer Benchmarks (${peer.sector||''})</div>
            <table class="data-table" style="font-size:11.5px">
              <thead><tr><th>Metric</th><th>Value</th><th>Peer Median</th><th>Percentile</th></tr></thead>
              <tbody>
                ${Object.entries(rankings).map(([m, info]) => `
                  <tr>
                    <td style="color:#94a3b8">${m.replace(/_/g,' ').replace(/\b\w/g,l=>l.toUpperCase())}</td>
                    <td style="font-family:var(--font-mono)">${info.value != null ? (info.value*100).toFixed(1)+'%' : '—'}</td>
                    <td style="font-family:var(--font-mono);color:#475569">${info.peer_median != null ? (info.peer_median*100).toFixed(1)+'%' : '—'}</td>
                    <td style="color:${scoreColor(info.percentile_rank||50)};font-family:var(--font-mono);font-weight:700">${info.percentile_rank != null ? info.percentile_rank+'th' : '—'}</td>
                  </tr>`).join('')}
              </tbody>
            </table>
          </div>` : ''}
      </div>
    </div>
  `;

  // Render radar with slight delay for DOM
  setTimeout(() => {
    if (dimKeys.length) {
      renderRadar(`dd-radar-${c.ticker}`,
        dimKeys.map(k => k.replace(/_/g,' ').replace(/\b\w/g,l=>l.toUpperCase())),
        dimVals, 10, '#60a5fa');
    }
  }, 50);
  dd.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ── Paper Trade helpers ───────────────────────────────────────────────────────

function _fmtPrice(p) {
  if (p == null) return '–';
  if (p < 0.01)  return '$' + p.toFixed(6);
  if (p < 1)     return '$' + p.toFixed(4);
  if (p < 100)   return '$' + p.toFixed(2);
  return '$' + p.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function openPaperTradeModal(r) {
  const t = r.trade;
  if (!t) return;

  // Parse predicted R:R ("6.1:1" → 6.1)
  const rrNum = t.rr ? parseFloat(t.rr) : null;

  // Extract numeric prices from entry/target/stop strings ("$69,499.60 …" → 69499.60)
  const parsePrice = (s) => {
    const m = s.match(/\$([\d,]+\.?\d*)/);
    return m ? parseFloat(m[1].replace(/,/g, '')) : null;
  };
  const entryP  = parsePrice(t.entry)  ?? r.price;
  const targetP = parsePrice(t.target) ?? r.price;
  const stopP   = parsePrice(t.stop)   ?? r.price;

  // Build modal
  const existing = document.getElementById('pt-modal');
  if (existing) existing.remove();

  const modal = document.createElement('div');
  modal.id = 'pt-modal';
  modal.style.cssText = `position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:10000;display:flex;align-items:center;justify-content:center;padding:20px`;
  const actionCol = t.action === 'BUY' ? '#4ade80' : '#f87171';

  modal.innerHTML = `
    <div style="background:#0d1421;border:1px solid #1e293b;border-top:2px solid ${actionCol};border-radius:12px;padding:24px;width:100%;max-width:480px;display:flex;flex-direction:column;gap:16px">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <div>
          <div style="font-size:16px;font-weight:700;color:#e2e8f0">◎ Paper Trade — ${r.ticker}</div>
          <div style="font-size:11px;color:#64748b;margin-top:2px">${r.setup_label} · Conviction ${r.conviction?.toFixed(0)}</div>
        </div>
        <button onclick="document.getElementById('pt-modal').remove()" style="background:none;border:none;color:#475569;font-size:18px;cursor:pointer">✕</button>
      </div>

      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px">
        <div>
          <label style="font-size:10px;color:#64748b;display:block;margin-bottom:4px">Entry Price</label>
          <input id="pt-entry" class="form-input" type="number" step="any" value="${entryP}" style="font-family:var(--font-mono)">
        </div>
        <div>
          <label style="font-size:10px;color:#4ade80;display:block;margin-bottom:4px">Target</label>
          <input id="pt-target" class="form-input" type="number" step="any" value="${targetP}" style="font-family:var(--font-mono)">
        </div>
        <div>
          <label style="font-size:10px;color:#f87171;display:block;margin-bottom:4px">Stop Loss</label>
          <input id="pt-stop" class="form-input" type="number" step="any" value="${stopP}" style="font-family:var(--font-mono)">
        </div>
      </div>

      <div style="background:rgba(0,0,0,0.2);border:1px solid #1e293b;border-radius:8px;padding:10px 12px;font-size:10.5px;color:#64748b;line-height:1.6">
        <strong style="color:${actionCol}">${t.action}</strong> · ${t.note}
      </div>

      <div style="display:flex;gap:8px">
        <button class="btn btn-primary" style="flex:1" onclick="_submitPaperTrade(${JSON.stringify({
          ticker:         r.ticker,
          setup_label:    r.setup_label,
          setup_category: r.setup_category,
          action:         t.action,
          predicted_rr:   rrNum,
          conviction:     r.conviction,
          trade_note:     t.note,
        }).replace(/"/g,'&quot;')})">
          Confirm Paper Trade
        </button>
        <button class="btn btn-secondary" onclick="document.getElementById('pt-modal').remove()">Cancel</button>
      </div>
    </div>`;

  document.body.appendChild(modal);
  modal.addEventListener('click', (e) => { if (e.target === modal) modal.remove(); });
}

async function _submitPaperTrade(meta) {
  const entry  = parseFloat(document.getElementById('pt-entry').value);
  const target = parseFloat(document.getElementById('pt-target').value);
  const stop   = parseFloat(document.getElementById('pt-stop').value);
  if (isNaN(entry) || isNaN(target) || isNaN(stop)) return alert('Invalid prices');

  const macroScore = State.macroResult?.deployment_score ?? null;

  const res = await API.openPaperTrade({
    ...meta,
    entry_price:  entry,
    target_price: target,
    stop_price:   stop,
    macro_score:  macroScore,
  });

  document.getElementById('pt-modal')?.remove();

  if (res.id) {
    const btn = document.createElement('div');
    btn.style.cssText = `position:fixed;bottom:24px;right:24px;background:#0d1421;border:1px solid #4ade80;border-radius:8px;padding:10px 16px;font-size:12px;color:#4ade80;z-index:9999`;
    btn.textContent = `✓ Paper trade #${res.id} opened for ${meta.ticker}`;
    document.body.appendChild(btn);
    setTimeout(() => btn.remove(), 3000);
  }
}

async function triggerLoop(btn) {
  const orig = btn.textContent;
  btn.textContent = '⟳ Running…';
  btn.disabled = true;
  try {
    const macroScore = State.macroResult?.deployment_score ?? null;
    const res = await API.runLoop({ universe: 'crypto', top_n: 100, macro_score: macroScore });
    const opened   = res.scan?.opened?.length   ?? 0;
    const resolved = res.positions?.resolved?.length ?? 0;
    const checked  = res.positions?.checked       ?? 0;

    // Show inline toast
    const toast = document.createElement('div');
    toast.style.cssText = `position:fixed;bottom:24px;right:24px;background:#0d1421;border:1px solid #00d4aa;border-radius:8px;padding:12px 18px;font-size:12px;color:#e2e8f0;z-index:9999;max-width:320px;line-height:1.6`;
    toast.innerHTML = `<strong style="color:#00d4aa">Loop complete</strong><br>
      Checked ${checked} positions · ${resolved} resolved<br>
      Scanned ${res.scan?.scan_count??0} setups · ${opened} new trade${opened!==1?'s':''} opened`;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 5000);

    // Reload the page to show new state
    const container = document.getElementById('page-content');
    if (container) await Pages.papertrades(container);
  } catch (err) {
    alert('Loop error: ' + err.message);
  } finally {
    btn.textContent = orig;
    btn.disabled = false;
  }
}

async function toggleLoopPause(btn) {
  const status = await API.getLoopStatus();
  if (status.scheduler_running) {
    await API.pauseLoop();
    btn.textContent = '▶ Resume Auto';
    btn.style.color = '#f87171';
  } else {
    await API.resumeLoop();
    btn.textContent = '⏸ Pause Auto';
    btn.style.color = '';
  }
}

async function checkPaperTrades(btn) {
  if (btn) btn.textContent = '⟳ Checking…';
  const res = await API.checkPaperTrades();
  if (btn) btn.textContent = '⟳ Check Prices';
  const n = res.resolved?.length || 0;
  if (n === 0) {
    alert(`Checked ${res.checked} open trades — no targets or stops hit yet.`);
  } else {
    const lines = res.resolved.map(r =>
      `${r.ticker}: ${r.status.replace('_',' ')} @ ${r.exit} (${r.pnl_pct >= 0 ? '+' : ''}${r.pnl_pct}%)`
    ).join('\n');
    alert(`Resolved ${n} trade(s):\n\n${lines}`);
    // Reload the page to show updated state
    const container = document.getElementById('content');
    if (container) await Pages.papertrades(container);
  }
}

async function _loadJournal() {
  try {
    const [jData, stats] = await Promise.all([API.getJournal(), API.getJournalStats()]);
    const entries = jData.entries || [];

    // Stats row
    const sEl = document.getElementById('journal-stats');
    if (sEl && stats.total_trades > 0) {
      sEl.innerHTML = `
        <div class="metrics-row" style="grid-template-columns:repeat(4,1fr)">
          <div class="metric-card" style="--card-top:#00d4aa"><div class="metric-label">Trades</div><div class="metric-value" style="color:#00d4aa">${stats.total_trades}</div></div>
          <div class="metric-card" style="--card-top:${stats.win_rate>=50?'#4ade80':'#f87171'}">
            <div class="metric-label">Win Rate</div>
            <div class="metric-value" style="color:${stats.win_rate>=50?'#4ade80':'#f87171'}">${stats.win_rate}%</div>
          </div>
          <div class="metric-card" style="--card-top:${stats.avg_pnl>=0?'#4ade80':'#f87171'}">
            <div class="metric-label">Avg P&L</div>
            <div class="metric-value" style="color:${stats.avg_pnl>=0?'#4ade80':'#f87171'}">${stats.avg_pnl>=0?'+':''}${stats.avg_pnl.toFixed(2)}%</div>
          </div>
          <div class="metric-card" style="--card-top:${stats.total_pnl>=0?'#4ade80':'#f87171'}">
            <div class="metric-label">Total P&L</div>
            <div class="metric-value" style="color:${stats.total_pnl>=0?'#4ade80':'#f87171'}">${stats.total_pnl>=0?'+':''}${stats.total_pnl.toFixed(2)}%</div>
          </div>
        </div>`;
    }

    const eEl = document.getElementById('journal-entries');
    if (!eEl) return;
    if (!entries.length) { eEl.innerHTML = '<div class="empty-state">No entries yet. Click ➕ New Entry to log a trade.</div>'; return; }

    const icons = { trade:'🔵', idea:'💡', note:'📝', review:'🔍' };
    eEl.innerHTML = entries.map(e => {
      const pnl = e.pnl_pct;
      const pnlStr = pnl != null ? `<span style="color:${pnl>=0?'#4ade80':'#f87171'};font-weight:700">${pnl>=0?'+':''}${pnl.toFixed(2)}%</span>` : '';
      return `
        <div class="journal-entry">
          <div class="entry-header">
            <div style="display:flex;align-items:center;gap:8px">
              <span style="font-size:15px">${icons[e.entry_type]||'📌'}</span>
              <span style="font-weight:700;font-size:13.5px">${e.ticker||e.entry_type.toUpperCase()}</span>
              ${e.direction ? `<span class="tag tag-blue" style="font-size:10px">${e.direction}</span>` : ''}
              ${pnlStr}
            </div>
            <div style="display:flex;align-items:center;gap:8px">
              <span style="font-size:11px;color:#475569;font-family:var(--font-mono)">${e.created_at.slice(0,10)}</span>
              <button class="btn btn-danger btn-sm btn-icon" onclick="deleteJournalEntry(${e.id})" title="Delete">✕</button>
            </div>
          </div>
          <div class="entry-body">
            ${e.rationale ? `<div style="margin-bottom:4px">${escHtml(e.rationale)}</div>` : ''}
            ${e.outcome   ? `<div style="color:#60a5fa">${escHtml(e.outcome)}</div>` : ''}
            ${e.tags ? `<div style="margin-top:6px">${e.tags.split(',').map(t=>`<span class="tag tag-purple" style="margin-right:4px;font-size:9.5px">${t.trim()}</span>`).join('')}</div>` : ''}
            ${e.deploy_score ? `<div style="margin-top:5px;font-size:10.5px;color:#475569;font-family:var(--font-mono)">Deploy score at entry: ${e.deploy_score} · ${e.regime||''}</div>` : ''}
          </div>
        </div>`;
    }).join('');
  } catch (err) {
    const eEl = document.getElementById('journal-entries');
    if (eEl) eEl.innerHTML = errorHTML(err.message);
  }
}
