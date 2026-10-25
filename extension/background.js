/**
 * Flowboard Bridge — Chrome Extension Background Service Worker
 *
 * Connects to local Python agent via WebSocket (agent runs WS server).
 * Captures Bearer token and proxies API calls through the browser context.
 */

const AGENT_WS_URL  = 'ws://127.0.0.1:8355';
const CALLBACK_URL  = 'http://127.0.0.1:8434/api/ext/callback';

let ws               = null;
let flowKey          = null;
let callbackSecret   = null; // Auth secret received from agent on WS connect
let state            = 'off'; // off | idle | running
let manualDisconnect = false;
let metrics = {
  tokenCapturedAt: null,
  requestCount:    0,
  successCount:    0,
  failedCount:     0,
  lastError:       null,
};

// Flow moved to flow.google.com in September 2026. In practice the only
// signed-in tab is flow.google.com/*; the labs.google patterns stay so an old
// pinned tab is still recognised rather than triggering a redundant spawn.
const flowUrls = [
  'https://flow.google.com/*',
  'https://labs.google/fx/tools/flow*',
  'https://labs.google/fx/*/tools/flow*',
];

// ─── URL → Log Type Classifier ─────────────────────────────

function classifyUrl(url) {
  if (url.includes('batchGenerateImages'))     return 'GEN_IMG';
  if (url.includes('batchAsyncGenerateVideo')) return 'GEN_VID';
  if (url.includes('batchCheckAsync'))         return 'POLL';
  return 'API';
}

// ─── Request Log (last 50 entries) ─────────────────────────

let requestLog = [];

function addRequestLog(entry) {
  requestLog.unshift(entry);
  if (requestLog.length > 50) requestLog.pop();
  broadcastRequestLog();
}

function updateRequestLog(id, updates) {
  const entry = requestLog.find((e) => e.id === id);
  if (entry) Object.assign(entry, updates);
  broadcastRequestLog();
}

function broadcastRequestLog() {
  chrome.runtime.sendMessage({ type: 'REQUEST_LOG_UPDATE', log: requestLog }).catch(() => {});
}

// ─── Startup ────────────────────────────────────────────────

chrome.runtime.onInstalled.addListener(init);
chrome.runtime.onStartup.addListener(init);

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'reconnect') connectToAgent();
  if (alarm.name === 'keepAlive') keepAlive();
});

async function init() {
  // Note: deliberately not restoring `userInfo` from storage. We used
  // to persist it here, but Google profile fields (name + email) are
  // PII and chrome.storage.local is plaintext + readable by other
  // extensions on the profile that hold the `storage` permission.
  // The agent replays user_info on every WS reconnect anyway via
  // fetchAndPushUserInfo(token), so persistence buys nothing.
  const data = await chrome.storage.local.get(['flowKey', 'metrics', 'callbackSecret']);
  if (data.flowKey)        flowKey        = data.flowKey;
  if (data.metrics)        Object.assign(metrics, data.metrics);
  if (data.callbackSecret) callbackSecret = data.callbackSecret;
  connectToAgent();
  chrome.alarms.create('keepAlive', { periodInMinutes: 0.4 });
}

// ─── Token Capture ──────────────────────────────────────────

chrome.webRequest.onBeforeSendHeaders.addListener(
  (details) => {
    if (!details?.requestHeaders?.length) return;
    const authHeader = details.requestHeaders.find(
      (h) => h.name?.toLowerCase() === 'authorization',
    );
    const value = authHeader?.value || '';
    if (!value.startsWith('Bearer ya29.')) return;

    const token = value.replace(/^Bearer\s+/i, '').trim();
    if (!token) return;

    // Always update — even if same token string, refresh the timestamp
    const tokenChanged = flowKey !== token;
    flowKey = token;
    metrics.tokenCapturedAt = Date.now();
    chrome.storage.local.set({ flowKey, metrics });

    // Only emit on the WS when the token actually rotated. The listener
    // fires on EVERY outbound aisandbox-pa request — and the agent's
    // own poll loops generate dozens per minute. Re-sending the same
    // string each time pushed the agent into an effective infinite
    // /v1/credits refresh loop (one credits GET per poll). The agent
    // side has a defensive dedupe too, but quiet at the source first.
    if (tokenChanged) {
      console.log('[Flowboard] Bearer token captured');
      if (ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'token_captured', flowKey }));
      }
      // Resolve the user's identity (email/name/picture) once per token —
      // saves the popup + AccountPanel from showing "Connected via
      // extension" placeholders. The token already has the userinfo.email
      // + userinfo.profile scopes Flow needs anyway, so this is a free
      // call. Errors are non-fatal and silent.
      fetchAndPushUserInfo(token);
    }
  },
  { urls: ['https://aisandbox-pa.googleapis.com/*', 'https://labs.google/*'] },
  ['requestHeaders', 'extraHeaders'],
);

let cachedUserInfo = null;

async function fetchAndPushUserInfo(token) {
  try {
    const resp = await fetch(
      'https://www.googleapis.com/oauth2/v2/userinfo',
      { headers: { authorization: `Bearer ${token}` } },
    );
    if (!resp.ok) {
      console.warn('[Flowboard] userinfo fetch returned', resp.status);
      return;
    }
    const info = await resp.json();
    // In-memory only — DO NOT persist to chrome.storage.local. PII
    // there is plaintext on disk and readable by other extensions
    // with the `storage` permission. Lifetime = service-worker
    // lifetime; rebuilt on next token rotation if the SW recycles.
    cachedUserInfo = info;
    console.log('[Flowboard] userinfo captured for', info?.email || '<no email>');
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'user_info', userInfo: info }));
    }
  } catch (e) {
    console.warn('[Flowboard] userinfo fetch failed:', e?.message || e);
  }
}

// ─── WebSocket to Agent ─────────────────────────────────────

