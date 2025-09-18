const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000';

import './style.css';

// Elements
const subjectEl = document.getElementById('subject');
const generateBtn = document.getElementById('generateBtn');
const stopBtn = document.getElementById('stopBtn');
const structureEl = document.getElementById('structure');
const statsModel = document.getElementById('statModel');
const statsTime = document.getElementById('statTime');
const statsSpeed = document.getElementById('statSpeed');
const statsTokens = document.getElementById('statTokens');
const downloadTxt = document.getElementById('downloadTxt');
const downloadPdf = document.getElementById('downloadPdf');

// Quota elements
const quotaLabel = document.getElementById('quotaLabel');
const quotaBar = document.getElementById('quotaBar');

const progressOuter = document.getElementById('progressOuter');
const progressInner = document.getElementById('progressInner');

// Notification elements
const notify = document.getElementById('notify');
const notifyInner = document.getElementById('notifyInner');
const notifyText = document.getElementById('notifyText');

const simpleControls = document.getElementById('simpleControls');
const advancedPanel = document.getElementById('advancedPanel');
const modeToggle = document.getElementById('modeToggle');
const themeToggle = document.getElementById('themeToggle');
const extraToggle = document.getElementById('extraToggle');
const extraPanel = document.getElementById('extraPanel');
const instrRequired = document.getElementById('instrRequired');
const instrQuestions = document.getElementById('instrQuestions');
const instrGoal = document.getElementById('instrGoal');

// BYOK elements
const byokOpen = document.getElementById('byokOpen');
const byokOverlay = document.getElementById('byokOverlay');
const byokModal = document.getElementById('byokModal');
const byokClose = document.getElementById('byokClose');
const byokInput = document.getElementById('byokInput');
const byokShow = document.getElementById('byokShow');
const byokRemember = document.getElementById('byokRemember');
const byokSave = document.getElementById('byokSave');
const byokClear = document.getElementById('byokClear');
const byokStatus = document.getElementById('byokStatus');

// Legal/contact modal elements
const openPrivacy = document.getElementById('openPrivacy');
const openTerms = document.getElementById('openTerms');
const openImpressum = document.getElementById('openImpressum');
const openContact = document.getElementById('openContact');

const privacyOverlay = document.getElementById('privacyOverlay');
const privacyModal = document.getElementById('privacyModal');
const privacyClose = document.getElementById('privacyClose');

const termsOverlay = document.getElementById('termsOverlay');
const termsModal = document.getElementById('termsModal');
const termsClose = document.getElementById('termsClose');

const impressumOverlay = document.getElementById('impressumOverlay');
const impressumModal = document.getElementById('impressumModal');
const impressumClose = document.getElementById('impressumClose');

const contactOverlay = document.getElementById('contactOverlay');
const contactModal = document.getElementById('contactModal');
const contactClose = document.getElementById('contactClose');
const contactName = document.getElementById('contactName');
const contactEmail = document.getElementById('contactEmail');
const contactMessage = document.getElementById('contactMessage');
const contactSubmit = document.getElementById('contactSubmit');
const contactTargetLink = contactModal ? contactModal.querySelector('a[href^="mailto:"]') : null;

// Advanced controls
let selectedModel = 'openai/gpt-oss-20b';
let selectedStyle = 'akadémikus';
let selectedLevel = 'általános';
const temperatureEl = document.getElementById('temperature');
const temperatureVal = document.getElementById('temperatureVal');
const topPEl = document.getElementById('topP');
const topPVal = document.getElementById('topPVal');
const targetLenEl = document.getElementById('targetLength');
const targetLenVal = document.getElementById('targetLengthVal');

// State
let accumulatingContent = '';
let sectionBuffers = new Map(); // title -> string
let controller = null; // AbortController for streaming
let inProgress = false;
let totalSections = 0;
let completedSections = 0;
const sectionStatusEls = new Map(); // title -> {container, statusEl, spinnerEl}

function setSectionWait(title, seconds, message) {
  ensureSectionContainer(title);
  const refs = sectionStatusEls.get(title);
  if (!refs) return;
  const { statusEl, spinnerEl } = refs;
  spinnerEl.classList.remove('hidden');
  spinnerEl.classList.add('animate-spin');
  const s = Number(seconds || 0).toFixed(1);
  statusEl.textContent = `Várakozás ${s}s (limit)`;
  statusEl.className = 'status-text text-xs text-yellow-400';
  if (message && typeof message === 'string' && message.toLowerCase().includes('429')) {
    showNotify('Átmeneti limit. Rövid várakozás…', 'warning', 2000);
  }
}

