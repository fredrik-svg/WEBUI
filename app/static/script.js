function buildAddressUrl(address, port, protocol) {
  const proto = (protocol || 'http').replace(/:$/, '');
  const numericPort = Number(port);
  const hasValidPort = Number.isFinite(numericPort) && numericPort > 0;
  const isHttps = proto === 'https';
  const needsPort = hasValidPort && !(
    (isHttps && numericPort === 443) || (!isHttps && numericPort === 80)
  );
  const host = address.includes(':') && !address.startsWith('[') ? `[${address}]` : address;
  const portPart = needsPort ? `:${numericPort}` : '';
  return `${proto}://${host}${portPart}`;
}

const STORAGE_KEYS = {
  model: 'ollama-webui:selected-model',
  ragEnabled: 'ollama-webui:rag-enabled',
  ragTopK: 'ollama-webui:rag-top-k'
};

function getStoredItem(key) {
  try {
    return window.localStorage ? window.localStorage.getItem(key) : null;
  } catch (e) {
    return null;
  }
}

function setStoredItem(key, value) {
  try {
    if (window.localStorage) {
      window.localStorage.setItem(key, value);
    }
  } catch (e) {
    /* ignore */
  }
}

async function fetchAppInfo() {
  const textEl = document.getElementById('connectText');
  const listEl = document.getElementById('connectList');
  if (!textEl || !listEl) return;

  textEl.textContent = 'Hämtar adressinformation…';
  listEl.innerHTML = '';

  try {
    const res = await fetch('/api/info');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    const addresses = Array.isArray(data.addresses) ? data.addresses : [];
    let port = data.port;
    if (port === undefined || port === null) {
      port = window.location.port ? Number(window.location.port) : undefined;
    }
    if (!Number.isFinite(Number(port)) || Number(port) <= 0) {
      port = 8000;
    }
    const proto = window.location.protocol === 'https:' ? 'https' : 'http';

    if (addresses.length === 0) {
      textEl.textContent = 'Hittade inga IP-adresser automatiskt. Kör `hostname -I` på servern för att se adressen.';
      return;
    }

    textEl.textContent = 'Öppna någon av följande adresser i webbläsaren på en annan dator i samma nätverk:';
    for (const addr of addresses) {
      const li = document.createElement('li');
      const url = buildAddressUrl(addr, port, proto);
      const link = document.createElement('a');
      link.href = url;
      link.textContent = url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      li.appendChild(link);
      listEl.appendChild(li);
    }
  } catch (e) {
    textEl.textContent = 'Kunde inte hämta anslutningsinfo. Kontrollera att servern kör och försök igen.';
  }
}

async function fetchModels() {
  const sel = document.getElementById('model');
  sel.innerHTML = '';
  try {
    const res = await fetch('/api/models');
    const data = await res.json();
    const models = data.models || [];
    const preferred = getStoredItem(STORAGE_KEYS.model) || window.DEFAULT_MODEL || 'llama3.2:1b';
    const available = new Set();
    if (models.length === 0) {
      const opt = document.createElement('option');
      opt.value = preferred;
      opt.textContent = preferred + ' (ej installerad än)';
      sel.appendChild(opt);
      available.add(opt.value);
    } else {
      for (const m of models) {
        const opt = document.createElement('option');
        opt.value = m;
        opt.textContent = m;
        sel.appendChild(opt);
        available.add(m);
      }
    }
    if (!available.has(preferred)) {
      const opt = document.createElement('option');
      opt.value = preferred;
      opt.textContent = preferred + ' (standard)';
      sel.appendChild(opt);
    }
    sel.value = preferred;
  } catch (e) {
    const opt = document.createElement('option');
    opt.value = window.DEFAULT_MODEL || 'llama3.2:1b';
    opt.textContent = opt.value + ' (endpoint otillgänglig)';
    sel.appendChild(opt);
    sel.value = opt.value;
  }
}

function renderRagSummary(payload) {
  const docs = Array.isArray(payload?.documents) ? payload.documents : [];
  const stats = payload?.stats || {};
  const chunkCount = Number(stats.chunk_count) || 0;
  const toggleEl = document.getElementById('ragToggle');
  const summaryEl = document.getElementById('ragSummaryText');

  if (summaryEl) {
    if (docs.length === 0) {
      summaryEl.textContent = 'Ingen text har lagts till ännu.';
    } else {
      const chunkLabel = chunkCount === 1 ? 'utdrag' : 'utdrag';
      summaryEl.textContent = `Texter: ${docs.length} • ${chunkCount} ${chunkLabel}.`;
    }
  }

  if (toggleEl) {
    if (docs.length === 0) {
      toggleEl.checked = false;
      toggleEl.disabled = true;
      setStoredItem(STORAGE_KEYS.ragEnabled, '0');
    } else {
      toggleEl.disabled = false;
      const stored = getStoredItem(STORAGE_KEYS.ragEnabled);
      if (stored !== null) {
        toggleEl.checked = stored === '1';
      }
    }
  }

  return { count: docs.length, chunkCount };
}