function connectToAgent() {
  if (manualDisconnect) return;
  if (ws?.readyState === WebSocket.CONNECTING) return;
  if (ws?.readyState === WebSocket.OPEN) return;

  try {
    ws = new WebSocket(AGENT_WS_URL);
  } catch (e) {
    console.error('[Flowboard] WS connect error:', e);
    scheduleReconnect();
    return;
  }

  ws.onopen = () => {
    console.log('[Flowboard] Connected to agent');
    chrome.alarms.clear('reconnect');
    setState('idle');

    const tokenAge = flowKey && metrics.tokenCapturedAt
      ? Date.now() - metrics.tokenCapturedAt
      : null;

    ws.send(JSON.stringify({
      type: 'extension_ready',
      flowKeyPresent: !!flowKey,
      tokenAge,
      // Lets the agent refuse commands this build does not know (TikTok
      // import needs >= 0.2.0) instead of waiting on a reply that never comes.
      version: chrome.runtime.getManifest().version,
    }));

    // Resend token immediately so agent can start without waiting for a capture
    if (flowKey) {
      ws.send(JSON.stringify({ type: 'token_captured', flowKey }));
    }
    // Replay cached userinfo so the agent's AccountPanel populates on
    // reconnect without waiting for the next token rotation. If we
    // never resolved one yet but a token IS present, kick off a fetch.
    if (cachedUserInfo) {
      ws.send(JSON.stringify({ type: 'user_info', userInfo: cachedUserInfo }));
    } else if (flowKey) {
      fetchAndPushUserInfo(flowKey);
    }
  };

  ws.onmessage = async ({ data }) => {
    try {
      const msg = JSON.parse(data);

      if (msg.type === 'callback_secret') {
        callbackSecret = msg.secret;
        chrome.storage.local.set({ callbackSecret: msg.secret });
        console.log('[Flowboard] Received callback secret');
      } else if (msg.type === 'pong') {
        // keepalive response — no-op
      } else if (msg.type === 'logout') {
        // Agent's /api/auth/logout invoked — drop in-memory identity
        // so the next reconnect picks up fresh credentials. Don't
        // touch chrome.storage (we don't persist identity there
        // anyway, but be explicit). The WS stays open; agent will
        // re-greet when the user logs back in.
        console.log('[Flowboard] logout requested by agent');
        cachedUserInfo = null;
        flowKey = null;
      } else if (msg.type === 'please_resend_userinfo') {
        // Agent's /api/auth/scan asks us to re-fetch userinfo when
        // its own cache is empty (e.g. agent restarted, or user
        // clicked "Scan extension" before WS finished its first
        // round-trip). If we have a cached profile, replay it
        // immediately; otherwise refetch from Google's userinfo
        // endpoint with whatever Bearer token we currently hold.
        if (cachedUserInfo) {
          ws.send(JSON.stringify({ type: 'user_info', userInfo: cachedUserInfo }));
        } else if (flowKey) {
          fetchAndPushUserInfo(flowKey);
        } else {
          console.log('[Flowboard] please_resend_userinfo: no token captured yet');
        }
      } else if (msg.method === 'batch_rpc') {
        await handleBatchRpc(msg);
      } else if (msg.method === 'list_shop_tabs') {
        await handleListShopTabs(msg);
      } else if (msg.method === 'read_tab') {
        await handleReadTab(msg);
      } else if (msg.method === 'read_page') {
        await handleReadPage(msg);
      } else if (msg.method === 'read_channel') {
        await handleReadChannel(msg);
      } else if (msg.method === 'scrape_page') {
        await handleScrapePage(msg);
      } else if (msg.method === 'read_account') {
        await handleReadAccount(msg);
      } else if (msg.method === 'open_flow_tab') {
        await handleOpenFlowTab(msg);
      } else if (msg.method === 'api_request') {
        await handleApiRequest(msg);
      } else if (msg.method === 'trpc_request') {
        await handleTrpcRequest(msg);
      } else if (msg.method === 'get_status') {
        sendToAgent({
          id: msg.id,
          result: {
            state,
            flowKeyPresent: !!flowKey,
            manualDisconnect,
            tokenAge: metrics.tokenCapturedAt ? Date.now() - metrics.tokenCapturedAt : null,
            metrics,
          },
        });
      }
    } catch (e) {
      console.error('[Flowboard] Message error:', e);
    }
  };

  ws.onclose = () => {
    setState('off');
    if (!manualDisconnect) scheduleReconnect();
  };

  ws.onerror = (e) => {
    console.error('[Flowboard] WS error:', e);
    metrics.lastError = 'WS_ERROR';
    chrome.storage.local.set({ metrics });
  };
}

function scheduleReconnect() {
  chrome.alarms.create('reconnect', { delayInMinutes: 0.083 }); // ~5 s
}

function keepAlive() {
  if (ws?.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'ping' }));
  } else {
    connectToAgent();
  }
}

// ─── Send to Agent ──────────────────────────────────────────

/**
 * Route a message to the agent.
 * Responses (msg.id present) go via HTTP callback — immune to WS drops.
 * Falls back to WS on HTTP failure. Non-response messages use WS directly.
 */
function sendToAgent(msg) {
  if (msg.id) {
    fetch(CALLBACK_URL, {
      method:  'POST',
      headers: {
        'Content-Type':      'application/json',
        'X-Callback-Secret': callbackSecret || '',
      },
      body: JSON.stringify(msg),
    }).catch(() => {
      // HTTP failed — fall back to WS
      if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
    });
    return;
  }
  // Non-response messages (ping, status, token_captured)
  if (ws?.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(msg));
  }
}

// ─── Page-context RPC runner (the current path) ─────────────
//
// Flow's rewritten frontend signs its calls with the session cookie plus a
// per-page `at` token, and every generate also carries a single-use reCAPTCHA.
// None of that can be replayed from the service worker, so the request has to
// be issued by the Flow page itself: mint a fresh captcha through the
// grecaptcha bridge, then run the batchexecute POST in the page's MAIN world,
// where `at` / `f.sid` / `bl` live.

const CAPTCHA_SLOT = '__CAPTCHA__';
const MAX_RPC_TEXT = 32000000; // the project listing alone is past 17 MB