function updateQuotaUI(perDay, remaining) {
  if (!quotaLabel || !quotaBar) return;
  const pd = Number(perDay) || 3;
  const rem = Math.max(0, Math.min(pd, Number(remaining) || 0));
  quotaLabel.textContent = `${rem}/${pd}`;
  const pct = pd > 0 ? Math.round((rem / pd) * 100) : 0;
  quotaBar.style.width = `${pct}%`;
}

async function refreshQuota() {
  try {
    const r = await fetch(`${API_BASE}/api/quota`, {
      method: 'GET',
      headers: Object.assign({}, byokKey ? { 'Authorization': `Bearer ${byokKey}` } : {}),
      cache: 'no-store',
      credentials: 'omit',
      mode: 'cors',
    });
    if (!r.ok) throw new Error('quota');
    const data = await r.json();
    updateQuotaUI(data.per_day, data.remaining);
    return data;
  } catch (e) {
    // Leave current UI as-is on failure to avoid misleading resets
    return null;
  }
}
let notifyTimeout = null;
let timerStartMs = null; // number | null
let timerIntervalId = null; // number | null

// BYOK state
// null = unknown (not yet fetched), true/false once /config is loaded
let requireByok = null;
let hasServerKey = null;
let byokKey = null;
let configPromise = null;

// Helpers
function setActive(buttons, target) {
  buttons.forEach(b => b.classList.remove('pill-active'));
  target.classList.add('pill-active');
}

function setRangeValue(inputEl, value) {
  inputEl.value = String(value);
  inputEl.dispatchEvent(new Event('input', { bubbles: true }));
  inputEl.dispatchEvent(new Event('change', { bubbles: true }));
}

function collectExtraInstructions() {
  const req = (instrRequired?.value || '').trim();
  const q = (instrQuestions?.value || '').trim();
  const g = (instrGoal?.value || '').trim();
  const parts = [];
  if (req) parts.push(`Kötelező tartalom:\n${req}`);
  if (q) parts.push(`Megválaszolandó kérdések:\n${q}`);
  if (g) parts.push(`Cél / célközönség:\n${g}`);
  const txt = parts.join("\n\n").trim();
  return txt.length ? txt : null;
}

function hideNotify() {
  if (notify) notify.classList.add('hidden');
  if (notifyTimeout) {
    clearTimeout(notifyTimeout);
    notifyTimeout = null;
  }
}

function showNotify(text, type = 'info', durationMs = 4000) {
  if (!notify || !notifyInner || !notifyText) return;
  notifyText.textContent = text;
  let extra = ' border-zinc-700 text-zinc-200';
  if (type === 'success') extra = ' border-green-600 text-green-200';
  else if (type === 'warning') extra = ' border-yellow-600 text-yellow-200';
  else if (type === 'error') extra = ' border-red-600 text-red-200';
  notifyInner.className = 'px-4 py-3 rounded-md border shadow-lg bg-zinc-900/90' + extra;
  notify.classList.remove('hidden');
  if (notifyTimeout) clearTimeout(notifyTimeout);
  notifyTimeout = setTimeout(() => {
    hideNotify();
  }, durationMs);
}

function resetUI() {
  structureEl.innerHTML = '';
  statsModel.textContent = 'HunBook-Agent_v0.6';
  statsTime.textContent = '0.00s';
  statsSpeed.textContent = '0.00 tok/s';
  statsTokens.textContent = '0';
  accumulatingContent = '';
  sectionBuffers.clear();
  sectionStatusEls.clear();
  totalSections = 0;
  completedSections = 0;
  inProgress = false;
  // stop timer if running
  if (timerIntervalId) {
    clearInterval(timerIntervalId);
    timerIntervalId = null;
  }
  timerStartMs = null;
  if (progressOuter) {
    progressOuter.classList.add('hidden');
  }
  if (progressInner) {
    progressInner.style.width = '0%';
  }
  stopBtn.disabled = true;
  // Always restore Generate button to idle state
  if (generateBtn) {
    generateBtn.disabled = false;
    generateBtn.textContent = 'Generálás';
  }
  if (downloadTxt) downloadTxt.disabled = true;
  if (downloadPdf) downloadPdf.disabled = true;
  hideNotify();
}

