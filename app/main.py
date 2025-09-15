import os
import json
import socket
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import httpx
from dotenv import load_dotenv

load_dotenv()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
DEFAULT_MODEL = os.getenv("LLM_MODEL", "llama3.2:1b")
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", "8000"))

app = FastAPI(title="Raspi Ollama WebUI (sv)")
from fastapi import UploadFile, File
import tempfile
from pydub import AudioSegment
from faster_whisper import WhisperModel

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


@app.get("/api/info")
async def app_info():
    return {
        "host": APP_HOST,
        "port": APP_PORT,
        "default_model": DEFAULT_MODEL,
        "ollama_host": OLLAMA_HOST,
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

@app.post("/api/chat")
async def chat(payload: dict):
    # payload: { messages: [...], model?: str, options?: {...} }
    messages = payload.get("messages", [])
    model = payload.get("model") or DEFAULT_MODEL
    options = payload.get("options", {})

    if not isinstance(messages, list) or not messages:
        raise HTTPException(status_code=400, detail="Skicka 'messages' som en icke-tom lista.")

    # Ollama format
    body = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": options
    }
    url = f"{OLLAMA_HOST}/api/chat"
    try:
        async with httpx.AsyncClient(timeout=300) as client:
            r = await client.post(url, json=body)
            r.raise_for_status()
            data = r.json()
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

from fastapi.responses import FileResponse
import pyttsx3
import tempfile

@app.post("/api/tts")
async def tts(payload: dict):
    """
    Text -> WAV (offline TTS via pyttsx3/espeak-ng)
    payload: { "text": "...", "rate": 180, "voice": "sv" }
    """
    text = payload.get("text", "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Saknar text att läsa upp.")
    rate = int(payload.get("rate", 180))
    voice_pref = payload.get("voice")  # e.g., "sv" or full id

    try:
        with tempfile.TemporaryDirectory() as td:
            out_wav = os.path.join(td, "speech.wav")
            engine = pyttsx3.init()
            try:
                engine.setProperty("rate", rate)
                # välj svensk röst om möjligt
                if voice_pref:
                    for v in engine.getProperty("voices"):
                        if voice_pref.lower() in (v.id.lower() + " " + (v.name or "").lower()):
                            engine.setProperty("voice", v.id)
                            break
                else:
                    # auto: leta efter sv-SE/svenska
                    for v in engine.getProperty("voices"):
                        name = (v.name or "").lower()
                        vid = v.id.lower()
                        if "sv" in vid or "swedish" in name or "svenska" in name:
                            engine.setProperty("voice", v.id)
                            break
            except Exception:
                pass
            engine.save_to_file(text, out_wav)
            engine.runAndWait()
            return FileResponse(out_wav, media_type="audio/wav", filename="tts_sv.wav")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS misslyckades: {e}")
