import io
import os
import json
import socket
import tempfile
from functools import lru_cache
from typing import List, Optional, Tuple

import httpx
import pyttsx3
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydub import AudioSegment
from pypdf import PdfReader
from faster_whisper import WhisperModel

from .rag_store import RAGResult, RAGStore

from urllib.parse import urlparse

load_dotenv()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
DEFAULT_MODEL = os.getenv("LLM_MODEL", "llama3.2:1b")
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", "8000"))
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
DEFAULT_RAG_PATH = os.path.join(os.path.expanduser("~"), ".ollama_webui_rag.json")
RAG_STORE_PATH = os.path.abspath(os.path.expanduser(os.getenv("RAG_STORE_PATH", DEFAULT_RAG_PATH)))

MAX_IMPORTED_CHARS = 40_000
MAX_PDF_BYTES = 8 * 1024 * 1024  # 8 MB
MAX_PDF_PAGES = 40

app = FastAPI(title="Raspi Ollama WebUI (sv)")
rag_store = RAGStore(OLLAMA_HOST, EMBED_MODEL, RAG_STORE_PATH)


def _normalize_document_text(text: str, limit: int = MAX_IMPORTED_CHARS) -> Tuple[str, bool]:
    cleaned = (text or "").strip()
    truncated = False
    if len(cleaned) > limit:
        cleaned = cleaned[:limit]
        truncated = True
    return cleaned, truncated


def _html_to_text_and_title(html: str) -> Tuple[str, Optional[str]]:
    soup = BeautifulSoup(html, "html.parser")
    title: Optional[str] = None
    if soup.title and isinstance(soup.title.string, str):
        title = soup.title.string.strip()
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    if soup.head:
        soup.head.decompose()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    clean = "\n".join(line for line in lines if line)
    return clean, title


def _extract_pdf_text(data: bytes, max_pages: int = MAX_PDF_PAGES) -> Tuple[str, int, int]:
    reader = PdfReader(io.BytesIO(data))
    total_pages = len(reader.pages)
    use_pages = min(total_pages, max_pages)
    parts: List[str] = []
    for idx in range(use_pages):
        page = reader.pages[idx]
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        page_text = page_text.strip()
        if page_text:
            parts.append(page_text)
    combined = "\n\n".join(parts).strip()
    return combined, total_pages, use_pages

WHISPER_MODEL_NAME = os.getenv("WHISPER_MODEL", "tiny")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
_whisper_model = None


def _add_address(value, ipv4, ipv6):
    if not value:
        return
    value = value.split('%')[0]  # ta bort ev. interface-suffix från IPv6
    if value in {"0.0.0.0", "::", "::1"}:
        return
    if value.startswith("127."):
        return
    if ":" in value:
        ipv6.add(value)
    else:
        ipv4.add(value)


def get_network_addresses():
    ipv4 = set()
    ipv6 = set()

    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None):
            addr = info[4][0]
            _add_address(addr, ipv4, ipv6)
    except OSError:
        pass

    for target in (("1.1.1.1", 80), ("8.8.8.8", 80)):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(target)
                _add_address(s.getsockname()[0], ipv4, ipv6)
        except OSError:
            continue

    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as s:
            s.connect(("2001:4860:4860::8888", 80))
            _add_address(s.getsockname()[0], ipv4, ipv6)
    except OSError:
        pass

    return sorted(ipv4) + sorted(ipv6)


def get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        # På Raspberry Pi (CPU), använd compute_type=int8 för bäst fart
        _whisper_model = WhisperModel(WHISPER_MODEL_NAME, device="cpu", compute_type=WHISPER_COMPUTE_TYPE)
    return _whisper_model

@app.post("/api/transcribe")
async def transcribe(audio: UploadFile = File(...)):
    # Spara inkommande ljud till temp, konvertera till WAV 16k mono, kör ASR
    try:
        with tempfile.TemporaryDirectory() as td:
            in_path = os.path.join(td, audio.filename)
            out_wav = os.path.join(td, "speech.wav")
            raw = await audio.read()
            with open(in_path, "wb") as f:
                f.write(raw)

            # Konvertera (stöd för webm/ogg/m4a/mp3/wav) -> wav 16k mono
            seg = AudioSegment.from_file(in_path)
            seg = seg.set_channels(1).set_frame_rate(16000)
            seg.export(out_wav, format="wav")

            model = get_whisper_model()
            segments, info = model.transcribe(out_wav, language="sv", beam_size=1)
            text = "".join(s.text for s in segments).strip()
            return {"text": text, "language": info.language, "duration": info.duration}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transkribering misslyckades: {e}")


# Static/templating
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "default_model": DEFAULT_MODEL
    })