function ensureSectionContainer(title) {
  const id = `sec-${btoa(unescape(encodeURIComponent(title))).replace(/=/g, '')}`;
  let el = document.getElementById(id);
  if (!el) {
    el = document.createElement('div');
    el.id = id;
    el.className = 'bg-zinc-900/60 border border-zinc-800 rounded-lg';
    el.innerHTML = `
      <div class="px-4 py-3 border-b border-zinc-800 flex items-center justify-between gap-2">
        <div class="flex items-center gap-2">
          <div class="w-1.5 h-1.5 rounded-full bg-indigo-600"></div>
          <h3 class="text-sm font-medium text-zinc-200">${title}</h3>
        </div>
        <div class="flex items-center gap-2 text-xs text-zinc-400">
          <div class="spinner w-3 h-3 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin"></div>
          <span class="status-text">Készül…</span>
        </div>
      </div>
      <div class="px-4 py-3 text-sm prose prose-invert max-w-none hidden"></div>
    `;
    structureEl.appendChild(el);
    const statusEl = el.querySelector('.status-text');
    const spinnerEl = el.querySelector('.spinner');
    sectionStatusEls.set(title, { container: el, statusEl, spinnerEl });
  }
  return el;
}

function setSectionStatus(title, status) {
  ensureSectionContainer(title);
  const refs = sectionStatusEls.get(title);
  if (!refs) return;
  const { statusEl, spinnerEl } = refs;
  if (status === 'in_progress') {
    spinnerEl.classList.remove('hidden');
    spinnerEl.classList.add('animate-spin');
    statusEl.textContent = 'Készül…';
    statusEl.className = 'status-text text-xs text-zinc-400';
  } else if (status === 'done') {
    spinnerEl.classList.remove('animate-spin');
    spinnerEl.classList.add('hidden');
    statusEl.textContent = 'Kész';
    statusEl.className = 'status-text text-xs text-green-400';
  } else if (status === 'aborted') {
    spinnerEl.classList.remove('animate-spin');
    spinnerEl.classList.add('hidden');
    statusEl.textContent = 'Megszakítva';
    statusEl.className = 'status-text text-xs text-yellow-400';
  } else if (status === 'error') {
    spinnerEl.classList.remove('animate-spin');
    spinnerEl.classList.add('hidden');
    statusEl.textContent = 'Hiba';
    statusEl.className = 'status-text text-xs text-red-400';
  } else {
    // pending
    spinnerEl.classList.add('hidden');
    statusEl.textContent = 'Várakozik…';
    statusEl.className = 'status-text text-xs text-zinc-500';
  }
}

function updateProgress() {
  if (!progressOuter || !progressInner) return;
  if (!inProgress || totalSections <= 0) {
    progressOuter.classList.add('hidden');
    progressInner.style.width = '0%';
    return;
  }
  progressOuter.classList.remove('hidden');
  const pct = Math.min(100, Math.round((completedSections / totalSections) * 100));
  progressInner.style.width = `${pct}%`;
}

function flattenStructure(struct) {
  // Returns array of {title, prompt}; depth-first leaves
  const items = [];
  function walk(node) {
    for (const [title, val] of Object.entries(node || {})) {
      if (typeof val === 'string') {
        items.push({ title, prompt: val });
      } else if (val && typeof val === 'object') {
        walk(val);
      }
    }
  }
  walk(struct);
  return items;
}

async function postJSON(path, body, signal, extraHeaders) {
  const r = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: Object.assign(
      { 'Content-Type': 'application/json' },
      byokKey ? { 'Authorization': `Bearer ${byokKey}` } : {},
      extraHeaders || {}
    ),
    body: JSON.stringify(body),
    signal,
    cache: 'no-store',
    credentials: 'omit',
    mode: 'cors',
  });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(`HTTP ${r.status}: ${t}`);
  }
  return r;
}

function humanTime(seconds) {
  return `${(seconds || 0).toFixed(2)}s`;
}

function humanTimeFromMs(ms) {
  return `${((ms || 0) / 1000).toFixed(2)}s`;
}

