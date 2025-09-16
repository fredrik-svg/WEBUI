function setEndpointDisplay() {
  const endpointEl = document.getElementById('endpoint');
  if (endpointEl) {
    endpointEl.textContent = (window.location.origin + '/api').replace('/api', '/');
  }
}

function setRagStatus(message, type = 'info') {
  const statusEl = document.getElementById('ragStatus');
  if (!statusEl) return;
  statusEl.textContent = message || '';
  statusEl.classList.remove('error', 'success');
  if (type === 'error') statusEl.classList.add('error');
  if (type === 'success') statusEl.classList.add('success');
}

function describeMetadata(meta) {
  if (!meta || typeof meta !== 'object') return '';
  const parts = [];
  const limit = window.RAG_MAX_CHARS || 40000;
  switch (meta.type) {
    case 'url': {
      if (meta.title) {
        parts.push(`Webbsida: ${meta.title}`);
      } else {
        parts.push('Webbsida');
      }
      if (meta.url) {
        parts.push(meta.url);
      }
      break;
    }
    case 'pdf': {
      const name = meta.filename || 'PDF';
      parts.push(`PDF: ${name}`);
      if (meta.pages_used && meta.total_pages) {
        parts.push(`Sidor ${meta.pages_used}/${meta.total_pages}`);
      } else if (meta.total_pages) {
        parts.push(`${meta.total_pages} sidor`);
      }
      break;
    }
    default:
      parts.push('Manuell text');
      break;
  }
  if (meta.original_characters) {
    parts.push(`≈ ${meta.original_characters} tecken före delning`);
  }
  if (meta.truncated) {
    parts.push(`Trunkerad till ${limit} tecken`);
  }
  return parts.join(' • ');
}

function updateSummary(count, chunkCount) {
  const summaryEl = document.getElementById('ragSummaryText');
  if (!summaryEl) return;
  if (!count) {
    summaryEl.textContent = 'Ingen text har lagts till ännu.';
    return;
  }
  const chunkLabel = chunkCount === 1 ? 'utdrag' : 'utdrag';
  summaryEl.textContent = `Texter: ${count} • ${chunkCount} ${chunkLabel}.`;
}

function renderRagDocs(docs, stats) {
  const listEl = document.getElementById('ragList');
  const clearBtn = document.getElementById('clearRag');
  const safeDocs = Array.isArray(docs) ? docs : [];
  const chunkCountRaw = (stats && typeof stats.chunk_count !== 'undefined') ? stats.chunk_count : 0;
  const chunkCount = Number(chunkCountRaw) || 0;

  if (listEl) {
    listEl.innerHTML = '';
    safeDocs.forEach((doc) => {
      const li = document.createElement('li');

      const preview = document.createElement('div');
      preview.className = 'preview';
      preview.textContent = doc.preview || '[Tom text]';
      li.appendChild(preview);

      const meta = document.createElement('div');
      meta.className = 'meta';
      const chunkInfo = document.createElement('span');
      const chunkLabel = (doc.chunks === 1) ? 'utdrag' : 'utdrag';
      chunkInfo.textContent = `${doc.chunks || 0} ${chunkLabel}`;
      meta.appendChild(chunkInfo);
      if (doc.created_at) {
        const created = new Date(doc.created_at);
        if (!Number.isNaN(created.valueOf())) {
          const createdSpan = document.createElement('span');
          createdSpan.textContent = created.toLocaleString('sv-SE');
          meta.appendChild(createdSpan);
        }
      }
      li.appendChild(meta);

      const metaInfo = describeMetadata(doc.metadata);
      if (metaInfo) {
        const source = document.createElement('div');
        source.className = 'meta source';
        source.textContent = metaInfo;
        li.appendChild(source);
      }

      const removeBtn = document.createElement('button');
      removeBtn.type = 'button';
      removeBtn.textContent = 'Ta bort';
      removeBtn.addEventListener('click', () => deleteRagDoc(doc.id));
      li.appendChild(removeBtn);

      listEl.appendChild(li);
    });
  }

  if (clearBtn) {
    clearBtn.disabled = safeDocs.length === 0;
  }

  updateSummary(safeDocs.length, chunkCount);
  return { count: safeDocs.length, chunkCount };
}