async function runBatchRpc(cmd) {
  const tabs = await chrome.tabs.query({ url: flowUrls });
  // Prefer a tab inside a project, then the one the user is looking at: a
  // stray Flow home tab under another signed-in account would otherwise win.
  let candidate =
    tabs.find((t) => t.url && t.url.includes('/project/') && !t.discarded) ||
    tabs.find((t) => t.active && !t.discarded) ||
    tabs.find((t) => !t.discarded) ||
    tabs[0];
  if (!candidate) {
    // No Flow tab — open one and give the app a moment to boot, otherwise
    // WIZ_global_data is not on the page yet and `at` comes back empty. Hold
    // the exact created tab id so a redirect or a stale tab cannot hijack
    // the recovery.
    let opened;
    try {
      opened = await openFlowTabResilient(false);
      await sleep(5000);
      candidate = opened?.id ? await chrome.tabs.get(opened.id).catch(() => null) : null;
    } catch (e) {
      return { error: e?.message || 'NO_FLOW_TAB' };
    }
    if (!candidate) return { error: 'NO_FLOW_TAB' };
  }
  // Chrome discards backgrounded tabs; executeScript throws on a dead one.
  const tab = await reviveTabIfNeeded(candidate);
  if (!tab) return { error: 'FLOW_TAB_DISCARDED' };

  let freq = cmd.freq;
  if (cmd.captchaAction) {
    const solved = await solveCaptcha(cmd.id, cmd.captchaAction);
    if (!solved?.token) return { error: `CAPTCHA_FAILED: ${solved?.error || 'no token'}` };
    freq = freq.split(CAPTCHA_SLOT).join(solved.token);
  }

  const [injected] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    world: 'MAIN',
    args: [cmd.rpcid, freq, MAX_RPC_TEXT, cmd.match || null],
    func: async (rpcid, freqStr, maxText, match) => {
      const wiz = globalThis.WIZ_global_data || {};
      const at = wiz.SNlM0e;
      const sid = wiz.FdrFJe;
      const bl = wiz.cfb2h;
      if (!at) return { error: 'NO_AT_TOKEN' };
      const reqid = Math.floor(Math.random() * 900000) + 100000;
      // Match Flow's own WIZ metadata. GEM_PIX_2 (Nano Banana Pro) rejects
      // image generation when source-path is missing, even where the lighter
      // models tolerate it.
      const sourcePath = location.pathname || '/';
      // With several Google accounts signed in, the page lives under /u/N/ and
      // its RPCs must too: without the prefix Google serves account 0, which
      // rejects this account's `at` token and answers without an envelope
      // ("no <rpcid> envelope in response (0 others)"). Ported from flowkit.
      const accountPrefix = (sourcePath.match(/^\/u\/\d+(?=\/)/) || [''])[0];
      const hl = (document.documentElement.lang || navigator.language || 'en').split('-')[0];
      const url =
        `${accountPrefix}/_/AiSandboxAngularFrontend/data/batchexecute?rpcids=${encodeURIComponent(rpcid)}` +
        `&source-path=${encodeURIComponent(sourcePath)}` +
        `&bl=${encodeURIComponent(bl || '')}&f.sid=${encodeURIComponent(sid || '')}` +
        `&hl=${encodeURIComponent(hl)}&_reqid=${reqid}&rt=c`;
      const resp = await fetch(url, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'content-type': 'application/x-www-form-urlencoded;charset=UTF-8',
          'x-same-domain': '1',
        },
        body: new URLSearchParams({ 'f.req': freqStr, at }),
      });
      const text = await resp.text();
      // The project listing is tens of megabytes and all we ever want from it
      // is one entry. Cutting it down in the page keeps that payload out of
      // the bridge on every poll — shipping it whole gets it truncated, which
      // loses roughly half of all lookups depending on where the id sorts.
      if (match) {
        // Case-insensitive, and the window starts 400 bytes BEFORE the hit:
        // ids come back in either case, and in the current listing entry
        // the media id sits before the second copy of the operation id.
        // Same window flowkit's extension returns. (`match`, not `at` —
        // that is the CSRF token above.)
        const found = text.toLowerCase().indexOf(match.toLowerCase());
        return {
          status: resp.status,
          matched: found !== -1,
          text: found === -1 ? '' : text.slice(Math.max(0, found - 400), found + 800),
        };
      }
      return { status: resp.status, text: text.slice(0, maxText) };
    },
  });

  return injected?.result || { error: 'NO_INJECTION_RESULT' };
}

async function handleBatchRpc(msg) {
  const { id, params } = msg;
  const { rpcid, freq, captchaAction, match } = params || {};
  if (!rpcid || !freq) {
    sendToAgent({ id, status: 400, error: 'INVALID_BATCH_RPC' });
    return;
  }

  setState('running');
  const hasCaptcha = !!captchaAction;
  if (hasCaptcha) metrics.requestCount++;
  // Polls and listing lookups run constantly; only the generates are worth a
  // row in the log the popup shows.
  const visible = hasCaptcha;
  if (visible) {
    addRequestLog({
      id,
      type: `RPC:${rpcid}`,
      time: new Date().toISOString(),
      status: 'processing',
      error: null,
      url: rpcid,
      payloadSummary: freq.slice(0, 200),
    });
  }

  try {
    const out = await runBatchRpc({ id, rpcid, freq, captchaAction, match });
    if (out.error) {
      if (hasCaptcha) { metrics.failedCount++; metrics.lastError = out.error; }
      if (visible) updateRequestLog(id, { status: 'failed', error: out.error });
      sendToAgent({ id, status: 502, error: out.error });
    } else {
      if (hasCaptcha) { metrics.successCount++; metrics.lastError = null; }
      if (visible) {
        updateRequestLog(id, {
          status: 'success',
          httpStatus: out.status,
          responseSummary: (out.text || '').slice(0, 300),
        });
      }
      sendToAgent({ id, status: out.status, data: out.text });
    }
  } catch (e) {
    const err = e?.message || 'BATCH_RPC_FAILED';
    if (hasCaptcha) { metrics.failedCount++; metrics.lastError = err; }
    if (visible) updateRequestLog(id, { status: 'failed', error: err });
    sendToAgent({ id, status: 500, error: err });
  }

  chrome.storage.local.set({ metrics });
  setState('idle');
}

// ─── Page scrape (TikTok showcase → product library) ────────
//
// Reads the product cards off a TikTok page the user already has open and
// signed in to (the affiliate showcase, a shop page). Nothing is clicked or
// submitted; the page is only scrolled so lazy cards render. The extraction
// is heuristic — TikTok's markup is not a contract — so the result carries
// `diag` (counts and a couple of card samples) to tune it against the real
// page instead of guessing.