function startGlobalTimer() {
  // Start or restart timer
  if (timerIntervalId) {
    clearInterval(timerIntervalId);
    timerIntervalId = null;
  }
  timerStartMs = performance.now();
  const update = () => {
    if (timerStartMs != null) {
      const elapsed = performance.now() - timerStartMs;
      statsTime.textContent = humanTimeFromMs(elapsed);
    }
  };
  update();
  timerIntervalId = setInterval(update, 100);
}

function stopGlobalTimer() {
  if (timerIntervalId) {
    clearInterval(timerIntervalId);
    timerIntervalId = null;
  }
}

function estimateWordCount() {
  let total = 0;
  for (const txt of sectionBuffers.values()) {
    if (!txt) continue;
    const words = txt
      .replace(/\s+/g, ' ')
      .trim()
      .split(' ')
      .filter(Boolean).length;
    total += words;
  }
  return total;
}

function updateStatsFromEvent(ev) {
  const s = ev.statistics || {};
  // Always display our agent name
  statsModel.textContent = 'HunBook-Agent_v0.6';
  // Do not overwrite the global timer here; it's updated continuously
  const out = s.output_tokens || 0;
  const t = s.output_time || 0.0001;
  statsSpeed.textContent = `${(out / t).toFixed(2)} tok/s`;
  // Show estimated total word count across accumulated sections
  statsTokens.textContent = `${estimateWordCount()}`;
}

