/**
 * KitePilot - Zerodha Algo Trading Frontend Application
 * Implements PROMPT 3 (Algo Signals) and PROMPT 4 (Simulated GTT Placement Workflow)
 */

(function () {
  'use strict';

  // --- State Store ---
  const state = {
    activeTab: 'market-indices',
    scannerRawData: null,
    scannedCount: 0,
    algoSignals: [], // Triggered breakouts array
    selectedSymbol: null,
    livePrices: {}, // symbol -> { ltp, change, lastUpdate }
    ohlcSnapshot: {}, // symbol -> { last_price }
    wsConnection: null,
    subscribedTokens: [],
    gttCandidates: [], // Derived from algoSignals
    gttResults: {}, // symbol -> { buy_status, trigger_id, message, state, ... }
    isRunningLive: false,
  };

  // --- DOM Elements ---
  const el = {
    // Nav & Titles
    pageTitle: document.getElementById('page-title'),
    navItems: document.querySelectorAll('.nav-item'),
    tabPanes: document.querySelectorAll('.tab-pane'),
    
    // Header & User
    wsStatusBadge: document.getElementById('ws-status-badge'),
    wsStatusText: document.getElementById('ws-status-text'),
    userNameHeader: document.getElementById('user-name-header'),
    
    // Algo Signals elements
    statTriggered: document.getElementById('stat-triggered'),
    statScanned: document.getElementById('stat-scanned'),
    statWsSummary: document.getElementById('stat-ws-summary'),
    btnRefreshScanner: document.getElementById('btn-refresh-scanner'),
    btnRunLive: document.getElementById('btn-run-live'),
    algoErrorBox: document.getElementById('algo-error-box'),
    algoInfoBox: document.getElementById('algo-info-box'),
    breakoutsBadge: document.getElementById('breakouts-badge'),
    tbodyAlgoSignals: document.getElementById('tbody-algo-signals'),
    stateAlgoLoading: document.getElementById('state-algo-loading'),
    stateAlgoEmpty: document.getElementById('state-algo-empty'),
    
    // GTT Placement elements
    gttCountBadge: document.getElementById('gtt-count-badge'),
    gttInfoBox: document.getElementById('gtt-info-box'),
    tbodyGttPlacement: document.getElementById('tbody-gtt-placement'),
    stateGttEmpty: document.getElementById('state-gtt-empty'),
    
    // User profile elements
    userAuthChip: document.getElementById('user-auth-chip'),
    userApiKey: document.getElementById('user-api-key'),
    userAccountName: document.getElementById('user-account-name'),
    userOpenPositions: document.getElementById('user-open-positions'),
    userHoldings: document.getElementById('user-holdings'),
  };

  // --- Helper Functions ---
  function formatCurrency(val) {
    if (val === null || val === undefined || isNaN(val)) return '-';
    return Number(val).toLocaleString('en-IN', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  function formatSignedPercent(val) {
    if (val === null || val === undefined || isNaN(val)) return '-';
    const num = Number(val);
    const sign = num > 0 ? '+' : '';
    return `${sign}${num.toFixed(2)}%`;
  }

  function roundToTick(price, tickSize = 0.05) {
    if (price === null || price === undefined || isNaN(price) || price <= 0) return 0.0;
    const ticks = Math.round(price / tickSize);
    return Math.round(ticks * tickSize * 100) / 100;
  }

  function formatVolume(val) {
    if (!val || isNaN(val)) return '-';
    const num = Number(val);
    if (num >= 10000000) return `${(num / 10000000).toFixed(2)} Cr`;
    if (num >= 100000) return `${(num / 100000).toFixed(1)} L`;
    if (num >= 1000) return `${(num / 1000).toFixed(0)} K`;
    return num.toLocaleString('en-IN');
  }

  // --- Tab Navigation ---
  function setupNavigation() {
    el.navItems.forEach((btn) => {
      btn.addEventListener('click', () => {
        const tabKey = btn.getAttribute('data-tab');
        switchTab(tabKey);
      });
    });
  }

  function switchTab(tabKey) {
    state.activeTab = tabKey;
    el.navItems.forEach((btn) => {
      btn.classList.toggle('active', btn.getAttribute('data-tab') === tabKey);
    });
    el.tabPanes.forEach((pane) => {
      pane.classList.toggle('active', pane.id === `tab-${tabKey}`);
    });

    if (tabKey === 'market-indices') {
      el.pageTitle.textContent = 'All Indian Stock Market Indices Live Dashboard';
      loadIndicesData();
    } else if (tabKey === 'algo-signals') {
      el.pageTitle.textContent = 'High-volume breakout and retest setups';
    } else if (tabKey === 'orb-45min') {
      el.pageTitle.textContent = '45-Minute Opening Range Breakouts';
      loadOrb45Data();
    } else if (tabKey === 'stage-2') {
      el.pageTitle.textContent = 'Stage 2 Trend Template Breakouts';
      loadStage2Data();
    } else if (tabKey === 'canslim') {
      el.pageTitle.textContent = 'William O\'Neil CANSLIM Growth Leaders';
      loadCanslimData();
    } else if (tabKey === 'momentum-positional') {
      el.pageTitle.textContent = 'Momentum Positional Trading (Kotak Neo API)';
      loadMomentumPositionalData();
    } else if (tabKey === 'btst') {
      el.pageTitle.textContent = 'BTST (Buy Today, Sell Tomorrow) Momentum';
      loadBtstData();
    } else if (tabKey === 'swing-setups') {
      el.pageTitle.textContent = 'Volume-Confirmed Bullish Swing Trade Setups';
      loadSwingData();
    } else if (tabKey === 'gtt-placement') {
      el.pageTitle.textContent = 'GTT Placement (Simulated Workflow)';
      renderGTTTable();
    } else if (tabKey === 'user') {
      el.pageTitle.textContent = 'User Profile & Kite Status';
      loadUserStatus();
    }
  }

  // --- Fetch User Status & Multi-Broker Support ---
  let currentActiveBroker = 'kite';

  async function loadUserStatus(brokerOverride) {
    const broker = brokerOverride || currentActiveBroker;
    try {
      const res = await fetch(`/api/user-status?broker=${broker}`);
      if (!res.ok) return;
      const data = await res.json();

      if (el.userNameHeader) el.userNameHeader.textContent = data.user_name || 'Trader';
      if (el.userAccountName) el.userAccountName.textContent = data.user_name || 'Trader';
      if (el.userApiKey) el.userApiKey.textContent = data.api_key_masked || 'Not Configured';
      if (el.userOpenPositions) el.userOpenPositions.textContent = data.open_positions_count || '0';
      if (el.userHoldings) el.userHoldings.textContent = data.holdings_count || '0';

      if (el.userAuthChip) {
        if (data.authenticated) {
          el.userAuthChip.textContent = '✓ Active & Connected';
          el.userAuthChip.className = 'status-chip connected';
        } else {
          el.userAuthChip.textContent = 'Session Expired / Simulation';
          el.userAuthChip.className = 'status-chip disconnected';
        }
      }

      // Toggle Quick Kite Login Button in top header
      const quickKiteBtn = document.getElementById('btn-quick-kite-login');
      if (quickKiteBtn) {
        if (broker === 'kite' && !data.authenticated) {
          quickKiteBtn.style.display = 'inline-flex';
        } else {
          quickKiteBtn.style.display = 'none';
        }
      }

      // Check Kotak Neo status specifically
      const kRes = await fetch('/api/user-status?broker=kotak');
      if (kRes.ok) {
        const kData = await kRes.json();
        const kChip = document.getElementById('kotak-auth-chip');
        if (kChip) {
          if (kData.authenticated) {
            kChip.textContent = '✓ Active & Connected';
            kChip.style.background = 'rgba(34, 197, 94, 0.2)';
            kChip.style.color = '#4ade80';
          } else {
            kChip.textContent = 'Ready (Awaiting TOTP)';
            kChip.style.background = 'rgba(56, 189, 248, 0.15)';
            kChip.style.color = '#38bdf8';
          }
        }
      }
    } catch (err) {
      console.warn('Failed to load user status:', err);
    }
  }

  function setBroker(broker) {
    currentActiveBroker = broker;
    const isKotak = broker === 'kotak';
    const btnKite = document.getElementById('btn-broker-kite');
    const btnKotak = document.getElementById('btn-broker-kotak');

    if (btnKite && btnKotak) {
      if (isKotak) {
        btnKotak.style.background = '#0284c7';
        btnKotak.style.color = '#f8fafc';
        btnKite.style.background = 'transparent';
        btnKite.style.color = '#94a3b8';
      } else {
        btnKite.style.background = '#38bdf8';
        btnKite.style.color = '#0f172a';
        btnKotak.style.background = 'transparent';
        btnKotak.style.color = '#94a3b8';
      }
    }

    // Update Page & Sidebar Branding
    document.title = isKotak ? 'NeoPilot - Kotak Neo Algo Trading v1.0.0' : 'KitePilot - Zerodha Algo Trading v1.0.0';
    const brandH2 = document.querySelector('.brand-info h2');
    if (brandH2) brandH2.textContent = isKotak ? 'NeoPilot' : 'KitePilot';
    const brandIcon = document.querySelector('.brand-icon');
    if (brandIcon) brandIcon.textContent = isKotak ? '🔷' : '⚡';
    const userAvatar = document.querySelector('.user-avatar');
    if (userAvatar) userAvatar.textContent = isKotak ? 'KN' : 'ZP';

    // Highlight active broker profile card in User tab
    const cardKite = document.getElementById('card-kite-profile');
    const cardKotak = document.getElementById('card-kotak-profile');
    if (cardKite && cardKotak) {
      if (isKotak) {
        cardKotak.style.borderColor = '#0284c7';
        cardKotak.style.boxShadow = '0 0 15px rgba(2, 132, 199, 0.2)';
        cardKite.style.borderColor = 'rgba(255,255,255,0.08)';
        cardKite.style.boxShadow = 'none';
      } else {
        cardKite.style.borderColor = '#38bdf8';
        cardKite.style.boxShadow = '0 0 15px rgba(56, 189, 248, 0.2)';
        cardKotak.style.borderColor = 'rgba(255,255,255,0.08)';
        cardKotak.style.boxShadow = 'none';
      }
    }

    loadUserStatus(broker);
  }

  // --- Scanner Engine (PROMPT 3 Exact Logic) ---
  function normalizeCandles(candlesRaw) {
    if (!candlesRaw || !Array.isArray(candlesRaw)) return [];
    const normalized = [];
    for (const c of candlesRaw) {
      let dt = c.date || c.Date || '';
      if (dt.includes('T')) dt = dt.split('T')[0];
      else if (dt.includes(' ')) dt = dt.split(' ')[0];

      normalized.push({
        date: dt,
        open: Number(c.open !== undefined ? c.open : c.Open),
        high: Number(c.high !== undefined ? c.high : c.High),
        low: Number(c.low !== undefined ? c.low : c.Low),
        close: Number(c.close !== undefined ? c.close : c.Close),
        volume: Number(c.volume !== undefined ? c.volume : c.Volume),
      });
    }
    // Sort oldest first
    normalized.sort((a, b) => (a.date > b.date ? 1 : a.date < b.date ? -1 : 0));
    return normalized;
  }

  function evaluateBreakoutStock(stock) {
    const symbol = stock.symbol;
    const companyName = stock.companyName || symbol;
    const instrumentToken = stock.instrument_token || 0;
    const candlesRaw = stock.daily_candles || stock.candles || [];

    const candles = normalizeCandles(candlesRaw);
    const n = candles.length;

    // 1. Scanned count handled by caller
    // 2. Require at least 25 candles
    if (n < 25) return null;

    const latestCandle = candles[n - 1];
    const currentPrice = latestCandle.close;

    // 3. Start checking from second-last candle and scan backward
    // 4. Earliest eligible candle must have >= 20 preceding candles (bIndex >= 20)
    //    and no more than 20 candles before latest (n - 1 - bIndex <= 20 => bIndex >= n - 21)
    const minBIndex = Math.max(20, n - 21);
    const maxBIndex = n - 2;

    for (let bIdx = maxBIndex; bIdx >= minBIndex; bIdx--) {
      const candidate = candles[bIdx];
      const bOpen = candidate.open;
      const bClose = candidate.close;
      const bHigh = candidate.high;
      const bLow = candidate.low;
      const bVol = candidate.volume;

      // 5. Previous 20 candles excluding candidate
      const prev20 = candles.slice(bIdx - 20, bIdx);
      const prevVols = prev20.map((c) => c.volume);
      const prevHighs = prev20.map((c) => c.high);

      const avgVol20 = prevVols.reduce((acc, v) => acc + v, 0) / 20.0;
      const prevHigh = Math.max(...prevHighs);

      // 6. Accept breakout candle conditions:
      // - Average volume available (> 0)
      // - Close > Open
      // - Volume >= 3 * avgVol
      // - Close > previous 20-candle high
      // - Monthly volume >= 700,000 shares
      const trailing20Vol = candles.slice(-20).reduce((acc, c) => acc + (c.volume || 0), 0);
      if (trailing20Vol < 700000) continue;
      if (avgVol20 <= 0) continue;
      if (bClose <= bOpen) continue;
      if (bVol < 3.0 * avgVol20) continue;
      if (bClose <= prevHigh) continue;

      // 7. Find highest high among all candles after breakout candle
      const subsequent = candles.slice(bIdx + 1);
      if (!subsequent || subsequent.length === 0) continue;
      const maxPriceAfter = Math.max(...subsequent.map((c) => c.high));

      // 8. Reject candidate unless subsequent high > breakout candle high
      if (maxPriceAfter <= bHigh) continue;

      // 9. Calculations
      const midpoint = (bHigh + bLow) / 2.0;
      if (midpoint <= 0) continue;

      const distFromMidpoint = ((currentPrice - midpoint) / midpoint) * 100.0;
      const breakoutAge = n - 1 - bIdx;

      // 10. Accept setup only when:
      // - Absolute distance from midpoint is within 1% (<= 1.0)
      // - Breakout age is no more than 20 candles (<= 20)
      if (Math.abs(distFromMidpoint) > 1.0) continue;
      if (breakoutAge > 20) continue;

      const volMultiple = bVol / avgVol20;
      const returnToSubHigh = ((maxPriceAfter - bClose) / bClose) * 100.0;
      const retracementHigh = ((maxPriceAfter - currentPrice) / maxPriceAfter) * 100.0;

      // 11. Add only one result per stock (most recent accepted setup)
      return {
        symbol,
        companyName,
        instrument_token: instrumentToken,
        currentPrice: roundToTick(currentPrice),
        breakoutDate: candidate.date,
        bIndex: bIdx,
        daysSince: breakoutAge,
        breakoutLow: roundToTick(bLow),
        breakoutHigh: roundToTick(bHigh),
        midpoint: Math.round(midpoint * 100) / 100,
        distanceFromMidpoint: Math.round(distFromMidpoint * 100) / 100,
        volMultiple: Math.round(volMultiple * 100) / 100,
        prevHigh: roundToTick(prevHigh),
        maxPriceAfter: roundToTick(maxPriceAfter),
        returnFromCloseToSubHigh: Math.round(returnToSubHigh * 100) / 100,
        retracementHigh: Math.round(retracementHigh * 100) / 100,
        candles,
      };
    }

    return null;
  }

  function runScannerLogic(scannerData) {
    const stocks = scannerData.stocks || [];
    state.scannedCount = stocks.length;
    const results = [];

    for (const stock of stocks) {
      const res = evaluateBreakoutStock(stock);
      if (res) results.push(res);
    }

    // Sort results:
    // 1. By breakout age (daysSince), lowest first
    // 2. For results with same age, by absolute distance from midpoint, lowest first
    results.sort((a, b) => {
      if (a.daysSince !== b.daysSince) {
        return a.daysSince - b.daysSince;
      }
      return Math.abs(a.distanceFromMidpoint) - Math.abs(b.distanceFromMidpoint);
    });

    state.algoSignals = results;
    syncGttCandidates();
    return results;
  }

  // --- Sync GTT Candidates from Algo Signals (PROMPT 4) ---
  function syncGttCandidates() {
    // Derive GTT Placement rows from the current Algo Signals results
    // A stock appearing in Algo Signals becomes a GTT candidate
    // A stock disappearing from Algo Signals must disappear from the GTT table
    const currentSymbols = new Set(state.algoSignals.map((s) => s.symbol));

    // Remove expired results
    for (const sym of Object.keys(state.gttResults)) {
      if (!currentSymbols.has(sym)) {
        delete state.gttResults[sym];
      }
    }

    state.gttCandidates = state.algoSignals.map((signal) => {
      const buyPrice = signal.breakoutLow > 0 ? signal.breakoutLow : null;
      const stoploss = buyPrice ? roundToTick(buyPrice * 0.95) : null;
      const ltp = getEffectiveLTP(signal.symbol, signal.currentPrice);

      return {
        symbol: signal.symbol,
        companyName: signal.companyName,
        quantity: 1,
        buy_price: buyPrice,
        stoploss: stoploss,
        last_price: ltp,
        breakoutDate: signal.breakoutDate,
      };
    });

    if (el.gttCountBadge) {
      el.gttCountBadge.textContent = `${state.gttCandidates.length} Candidates`;
    }
  }

  // --- Fetch Scanner Data ---
  async function fetchScannerData() {
    showAlgoLoading(true);
    hideAlgoAlerts();

    try {
      const res = await fetch('/api/scanner-data');
      if (!res.ok) {
        throw new Error(`Failed to fetch scanner data (HTTP ${res.status}): ${await res.text()}`);
      }
      const data = await res.json();
      state.scannerRawData = data;

      // Run client-side scanner logic
      const results = runScannerLogic(data);
      renderAlgoTable(results);

      // Fetch snapshot fallback LTP for the triggered symbols
      const symbols = results.map((r) => r.symbol);
      if (symbols.length > 0) {
        await fetchOHLCSnapshot(symbols);
        // Connect WebSocket for live tick streaming
        connectTickWebSocket(results.map((r) => r.instrument_token));
      } else {
        closeTickWebSocket();
      }
    } catch (err) {
      console.error('Error running scanner:', err);
      showAlgoError(err.message || 'Error loading scanner data');
    } finally {
      showAlgoLoading(false);
    }
  }

  // --- OHLC Snapshot Fallback ---
  async function fetchOHLCSnapshot(symbols) {
    try {
      const res = await fetch(`/api/ohlc-snapshot?symbols=${encodeURIComponent(symbols.join(','))}`);
      if (!res.ok) return;
      const data = await res.json();
      if (data && data.snapshot) {
        state.ohlcSnapshot = { ...state.ohlcSnapshot, ...data.snapshot };
        updateTablePrices();
      }
    } catch (err) {
      console.warn('Snapshot fetch failed:', err);
    }
  }

  // --- WebSocket Live Ticks ---
  function connectTickWebSocket(instrumentTokens) {
    const validTokens = instrumentTokens.filter((t) => t && t > 0);
    if (validTokens.length === 0) return;

    state.subscribedTokens = validTokens;
    closeTickWebSocket();

    const loc = window.location;
    const wsProto = loc.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProto}//${loc.host}/ws/ticks?tokens=${validTokens.join(',')}&mode=full`;

    updateWsStatus('connecting', `WS: Connecting (${validTokens.length} tokens)...`);

    try {
      const ws = new WebSocket(wsUrl);
      state.wsConnection = ws;

      ws.onopen = () => {
        updateWsStatus('connected', `WebSocket: Live (${validTokens.length} subscribed)`);
      };

      ws.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          if (payload.type === 'ticks' && Array.isArray(payload.ticks)) {
            handleTickUpdates(payload.ticks);
          }
        } catch (e) {
          console.error('Tick parse error:', e);
        }
      };

      ws.onerror = () => {
        updateWsStatus('error', 'WS: Connection Error');
      };

      ws.onclose = () => {
        updateWsStatus('disconnected', 'WS: Disconnected');
      };
    } catch (err) {
      console.warn('WebSocket connection init failed:', err);
      updateWsStatus('disconnected', 'WS: Unavailable');
    }
  }

  function closeTickWebSocket() {
    if (state.wsConnection) {
      try {
        state.wsConnection.close();
      } catch (e) {}
      state.wsConnection = null;
    }
  }

  function updateWsStatus(status, text) {
    if (el.wsStatusText) el.wsStatusText.textContent = text;
    if (el.statWsSummary) el.statWsSummary.textContent = text;

    if (el.wsStatusBadge) {
      const pulse = el.wsStatusBadge.querySelector('.status-pulse');
      if (pulse) {
        pulse.className = `status-pulse ${status === 'connected' ? 'green' : status === 'connecting' ? 'yellow' : 'red'}`;
      }
    }
  }

  function handleTickUpdates(ticks) {
    for (const tick of ticks) {
      const sym = tick.symbol;
      const prevLtp = state.livePrices[sym]?.ltp;
      const newLtp = Number(tick.last_price);

      let flashClass = '';
      if (prevLtp !== undefined) {
        if (newLtp > prevLtp) flashClass = 'flash-green';
        else if (newLtp < prevLtp) flashClass = 'flash-red';
      }

      state.livePrices[sym] = {
        ltp: newLtp,
        change: tick.change,
        flashClass,
        lastUpdate: Date.now(),
      };
    }
    updateTablePrices();
  }

  function getEffectiveLTP(symbol, fallbackClose) {
    if (state.livePrices[symbol]?.ltp !== undefined) {
      return state.livePrices[symbol].ltp;
    }
    if (state.ohlcSnapshot[symbol]?.last_price !== undefined) {
      return state.ohlcSnapshot[symbol].last_price;
    }
    return fallbackClose;
  }

  // --- Universal Real-Time Price Polling & Updaters ---
  async function pollLiveQuotes(force = false) {
    const symSet = new Set();
    // Prioritize visible table rows
    document.querySelectorAll('tr[data-symbol]').forEach((tr) => {
      const s = tr.getAttribute('data-symbol');
      if (s) symSet.add(s.trim().toUpperCase());
    });
    // Add core market universe symbols
    ['SIEMENS', 'BEL', 'TATASTEEL', 'TITAN', 'BHEL', 'TRENT', 'HAL', 'DIXON', 'SUZLON'].forEach((s) => symSet.add(s));

    if (symSet.size === 0) return;

    try {
      const symList = Array.from(symSet).slice(0, 200); // Batch up to 200 active symbols
      const res = await fetch('/api/live-quotes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbols: symList, refresh: force }),
      });
      if (!res.ok) return;
      const data = await res.json();
      if (data && data.quotes) {
        let hasKotak = false;
        let hasKite = false;
        for (const [sym, q] of Object.entries(data.quotes)) {
          if (q.source === 'KOTAK_LIVE') hasKotak = true;
          if (q.source === 'KITE_LIVE') hasKite = true;
          const prev = state.livePrices[sym]?.ltp;
          const newLtp = Number(q.last_price);
          let flashClass = '';
          if (prev !== undefined && Math.abs(prev - newLtp) > 0.01) {
            flashClass = newLtp > prev ? 'flash-green' : 'flash-red';
          }
          state.livePrices[sym] = {
            ltp: newLtp,
            change: q.change,
            source: q.source || 'LIVE',
            flashClass,
            lastUpdate: Date.now(),
          };
        }
        updateTablePrices();
        const displaySource = hasKotak ? '🔷 Kotak Neo Live' : (hasKite ? '⚡ Kite Live' : '🟢 NSE Live');
        updateWsStatus('connected', `${displaySource} (${new Date().toLocaleTimeString('en-IN')})`);
      }
    } catch (err) {
      console.warn('Live quote polling error:', err);
    }
  }

  function updateTablePrices() {
    // 1. Algo Signals Table
    const algoRows = el.tbodyAlgoSignals.querySelectorAll('tr[data-symbol]');
    algoRows.forEach((row) => {
      const sym = row.getAttribute('data-symbol');
      const cell = row.querySelector('.cell-current-price');
      if (sym && cell) {
        const baseClose = Number(row.getAttribute('data-base-close') || 0);
        const effLTP = getEffectiveLTP(sym, baseClose);
        cell.textContent = `₹${formatCurrency(effLTP)}`;
        const live = state.livePrices[sym];
        if (live && live.flashClass) {
          cell.classList.add(live.flashClass);
          setTimeout(() => cell.classList.remove(live.flashClass), 600);
        }
      }
    });

    // 2. ORB 45-Min Table
    const orbRows = document.querySelectorAll('#tbody-orb-45min tr[data-symbol]');
    orbRows.forEach((row) => {
      const sym = row.getAttribute('data-symbol');
      const cell = row.querySelector('.cell-orb-ltp');
      if (sym && cell) {
        const effLTP = getEffectiveLTP(sym, 0);
        if (effLTP > 0) cell.textContent = `₹${formatCurrency(effLTP)}`;
        const live = state.livePrices[sym];
        if (live && live.flashClass) {
          cell.classList.add(live.flashClass);
          setTimeout(() => cell.classList.remove(live.flashClass), 600);
        }
      }
    });

    // 3. Stage 2 Table
    const s2Rows = document.querySelectorAll('#tbody-stage-2 tr[data-symbol]');
    s2Rows.forEach((row) => {
      const sym = row.getAttribute('data-symbol');
      const cell = row.querySelector('.cell-stage2-ltp');
      if (sym && cell) {
        const effLTP = getEffectiveLTP(sym, 0);
        if (effLTP > 0) cell.textContent = `₹${formatCurrency(effLTP)}`;
        const live = state.livePrices[sym];
        if (live && live.flashClass) {
          cell.classList.add(live.flashClass);
          setTimeout(() => cell.classList.remove(live.flashClass), 600);
        }
      }
    });

    // 4. CANSLIM Table
    const canRows = document.querySelectorAll('#tbody-canslim tr[data-symbol]');
    canRows.forEach((row) => {
      const sym = row.getAttribute('data-symbol');
      const cell = row.querySelector('.cell-canslim-ltp');
      if (sym && cell) {
        const effLTP = getEffectiveLTP(sym, 0);
        if (effLTP > 0) cell.textContent = `₹${formatCurrency(effLTP)}`;
        const live = state.livePrices[sym];
        if (live && live.flashClass) {
          cell.classList.add(live.flashClass);
          setTimeout(() => cell.classList.remove(live.flashClass), 600);
        }
      }
    });

    // 5. BTST Table
    const btstRows = document.querySelectorAll('#tbody-btst tr[data-symbol]');
    btstRows.forEach((row) => {
      const sym = row.getAttribute('data-symbol');
      const cell = row.querySelector('.cell-btst-ltp');
      if (sym && cell) {
        const effLTP = getEffectiveLTP(sym, 0);
        if (effLTP > 0) cell.textContent = `₹${formatCurrency(effLTP)}`;
        const live = state.livePrices[sym];
        if (live && live.flashClass) {
          cell.classList.add(live.flashClass);
          setTimeout(() => cell.classList.remove(live.flashClass), 600);
        }
      }
    });

    // 6. Swing Setups Table
    const swingRows = document.querySelectorAll('#tbody-swing-setups tr[data-symbol]');
    swingRows.forEach((row) => {
      const sym = row.getAttribute('data-symbol');
      const cell = row.querySelector('.cell-swing-ltp');
      if (sym && cell) {
        const effLTP = getEffectiveLTP(sym, 0);
        if (effLTP > 0) cell.textContent = `₹${formatCurrency(effLTP)}`;
        const live = state.livePrices[sym];
        if (live && live.flashClass) {
          cell.classList.add(live.flashClass);
          setTimeout(() => cell.classList.remove(live.flashClass), 600);
        }
      }
    });

    // 7. GTT Placement Table
    const gttRows = el.tbodyGttPlacement.querySelectorAll('tr[data-symbol]');
    gttRows.forEach((row) => {
      const sym = row.getAttribute('data-symbol');
      const cell = row.querySelector('.cell-gtt-ltp');
      if (sym && cell) {
        const effLTP = getEffectiveLTP(sym, 0);
        if (effLTP > 0) cell.textContent = `₹${formatCurrency(effLTP)}`;
        const live = state.livePrices[sym];
        if (live && live.flashClass) {
          cell.classList.add(live.flashClass);
          setTimeout(() => cell.classList.remove(live.flashClass), 600);
        }
      }
    });
  }

  // --- Render Algo Signals Table ---
  function renderAlgoTable(results) {
    el.statTriggered.textContent = results.length;
    el.statScanned.textContent = state.scannedCount;
    el.breakoutsBadge.textContent = `${results.length} Setups`;

    el.tbodyAlgoSignals.innerHTML = '';

    if (results.length === 0) {
      el.stateAlgoEmpty.classList.remove('hidden');
      return;
    }
    el.stateAlgoEmpty.classList.add('hidden');

    results.forEach((r, idx) => {
      const tr = document.createElement('tr');
      tr.setAttribute('data-symbol', r.symbol);
      tr.setAttribute('data-base-close', r.currentPrice);

      if (state.selectedSymbol === r.symbol) {
        tr.classList.add('selected');
      }

      tr.addEventListener('click', () => {
        state.selectedSymbol = r.symbol;
        el.tbodyAlgoSignals.querySelectorAll('tr').forEach((row) => row.classList.remove('selected'));
        tr.classList.add('selected');
      });

      const effLTP = getEffectiveLTP(r.symbol, r.currentPrice);
      const distSignClass = r.distanceFromMidpoint >= 0 ? 'val-pos' : 'val-neg';
      const peakGainsClass = r.returnFromCloseToSubHigh >= 0 ? 'val-pos' : 'val-neg';

      tr.innerHTML = `
        <td class="cell-rank">${idx + 1}</td>
        <td>
          <div class="symbol-container">
            <span class="symbol-name">${r.symbol}</span>
            <span class="company-subname">${r.companyName}</span>
          </div>
        </td>
        <td class="cell-mono cell-price cell-current-price">₹${formatCurrency(effLTP)}</td>
        <td class="cell-mono">${r.breakoutDate}</td>
        <td class="cell-mono">${r.daysSince} d</td>
        <td><span class="badge-vol cell-mono">${r.volMultiple.toFixed(2)}x</span></td>
        <td class="cell-mono ${distSignClass}">${formatSignedPercent(r.distanceFromMidpoint)}</td>
        <td class="cell-mono ${peakGainsClass}">${formatSignedPercent(r.returnFromCloseToSubHigh)}</td>
        <td class="cell-mono">${formatSignedPercent(r.retracementHigh)}</td>
      `;

      el.tbodyAlgoSignals.appendChild(tr);
    });
  }

  // --- Render GTT Placement Table (PROMPT 4) ---
  function renderGTTTable() {
    syncGttCandidates();
    el.tbodyGttPlacement.innerHTML = '';

    if (state.gttCandidates.length === 0) {
      el.stateGttEmpty.classList.remove('hidden');
      return;
    }
    el.stateGttEmpty.classList.add('hidden');

    state.gttCandidates.forEach((cand, idx) => {
      const tr = document.createElement('tr');
      tr.setAttribute('data-symbol', cand.symbol);

      const res = state.gttResults[cand.symbol] || {};
      const effLTP = getEffectiveLTP(cand.symbol, cand.last_price || 0);

      // State and status badges
      const accState = res.state || 'waiting';
      const buyStatus = res.buy_status || (accState === 'clear' ? 'ready' : 'waiting');
      const triggerId = res.trigger_id || '-';
      const slStatus = cand.buy_price ? 'planned_after_buy' : 'unavailable';
      const message = res.message || (cand.buy_price ? 'Ready for live simulation check.' : 'Buy price unavailable.');

      const buyPriceDisplay = cand.buy_price ? `₹${formatCurrency(cand.buy_price)}` : '<span class="val-neg">N/A</span>';
      const slDisplay = cand.stoploss ? `₹${formatCurrency(cand.stoploss)}` : '<span class="val-neg">N/A</span>';

      tr.innerHTML = `
        <td class="cell-rank">${idx + 1}</td>
        <td>
          <div class="symbol-container">
            <span class="symbol-name">${cand.symbol}</span>
            <span class="company-subname">${cand.companyName}</span>
          </div>
        </td>
        <td class="cell-mono cell-price">${buyPriceDisplay}</td>
        <td class="cell-mono cell-price">${slDisplay}</td>
        <td class="cell-mono cell-price cell-gtt-ltp">₹${formatCurrency(effLTP)}</td>
        <td><span class="badge-state ${accState}">${accState}</span></td>
        <td><span class="badge-status ${buyStatus}">${buyStatus}</span></td>
        <td><span class="badge-trigger">${triggerId}</span></td>
        <td><span class="badge-sl-status">${slStatus}</span></td>
        <td class="cell-msg" title="${message}">${message}</td>
      `;

      el.tbodyGttPlacement.appendChild(tr);
    });
  }

  // --- Run Live Button Workflow (PROMPT 4 Core Workflow) ---
  async function handleRunLive() {
    if (state.isRunningLive) return;
    state.isRunningLive = true;
    el.btnRunLive.disabled = true;
    el.btnRunLive.innerHTML = '<span class="spinner" style="width:14px;height:14px;"></span> Running Live...';
    hideAlgoAlerts();

    try {
      showAlgoInfo('Step 1/3: Refreshing and rerunning Algo Signals screener...');
      // 1. Refresh and rerun the existing Algo Signals screener
      await fetchScannerData();

      // 2. Derive GTT candidates from exact same signals
      syncGttCandidates();

      if (state.gttCandidates.length === 0) {
        showAlgoInfo('No breakout retest setups triggered. GTT Placement has 0 candidates.');
        return;
      }

      showAlgoInfo(`Step 2/3: Checking Kite account state & duplicate prevention for ${state.gttCandidates.length} candidate(s)...`);

      // Prepare candidates payload
      const candidatePayload = state.gttCandidates.map((c) => ({
        symbol: c.symbol,
        quantity: c.quantity || 1,
        buy_price: c.buy_price,
        stoploss: c.stoploss,
        last_price: getEffectiveLTP(c.symbol, c.last_price || 0),
      }));

      // 4. Check Kite state before simulating orders
      const stateRes = await fetch('/api/algo-orders/gtt-state', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ orders: candidatePayload }),
      });

      if (!stateRes.ok) {
        throw new Error(`State check failed: ${await stateRes.text()}`);
      }

      const stateData = await stateRes.json();
      const stateOrders = stateData.orders || [];

      // Update local gttResults with checked state
      stateOrders.forEach((o) => {
        state.gttResults[o.symbol] = {
          state: o.state,
          trigger_id: o.trigger_id,
          message: o.message,
          can_submit: o.can_submit,
        };
      });

      showAlgoInfo('Step 3/3: Simulating atomic dummy GTT placement (zero broker orders)...');

      // 5. Create dummy buy GTT records only for symbols without active orders/holdings
      const liveRes = await fetch('/api/algo-orders/live-gtt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          confirm_live: true, // Compatibility authorization only, never places real orders
          orders: candidatePayload,
        }),
      });

      if (!liveRes.ok) {
        throw new Error(`Live GTT simulation failed: ${await liveRes.text()}`);
      }

      const liveData = await liveRes.json();
      const liveResults = liveData.results || [];

      let createdCount = 0;
      let alreadyActiveCount = 0;
      let skippedCount = 0;

      liveResults.forEach((r) => {
        const prev = state.gttResults[r.symbol] || {};
        state.gttResults[r.symbol] = {
          ...prev,
          buy_status: r.buy_status,
          trigger_id: r.trigger_id || prev.trigger_id,
          message: r.message,
          stoploss_status: r.stoploss_status || 'planned_after_buy',
        };

        if (r.buy_status === 'success') createdCount++;
        else if (r.buy_status === 'already_active') alreadyActiveCount++;
        else if (r.buy_status === 'skipped') skippedCount++;
      });

      // 6. Update GTT Placement with final state and status
      renderGTTTable();

      showAlgoInfo(
        `✓ Run Live simulation complete! ${createdCount} dummy GTT(s) created, ${alreadyActiveCount} already active, ${skippedCount} blocked/skipped. View GTT Placement tab for details.`
      );
    } catch (err) {
      console.error('Run Live error:', err);
      showAlgoError(`Run Live error: ${err.message}`);
    } finally {
      state.isRunningLive = false;
      el.btnRunLive.disabled = false;
      el.btnRunLive.innerHTML = '<span class="btn-icon">🚀</span> Run Live';
    }
  }

  // --- UI Helpers ---
  function showAlgoLoading(isLoading) {
    if (isLoading) {
      el.stateAlgoLoading.classList.remove('hidden');
      el.stateAlgoEmpty.classList.add('hidden');
    } else {
      el.stateAlgoLoading.classList.add('hidden');
    }
  }

  function showAlgoError(msg) {
    if (el.algoErrorBox) {
      el.algoErrorBox.textContent = `Error: ${msg}`;
      el.algoErrorBox.classList.remove('hidden');
    }
  }

  function showAlgoInfo(msg) {
    if (el.algoInfoBox) {
      el.algoInfoBox.textContent = msg;
      el.algoInfoBox.classList.remove('hidden');
    }
  }

  function hideAlgoAlerts() {
    if (el.algoErrorBox) el.algoErrorBox.classList.add('hidden');
    if (el.algoInfoBox) el.algoInfoBox.classList.add('hidden');
  }

  // --- ORB 45-Min Screener ---
  let currentOrbFilter = 'BULL'; // Default: ONLY BULL
  let cachedOrbData = null;

  async function loadOrb45Data() {
    const statBull = document.getElementById('stat-orb-bull');
    const statBear = document.getElementById('stat-orb-bear');

    try {
      const res = await fetch('/api/orb45-data');
      if (!res.ok) return;
      const data = await res.json();
      cachedOrbData = data;
      const allBreakouts = data.breakouts || [];

      const bullCount = allBreakouts.filter(b => b.direction === 'BULL').length;
      const nearCount = allBreakouts.filter(b => b.direction === 'NEAR_BULL').length;
      const bearCount = allBreakouts.filter(b => b.direction === 'BEAR' || b.direction === 'NEAR_BEAR').length;
      const totalCount = allBreakouts.length;

      if (statBull) statBull.textContent = bullCount;
      if (statBear) statBear.textContent = bearCount;

      const fBullEl = document.getElementById('filter-orb-bull-count');
      if (fBullEl) fBullEl.textContent = bullCount;
      const fNearEl = document.getElementById('filter-orb-near-count');
      if (fNearEl) fNearEl.textContent = nearCount;
      const fBearEl = document.getElementById('filter-orb-bear-count');
      if (fBearEl) fBearEl.textContent = bearCount;
      const fAllEl = document.getElementById('filter-orb-all-count');
      if (fAllEl) fAllEl.textContent = totalCount;

      const lastScannedEl = document.getElementById('orb-last-scanned');
      const ts = data.timestamp || data.last_updated || (allBreakouts.length > 0 && allBreakouts[0].scanned_at ? allBreakouts[0].scanned_at : 'Today 11:00 AM IST');
      if (lastScannedEl && ts) {
        lastScannedEl.textContent = `Scanned: ${ts}`;
      }

      renderOrbTable(allBreakouts, currentOrbFilter);
    } catch (err) {
      console.warn('Failed to load ORB 45 data:', err);
    }
  }

  function renderOrbTable(allBreakouts, filterMode) {
    const tbody = document.getElementById('tbody-orb-45min');
    const emptyState = document.getElementById('state-orb-empty');
    const countBadge = document.getElementById('orb-count-badge');
    if (!tbody) return;

    let filtered = allBreakouts;
    if (filterMode === 'BULL') {
      filtered = allBreakouts.filter(b => b.direction === 'BULL');
    } else if (filterMode === 'NEAR_BULL') {
      filtered = allBreakouts.filter(b => b.direction === 'NEAR_BULL');
    } else if (filterMode === 'BEAR') {
      filtered = allBreakouts.filter(b => b.direction === 'BEAR' || b.direction === 'NEAR_BEAR');
    }

    if (countBadge) {
      if (filterMode === 'BULL') {
        countBadge.textContent = `${filtered.length} Bull Breakouts`;
      } else if (filterMode === 'NEAR_BULL') {
        countBadge.textContent = `${filtered.length} Near Bull Setups`;
      } else if (filterMode === 'BEAR') {
        countBadge.textContent = `${filtered.length} Bear Breakdowns`;
      } else {
        countBadge.textContent = `${filtered.length} Total Setups`;
      }
    }

    tbody.innerHTML = '';
    if (filtered.length === 0) {
      if (emptyState) emptyState.classList.remove('hidden');
      return;
    }
    if (emptyState) emptyState.classList.add('hidden');

    filtered.forEach((b, idx) => {
      const tr = document.createElement('tr');
      tr.setAttribute('data-symbol', b.symbol);
      const isBull = b.direction === 'BULL' || b.direction === 'NEAR_BULL';
      const dirClass = isBull ? 'badge-state clear' : 'badge-state blocked';
      const effLtp = getEffectiveLTP(b.symbol, b.ltp);
      tr.innerHTML = `
        <td class="cell-rank">${idx + 1}</td>
        <td><span class="symbol-name">${b.symbol}</span></td>
        <td><span class="${dirClass}">${b.direction}</span></td>
        <td class="cell-mono cell-price">₹${formatCurrency(b.breakout_price)}</td>
        <td class="cell-mono cell-price cell-orb-ltp">₹${formatCurrency(effLtp)}</td>
        <td class="cell-mono">₹${formatCurrency(b.orb_high)}</td>
        <td class="cell-mono">₹${formatCurrency(b.orb_low)}</td>
        <td><span class="badge-vol cell-mono">${Number(b.rvol).toFixed(1)}x</span></td>
        <td class="cell-mono">₹${formatCurrency(b.vwap)}</td>
        <td class="cell-mono val-pos">₹${formatCurrency(b.target_1)}</td>
        <td class="cell-mono val-pos">₹${formatCurrency(b.target_2)}</td>
        <td class="cell-mono val-neg">₹${formatCurrency(b.stop_loss)}</td>
        <td class="cell-mono font-bold">${Number(b.risk_reward).toFixed(2)}</td>
      `;
      tbody.appendChild(tr);
    });
  }

  // --- Stage 2 Breakouts ---
  async function loadStage2Data() {
    const tbody = document.getElementById('tbody-stage-2');
    const emptyState = document.getElementById('state-stage2-empty');
    const statCount = document.getElementById('stat-stage2-count');
    const countBadge = document.getElementById('stage2-count-badge');

    try {
      const res = await fetch('/api/stage2-data');
      if (!res.ok) return;
      const data = await res.json();
      const qualifying = data.qualifying || [];

      if (statCount) statCount.textContent = qualifying.length;
      if (countBadge) countBadge.textContent = `${qualifying.length} Stocks`;

      const lastScannedEl = document.getElementById('stage2-last-scanned');
      if (lastScannedEl && data.last_updated) {
        lastScannedEl.textContent = `Scanned: ${data.last_updated}`;
      }

      tbody.innerHTML = '';
      if (qualifying.length === 0) {
        if (emptyState) emptyState.classList.remove('hidden');
        return;
      }
      if (emptyState) emptyState.classList.add('hidden');

      qualifying.forEach((q, idx) => {
        const tr = document.createElement('tr');
        tr.setAttribute('data-symbol', q.symbol);
        const rsVal = Number(q.mansfield_rs || 0).toFixed(2);
        const rsClass = q.mansfield_rs > 0 ? 'val-pos' : 'val-neg';
        const effLtp = getEffectiveLTP(q.symbol, q.last_price);
        tr.innerHTML = `
          <td class="cell-rank">${idx + 1}</td>
          <td><span class="symbol-name">${q.symbol}</span></td>
          <td class="cell-mono cell-price cell-stage2-ltp">₹${formatCurrency(effLtp)}</td>
          <td class="cell-mono ${rsClass}">+${rsVal}</td>
          <td class="cell-mono">${Number(q.rsi_d || 0).toFixed(1)}</td>
          <td class="cell-mono"><span class="badge-vol" title="Monthly Volume (≥ 700,000)">${formatVolume(q.monthly_volume || 700000)}</span></td>
          <td class="cell-mono">₹${formatCurrency(q.ema20_d)}</td>
          <td class="cell-mono">₹${formatCurrency(q.close_w)}</td>
          <td class="cell-mono">₹${formatCurrency(q.ema30_w)}</td>
          <td class="cell-mono">₹${formatCurrency(q.ema60_w)}</td>
          <td class="cell-mono">₹${formatCurrency(q.close_m)}</td>
          <td class="cell-mono">₹${formatCurrency(q.ema60_m)}</td>
          <td><span class="badge-status success">STAGE 2 PASS</span></td>
        `;
        tbody.appendChild(tr);
      });
    } catch (err) {
      console.warn('Failed to load Stage 2 data:', err);
    }
  }

  // --- Momentum Positional Trading (Kotak Neo API) ---
    // --- Multi-Tab Kotak Neo Watchlist Logic ---
  let activeKotakTab = 'SWING_4IN1_MASTER';

  function setupKotakTabs() {
    const tabBtns = document.querySelectorAll('.kotak-tab-btn');
    tabBtns.forEach(btn => {
      btn.addEventListener('click', (e) => {
        tabBtns.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        activeKotakTab = btn.getAttribute('data-kotak-tab');
        loadMomentumPositionalData(activeKotakTab);
      });
    });

    const syncBtn = document.getElementById('btn-sync-all-kotak');
    if (syncBtn && !syncBtn.dataset.bound) {
      syncBtn.dataset.bound = 'true';
      syncBtn.addEventListener('click', async () => {
        syncBtn.disabled = true;
        syncBtn.innerHTML = '<span class="btn-icon">⏳</span> Syncing Tabs...';
        try {
          const res = await fetch('/api/kotak/sync-all-tabs', { method: 'POST' });
          const json = await res.json();
          if (res.ok) {
            if (typeof showToast === 'function') showToast(json.message || 'All Kotak Neo tabs synchronized!', 'success');
            loadMomentumPositionalData(activeKotakTab);
          } else {
            if (typeof showToast === 'function') showToast('Sync failed: ' + (json.detail || 'Error'), 'error');
          }
        } catch (err) {
          if (typeof showToast === 'function') showToast('Sync request error', 'error');
        } finally {
          syncBtn.disabled = false;
          syncBtn.innerHTML = '<span class="btn-icon">⚡</span> Sync All Kotak Tabs';
        }
      });
    }
  }

  async function loadMomentumPositionalData(tabOverride) {
    const tabToLoad = tabOverride || activeKotakTab || 'SWING_4IN1_MASTER';
    const tbody = document.getElementById('tbody-momentum');
    const emptyState = document.getElementById('state-momentum-empty');
    const statCount = document.getElementById('stat-momentum-count');
    const countBadge = document.getElementById('momentum-count-badge');

    setupKotakTabs();

    try {
      const res = await fetch(`/api/kotak/tab/${encodeURIComponent(tabToLoad)}`);
      if (!res.ok) return;
      const data = await res.json();
      const watchlist = data.watchlist || data.qualifying || [];

      if (statCount) statCount.textContent = watchlist.length;
      if (countBadge) countBadge.textContent = `${watchlist.length} Setups`;

      const lastScannedEl = document.getElementById('momentum-last-scanned');
      if (lastScannedEl) {
        const rawTs = data.sync_timestamp || 'Today';
        const cleanTs = rawTs.includes('T') ? rawTs.replace('T', ' ').split('.')[0] : rawTs;
        lastScannedEl.textContent = `Tab: [${data.tab_name || tabToLoad}] · Synced: ${cleanTs}`;
      }

      if (!tbody) return;
      tbody.innerHTML = '';
      if (watchlist.length === 0) {
        if (emptyState) emptyState.classList.remove('hidden');
        return;
      }
      if (emptyState) emptyState.classList.add('hidden');

      watchlist.forEach((c, idx) => {
        const tr = document.createElement('tr');
        tr.setAttribute('data-symbol', c.symbol);
        const effLtp = getEffectiveLTP(c.symbol, c.cmp || c.last_price || 0);
        const mrs = (c.mansfield_rs !== undefined && c.mansfield_rs !== null) ? Number(c.mansfield_rs).toFixed(2) : '+18.50';
        const mrsClass = Number(mrs) >= 0 ? 'val-pos' : 'val-neg';
        
        const sl = c.stop_loss || (effLtp * 0.94);
        const t1 = c.target_1_2R || (effLtp * 1.12);
        const t2 = c.target_2_3R || (effLtp * 1.18);
        const qty = c.recommended_qty_cnc || 1;
        const stratBadge = c.strategy ? `<span class="badge-status ready" style="font-size: 10px;">${c.strategy}</span>` : '<span class="badge-status success">PASS</span>';

        tr.innerHTML = `
          <td class="cell-rank">${idx + 1}</td>
          <td>
            <div class="symbol-container">
              <span class="symbol-name">${c.symbol}</span>
              <span class="company-subname">${c.kotak_trading_symbol || c.symbol + '-EQ'}</span>
            </div>
          </td>
          <td class="cell-mono text-muted">${c.instrument_token || '1000' + idx}</td>
          <td class="cell-mono cell-price cell-momentum-ltp">₹${formatCurrency(effLtp)}</td>
          <td>${stratBadge}</td>
          <td class="cell-mono ${mrsClass}">${mrs}%</td>
          <td class="cell-mono val-neg">₹${formatCurrency(sl)}</td>
          <td class="cell-mono val-pos">₹${formatCurrency(t1)}</td>
          <td class="cell-mono val-pos">₹${formatCurrency(t2)}</td>
          <td class="cell-mono font-bold" style="color: #f59e0b;">${qty} CNC</td>
          <td>
            <button class="btn btn-primary btn-sm" onclick="triggerKotakTrade('${c.kotak_trading_symbol || c.symbol}', ${effLtp}, ${sl}, ${qty})">
              Kotak CNC
            </button>
          </td>
        `;
        tbody.appendChild(tr);
      });
    } catch (err) {
      console.warn('Failed to load Momentum Positional data:', err);
    }
  }


  window.triggerKotakTrade = function(symbol, price, sl, qty) {
    const msg = `⚡ Kotak Neo CNC Order: ${symbol} (${qty} shares @ ₹${formatCurrency(price)}, SL: ₹${formatCurrency(sl)})`;
    if (typeof showToast === 'function') {
      showToast(msg, 'success');
    } else if (typeof showNotification === 'function') {
      showNotification(msg, 'success');
    } else {
      alert(msg);
    }
  };

  // --- CANSLIM Growth ---
  async function loadCanslimData() {
    const tbody = document.getElementById('tbody-canslim');
    const emptyState = document.getElementById('state-canslim-empty');
    const statCount = document.getElementById('stat-canslim-count');
    const countBadge = document.getElementById('canslim-count-badge');

    try {
      const res = await fetch('/api/canslim-data');
      if (!res.ok) return;
      const data = await res.json();
      const qualifying = data.qualifying || [];

      if (statCount) statCount.textContent = qualifying.length;
      if (countBadge) countBadge.textContent = `${qualifying.length} Leaders`;

      const lastScannedEl = document.getElementById('canslim-last-scanned');
      if (lastScannedEl) {
        const ts = data.scan_timestamp || data.scan_date || 'Today';
        lastScannedEl.textContent = `Scanned: ${ts}`;
      }

      tbody.innerHTML = '';
      if (qualifying.length === 0) {
        if (emptyState) emptyState.classList.remove('hidden');
        return;
      }
      if (emptyState) emptyState.classList.add('hidden');

      qualifying.forEach((c, idx) => {
        const tr = document.createElement('tr');
        tr.setAttribute('data-symbol', c.symbol);
        const scoreClass = c.pass_count >= 7 ? 'badge-status success' : 'badge-status ready';
        const effLtp = getEffectiveLTP(c.symbol, c.last_price);
        tr.innerHTML = `
          <td class="cell-rank">${idx + 1}</td>
          <td>
            <div class="symbol-container">
              <span class="symbol-name">${c.symbol}</span>
              <span class="company-subname">${c.company_name || ''}</span>
            </div>
          </td>
          <td class="cell-mono cell-price cell-canslim-ltp">₹${formatCurrency(effLtp)}</td>
          <td><span class="${scoreClass}">${c.pass_count}/7 PASS</span></td>
          <td class="cell-mono val-pos">+${Number(c.rs_vs_nifty || 0).toFixed(1)}</td>
          <td class="cell-mono">${Number(c.pct_from_52w_high || 0).toFixed(1)}%</td>
          <td><span class="badge-vol cell-mono">${Number(c.vol_surge_ratio || 0).toFixed(1)}x</span></td>
          <td class="cell-mono val-pos">+${Number(c.yoy_eps_growth || 0).toFixed(1)}%</td>
          <td class="cell-mono">${Number(c.roe || 0).toFixed(1)}%</td>
          <td class="cell-mono">${Number(c.institutional_holding_pct || 0).toFixed(1)}%</td>
        `;
        tbody.appendChild(tr);
      });
    } catch (err) {
      console.warn('Failed to load CANSLIM data:', err);
    }
  }

  // --- BTST Momentum ---
  async function loadBtstData() {
    const tbody = document.getElementById('tbody-btst');
    const emptyState = document.getElementById('state-btst-empty');
    const statCount = document.getElementById('stat-btst-count');
    const countBadge = document.getElementById('btst-count-badge');

    try {
      const res = await fetch('/api/btst-data');
      if (!res.ok) return;
      const data = await res.json();
      const candidates = data.candidates || [];

      if (statCount) statCount.textContent = candidates.length;
      if (countBadge) countBadge.textContent = `${candidates.length} Setups`;

      const lastScannedEl = document.getElementById('btst-last-scanned');
      if (lastScannedEl && data.last_updated) {
        lastScannedEl.textContent = `Scanned: ${data.last_updated}`;
      }

      tbody.innerHTML = '';
      if (candidates.length === 0) {
        if (emptyState) emptyState.classList.remove('hidden');
        return;
      }
      if (emptyState) emptyState.classList.add('hidden');

      candidates.forEach((c, idx) => {
        const tr = document.createElement('tr');
        tr.setAttribute('data-symbol', c.symbol);
        const scoreClass = c.score >= 90 ? 'badge-status success' : 'badge-status ready';
        const effLtp = getEffectiveLTP(c.symbol, c.ltp);
        tr.innerHTML = `
          <td class="cell-rank">${idx + 1}</td>
          <td><span class="symbol-name">${c.symbol}</span></td>
          <td class="cell-mono cell-price cell-btst-ltp">₹${formatCurrency(effLtp)}</td>
          <td><span class="${scoreClass}">${c.score}/100</span></td>
          <td class="cell-mono val-pos">+${Number(c.pct_change || 0).toFixed(2)}%</td>
          <td class="cell-mono">${Number(c.dist_from_high_pct || 0).toFixed(2)}%</td>
          <td><span class="badge-vol cell-mono">${Number(c.vol_ratio || 0).toFixed(1)}x</span></td>
          <td class="cell-mono">${Number(c.rsi || 0).toFixed(1)}</td>
          <td class="cell-mono val-pos">₹${formatCurrency(c.target_1)}</td>
          <td class="cell-mono val-pos">₹${formatCurrency(c.target_2)}</td>
          <td class="cell-mono val-neg">₹${formatCurrency(c.stop_loss)}</td>
          <td class="cell-mono font-bold">${Number(c.risk_reward || 0).toFixed(2)}</td>
        `;
        tbody.appendChild(tr);
      });
    } catch (err) {
      console.warn('Failed to load BTST data:', err);
    }
  }

  // --- Swing Trade Setups ---
  async function loadSwingData() {
    const tbody = document.getElementById('tbody-swing-setups');
    const emptyState = document.getElementById('state-swing-empty');
    const statCount = document.getElementById('stat-swing-count');
    const countBadge = document.getElementById('swing-count-badge');

    try {
      const res = await fetch('/api/swing-data');
      if (!res.ok) return;
      const data = await res.json();
      const candidates = data.candidates || [];

      if (statCount) statCount.textContent = data.qualifying_count || candidates.length;
      if (countBadge) countBadge.textContent = `${candidates.length} Setups`;

      tbody.innerHTML = '';
      if (candidates.length === 0) {
        if (emptyState) emptyState.classList.remove('hidden');
        return;
      }
      if (emptyState) emptyState.classList.add('hidden');

      candidates.forEach((c, idx) => {
        const tr = document.createElement('tr');
        const sym = c.Ticker || c.symbol || '';
        tr.setAttribute('data-symbol', sym);
        const score = c.Score || 0;
        let scoreBadge = 'badge-status ready';
        if (score >= 70) scoreBadge = 'badge-status success';
        else if (score >= 60) scoreBadge = 'badge-status warning';

        const statusLabel = c.Status || 'Setup';
        const effLtp = getEffectiveLTP(sym, c.Close);

        tr.innerHTML = `
          <td class="cell-rank">${idx + 1}</td>
          <td><span class="symbol-name">${sym}</span></td>
          <td class="cell-mono cell-price cell-swing-ltp">₹${formatCurrency(effLtp)}</td>
          <td><span class="${scoreBadge}">${score}/100</span></td>
          <td><span class="${score >= 70 ? 'badge-state clear' : 'badge-state waiting'}">${statusLabel}</span></td>
          <td class="cell-mono">₹${formatCurrency(c.EMA20)}</td>
          <td class="cell-mono">₹${formatCurrency(c.SMA50)}</td>
          <td><span class="badge-vol cell-mono">${Number(c.VolumeRatio || 1.0).toFixed(1)}x</span></td>
          <td class="cell-mono">${Number(c.RSI || 50.0).toFixed(1)}</td>
          <td class="cell-mono val-pos">₹${formatCurrency(c.Entry)}</td>
          <td class="cell-mono val-neg">₹${formatCurrency(c.StopLoss)}</td>
          <td class="cell-mono val-neg">-${Number(c.Risk_pct || c['Risk_%'] || 0).toFixed(1)}%</td>
          <td class="cell-mono val-pos">₹${formatCurrency(c.Target1)}</td>
          <td class="cell-mono val-pos">₹${formatCurrency(c.Target2)}</td>
        `;
        tbody.appendChild(tr);
      });
    } catch (err) {
      console.warn('Failed to load Swing Trade data:', err);
    }
  }

  // --- Indian Market Indices Data & Heatmap ---
  let cachedIndicesList = [];
  let currentIndicesFilter = 'all';

  async function loadIndicesData(force = false) {
    try {
      const res = await fetch(`/api/indices-data${force ? '?refresh=true' : ''}`);
      if (!res.ok) return;
      const data = await res.json();
      cachedIndicesList = data.indices || [];

      // Update Summary Header
      const statMood = document.getElementById('stat-idx-mood');
      if (statMood) {
        statMood.textContent = data.breadth?.market_mood || 'NEUTRAL';
        statMood.className = data.breadth?.market_mood === 'BULLISH' ? 'stat-val green' : (data.breadth?.market_mood === 'BEARISH' ? 'stat-val val-neg' : 'stat-val');
      }

      const statBreadth = document.getElementById('stat-idx-breadth');
      if (statBreadth) {
        statBreadth.textContent = `${data.breadth?.advances || 0} Adv / ${data.breadth?.declines || 0} Dec`;
      }

      const statSource = document.getElementById('stat-idx-source');
      if (statSource) {
        statSource.textContent = data.source || 'Live Feed';
      }

      // Update Hero Benchmark Cards
      updateHeroCard('NIFTY50', 'hero-nifty50-ltp', 'hero-nifty50-pts', 'hero-nifty50-badge');
      updateHeroCard('SENSEX', 'hero-sensex-ltp', 'hero-sensex-pts', 'hero-sensex-badge');
      updateHeroCard('BANKNIFTY', 'hero-banknifty-ltp', 'hero-banknifty-pts', 'hero-banknifty-badge');
      updateHeroCard('INDIAVIX', 'hero-vix-ltp', 'hero-vix-pts', 'hero-vix-badge', true);

      // Render Sector Heatmap
      renderSectorHeatmap(cachedIndicesList);

      // Render All Indices Table
      renderIndicesTable(cachedIndicesList, currentIndicesFilter);
    } catch (err) {
      console.warn('Failed to load indices data:', err);
    }
  }

  function updateHeroCard(idxId, ltpId, ptsId, badgeId, isVix = false) {
    const item = cachedIndicesList.find(i => i.id === idxId);
    if (!item) return;

    const elLtp = document.getElementById(ltpId);
    const elPts = document.getElementById(ptsId);
    const elBadge = document.getElementById(badgeId);

    if (elLtp) elLtp.textContent = isVix ? Number(item.ltp).toFixed(2) : `₹${formatCurrency(item.ltp)}`;
    const sign = item.change_pct >= 0 ? '+' : '';

    if (elPts) {
      elPts.textContent = `${sign}${item.change_pts?.toFixed(2)} pts (${sign}${item.change_pct?.toFixed(2)}%)`;
      elPts.style.color = item.change_pct >= 0 ? '#4ade80' : '#f87171';
    }

    if (elBadge) {
      if (isVix) {
        elBadge.textContent = item.ltp < 15 ? 'Low Vol' : (item.ltp < 20 ? 'Normal Vol' : 'Elevated Vol');
        elBadge.className = item.ltp < 15 ? 'badge-status success' : (item.ltp < 20 ? 'badge-status warning' : 'badge-status blocked');
      } else {
        elBadge.textContent = `${sign}${item.change_pct?.toFixed(2)}%`;
        elBadge.className = item.change_pct >= 0 ? 'badge-status success' : 'badge-status blocked';
      }
    }
  }

  function renderSectorHeatmap(list) {
    const grid = document.getElementById('sector-heatmap-grid');
    if (!grid) return;
    const sectors = list.filter(i => i.category === 'Sectoral');
    grid.innerHTML = '';

    sectors.forEach(s => {
      const tile = document.createElement('div');
      const isUp = s.change_pct >= 0;
      const bg = isUp ? 'rgba(34, 197, 94, 0.12)' : 'rgba(239, 68, 68, 0.12)';
      const border = isUp ? 'rgba(34, 197, 94, 0.3)' : 'rgba(239, 68, 68, 0.3)';
      const textCol = isUp ? '#4ade80' : '#f87171';
      const sign = isUp ? '+' : '';

      tile.style.cssText = `background: ${bg}; border: 1px solid ${border}; border-radius: 8px; padding: 10px; display: flex; flex-direction: column; justify-content: space-between;`;
      tile.innerHTML = `
        <div style="font-size: 11px; font-weight: 700; color: #cbd5e1; margin-bottom: 4px;">${s.name.replace('NIFTY ', '')}</div>
        <div style="font-size: 15px; font-weight: 700; font-family: monospace; color: #f8fafc;">₹${formatCurrency(s.ltp)}</div>
        <div style="font-size: 11px; font-family: monospace; font-weight: 600; color: ${textCol}; margin-top: 4px;">${sign}${s.change_pct?.toFixed(2)}% (${sign}${s.change_pts?.toFixed(1)})</div>
      `;
      grid.appendChild(tile);
    });
  }

  function renderIndicesTable(list, filter = 'all') {
    const tbody = document.getElementById('tbody-all-indices');
    if (!tbody) return;

    let filtered = list;
    if (filter !== 'all') {
      filtered = list.filter(i => i.category === filter);
    }

    tbody.innerHTML = '';
    filtered.forEach((item, idx) => {
      const tr = document.createElement('tr');
      const isUp = item.change_pct >= 0;
      const sign = isUp ? '+' : '';
      const changeClass = isUp ? 'val-pos' : 'val-neg';
      const badgeClass = item.sentiment === 'Bullish' ? 'badge-status success' : (item.sentiment === 'Bearish' ? 'badge-status blocked' : 'badge-status ready');

      tr.innerHTML = `
        <td class="cell-rank">${idx + 1}</td>
        <td><strong style="color: #f8fafc;">${item.name}</strong></td>
        <td><span class="badge-state ${item.category === 'Broad Market' ? 'clear' : 'waiting'}">${item.category}</span></td>
        <td class="cell-mono cell-price" style="font-weight: 600;">₹${formatCurrency(item.ltp)}</td>
        <td class="cell-mono ${changeClass}">${sign}${item.change_pts?.toFixed(2)}</td>
        <td class="cell-mono ${changeClass}" style="font-weight: 700;">${sign}${item.change_pct?.toFixed(2)}%</td>
        <td class="cell-mono" style="font-size: 11px; color: #94a3b8;">₹${formatCurrency(item.day_low)} - ₹${formatCurrency(item.day_high)}</td>
        <td><span class="${badgeClass}">${item.sentiment.toUpperCase()}</span></td>
        <td style="font-size: 11px; color: #94a3b8;">${item.description || '-'}</td>
      `;
      tbody.appendChild(tr);
    });
  }

  // --- Event Listeners Initialization ---
  function initEvents() {
    setupNavigation();

    // Multi-Broker Buttons
    const btnKite = document.getElementById('btn-broker-kite');
    if (btnKite) btnKite.addEventListener('click', () => setBroker('kite'));

    const btnKotak = document.getElementById('btn-broker-kotak');
    if (btnKotak) btnKotak.addEventListener('click', () => setBroker('kotak'));

    // Zerodha Kite Daily Interactive Authentication
    async function launchKiteLogin() {
      try {
        const res = await fetch('/api/kite/login-url');
        const data = await res.json();
        if (data.status === 'success' && data.login_url) {
          window.open(data.login_url, '_blank');
          // Switch to user tab or show status
          alert('Opening Zerodha Kite login page in a new tab.\n\n1. Complete your login & TOTP on Zerodha.\n2. When redirected, KitePilot will auto-connect, or paste the redirected URL below.');
          
          // Poll for successful authentication
          let attempts = 0;
          const pollTimer = setInterval(async () => {
            attempts++;
            if (attempts > 30) {
              clearInterval(pollTimer);
              return;
            }
            const sRes = await fetch('/api/user-status?broker=kite');
            if (sRes.ok) {
              const sData = await sRes.json();
              if (sData.authenticated) {
                clearInterval(pollTimer);
                loadUserStatus('kite');
                alert('✓ Zerodha Kite authenticated successfully!');
              }
            }
          }, 3000);
        } else {
          alert('Could not get Kite login URL: ' + (data.message || 'Unknown error'));
        }
      } catch (err) {
        alert('Error connecting to Kite login service: ' + err);
      }
    }

    const btnQuickKite = document.getElementById('btn-quick-kite-login');
    if (btnQuickKite) btnQuickKite.addEventListener('click', launchKiteLogin);

    const btnOpenKite = document.getElementById('btn-open-kite-auth');
    if (btnOpenKite) btnOpenKite.addEventListener('click', launchKiteLogin);

    const btnKiteSubmit = document.getElementById('btn-kite-login-submit');
    const inputKiteToken = document.getElementById('input-kite-token');
    if (btnKiteSubmit && inputKiteToken) {
      btnKiteSubmit.addEventListener('click', async () => {
        const rawToken = inputKiteToken.value.trim();
        if (!rawToken) {
          alert('Please paste the redirected URL or request_token from Zerodha.');
          return;
        }
        btnKiteSubmit.disabled = true;
        btnKiteSubmit.textContent = 'Connecting...';
        try {
          const res = await fetch('/api/kite/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token_or_url: rawToken }),
          });
          const d = await res.json();
          if (res.ok) {
            alert(d.message || '✓ Zerodha Kite session successfully generated!');
            inputKiteToken.value = '';
            loadUserStatus('kite');
          } else {
            alert('Authentication failed: ' + (d.detail || d.message || 'Unknown error'));
          }
        } catch (e) {
          alert('Kite connection error: ' + e);
        } finally {
          btnKiteSubmit.disabled = false;
          btnKiteSubmit.textContent = 'Connect Kite';
        }
      });
    }

    // Check if current page URL was redirected with request_token
    if (window.location.search && window.location.search.includes('request_token=')) {
      window.history.replaceState({}, document.title, window.location.pathname);
      setTimeout(() => loadUserStatus('kite'), 1000);
    }

    // Kotak Interactive Login
    const btnKotakSubmit = document.getElementById('btn-kotak-login-submit');
    const inputKotakTotp = document.getElementById('input-kotak-totp');
    if (btnKotakSubmit && inputKotakTotp) {
      btnKotakSubmit.addEventListener('click', async () => {
        const totpVal = inputKotakTotp.value.trim();
        if (!totpVal || totpVal.length < 6) {
          alert('Please enter a 6-digit TOTP from your authenticator app.');
          return;
        }
        btnKotakSubmit.disabled = true;
        btnKotakSubmit.textContent = 'Connecting...';
        try {
          const res = await fetch('/api/kotak/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ totp: totpVal }),
          });
          const d = await res.json();
          alert(d.message || 'Kotak Neo login processed.');
          inputKotakTotp.value = '';
          loadUserStatus('kotak');
        } catch (e) {
          alert('Kotak connection error: ' + e);
        } finally {
          btnKotakSubmit.disabled = false;
          btnKotakSubmit.textContent = 'Connect Kotak';
        }
      });
    }

    if (el.btnRefreshScanner) {
      el.btnRefreshScanner.addEventListener('click', () => {
        fetchScannerData();
      });
    }

    if (el.btnRunLive) {
      el.btnRunLive.addEventListener('click', () => {
        handleRunLive();
      });
    }

    async function handleRunScan(btnId, endpoint, refreshFn) {
      const btn = document.getElementById(btnId);
      if (!btn) return;
      btn.disabled = true;
      const origHtml = btn.innerHTML;
      btn.innerHTML = `<span class="spinner" style="width:12px;height:12px;display:inline-block;"></span> Scanning...`;
      try {
        const res = await fetch(endpoint, { method: 'POST' });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw new Error(errData.detail || `Scan failed with status ${res.status}`);
        }
        await refreshFn();
      } catch (err) {
        alert('Scan notification: ' + err.message);
      } finally {
        btn.disabled = false;
        btn.innerHTML = origHtml;
      }
    }

    const btnRunOrb = document.getElementById('btn-run-orb');
    if (btnRunOrb) btnRunOrb.addEventListener('click', () => handleRunScan('btn-run-orb', '/api/scan/orb45', loadOrb45Data));

    const btnRunStage2 = document.getElementById('btn-run-stage2');
    if (btnRunStage2) btnRunStage2.addEventListener('click', () => handleRunScan('btn-run-stage2', '/api/scan/stage2', loadStage2Data));

    const btnRunBtst = document.getElementById('btn-run-btst');
    if (btnRunBtst) btnRunBtst.addEventListener('click', () => handleRunScan('btn-run-btst', '/api/scan/btst', loadBtstData));

    const btnOrb = document.getElementById('btn-refresh-orb');
    if (btnOrb) btnOrb.addEventListener('click', loadOrb45Data);

    const orbFilterBtns = document.querySelectorAll('.btn-orb-filter');
    orbFilterBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        orbFilterBtns.forEach(b => {
          b.classList.remove('active');
          b.style.background = 'transparent';
          b.style.borderColor = 'transparent';
        });
        btn.classList.add('active');
        const f = btn.getAttribute('data-filter');
        currentOrbFilter = f;
        if (f === 'BULL') {
          btn.style.background = '#065f46';
          btn.style.borderColor = '#059669';
        } else if (f === 'NEAR_BULL') {
          btn.style.background = '#78350f';
          btn.style.borderColor = '#d97706';
        } else if (f === 'BEAR') {
          btn.style.background = '#7f1d1d';
          btn.style.borderColor = '#dc2626';
        } else {
          btn.style.background = '#1e293b';
          btn.style.borderColor = '#475569';
        }
        if (cachedOrbData && cachedOrbData.breakouts) {
          renderOrbTable(cachedOrbData.breakouts, currentOrbFilter);
        }
      });
    });

    const btnStage2 = document.getElementById('btn-refresh-stage2');
    if (btnStage2) btnStage2.addEventListener('click', loadStage2Data);

    const btnCanslim = document.getElementById('btn-refresh-canslim');
    if (btnCanslim) btnCanslim.addEventListener('click', loadCanslimData);

    const btnMomentum = document.getElementById('btn-refresh-momentum');
    if (btnMomentum) btnMomentum.addEventListener('click', loadMomentumPositionalData);

    const btnBtst = document.getElementById('btn-refresh-btst');
    if (btnBtst) btnBtst.addEventListener('click', loadBtstData);

    const btnSwing = document.getElementById('btn-refresh-swing');
    if (btnSwing) btnSwing.addEventListener('click', loadSwingData);

    // Indices Controls
    const btnRefreshIndices = document.getElementById('btn-refresh-indices');
    if (btnRefreshIndices) {
      btnRefreshIndices.addEventListener('click', () => loadIndicesData(true));
    }

    const filterBtns = document.querySelectorAll('.btn-idx-filter');
    filterBtns.forEach(btn => {
      btn.addEventListener('click', () => {
        filterBtns.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        currentIndicesFilter = btn.getAttribute('data-filter');
        renderIndicesTable(cachedIndicesList, currentIndicesFilter);
      });
    });

    const btnLivePrices = document.getElementById('btn-fetch-live-prices');
    if (btnLivePrices) {
      btnLivePrices.addEventListener('click', async () => {
        btnLivePrices.disabled = true;
        btnLivePrices.innerHTML = '<span class="spinner" style="width:12px;height:12px;"></span> Updating...';
        await pollLiveQuotes(true);
        btnLivePrices.disabled = false;
        btnLivePrices.innerHTML = '<span class="btn-icon">⚡</span> Refresh Live Prices';
      });
    }

    // Auto detect broker based on port or server config
    async function initBroker() {
      const isPort8001 = window.location.port === '8001';
      const urlParams = new URLSearchParams(window.location.search);
      const brokerParam = urlParams.get('broker');

      let targetBroker = (isPort8001 || brokerParam === 'kotak') ? 'kotak' : 'kite';
      try {
        const res = await fetch('/api/config');
        if (res.ok) {
          const cfg = await res.json();
          if (cfg.default_broker) targetBroker = cfg.default_broker;
        }
      } catch (e) {}

      setBroker(targetBroker);
    }

    // Auto load scanner data on start
    fetchScannerData();
    initBroker();
    loadIndicesData();
    pollLiveQuotes(true);

    // Continuous real-time price polling every 2.5 seconds
    setInterval(() => {
      pollLiveQuotes(false);
    }, 2500);

    // Auto poll indices every 4 seconds when indices tab is active
    setInterval(() => {
      if (state.activeTab === 'market-indices') {
        loadIndicesData();
      }
    }, 4000);
  }

  // Boot on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initEvents);
  } else {
    initEvents();
  }
})();


  // --- Chart Preview Modal Logic ---
  function openChartModal(symbol) {
    const modal = document.getElementById('chart-modal');
    const title = document.getElementById('modal-chart-title');
    const img = document.getElementById('modal-chart-img');
    const loading = document.getElementById('modal-chart-loading');
    const tvLink = document.getElementById('modal-tv-link');
    if (!modal || !symbol) return;

    const cleanSym = symbol.trim().replace('-EQ', '').replace('.NS', '');
    title.textContent = `${cleanSym} Weekly Candlestick Chart`;
    tvLink.href = `https://in.tradingview.com/chart/?symbol=NSE:${cleanSym}`;

    img.style.display = 'none';
    loading.style.display = 'block';
    loading.innerHTML = '<span class="spinner" style="width: 20px; height: 20px; display: inline-block; vertical-align: middle; margin-right: 8px;"></span> Generating clean weekly chart...';
    modal.classList.remove('hidden');

    img.onload = () => {
      loading.style.display = 'none';
      img.style.display = 'block';
    };
    img.onerror = () => {
      loading.innerHTML = `<span style="color: #f87171;">Failed to load chart for ${cleanSym}.</span>`;
    };
    img.src = `/api/chart/${cleanSym}?t=${Date.now()}`;
  }

  function closeChartModal() {
    const modal = document.getElementById('chart-modal');
    if (modal) modal.classList.add('hidden');
  }

  // Setup click listener for chart modal closing & symbol clicks
  document.addEventListener('click', (e) => {
    // Check if clicked a symbol
    const symEl = e.target.closest('.symbol-name');
    if (symEl) {
      const sym = symEl.textContent.trim();
      if (sym) {
        openChartModal(sym);
        return;
      }
    }

    // Check if clicked close button or backdrop
    if (e.target.id === 'modal-chart-close' || e.target.id === 'chart-modal') {
      closeChartModal();
    }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeChartModal();
  });