// Email / credits / plan of the Google account this Chrome profile uses on
// Flow. flow.google.com mints no Bearer token any more, so the only place
// these numbers exist is the account panel in the page: open it, read it,
// close it (a short flicker on the Flow tab, only when asked).
async function handleReadAccount(msg) {
  const { id } = msg;
  try {
    const tabs = await chrome.tabs.query({ url: ['https://flow.google.com/*', 'https://labs.google/fx/*'] });
    if (!tabs.length) {
      sendToAgent({ id, status: 404, error: 'NO_FLOW_TAB' });
      return;
    }
    const tab = tabs.find((t) => t.active) || tabs.sort((a, b) => (b.lastAccessed || 0) - (a.lastAccessed || 0))[0];
    const [res] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: readAccountInPage,
    });
    const out = res && res.result;
    if (!out || out.error) {
      sendToAgent({ id, status: 404, error: (out && out.error) || 'ACCOUNT_PANEL_NOT_FOUND' });
      return;
    }
    sendToAgent({ id, status: 200, data: JSON.stringify({ tabUrl: tab.url, ...out }) });
  } catch (e) {
    sendToAgent({ id, status: 500, error: e?.message || 'READ_ACCOUNT_FAILED' });
  }
}

// Open (or focus) flow.google.com for a given Google account. `authuser=<email>`
// makes Google pick that signed-in account when it can; otherwise the user
// switches on the page — the agent keeps reading the panel until it matches.
async function handleOpenFlowTab(msg) {
  const { id, params } = msg;
  const email = params && params.email ? String(params.email) : '';
  try {
    const url = 'https://flow.google.com/' + (email ? '?authuser=' + encodeURIComponent(email) : '');
    const tabs = await chrome.tabs.query({ url: ['https://flow.google.com/*', 'https://labs.google/fx/*'] });
    const existing = tabs.find((t) => t.active) || tabs[0];
    if (existing) {
      await chrome.tabs.update(existing.id, { url, active: true });
      try { await chrome.windows.update(existing.windowId, { focused: true }); } catch (e) { /* ignore */ }
    } else {
      await chrome.tabs.create({ url, active: true });
    }
    sendToAgent({ id, status: 200, data: JSON.stringify({ opened: true, url }) });
  } catch (e) {
    sendToAgent({ id, status: 500, error: e?.message || 'OPEN_TAB_FAILED' });
  }
}

// Runs inside the Flow page: must be self-contained.
async function readAccountInPage() {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const panelSel = 'flow-account-panel';
  const read = () => {
    const panel = document.querySelector(panelSel);
    if (!panel) return null;
    const c = panel.querySelector('.credits-count');
    const e = panel.querySelector('.user-email');
    return { credits: c ? c.textContent.trim() : null, email: e ? e.textContent.trim() : null };
  };
  let out = read();
  let opened = false;
  if (!out) {
    const btn = document.querySelector('.header-user-button') || document.querySelector('[aria-label*="tài khoản" i], [aria-label*="account" i]');
    if (!btn) return { error: 'NO_ACCOUNT_BUTTON' };
    btn.click();
    opened = true;
    for (let i = 0; i < 25 && !out; i++) {
      await sleep(120);
      out = read();
      if (out && !out.credits && !out.email) out = null;
    }
  }
  const chip = document.querySelector('flow-user-tier-chip');
  const tier = chip ? chip.textContent.trim() : null;
  if (opened) {
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await sleep(150);
    if (document.querySelector(panelSel)) {
      const bd = document.querySelector('.cdk-overlay-backdrop');
      if (bd) bd.click();
    }
  }
  if (!out) return { error: 'ACCOUNT_PANEL_NOT_FOUND', tier };
  return { ...out, tier };
}

// ─── Read one product page in a background tab (Shopee) ─────
//
// Shopee renders its product pages in JavaScript and only for a signed-in
// browser, so the agent cannot fetch them. This opens the link in an inactive
// tab of the user's own Chrome, waits until the product has rendered, reads
// what a product card needs, and closes the tab again. Nothing is clicked.

const READ_PAGE_HOSTS = /^https:\/\/([a-z0-9-]+\.)*(shopee\.vn|shp\.ee)\//i;

async function handleReadPage(msg) {
  const { id, params } = msg;
  const { url, timeoutMs = 25000, minText = 1500 } = params || {};
  if (!READ_PAGE_HOSTS.test(url || '')) {
    sendToAgent({ id, status: 400, error: 'URL_NOT_ALLOWED' });
    return;
  }
  let tab = null;
  try {
    tab = await chrome.tabs.create({ url, active: false });
    const deadline = Date.now() + timeoutMs;
    let result = null;
    while (Date.now() < deadline) {
      await sleep(1200);
      let t;
      try { t = await chrome.tabs.get(tab.id); } catch { break; }
      if (/\/verify\/|\/buyer\/login/.test(t.url || '')) {
        result = { blocked: true, url: t.url };
        break;
      }
      if (t.status !== 'complete') continue;
      const [r] = await chrome.scripting.executeScript({
        target: { tabId: tab.id }, func: readProductPageInPage, args: [minText],
      });
      if (r?.result) result = r.result;
      if (r?.result?.ready) break;
    }
    sendToAgent({ id, status: 200, data: JSON.stringify(result || { timeout: true }) });
  } catch (e) {
    sendToAgent({ id, status: 500, error: e?.message || 'READ_PAGE_FAILED' });
  } finally {
    if (tab?.id) chrome.tabs.remove(tab.id).catch(() => {});
  }
}

// "Kênh của tôi" → "Xem & đánh giá kênh": open the seller's page (Facebook,
// TikTok, Instagram, YouTube, Threads, Zalo) in a background tab of THEIR
// Chrome (logged in, so Facebook shows the posts), scroll a few screens so
// recent posts load, read the text, close the tab.
const READ_CHANNEL_HOSTS = /^https:\/\/([a-z0-9-]+\.)*(facebook\.com|fb\.com|instagram\.com|tiktok\.com|youtube\.com|threads\.net|threads\.com|zalo\.me)\//i;