async function generate() {
  const subject = subjectEl.value.trim();
  if (!subject) {
    alert('Adj meg egy témát.');
    return;
  }

  // Wait config if still loading, then gate BYOK only if backend requires it
  try { await configPromise; } catch {}
  if (requireByok === true && !byokKey) {
    showNotify('A generálás API-kulcs nélkül nem indítható. A menüsorban az "API-kulcs (BYOK)" gombra kattintva szerezd be és állítsd be a kulcsot.', 'warning', 6000);
    openByok();
    return;
  }

  // Quóta előellenőrzés
  const q = await refreshQuota();
  if (q && Number(q.remaining) <= 0) {
    showNotify('Elérted a mai kvótát. Kérjük, próbáld meg holnap újra.', 'warning', 6000);
    return;
  }

  resetUI();
  generateBtn.disabled = true;
  generateBtn.textContent = 'Generálás folyamatban…';

  try {
    // Prepare controller early so Stop can cancel /api/structure as well
    controller = new AbortController();
    stopBtn.disabled = false;
    // Start global timer at the beginning of generation
    startGlobalTimer();
    // Warm up backend to avoid Render Free cold-start CORS/preflight quirks
    try {
      const warm = await fetch(`${API_BASE}/healthz`, { method: 'GET', mode: 'cors', cache: 'no-store', credentials: 'omit' });
      if (!warm.ok) throw new Error('warmup');
    } catch (_) {
      // small backoff then retry once
      await new Promise(r => setTimeout(r, 800));
      try { await fetch(`${API_BASE}/healthz`, { method: 'GET', mode: 'cors', cache: 'no-store', credentials: 'omit' }); } catch {}
    }
    // Validate API key availability before starting expensive calls
    try {
      const headers = Object.assign({}, byokKey ? { 'Authorization': `Bearer ${byokKey}` } : {});
      const vr = await fetch(`${API_BASE}/api/key/validate`, {
        method: 'GET',
        headers,
        cache: 'no-store',
        credentials: 'omit',
        mode: 'cors',
      });
      if (!vr.ok) {
        const t = await vr.text().catch(() => '');
        throw new Error(`HTTP ${vr.status}: ${t}`);
      }
    } catch (err) {
      // If BYOK is required or server key is missing/invalid, prompt for key and abort
      showNotify('Adj meg érvényes Groq API-kulcsot (BYOK) a generáláshoz.', 'warning', 6000);
      openByok();
      throw err; // routed to outer catch, which resets UI safely
    }
    // 1) Structure
    const extraTxt = collectExtraInstructions();
    const structureReq = {
      subject,
      params: {
        model: selectedModel,
        temperature: Number(temperatureEl.value),
        top_p: Number(topPEl.value),
        max_tokens: 8000,
        language: 'hu',
        include_intro: false,
        include_conclusion: false,
        depth: 2,
        extra_instructions: extraTxt || undefined,
      },
    };
    const structureRes = await postJSON('/api/structure', structureReq, controller.signal).then(r => r.json());
    // Quota consumed server-side at structure start; refresh UI
    await refreshQuota();

    // Flatten and render skeletons (titles only)
    const leaves = flattenStructure(structureRes.structure);
    totalSections = leaves.length;
    completedSections = 0;
    for (const item of leaves) {
      ensureSectionContainer(item.title);
      setSectionStatus(item.title, 'pending');
      sectionBuffers.set(item.title, '');
    }
    inProgress = true;
    updateProgress();
    // Enable Stop only once structure is ready and streaming will start
    stopBtn.disabled = false;

    // 2) Stream sections
    const streamReq = {
      structure: structureRes.structure,
      params: {
        model: selectedModel,
        temperature: Number(temperatureEl.value),
        top_p: Number(topPEl.value),
        max_tokens: 8000,
        language: 'hu',
        style: selectedStyle,
        reading_level: selectedLevel,
        target_length: Number(targetLenEl.value),
        parallelism: 1,
        extra_instructions: extraTxt || undefined,
      },
    };

    // Reuse the same controller for the streaming phase
    if (downloadTxt) downloadTxt.disabled = true;
    if (downloadPdf) downloadPdf.disabled = true;
    const resp = await fetch(`${API_BASE}/api/sections/stream`, {
      method: 'POST',
      headers: Object.assign(
        { 'Content-Type': 'application/json' },
        byokKey ? { 'Authorization': `Bearer ${byokKey}` } : {}
      ),
      body: JSON.stringify(streamReq),
      signal: controller.signal,
      cache: 'no-store',
      credentials: 'omit',
      mode: 'cors',
    });
    // If backend returned non-OK (e.g., 401/429/500), surface the error immediately
    if (!resp.ok || !resp.body) {
      let t = '';
      try { t = await resp.text(); } catch {}
      throw new Error(`HTTP ${resp.status}: ${t}`);
    }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buf = '';
    // Watchdog: abort if no data arrives for a while (e.g., network stalls)
    let lastActivity = Date.now();
    const STALL_MS = 45000; // 45s without any data => abort
    const watchdog = setInterval(() => {
      if (!inProgress) return;
      if (Date.now() - lastActivity > STALL_MS) {
        console.warn('Stream stalled, aborting');
        try { controller?.abort(); } catch {}
      }
    }, 5000);
    let finishedNormally = false;

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      lastActivity = Date.now();
      buf += decoder.decode(value, { stream: true });
      let lines = buf.split('\n');
      buf = lines.pop() || '';
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const ev = JSON.parse(line);
          if (ev.type === 'section_start') {
            ensureSectionContainer(ev.title);
            setSectionStatus(ev.title, 'in_progress');
          } else if (ev.type === 'token') {
            // Do not render live text; only accumulate for download
            const curr = sectionBuffers.get(ev.title) || '';
            sectionBuffers.set(ev.title, curr + ev.delta);
          } else if (ev.type === 'stats') {
            updateStatsFromEvent(ev);
          } else if (ev.type === 'rate_limit_wait') {
            setSectionWait(ev.title, ev.wait, ev.message);
          } else if (ev.type === 'section_end') {
            setSectionStatus(ev.title, 'done');
            completedSections += 1;
            updateProgress();
          } else if (ev.type === 'done') {
            finishedNormally = true;
            // Build accumulatingContent
            accumulatingContent = '';
            for (const [title, txt] of sectionBuffers.entries()) {
              accumulatingContent += `# ${title}\n\n${txt}\n\n`;
            }
            // Force-complete any sections not explicitly closed to avoid UI stuck on last item
            for (const [title, refs] of sectionStatusEls.entries()) {
              const stEl = refs?.statusEl;
              if (stEl && stEl.textContent !== 'Kész') {
                setSectionStatus(title, 'done');
              }
            }
            inProgress = false;
            updateProgress();
            stopBtn.disabled = true;
            stopGlobalTimer();
            if (downloadTxt) downloadTxt.disabled = false;
            if (downloadPdf) downloadPdf.disabled = false;
            showNotify('A generálás befejeződött. Letöltésre kész.', 'success');
            await refreshQuota();
          } else if (ev.type === 'error') {
            console.error('Stream error:', ev.message);
            inProgress = false;
            stopBtn.disabled = true;
            stopGlobalTimer();
            if (downloadTxt) downloadTxt.disabled = true;
            if (downloadPdf) downloadPdf.disabled = true;
            if (String(ev.message || '').toLowerCase().includes('api key')) {
              showNotify('Adj meg Groq API-kulcsot (BYOK) a generáláshoz.', 'warning');
              openByok();
            } else {
              showNotify('Hiba történt, kérlek próbáld újra', 'error');
            }
            await refreshQuota();
          } else if (ev.type === 'aborted') {
            // Backend-side cancellation
            inProgress = false;
            stopBtn.disabled = true;
            stopGlobalTimer();
            // Ensure downloads remain disabled and UI resets
            if (downloadTxt) downloadTxt.disabled = true;
            if (downloadPdf) downloadPdf.disabled = true;
            resetUI();
            showNotify('A generálás megszakítva.', 'warning');
            await refreshQuota();
          }
        } catch (e) {
          console.warn('Bad NDJSON line', line, e);
        }
      }
    }
    // If the stream ended without sending a 'done' or explicit error, treat as network stall
    if (!finishedNormally) {
      inProgress = false;
      updateProgress();
      stopBtn.disabled = true;
      stopGlobalTimer();
      if (downloadTxt) downloadTxt.disabled = true;
      if (downloadPdf) downloadPdf.disabled = true;
      showNotify('A kapcsolat megszakadt. Próbáld újra.', 'warning');
      await refreshQuota();
    }
  } catch (e) {
    console.error(e);
    if (e.name === 'AbortError') {
      // Aborted by user: reset immediately, then notify
      resetUI();
      showNotify('A generálás megszakítva.', 'warning');
      await refreshQuota();
    } else {
      const msg = (e && e.message) ? e.message : '';
      if (msg.includes('HTTP 429')) {
        if (msg.toLowerCase().includes('quota') || msg.toLowerCase().includes('daily quota')) {
          showNotify('Elérted a mai kvótát. Kérjük, próbáld meg holnap újra.', 'warning', 6000);
        } else {
          showNotify('Elérted a napi keretet ennél a modellnél. Válts 120B-re vagy próbáld később.', 'warning', 6000);
        }
        await refreshQuota();
      } else if (msg.includes('HTTP 401') || msg.toLowerCase().includes('api key')) {
        showNotify('Adj meg Groq API-kulcsot (BYOK) a generáláshoz.', 'warning');
        openByok();
      } else {
        showNotify('Hiba történt, kérlek próbáld újra', 'error');
      }
      // Biztonság kedvéért frissítsünk kvótát minden hibánál
      await refreshQuota();
      for (const [title, refs] of sectionStatusEls.entries()) {
        const stEl = refs.statusEl;
        if (stEl && stEl.textContent !== 'Kész') {
          setSectionStatus(title, 'error');
        }
      }
      if (downloadTxt) downloadTxt.disabled = true;
      if (downloadPdf) downloadPdf.disabled = true;
      inProgress = false;
      updateProgress();
      stopGlobalTimer();
    }
  } finally {
    try { clearInterval(watchdog); } catch {}
    generateBtn.disabled = false;
    generateBtn.textContent = 'Generálás';
    stopBtn.disabled = true;
    controller = null;
  }
}