@app.get("/rag", response_class=HTMLResponse)
async def rag_page(request: Request):
    return templates.TemplateResponse("rag.html", {
        "request": request,
        "embedding_model": EMBED_MODEL,
        "MAX_IMPORTED_CHARS": MAX_IMPORTED_CHARS,
    })


@app.get("/api/info")
async def app_info():
    return {
        "host": APP_HOST,
        "port": APP_PORT,
        "default_model": DEFAULT_MODEL,
        "ollama_host": OLLAMA_HOST,
        "embedding_model": EMBED_MODEL,
        "addresses": get_network_addresses()
    }

@app.get("/api/models")
async def list_models():
    # Proxy till Ollamas /api/tags
    url = f"{OLLAMA_HOST}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
            # Förenkla svaret
            models = [m.get("name") for m in data.get("models", []) if m.get("name")]
            return {"models": models}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Kunde inte hämta modeller: {e}")


@app.get("/api/rag/docs")
async def list_rag_documents():
    docs = await rag_store.list_documents()
    stats = await rag_store.stats()
    embedding_status = await rag_store.embedding_status()
    return {
        "documents": docs,
        "stats": stats,
        "embedding_model": EMBED_MODEL,
        "embedding_status": embedding_status,
    }


@app.post("/api/rag/docs")
async def add_rag_document(payload: dict):
    original = (payload.get("text") or "")
    normalized, truncated = _normalize_document_text(original)
    metadata = {"type": "text", "original_characters": len(original.strip())}
    if truncated:
        metadata["truncated"] = True
    try:
        document = await rag_store.add_document(normalized, metadata=metadata)
        return {"document": document}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except RuntimeError as re:
        raise HTTPException(status_code=502, detail=str(re))


@app.post("/api/rag/docs/url")
async def add_rag_document_from_url(payload: dict):
    raw_url = str(payload.get("url") or "").strip()
    if not raw_url:
        raise HTTPException(status_code=400, detail="Ange en URL att hämta.")

    parsed = urlparse(raw_url)
    if not parsed.scheme:
        raw_url = f"https://{raw_url}"
        parsed = urlparse(raw_url)
    if not parsed.netloc:
        raise HTTPException(status_code=400, detail="Ogiltig URL. Ange en fullständig adress.")

    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            response = await client.get(raw_url, headers={"User-Agent": "Ollama-WebUI/1.0"})
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:  # type: ignore[no-untyped-def]
        status_code = exc.response.status_code if exc.response else 500
        if 400 <= status_code < 500:
            raise HTTPException(status_code=400, detail=f"Sidan svarade med HTTP {status_code}. Kontrollera adressen.") from exc
        raise HTTPException(status_code=502, detail=f"Kunde inte hämta sidan (HTTP {status_code}).") from exc
    except httpx.HTTPError as exc:  # type: ignore[no-untyped-def]
        raise HTTPException(status_code=502, detail=f"Kunde inte hämta sidan: {exc}") from exc

    content_type = response.headers.get("content-type", "").lower()
    if "html" not in content_type and "text" not in content_type:
        raise HTTPException(status_code=400, detail="URL:en verkar inte innehålla någon läsbar text.")

    text, title = _html_to_text_and_title(response.text)
    normalized, truncated = _normalize_document_text(text)
    if not normalized:
        raise HTTPException(status_code=400, detail="Kunde inte läsa någon text från sidan.")

    metadata = {
        "type": "url",
        "url": raw_url,
        "original_characters": len(text),
    }
    if title:
        metadata["title"] = title
    if truncated:
        metadata["truncated"] = True

    try:
        document = await rag_store.add_document(normalized, metadata=metadata)
        return {"document": document}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except RuntimeError as re:
        raise HTTPException(status_code=502, detail=str(re))


@app.post("/api/rag/docs/pdf")
async def add_rag_document_from_pdf(file: UploadFile = File(...)):
    filename = file.filename or "uppladdad.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Endast PDF-filer stöds.")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Filen är tom.")
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(status_code=400, detail="PDF-filen är för stor. Max 8 MB stöds.")

    try:
        text, total_pages, used_pages = _extract_pdf_text(data)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Kunde inte läsa PDF-filen: {exc}") from exc

    normalized, truncated = _normalize_document_text(text)
    if not normalized:
        raise HTTPException(status_code=400, detail="Kunde inte hitta någon text i PDF-filen.")

    metadata = {
        "type": "pdf",
        "filename": filename,
        "total_pages": total_pages,
        "pages_used": used_pages,
        "original_characters": len(text),
    }
    if truncated:
        metadata["truncated"] = True

    try:
        document = await rag_store.add_document(normalized, metadata=metadata)
        return {"document": document}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except RuntimeError as re:
        raise HTTPException(status_code=502, detail=str(re))