async function handleReadChannel(msg) {
  const { id, params } = msg;
  const { url, timeoutMs = 30000, scrolls = 5 } = params || {};
  if (!READ_CHANNEL_HOSTS.test(url || '')) {
    sendToAgent({ id, status: 400, error: 'URL_NOT_ALLOWED' });
    return;
  }
  let tab = null;
  try {
    tab = await chrome.tabs.create({ url, active: false });
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      await sleep(1000);
      let t;
      try { t = await chrome.tabs.get(tab.id); } catch { break; }
      if (t.status === 'complete') break;
    }
    await sleep(2500);
    for (let i = 0; i < scrolls; i++) {
      await chrome.scripting.executeScript({
        target: { tabId: tab.id }, func: () => window.scrollBy(0, Math.round(window.innerHeight * 1.8)),
      });
      await sleep(1600);
    }
    const [r] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: readChannelPageInPage });
    sendToAgent({ id, status: 200, data: JSON.stringify(r?.result || { empty: true }) });
  } catch (e) {
    sendToAgent({ id, status: 500, error: e?.message || 'READ_CHANNEL_FAILED' });
  } finally {
    if (tab?.id) chrome.tabs.remove(tab.id).catch(() => {});
  }
}

// Runs inside the page: must be self-contained.
function readChannelPageInPage() {
  const meta = (n) => document.querySelector(`meta[property="${n}"], meta[name="${n}"]`)?.content || '';
  // Facebook renders hundreds of hidden "Facebook" spans; drop them and
  // repeated lines so the 40k budget goes to the posts.
  const lines = [];
  for (const raw of (document.body?.innerText || '').split('\n')) {
    const line = raw.trim();
    if (!line || /^(facebook|instagram|tiktok|·)$/i.test(line) || lines[lines.length - 1] === line) continue;
    lines.push(line);
  }
  const text = lines.join('\n').slice(0, 40000);
  return {
    url: location.href,
    title: document.title || '',
    description: meta('og:description') || meta('description'),
    image: meta('og:image'),
    text,
  };
}

// "Nhập từ tab đang mở": every TikTok / Shopee tab, so the agent can tell
// which shop each one is and which are product pages. Nothing is read yet.
const SHOP_TAB_PATTERNS = ['https://*.tiktok.com/*', 'https://shopee.vn/*', 'https://*.shopee.vn/*'];
const SHOP_TAB_URL = /^https:\/\/([a-z0-9-]+\.)*(tiktok\.com|shopee\.vn)\//i;

async function handleListShopTabs(msg) {
  const { id } = msg;
  try {
    const tabs = await chrome.tabs.query({ url: SHOP_TAB_PATTERNS });
    sendToAgent({
      id, status: 200,
      data: JSON.stringify({
        tabs: tabs.map((t) => ({
          id: t.id, url: t.url || '', title: t.title || '', active: !!t.active,
          lastAccessed: t.lastAccessed || 0, discarded: !!t.discarded, status: t.status || '',
        })),
      }),
    });
  } catch (e) {
    sendToAgent({ id, status: 500, error: e?.message || 'LIST_TABS_FAILED' });
  }
}

/** A tab Chrome put to sleep (memory saver) or that is still loading:
 *  reload / wait until it is complete, at most `ms`. */
async function readyTab(tabId, ms) {
  let t = await chrome.tabs.get(tabId);
  if (t.discarded) {
    await chrome.tabs.reload(tabId);
    await sleep(800);
  }
  const deadline = Date.now() + ms;
  while (Date.now() < deadline) {
    t = await chrome.tabs.get(tabId);
    if (t.status === 'complete' && !t.discarded) return t;
    await sleep(600);
  }
  return t;
}

// Read one tab in place: what readProductPageInPage sees, plus tabUrl / tabTitle. Nothing is clicked.
async function handleReadTab(msg) {
  const { id, params } = msg;
  const { tabId, minText = 1500 } = params || {};
  try {
    const tab = await readyTab(tabId, 20000);
    if (!SHOP_TAB_URL.test(tab.url || '')) {
      sendToAgent({ id, status: 400, error: 'URL_NOT_ALLOWED' });
      return;
    }
    // A page that has just loaded renders its product a moment later.
    let result = null;
    for (let i = 0; i < 6; i++) {
      const [r] = await chrome.scripting.executeScript({ target: { tabId }, func: readProductPageInPage, args: [minText] });
      result = r?.result || result;
      if (result?.ready) break;
      await sleep(1200);
    }
    sendToAgent({ id, status: 200, data: JSON.stringify({ ...(result || {}), tabUrl: tab.url, tabTitle: tab.title }) });
  } catch (e) {
    sendToAgent({ id, status: 500, error: /No tab with id/i.test(e?.message || '') ? 'TAB_CLOSED' : (e?.message || 'READ_TAB_FAILED') });
  }
}

// Runs inside the page: must be self-contained.
function readProductPageInPage(minText) {
  const text = document.body ? document.body.innerText || '' : '';
  const meta = (n) => (document.querySelector(`meta[property="${n}"], meta[name="${n}"]`) || {}).content || '';
  const ld = [];
  document.querySelectorAll('script[type="application/ld+json"]').forEach((s) => {
    try { ld.push(JSON.parse(s.textContent)); } catch (e) { /* not JSON */ }
  });
  const images = Array.from(document.images)
    .map((i) => ({ src: i.currentSrc || i.src, w: i.naturalWidth, h: i.naturalHeight }))
    .filter((i) => i.src && i.src.startsWith('http') && i.w >= 300 && i.h >= 300)
    .sort((a, b) => b.w * b.h - a.w * a.h)
    .slice(0, 8);
  const hasProduct = ld.some((x) => JSON.stringify(x).includes('"Product"'));
  return {
    ready: hasProduct || text.length >= minText,
    url: location.href,
    title: document.title,
    description: meta('og:description') || meta('description'),
    ogImage: meta('og:image'),
    ld,
    images,
    text: text.slice(0, 15000),
  };
}

async function handleScrapePage(msg) {
  const { id, params } = msg;
  const { urlPatterns, scrolls, maxItems, tabId } = params || {};
  const patterns = Array.isArray(urlPatterns) && urlPatterns.length
    ? urlPatterns : ['https://*.tiktok.com/*'];
  try {
    let tab;
    if (tabId) {
      // A tab picked in "Nhập từ tab đang mở".
      tab = await readyTab(tabId, 20000);
      if (!/^https:\/\/([a-z0-9-]+\.)*tiktok\.com\//i.test(tab.url || '')) {
        sendToAgent({ id, status: 400, error: 'URL_NOT_ALLOWED' });
        return;
      }
    } else {
      const tabs = await chrome.tabs.query({ url: patterns });
      if (!tabs.length) {
        sendToAgent({ id, status: 404, error: 'NO_TIKTOK_TAB' });
        return;
      }
      // The tab the user is looking at wins; otherwise the most recently used.
      tab = tabs.find((t) => t.active) || tabs.sort((a, b) => (b.lastAccessed || 0) - (a.lastAccessed || 0))[0];
    }
    const [res] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: scrapeProductCardsInPage,
      args: [{ scrolls: scrolls || 12, maxItems: maxItems || 200 }],
    });
    sendToAgent({ id, status: 200, data: JSON.stringify({ tabUrl: tab.url, tabTitle: tab.title, ...(res?.result || {}) }) });
  } catch (e) {
    sendToAgent({ id, status: 500, error: e?.message || 'SCRAPE_FAILED' });
  }
}