// Event bindings
modeToggle.addEventListener('click', () => {
  const hidden = advancedPanel.classList.toggle('hidden');
  modeToggle.textContent = hidden ? 'Haladó mód' : 'Egyszerű mód';
});

themeToggle.addEventListener('click', () => {
  const html = document.documentElement;
  const isDark = html.classList.toggle('dark');
  themeToggle.textContent = isDark ? '☾ Sötét' : '☼ Világos';
});

// Toggle extra instructions panel
if (extraToggle && extraPanel) {
  extraToggle.addEventListener('click', () => {
    const hidden = extraPanel.classList.toggle('hidden');
    extraToggle.textContent = hidden ? 'Megnyitás' : 'Bezárás';
  });
}

// BYOK helpers
function openByok() {
  if (byokOverlay) byokOverlay.classList.remove('hidden');
  if (byokModal) byokModal.classList.remove('hidden');
  if (byokInput && byokKey) byokInput.value = byokKey;
  updateByokStatus();
}
function closeByok() {
  if (byokOverlay) byokOverlay.classList.add('hidden');
  if (byokModal) byokModal.classList.add('hidden');
}
function updateByokStatus() {
  if (!byokStatus) return;
  byokStatus.textContent = byokKey ? 'Kulcs beállítva' : 'Nincs kulcs';
}
function loadByok() {
  try {
    const saved = localStorage.getItem('byok_key');
    if (saved) byokKey = saved;
  } catch {}
  updateByokStatus();
}
async function loadConfig() {
  try {
    const r = await fetch(`${API_BASE}/config`);
    if (r.ok) {
      const cfg = await r.json();
      requireByok = !!cfg.require_byok;
      hasServerKey = !!cfg.has_server_key;
      // If server lacks a key, enforce BYOK client-side too
      if (hasServerKey === false) requireByok = true;
    }
  } catch {}
}