async function fetchRagSummary() {
  const summaryEl = document.getElementById('ragSummaryText');
  if (summaryEl) {
    summaryEl.textContent = 'Hämtar statistik…';
  }
  try {
    const res = await fetch('/api/rag/docs');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    const summary = renderRagSummary(data);
    if (summary.count === 0 && summaryEl) {
      summaryEl.textContent = 'Ingen text har lagts till ännu.';
    }
  } catch (e) {
    if (summaryEl) {
      summaryEl.textContent = 'Kunde inte hämta kunskapsbasen: ' + e.message;
    }
    const toggleEl = document.getElementById('ragToggle');
    if (toggleEl) {
      toggleEl.checked = false;
      toggleEl.disabled = true;
    }
  }
}

function renderRagResults(items) {
  const wrap = document.getElementById('ragResults');
  if (!wrap) return;
  const list = wrap.querySelector('ol');
  if (!list) return;
  list.innerHTML = '';
  if (!Array.isArray(items) || items.length === 0) {
    wrap.hidden = true;
    return;
  }
  items.forEach((item, idx) => {
    const li = document.createElement('li');
    const header = document.createElement('strong');
    let label = `Utdrag ${idx + 1}`;
    if (typeof item.score === 'number' && !Number.isNaN(item.score)) {
      const clamped = Math.max(-1, Math.min(1, item.score));
      const percent = Math.round(clamped * 1000) / 10;
      label += ` • likhet ${percent}%`;
    }
    header.textContent = label;
    const content = document.createElement('div');
    content.textContent = item.text || '';
    li.appendChild(header);
    li.appendChild(content);
    list.appendChild(li);
  });
  wrap.hidden = false;
}

function addMsg(role, text) {
  const wrap = document.getElementById('history');
  const div = document.createElement('div');
  div.className = 'msg ' + (role === 'user' ? 'user' : 'assistant');
  div.textContent = text;
  wrap.appendChild(div);
  div.scrollIntoView({ behavior: 'smooth', block: 'end' });
}

async function sendPrompt() {
  const ta = document.getElementById('prompt');
  const temperature = parseFloat(document.getElementById('temperature').value);
  const model = document.getElementById('model').value || window.DEFAULT_MODEL || 'llama3.2:1b';
  const ragToggleEl = document.getElementById('ragToggle');
  const ragTopKInput = document.getElementById('ragTopK');
  let ragTopK = parseInt(ragTopKInput?.value || '3', 10);
  if (!Number.isFinite(ragTopK) || ragTopK < 1) {
    ragTopK = 3;
  }
  if (ragTopK > 10) ragTopK = 10;
  if (ragTopKInput) {
    ragTopKInput.value = String(ragTopK);
  }
  const useRag = !!(ragToggleEl && !ragToggleEl.disabled && ragToggleEl.checked);
  const userText = ta.value.trim();
  if (!userText) return;
  addMsg('user', userText);
  ta.value = '';

  const body = {
    model,
    messages: [
      // System på svenska för att förstärka svensk kontext
      { role: 'system', content: 'Du är en hjälpsam AI som svarar på flytande svenska. Var tydlig och kortfattad.' },
      { role: 'user', content: userText }
    ],
    options: { temperature }
  };
  if (useRag) {
    body.use_rag = true;
    body.rag_top_k = ragTopK;
  }

  const btn = document.getElementById('send');
  btn.disabled = true;
  btn.textContent = 'Tänker…';
  renderRagResults([]);
  try {
    const res = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || ('HTTP ' + res.status));
    }
    const data = await res.json();
    const text = data?.message?.content || '[Inget svar]';
    addMsg('assistant', text);
    if (useRag || Array.isArray(data?.rag_context)) {
      renderRagResults(data?.rag_context || []);
    } else {
      renderRagResults([]);
    }
  } catch (e) {
    addMsg('assistant', 'Fel: ' + e.message + '\nTips: säkerställ att Ollama kör och att modellen är hämtad.');
    renderRagResults([]);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Skicka';
  }
}

const sendBtn = document.getElementById('send');
if (sendBtn) sendBtn.addEventListener('click', sendPrompt);

const promptEl = document.getElementById('prompt');
if (promptEl) {
  promptEl.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') sendPrompt();
  });
}

const refreshBtn = document.getElementById('refreshModels');
if (refreshBtn) refreshBtn.addEventListener('click', fetchModels);

const modelSelect = document.getElementById('model');
if (modelSelect) {
  modelSelect.addEventListener('change', (e) => {
    setStoredItem(STORAGE_KEYS.model, e.target.value);
  });
}