// Runs inside the page: must be self-contained (no closure over this file).
async function scrapeProductCardsInPage(opts) {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const PRICE = /(?:₫|đ)\s?\d[\d.,]*|\d{1,3}(?:[.,]\d{3})+\s?(?:₫|đ|d\b|VND)|\d+\s?(?:₫|đ)(?![a-zà-ỹ])/i;
  const PRODUCT_ID = /product[\/=](\d{10,})/i;
  const NOISE = /^(đã bán|sold|hoa hồng|commission|thêm|add|xem|chia sẻ|share|-?\d+%|miễn phí|free|freeship)/i;

  const found = new Map();
  const seenCards = new WeakSet();
  const samples = [];
  let anchorHits = 0;

  const bigImg = (el) => Array.from(el.querySelectorAll('img'))
    .filter((i) => (i.naturalWidth || i.width || 0) >= 60 && (i.currentSrc || i.src));

  function titleOf(card) {
    const lines = (card.innerText || '').split('\n').map((l) => l.trim()).filter(Boolean);
    const cands = lines.filter((l) => l.length >= 6 && !PRICE.test(l) && !NOISE.test(l));
    cands.sort((a, b) => b.length - a.length);
    return cands[0] || '';
  }

  function add(card, href, pid) {
    if (seenCards.has(card)) return;
    const imgs = bigImg(card);
    const title = titleOf(card);
    const priceMatch = PRICE.exec(card.innerText || '');
    if (!title || !imgs.length) return;
    const image = imgs[0].currentSrc || imgs[0].src;
    const key = pid || href || `${image}|${title}`;
    if (found.has(key)) return;
    seenCards.add(card);
    found.set(key, {
      id: pid || '',
      title: title.slice(0, 200),
      price: priceMatch ? priceMatch[0].trim() : '',
      image,
      url: href || '',
    });
    if (samples.length < 2) samples.push(card.outerHTML.slice(0, 600));
  }

  function climb(node) {
    // The smallest ancestor that holds an image and a price: the card.
    let el = node;
    for (let i = 0; i < 8 && el && el !== document.body; i++, el = el.parentElement) {
      if (PRICE.test(el.innerText || '') && bigImg(el).length) return el;
    }
    return null;
  }

  function harvest() {
    for (const a of document.querySelectorAll('a[href]')) {
      const m = PRODUCT_ID.exec(a.href);
      if (!m) continue;
      anchorHits++;
      const card = climb(a);
      if (card) add(card, a.href.split('?')[0], m[1]);
    }
    // Cards that are not links: start from images with a price nearby.
    for (const img of document.querySelectorAll('img')) {
      if ((img.naturalWidth || img.width || 0) < 80) continue;
      const card = climb(img);
      if (card) add(card, '', '');
    }
  }

  function scrollables() {
    return Array.from(document.querySelectorAll('*')).filter((el) => {
      if (el.scrollHeight <= el.clientHeight + 80) return false;
      const oy = getComputedStyle(el).overflowY;
      return oy === 'auto' || oy === 'scroll';
    });
  }

  let stable = 0;
  for (let round = 0; round < opts.scrolls && stable < 3 && found.size < opts.maxItems; round++) {
    const before = found.size;
    harvest();
    window.scrollTo(0, document.body.scrollHeight);
    for (const el of scrollables()) el.scrollTop = el.scrollHeight;
    await sleep(900);
    harvest();
    stable = found.size === before ? stable + 1 : 0;
  }
  window.scrollTo(0, 0);

  return {
    items: Array.from(found.values()).slice(0, opts.maxItems),
    diag: {
      anchorHits,
      imgs: document.images.length,
      scrollables: scrollables().length,
      samples,
      bodyText: (document.body.innerText || '').slice(0, 400),
    },
  };
}

// ─── API Request Proxy (legacy) ─────────────────────────────
//
// The pre-migration REST path. aisandbox-pa required the `Bearer ya29.…`
// captured below, and flow.google.com does not mint one, so this answers
// NO_FLOW_KEY for real work now. Kept for the manual `proxy` request type,
// and so an extension updated ahead of its agent stays backwards compatible.