@app.delete("/api/rag/docs/{doc_id}")
async def delete_rag_document(doc_id: str):
    removed = await rag_store.delete_document(doc_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Dokumentet hittades inte.")
    stats = await rag_store.stats()
    return {"removed": True, "stats": stats}


@app.delete("/api/rag/docs")
async def clear_rag_documents():
    await rag_store.clear()
    return {"cleared": True}

@app.post("/api/chat")
async def chat(payload: dict):
    # payload: { messages: [...], model?: str, options?: {...}, use_rag?: bool, rag_top_k?: int }
    messages = payload.get("messages", [])
    model = payload.get("model") or DEFAULT_MODEL
    options = payload.get("options", {})

    if not isinstance(messages, list) or not messages:
        raise HTTPException(status_code=400, detail="Skicka 'messages' som en icke-tom lista.")

    use_rag = bool(payload.get("use_rag"))
    rag_top_k_raw = payload.get("rag_top_k", 3)
    try:
        rag_top_k = int(rag_top_k_raw)
    except (TypeError, ValueError):
        rag_top_k = 3
    rag_top_k = max(1, min(rag_top_k, 10))

    enriched_messages = list(messages)
    rag_matches: List[RAGResult] = []

    if use_rag:
        user_prompt = ""
        for msg in reversed(enriched_messages):
            if isinstance(msg, dict) and msg.get("role") == "user":
                user_prompt = str(msg.get("content", "")).strip()
                if user_prompt:
                    break
        if user_prompt:
            try:
                rag_matches = await rag_store.search(user_prompt, top_k=rag_top_k)
            except RuntimeError as err:
                raise HTTPException(status_code=502, detail=str(err))
            if rag_matches:
                context_intro = (
                    "Använd följande utdrag från kunskapsbasen när du svarar. "
                    "Om informationen inte räcker ska du säga att du saknar underlag."
                )
                context_body = "\n\n".join(
                    f"Utdrag {idx + 1}:\n{match.text}"
                    for idx, match in enumerate(rag_matches)
                )
                context_message = {
                    "role": "system",
                    "content": f"{context_intro}\n\n{context_body}",
                }
                if enriched_messages and isinstance(enriched_messages[0], dict) and enriched_messages[0].get("role") == "system":
                    insert_at = 1
                else:
                    insert_at = 0
                enriched_messages.insert(insert_at, context_message)

    body = {
        "model": model,
        "messages": enriched_messages,
        "stream": False,
        "options": options,
    }
    url = f"{OLLAMA_HOST}/api/chat"
    try:
        async with httpx.AsyncClient(timeout=300) as client:
            r = await client.post(url, json=body)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict):
                data["rag_context"] = [
                    {
                        "doc_id": match.doc_id,
                        "chunk_index": match.chunk_index,
                        "score": match.score,
                        "text": match.text,
                    }
                    for match in rag_matches
                ] if use_rag else []
                data["rag_used"] = use_rag and bool(rag_matches)
            return JSONResponse(data)
    except httpx.HTTPStatusError as se:
        # Vid typiska fel: modell saknas, minne etc.
        text = se.response.text
        raise HTTPException(status_code=se.response.status_code, detail=f"Ollama-fel ({se.response.status_code}): {text}")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Kunde inte nå Ollama: {e}")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=APP_HOST, port=APP_PORT, reload=False)