async function fetchRagDocs(statusOverride) {
  if (!statusOverride) {
    setRagStatus('Hämtar kunskapsbas…');
  }
  try {
    const res = await fetch('/api/rag/docs');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    const summary = renderRagDocs(data.documents, data.stats);
    if (data && data.embedding_model) {
      const modelEl = document.getElementById('ragModelName');
      if (modelEl) {
        modelEl.textContent = data.embedding_model;
      }
    }
    if (statusOverride && statusOverride.text) {
      setRagStatus(statusOverride.text, statusOverride.type || 'info');
    } else if (summary.count === 0) {
      setRagStatus('Ingen text har lagts till ännu.');
    } else {
      const chunkLabel = summary.chunkCount === 1 ? 'utdrag' : 'utdrag';
      setRagStatus(`Texter: ${summary.count} • ${summary.chunkCount} ${chunkLabel}.`);
    }
  } catch (e) {
    setRagStatus('Kunde inte hämta kunskapsbasen: ' + e.message, 'error');
    const listEl = document.getElementById('ragList');
    if (listEl) listEl.innerHTML = '';
    updateSummary(0, 0);
    const clearBtn = document.getElementById('clearRag');
    if (clearBtn) clearBtn.disabled = true;
  }
}

async function addTextDoc() {
  const textarea = document.getElementById('ragTextInput');
  const btn = document.getElementById('addTextBtn');
  if (!textarea || !btn) return;
  const text = textarea.value.trim();
  if (!text) {
    setRagStatus('Skriv eller klistra in text först.', 'error');
    return;
  }
  setRagStatus('Lägger till text…');
  btn.disabled = true;
  try {
    const res = await fetch('/api/rag/docs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text })
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || ('HTTP ' + res.status));
    }
    textarea.value = '';
    await fetchRagDocs({ text: 'Texten lades till i kunskapsbasen.', type: 'success' });
  } catch (e) {
    setRagStatus('Kunde inte lägga till text: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
  }
}

async function addUrlDoc() {
  const input = document.getElementById('ragUrlInput');
  const btn = document.getElementById('addUrlBtn');
  if (!input || !btn) return;
  const url = input.value.trim();
  if (!url) {
    setRagStatus('Ange en URL först.', 'error');
    return;
  }
  setRagStatus('Hämtar webbsidan…');
  btn.disabled = true;
  try {
    const res = await fetch('/api/rag/docs/url', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url })
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || ('HTTP ' + res.status));
    }
    input.value = '';
    await fetchRagDocs({ text: 'Webbsidan lades till i kunskapsbasen.', type: 'success' });
  } catch (e) {
    setRagStatus('Kunde inte lägga till webbsidan: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
  }
}

async function uploadPdf(event) {
  event.preventDefault();
  const input = document.getElementById('ragPdfInput');
  const form = document.getElementById('ragPdfForm');
  if (!input || !form) return;
  const file = input.files && input.files[0];
  if (!file) {
    setRagStatus('Välj en PDF-fil först.', 'error');
    return;
  }
  setRagStatus('Laddar upp PDF…');
  const submitBtn = form.querySelector('button[type="submit"]');
  if (submitBtn) submitBtn.disabled = true;
  try {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch('/api/rag/docs/pdf', { method: 'POST', body: formData });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || ('HTTP ' + res.status));
    }
    input.value = '';
    await fetchRagDocs({ text: 'PDF-filen lades till i kunskapsbasen.', type: 'success' });
  } catch (e) {
    setRagStatus('Kunde inte lägga till PDF: ' + e.message, 'error');
  } finally {
    if (submitBtn) submitBtn.disabled = false;
  }
}

async function deleteRagDoc(id) {
  if (!id) return;
  try {
    const res = await fetch(`/api/rag/docs/${encodeURIComponent(id)}`, { method: 'DELETE' });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || ('HTTP ' + res.status));
    }
    await fetchRagDocs({ text: 'Texten togs bort.', type: 'success' });
  } catch (e) {
    setRagStatus('Kunde inte ta bort text: ' + e.message, 'error');
  }
}

async function clearRagDocs() {
  if (!window.confirm('Är du säker på att du vill tömma kunskapsbasen?')) {
    return;
  }
  try {
    const res = await fetch('/api/rag/docs', { method: 'DELETE' });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || ('HTTP ' + res.status));
    }
    await fetchRagDocs({ text: 'Kunskapsbasen tömdes.', type: 'success' });
  } catch (e) {
    setRagStatus('Kunde inte rensa kunskapsbasen: ' + e.message, 'error');
  }
}

setEndpointDisplay();
setRagStatus('');
fetchRagDocs();

const addTextButton = document.getElementById('addTextBtn');
if (addTextButton) addTextButton.addEventListener('click', addTextDoc);
const addUrlButton = document.getElementById('addUrlBtn');
if (addUrlButton) addUrlButton.addEventListener('click', addUrlDoc);
const pdfForm = document.getElementById('ragPdfForm');
if (pdfForm) pdfForm.addEventListener('submit', uploadPdf);
const clearBtn = document.getElementById('clearRag');
if (clearBtn) clearBtn.addEventListener('click', clearRagDocs);