const ragToggleElInit = document.getElementById('ragToggle');
if (ragToggleElInit) {
  const stored = getStoredItem(STORAGE_KEYS.ragEnabled);
  if (stored !== null) {
    ragToggleElInit.checked = stored === '1';
  }
  ragToggleElInit.addEventListener('change', (e) => {
    setStoredItem(STORAGE_KEYS.ragEnabled, e.target.checked ? '1' : '0');
  });
}

const ragTopKInput = document.getElementById('ragTopK');
if (ragTopKInput) {
  const storedTopK = parseInt(getStoredItem(STORAGE_KEYS.ragTopK) || '', 10);
  if (Number.isFinite(storedTopK) && storedTopK >= 1) {
    const clamped = Math.min(10, storedTopK);
    ragTopKInput.value = String(clamped);
  }
  ragTopKInput.addEventListener('change', () => {
    let value = parseInt(ragTopKInput.value, 10);
    if (!Number.isFinite(value) || value < 1) value = 3;
    if (value > 10) value = 10;
    ragTopKInput.value = String(value);
    setStoredItem(STORAGE_KEYS.ragTopK, String(value));
  });
}

document.getElementById('endpoint').textContent = (window.location.origin + '/api').replace('/api','/');
renderRagResults([]);
fetchModels();
fetchAppInfo();
fetchRagSummary();


// --- Whisper inspelning ---
let mediaRecorder;
let chunks = [];
let recording = false;

async function startRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaRecorder = new MediaRecorder(stream);
    chunks = [];
    mediaRecorder.ondataavailable = e => { if (e.data.size > 0) chunks.push(e.data); };
    mediaRecorder.onstop = sendAudioForTranscription;
    mediaRecorder.start();
    recording = true;
    document.getElementById('micBtn').classList.add('recording');
  } catch (e) {
    addMsg('assistant', 'Kunde inte starta mikrofon: ' + e.message);
  }
}

function stopRecording() {
  if (mediaRecorder && recording) {
    mediaRecorder.stop();
    recording = false;
    document.getElementById('micBtn').classList.remove('recording');
  }
}

async function sendAudioForTranscription() {
  const blob = new Blob(chunks, { type: 'audio/webm' });
  const form = new FormData();
  form.append('audio', blob, 'speech.webm');
  try {
    const res = await fetch('/api/transcribe', { method: 'POST', body: form });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    const text = data.text || '';
    if (text) {
      const ta = document.getElementById('prompt');
      ta.value = (ta.value ? (ta.value + ' ') : '') + text;
    } else {
      addMsg('assistant', 'Ingen text hittades i inspelningen.');
    }
  } catch (e) {
    addMsg('assistant', 'Transkriberingsfel: ' + e.message);
  }
}

const micBtn = document.getElementById('micBtn');
micBtn.addEventListener('mousedown', startRecording);
micBtn.addEventListener('mouseup', stopRecording);
micBtn.addEventListener('mouseleave', () => { if (recording) stopRecording(); });
micBtn.addEventListener('touchstart', (e) => { e.preventDefault(); startRecording(); });
micBtn.addEventListener('touchend', (e) => { e.preventDefault(); stopRecording(); });


// --- TTS (browser först, server fallback) ---
function speakBrowser(text) {
  if (!('speechSynthesis' in window)) return false;
  const utter = new SpeechSynthesisUtterance(text);
  // välj svensk röst om möjligt
  const voices = speechSynthesis.getVoices();
  const sv = voices.find(v => (v.lang && v.lang.toLowerCase().startsWith('sv')) || /swedish|svenska/i.test(v.name));
  if (sv) utter.voice = sv;
  utter.lang = sv?.lang || 'sv-SE';
  speechSynthesis.speak(utter);
  return true;
}

async function downloadServerTTS(text) {
  try {
    const res = await fetch('/api/tts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text, rate: 180, voice: 'sv' }) });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'svar_sv.wav';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (e) {
    addMsg('assistant', 'Kunde inte skapa ljudfil: ' + e.message);
  }
}

let lastAssistantText = '';

// Hooka in i addMsg för att spara/säga upp svar
const _origAddMsg = addMsg;
addMsg = function(role, text) {
  _origAddMsg(role, text);
  if (role === 'assistant') {
    lastAssistantText = text;
    const doTts = document.getElementById('ttsToggle')?.checked;
    if (doTts) {
      if (!speakBrowser(text)) {
        // Om webbläsaren saknar TTS, försök servern & spela upp i sidan
        downloadServerTTS(text);
      }
    }
  }
};

document.getElementById('dlTts').addEventListener('click', () => {
  if (!lastAssistantText) {
    addMsg('assistant', 'Inget svar att läsa upp ännu.');
    return;
  }
  downloadServerTTS(lastAssistantText);
});