async function handleApiRequest(msg) {
  const { id, params } = msg;
  const { url, method, headers, body, captchaAction } = params || {};

  if (!url || !url.startsWith('https://aisandbox-pa.googleapis.com/')) {
    sendToAgent({ id, status: 400, error: 'INVALID_URL' });
    return;
  }

  setState('running');
  const hasCaptcha = !!captchaAction;
  if (hasCaptcha) metrics.requestCount++;

  addRequestLog({
    id,
    type:   classifyUrl(url),
    time:   new Date().toISOString(),
    status: 'processing',
    url,
  });

  try {
    // Step 0: Fail fast if we have no bearer token. Avoids burning a reCAPTCHA
    // solve (rate-limited + single-use) only to discover later that we can't
    // send the request.
    if (!flowKey) {
      sendToAgent({ id, status: 503, error: 'NO_FLOW_KEY' });
      if (hasCaptcha) { metrics.failedCount++; metrics.lastError = 'NO_FLOW_KEY'; }
      chrome.storage.local.set({ metrics });
      updateRequestLog(id, { status: 'failed', error: 'NO_FLOW_KEY' });
      setState('idle');
      return;
    }

    // Step 1: Solve captcha if needed
    let captchaToken = null;
    if (captchaAction) {
      const captchaResult = await solveCaptcha(id, captchaAction);
      captchaToken = captchaResult?.token || null;
      if (!captchaToken) {
        const err = captchaResult?.error || 'CAPTCHA_FAILED';
        console.error(`[Flowboard] Captcha failed for ${captchaAction}: ${err}`);
        sendToAgent({ id, status: 403, error: `CAPTCHA_FAILED: ${err}` });
        if (hasCaptcha) { metrics.failedCount++; metrics.lastError = `CAPTCHA_FAILED: ${err}`; }
        chrome.storage.local.set({ metrics });
        updateRequestLog(id, { status: 'failed', error: `CAPTCHA_FAILED: ${err}` });
        setState('idle');
        return;
      }
    }

    // Step 2: Inject captcha token into body clone if present
    let finalBody = body;
    if (captchaToken && finalBody) {
      finalBody = JSON.parse(JSON.stringify(finalBody)); // deep clone
      if (finalBody.clientContext?.recaptchaContext) {
        finalBody.clientContext.recaptchaContext.token = captchaToken;
      }
      if (finalBody.requests && Array.isArray(finalBody.requests)) {
        for (const req of finalBody.requests) {
          if (req.clientContext?.recaptchaContext) {
            req.clientContext.recaptchaContext.token = captchaToken;
          }
        }
      }
    }

    const fetchHeaders = { ...(headers || {}), authorization: `Bearer ${flowKey}` };

    const response = await fetch(url, {
      method:      method || 'POST',
      headers:     fetchHeaders,
      credentials: 'include',
      body:        method === 'GET' ? undefined : JSON.stringify(finalBody),
    });

    const responseText = await response.text();
    let responseData;
    try {
      responseData = JSON.parse(responseText);
    } catch {
      responseData = responseText;
    }

    sendToAgent({ id, status: response.status, data: responseData });

    if (response.ok) {
      if (hasCaptcha) { metrics.successCount++; metrics.lastError = null; }
      updateRequestLog(id, { status: 'success', httpStatus: response.status });
    } else {
      if (hasCaptcha) { metrics.failedCount++; metrics.lastError = `API_${response.status}`; }
      updateRequestLog(id, { status: 'failed', httpStatus: response.status, error: `API_${response.status}` });
    }
  } catch (e) {
    sendToAgent({ id, status: 500, error: e.message || 'API_REQUEST_FAILED' });
    if (hasCaptcha) { metrics.failedCount++; metrics.lastError = e.message || 'API_REQUEST_FAILED'; }
    updateRequestLog(id, { status: 'failed', error: e.message || 'API_REQUEST_FAILED' });
  }

  chrome.storage.local.set({ metrics });
  setState('idle');
}

// ─── Token Refresh (minimal) ────────────────────────────────

let _openingFlowTab = false;

const FLOW_URL = 'https://flow.google.com/';

/**
 * Open a Flow tab even when Chrome has zero windows. `chrome.tabs.create`
 * throws "No current window" in that state because it needs a window
 * context to attach to; `chrome.windows.create` spawns a fresh window
 * and tab in one call. Falls back through both paths so we recover from
 * "all-windows-closed but service-worker-still-alive" silently.
 */
async function openFlowTabResilient(active = false) {
  try {
    return await chrome.tabs.create({ url: FLOW_URL, active });
  } catch (e) {
    const msg = e?.message || '';
    if (!msg.includes('No current window')) throw e;
    console.log('[Flowboard] No Chrome window — spawning a fresh one for Flow');
    const win = await chrome.windows.create({
      url: FLOW_URL,
      focused: false,
      state: 'minimized',
    });
    return win.tabs?.[0] ?? null;
  }
}

async function captureTokenFromFlowTab() {
  const tabs = await chrome.tabs.query({ url: flowUrls });

  if (!tabs.length) {
    if (_openingFlowTab) return;
    _openingFlowTab = true;
    try {
      console.log('[Flowboard] No Flow tab — opening in background');
      await openFlowTabResilient(false);
    } catch (e) {
      console.error('[Flowboard] Failed to open Flow tab:', e);
    } finally {
      _openingFlowTab = false;
    }
    return;
  }

  try {
    // Trigger a credentialed request so the page re-issues an Authorization header
    await chrome.scripting.executeScript({
      target: { tabId: tabs[0].id },
      func:   () => fetch('/fx/tools/flow', { credentials: 'include' }),
    });
    console.log('[Flowboard] Token refresh triggered on Flow tab');
  } catch (e) {
    console.error('[Flowboard] Token refresh failed:', e);
  }
}

// ─── reCAPTCHA Solving ──────────────────────────────────────

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function requestCaptchaFromTab(tabId, requestId, pageAction) {
  try {
    return await chrome.tabs.sendMessage(tabId, {
      type: 'GET_CAPTCHA',
      requestId,
      pageAction,
    });
  } catch (error) {
    const msg = error?.message || '';
    const shouldInject =
      msg.includes('Receiving end does not exist') ||
      msg.includes('Could not establish connection');
    if (!shouldInject) throw error;

    // Inject content script and retry. Both the inject + re-send can
    // throw "No current window" / "No tab with id" if the tab dies in
    // between (Chrome aggressively discards background tabs). Surface
    // those verbatim so solveCaptcha's loop can move to the next
    // candidate instead of bubbling a confusing message to the user.
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ['content.js'],
    });
    await sleep(200);
    return await chrome.tabs.sendMessage(tabId, {
      type: 'GET_CAPTCHA',
      requestId,
      pageAction,
    });
  }
}

/** Try to wake a discarded Flow tab so `sendMessage` can reach it.
 *  Chrome auto-discards backgrounded tabs to save memory; the tab still
 *  shows up in `chrome.tabs.query` but cross-context calls fail with
 *  "No current window" / "No tab with id". A reload re-hydrates it. */
async function reviveTabIfNeeded(tab) {
  if (!tab?.discarded) return tab;
  try {
    await chrome.tabs.reload(tab.id);
    await sleep(2500);
    const fresh = await chrome.tabs.get(tab.id);
    return fresh;
  } catch {
    return null;
  }
}

function captchaFromTab(tabId, requestId, captchaAction) {
  return Promise.race([
    requestCaptchaFromTab(tabId, requestId, captchaAction),
    new Promise((_, rej) => setTimeout(() => rej(new Error('CAPTCHA_TIMEOUT')), 30000)),
  ]);
}