def _safe_int(value: Optional[str], fallback: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


DEFAULT_TTS_ENGINE = (os.getenv("TTS_ENGINE", "espeak_mbrola") or "espeak_mbrola").strip().lower()
DEFAULT_TTS_RATE = _safe_int(os.getenv("TTS_RATE", "180"), 180)
DEFAULT_TTS_VOICE_HINT = os.getenv("TTS_VOICE_HINT", "sv") or "sv"


@lru_cache(maxsize=1)
def _pyttsx3_voice_catalog() -> List[dict]:
    """Hämtar och cachar tillgängliga röster från pyttsx3."""

    voices: List[dict] = []
    engine = pyttsx3.init()
    try:
        for voice in engine.getProperty("voices"):
            languages: List[str] = []
            raw_languages = getattr(voice, "languages", None)
            if raw_languages:
                try:
                    for lang in raw_languages:
                        if isinstance(lang, bytes):
                            languages.append(lang.decode("utf-8", "ignore"))
                        else:
                            languages.append(str(lang))
                except TypeError:
                    pass
            haystack_parts = [voice.id or "", voice.name or "", *languages]
            voices.append(
                {
                    "id": voice.id,
                    "name": voice.name or "",
                    "languages": languages,
                    "haystack": " ".join(part.lower() for part in haystack_parts if part),
                }
            )
    finally:
        try:
            engine.stop()
        except Exception:
            pass
    return voices


def _match_voice(predicate) -> Optional[str]:
    for voice in _pyttsx3_voice_catalog():
        if predicate(voice):
            return voice["id"]
    return None


def _select_voice_id(engine_choice: str, voice_pref: Optional[str], voice_id: Optional[str]) -> Optional[str]:
    voices = _pyttsx3_voice_catalog()
    if voice_id and any(v["id"] == voice_id for v in voices):
        return voice_id

    def haystack_contains(voice: dict, *needles: str) -> bool:
        return all(needle in voice.get("haystack", "") for needle in needles if needle)

    if voice_pref:
        pref = voice_pref.lower()
        matched = _match_voice(lambda v: haystack_contains(v, pref))
        if matched:
            return matched

    normalized_choice = (engine_choice or "").lower().strip()

    if normalized_choice == "whisper":
        matched = _match_voice(lambda v: haystack_contains(v, "whisper"))
        if matched:
            return matched
    elif normalized_choice in {"espeak_mbrola", "mbrola", "espeak-mbrola"}:
        matched = _match_voice(lambda v: haystack_contains(v, "mb", "sv"))
        if matched:
            return matched
        matched = _match_voice(lambda v: haystack_contains(v, "mb"))
        if matched:
            return matched
    elif normalized_choice:
        matched = _match_voice(lambda v: haystack_contains(v, normalized_choice))
        if matched:
            return matched

    if voice_pref:
        matched = _match_voice(lambda v: haystack_contains(v, voice_pref.lower()))
        if matched:
            return matched

    matched = _match_voice(lambda v: haystack_contains(v, "sv"))
    if matched:
        return matched

    matched = _match_voice(lambda v: haystack_contains(v, "swedish"))
    if matched:
        return matched

    return voices[0]["id"] if voices else None


def _available_tts_options() -> List[dict]:
    voices = _pyttsx3_voice_catalog()

    def list_ids(predicate) -> List[str]:
        return [voice["id"] for voice in voices if predicate(voice)]

    whisper_ids = list_ids(lambda v: "whisper" in v.get("haystack", ""))
    mbrola_ids = list_ids(lambda v: "mb" in v.get("haystack", ""))
    swedish_mbrola_ids = list_ids(lambda v: "mb" in v.get("haystack", "") and ("sv" in v.get("haystack", "") or "swedish" in v.get("haystack", "")))

    return [
        {
            "id": "whisper",
            "label": "Whisper (eSpeak NG)",
            "available": bool(whisper_ids),
            "voices": whisper_ids,
            "description": "Använder eSpeak NG:s viskande röst.",
        },
        {
            "id": "espeak_mbrola",
            "label": "eSpeak NG + MBROLA",
            "available": bool(mbrola_ids),
            "voices": mbrola_ids,
            "swedish_voices": swedish_mbrola_ids,
            "description": "Kräver MBROLA-röster (t.ex. mb-sv1) installerade i eSpeak NG.",
        },
    ]


@app.get("/api/tts/options")
async def tts_options():
    voices = _pyttsx3_voice_catalog()
    fallback_voice = _select_voice_id(DEFAULT_TTS_ENGINE, DEFAULT_TTS_VOICE_HINT, None)
    return {
        "default_engine": DEFAULT_TTS_ENGINE,
        "options": _available_tts_options(),
        "fallback_voice": fallback_voice,
        "total_voices": len(voices),
    }


@app.post("/api/tts")
async def tts(payload: dict):
    """Text -> WAV (offline TTS via pyttsx3/eSpeak NG)."""

    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Saknar text att läsa upp.")

    try:
        rate = int(payload.get("rate") or DEFAULT_TTS_RATE)
    except (TypeError, ValueError):
        rate = DEFAULT_TTS_RATE

    engine_choice = (payload.get("engine") or DEFAULT_TTS_ENGINE).strip().lower()
    voice_pref = (payload.get("voice") or DEFAULT_TTS_VOICE_HINT or "").strip()
    voice_id = payload.get("voice_id")

    try:
        with tempfile.TemporaryDirectory() as td:
            out_wav = os.path.join(td, "speech.wav")
            engine = pyttsx3.init()
            try:
                engine.setProperty("rate", rate)
            except Exception:
                pass

            selected_voice = _select_voice_id(engine_choice, voice_pref or None, voice_id)
            if selected_voice:
                try:
                    engine.setProperty("voice", selected_voice)
                except Exception:
                    pass

            engine.save_to_file(text, out_wav)
            engine.runAndWait()

            if not os.path.exists(out_wav):
                raise RuntimeError("Ingen ljudfil genererades av talsyntesen.")

            return FileResponse(out_wav, media_type="audio/wav", filename="tts_sv.wav")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"TTS misslyckades: {exc}") from exc
