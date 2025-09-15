async function fetchModels() {
  const sel = document.getElementById('model');
  sel.innerHTML = '';
  try {
    const res = await fetch('/api/models');
    const data = await res.json();
    const models = data.models || [];
    if (models.length === 0) {
      // visa standard
      const opt = document.createElement('option');
      opt.value = window.DEFAULT_MODEL || 'llama3.2:1b-instruct';
      opt.textContent = opt.value + ' (ej installerad än)';
      sel.appendChild(opt);
    } else {
      for (const m of models) {
        const opt = document.createElement('option');
        opt.value = m;
        opt.textContent = m;
        sel.appendChild(opt);
      }
    }
  } catch (e) {
    const opt = document.createElement('option');
    opt.value = window.DEFAULT_MODEL || 'llama3.2:1b-instruct';
    opt.textContent = opt.value + ' (endpoint otillgänglig)';
    sel.appendChild(opt);
  }
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
  const model = document.getElementById('model').value || window.DEFAULT_MODEL || 'llama3.2:1b-instruct';
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

  const btn = document.getElementById('send');
  btn.disabled = true;
  btn.textContent = 'Tänker…';
  try {
    const res = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || ('HTTP ' + res.status));
    }
    const data = await res.json();
    const text = data?.message?.content || '[Inget svar]';
    addMsg('assistant', text);
  } catch (e) {
    addMsg('assistant', 'Fel: ' + e.message + '\nTips: säkerställ att Ollama kör och att modellen är hämtad.');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Skicka';
  }
}

document.getElementById('send').addEventListener('click', sendPrompt);
document.getElementById('prompt').addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') sendPrompt();
});
document.getElementById('refreshModels').addEventListener('click', fetchModels);

document.getElementById('endpoint').textContent = (window.location.origin + '/api').replace('/api','/');
fetchModels();


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