async function solveCaptcha(requestId, captchaAction) {
  const tabs = await chrome.tabs.query({ url: flowUrls });

  // No Flow tab at all — spawn one (handles "no Chrome window" via the
  // resilient helper).
  if (!tabs.length) {
    try {
      await openFlowTabResilient(false);
      await sleep(3000);
    } catch (e) {
      return { error: e.message || 'NO_FLOW_TAB' };
    }
  }

  // Try each Flow tab in turn — gracefully skip dead/discarded ones
  // instead of bubbling "No current window" up to the user. Re-query
  // because we might have just spawned a new one above.
  const candidates = await chrome.tabs.query({ url: flowUrls });
  const errors = [];
  for (const tab of candidates) {
    const live = await reviveTabIfNeeded(tab);
    if (!live) continue;
    try {
      const resp = await captchaFromTab(live.id, requestId, captchaAction);
      // A tab that replies without a token is a tab sitting on a page that
      // never loaded grecaptcha — another Flow tab may well be fine. Returning
      // on the first reply let one stale tab veto every generation.
      if (!resp?.token) {
        errors.push(resp?.error || 'NO_TOKEN');
        continue;
      }
      return resp;
    } catch (e) {
      const msg = e?.message || '';
      errors.push(msg);
      // Tab evaporated mid-call (window closed, tab discarded again,
      // or page navigated away). Move on to the next candidate.
      if (
        msg.includes('No current window') ||
        msg.includes('No tab with id') ||
        msg.includes('Receiving end does not exist')
      ) {
        continue;
      }
      return { error: msg };
    }
  }

  // All candidates failed — last-ditch: spawn a fresh Flow tab and try THAT
  // exact tab once. This handles every existing Flow tab being in a window we
  // could not recover from. Previously this re-queried all Flow tabs and took
  // fresh[0], which could pick the same stale tab again while leaking the
  // newly created one on every retry.
  let recoveryTab = null;
  try {
    recoveryTab = await openFlowTabResilient(false);
    await sleep(3000);
    const target = recoveryTab?.id
      ? await chrome.tabs.get(recoveryTab.id).catch(() => null)
      : null;
    if (!target || target.discarded) return { error: 'NO_FLOW_TAB' };
    return await captchaFromTab(target.id, requestId, captchaAction);
  } catch (e) {
    return { error: e?.message || errors[0] || 'NO_FLOW_TAB' };
  } finally {
    // A recovery tab is disposable: there were already Flow tabs available for
    // the signed RPC itself. Do not let captcha retries accumulate tabs.
    if (recoveryTab?.id) {
      try { await chrome.tabs.remove(recoveryTab.id); } catch { /* already gone */ }
    }
  }
}

// ─── TRPC Request Proxy ─────────────────────────────────────

async function handleTrpcRequest(msg) {
  const { id, params } = msg;
  const { url, method = 'POST', headers = {}, body } = params;

  // Tightly scoped to TRPC endpoints — prevents the agent from navigating to
  // arbitrary labs.google paths (e.g. /fx/api/trpc/account.deleteAccount would
  // also match /fx/api/trpc/ but account-level mutations should be gated server
  // side if they're ever needed).
  if (!url || !url.startsWith('https://labs.google/fx/api/trpc/')) {
    sendToAgent({ id, error: 'INVALID_TRPC_URL' });
    return;
  }

  setState('running');
  // TRPC calls are silent — don't add to request log, don't bump metrics

  const fetchHeaders = { 'Content-Type': 'application/json', ...headers };
  if (flowKey) {
    fetchHeaders['authorization'] = `Bearer ${flowKey}`;
  }

  try {
    const resp = await fetch(url, {
      method,
      headers: fetchHeaders,
      body:    body ? JSON.stringify(body) : undefined,
      credentials: 'include',
    });
    const data = await resp.json();
    sendToAgent({ id, status: resp.status, data });
  } catch (e) {
    console.error('[Flowboard] tRPC request failed:', e);
    sendToAgent({ id, error: e.message || 'TRPC_FETCH_FAILED' });
  } finally {
    setState('idle');
  }
}

// ─── State & Badge ──────────────────────────────────────────

function setState(newState) {
  state = newState;
  const badges = { idle: '●', running: '▶', off: '○' };
  const colors  = { idle: '#22c55e', running: '#f5b301', off: '#6b7280' };
  chrome.action.setBadgeText({ text: badges[newState] || '' });
  chrome.action.setBadgeBackgroundColor({ color: colors[newState] || '#000' });
  broadcastStatus();
}

function broadcastStatus() {
  chrome.runtime.sendMessage({ type: 'STATUS_PUSH' }).catch(() => {});
}

// ─── Popup Message Handlers ─────────────────────────────────

chrome.runtime.onMessage.addListener((msg, _, reply) => {
  if (msg.type === 'STATUS') {
    reply({
      connected:       ws?.readyState === WebSocket.OPEN,
      flowKeyPresent:  !!flowKey,
      manualDisconnect,
      tokenAge:        metrics.tokenCapturedAt ? Date.now() - metrics.tokenCapturedAt : null,
      metrics: {
        requestCount: metrics.requestCount,
        successCount: metrics.successCount,
        failedCount:  metrics.failedCount,
        lastError:    metrics.lastError,
      },
      state,
    });
    return true;
  }

  if (msg.type === 'DISCONNECT') {
    manualDisconnect = true;
    ws?.close();
    reply({ ok: true });
    return true;
  }

  if (msg.type === 'RECONNECT') {
    manualDisconnect = false;
    connectToAgent();
    reply({ ok: true });
    return true;
  }

  if (msg.type === 'REQUEST_LOG') {
    reply({ log: requestLog });
    return true;
  }

  if (msg.type === 'OPEN_FLOW_TAB') {
    chrome.tabs.query({ url: flowUrls }).then(async (tabs) => {
      try {
        if (tabs.length) {
          await chrome.tabs.update(tabs[0].id, { active: true });
          reply({ ok: true, tabId: tabs[0].id });
        } else {
          // User-initiated → focus the new window so they can see it.
          const tab = await openFlowTabResilient(true);
          reply({ ok: true, tabId: tab?.id });
        }
      } catch (e) {
        reply({ error: e.message });
      }
    }).catch((e) => reply({ error: e.message }));
    return true;
  }

  if (msg.type === 'REFRESH_TOKEN') {
    captureTokenFromFlowTab()
      .then(() => reply({ ok: true }))
      .catch((e) => reply({ error: e.message }));
    return true;
  }

  return true;
});

console.log('[Flowboard] Extension loaded');