// BYOK bindings
if (byokOpen) byokOpen.addEventListener('click', openByok);
if (byokClose) byokClose.addEventListener('click', closeByok);
if (byokOverlay) byokOverlay.addEventListener('click', closeByok);
if (byokShow && byokInput) byokShow.addEventListener('change', () => {
  byokInput.type = byokShow.checked ? 'text' : 'password';
});
if (byokSave) byokSave.addEventListener('click', () => {
  const val = (byokInput?.value || '').trim();
  if (!val) {
    // Treat empty save as clear
    byokKey = null;
    try { localStorage.removeItem('byok_key'); } catch {}
    updateByokStatus();
    showNotify('API-kulcs törölve.', 'success');
    closeByok();
    return;
  }
  byokKey = val;
  try {
    if (byokRemember?.checked) {
      localStorage.setItem('byok_key', byokKey);
    } else {
      localStorage.removeItem('byok_key');
    }
  } catch {}
  updateByokStatus();
  showNotify('API-kulcs elmentve.', 'success');
  closeByok();
  refreshQuota();
});
if (byokClear) byokClear.addEventListener('click', () => {
  byokKey = null;
  try { localStorage.removeItem('byok_key'); } catch {}
  if (byokInput) byokInput.value = '';
  updateByokStatus();
  showNotify('API-kulcs törölve.', 'success');
  refreshQuota();
});

Array.from(document.querySelectorAll('[data-model]')).forEach(btn => {
  btn.addEventListener('click', () => {
    const group = document.querySelectorAll('[data-model]');
    setActive(group, btn);
    selectedModel = btn.getAttribute('data-model');
  });
});

Array.from(document.querySelectorAll('[data-style]')).forEach(btn => {
  btn.addEventListener('click', () => {
    const group = document.querySelectorAll('[data-style]');
    setActive(group, btn);
    selectedStyle = btn.getAttribute('data-style');
  });
});

Array.from(document.querySelectorAll('[data-level]')).forEach(btn => {
  btn.addEventListener('click', () => {
    const group = document.querySelectorAll('[data-level]');
    setActive(group, btn);
    selectedLevel = btn.getAttribute('data-level');
  });
});

function bindRange(input, out) {
  const update = () => (out.textContent = Number(input.value).toFixed(input.step && input.step.includes('.') ? 2 : 0));
  input.addEventListener('input', update);
  update();
}

bindRange(temperatureEl, temperatureVal);
bindRange(topPEl, topPVal);
bindRange(targetLenEl, targetLenVal);

generateBtn.addEventListener('click', generate);

stopBtn.addEventListener('click', () => {
  if (controller) {
    controller.abort();
  }
});

// ----- Legal & Contact modals wiring -----
function openModal(overlayEl, modalEl) {
  if (overlayEl) overlayEl.classList.remove('hidden');
  if (modalEl) modalEl.classList.remove('hidden');
}
function closeModal(overlayEl, modalEl) {
  if (overlayEl) overlayEl.classList.add('hidden');
  if (modalEl) modalEl.classList.add('hidden');
}

// Privacy
if (openPrivacy) openPrivacy.addEventListener('click', () => openModal(privacyOverlay, privacyModal));
if (privacyClose) privacyClose.addEventListener('click', () => closeModal(privacyOverlay, privacyModal));
if (privacyOverlay) privacyOverlay.addEventListener('click', () => closeModal(privacyOverlay, privacyModal));

// Terms
if (openTerms) openTerms.addEventListener('click', () => openModal(termsOverlay, termsModal));
if (termsClose) termsClose.addEventListener('click', () => closeModal(termsOverlay, termsModal));
if (termsOverlay) termsOverlay.addEventListener('click', () => closeModal(termsOverlay, termsModal));

// Impresszum
if (openImpressum) openImpressum.addEventListener('click', () => openModal(impressumOverlay, impressumModal));
if (impressumClose) impressumClose.addEventListener('click', () => closeModal(impressumOverlay, impressumModal));
if (impressumOverlay) impressumOverlay.addEventListener('click', () => closeModal(impressumOverlay, impressumModal));

// Contact
if (openContact) openContact.addEventListener('click', () => openModal(contactOverlay, contactModal));
if (contactClose) contactClose.addEventListener('click', () => closeModal(contactOverlay, contactModal));
if (contactOverlay) contactOverlay.addEventListener('click', () => closeModal(contactOverlay, contactModal));
if (contactSubmit) contactSubmit.addEventListener('click', () => {
  const to = 'jozsef.molnos@tris-universe.com';
  const name = (contactName?.value || '').trim();
  const email = (contactEmail?.value || '').trim();
  const message = (contactMessage?.value || '').trim();
  const subject = 'Kapcsolat – HunBook';
  const lines = [];
  if (name) lines.push(`Név: ${name}`);
  if (email) lines.push(`Email: ${email}`);
  if (message) lines.push('', message);
  const mailto = `mailto:${to}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(lines.join('\n'))}`;
  window.location.href = mailto;
  closeModal(contactOverlay, contactModal);
});

// Templates: simple mode
const simpleTemplatesEl = document.getElementById('simpleTemplates');
if (simpleTemplatesEl) {
  simpleTemplatesEl.addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-template="simple"][data-subject]');
    if (!btn) return;
    const subj = btn.getAttribute('data-subject') || '';
    subjectEl.value = subj;
  });
}

// Templates: advanced mode with recommended settings
const advancedTemplatesEl = document.getElementById('advancedTemplates');
if (advancedTemplatesEl) {
  advancedTemplatesEl.addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-template="advanced"]');
    if (!btn) return;

    // Ensure advanced panel is visible
    if (advancedPanel.classList.contains('hidden')) {
      modeToggle.click();
    }

    // Subject
    const subj = btn.getAttribute('data-subject') || '';
    subjectEl.value = subj;

    // Style
    const style = btn.getAttribute('data-style');
    if (style) {
      const styleBtn = document.querySelector(`[data-style="${CSS.escape(style)}"]`);
      if (styleBtn) {
        const group = document.querySelectorAll('[data-style]');
        setActive(group, styleBtn);
        selectedStyle = style;
      }
    }

    // Reading level
    const level = btn.getAttribute('data-level');
    if (level) {
      const levelBtn = document.querySelector(`[data-level="${CSS.escape(level)}"]`);
      if (levelBtn) {
        const group = document.querySelectorAll('[data-level]');
        setActive(group, levelBtn);
        selectedLevel = level;
      }
    }

    // Sliders
    const t = btn.getAttribute('data-temp');
    if (t) setRangeValue(temperatureEl, parseFloat(t));
    const tp = btn.getAttribute('data-top-p');
    if (tp) setRangeValue(topPEl, parseFloat(tp));
    const target = btn.getAttribute('data-target');
    if (target) setRangeValue(targetLenEl, parseInt(target));
  });
}

downloadTxt.addEventListener('click', async () => {
  try {
    if (!accumulatingContent) return;
    const r = await postJSON('/api/export/markdown', {
      content: accumulatingContent,
      filename: 'groqbook'
    });
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'groqbook.txt';
    a.click();
    URL.revokeObjectURL(url);
    // Reset UI once download has started
    resetUI();
  } catch (err) {
    console.error(err);
    showNotify('Hiba történt, kérlek próbáld újra', 'error');
  }
});

// Initialize UI state on load (module loaded after DOM)
resetUI();
loadByok();
configPromise = loadConfig();
if (notify) {
  notify.addEventListener('click', hideNotify);
}
refreshQuota();

downloadPdf.addEventListener('click', async () => {
  try {
    if (!accumulatingContent) return;
    const r = await postJSON('/api/export/pdf', {
      content: accumulatingContent,
      filename: 'groqbook'
    });
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'groqbook.pdf';
    a.click();
    URL.revokeObjectURL(url);
    // Reset UI once download has started
    resetUI();
  } catch (err) {
    console.error(err);
    showNotify('Hiba történt, kérlek próbáld újra', 'error');
  }
});
