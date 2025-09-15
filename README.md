# Raspi Ollama WebUI (svenska)

En superlätt WebUI för att köra Ollama på Raspberry Pi (ARM64). UI:t är på svenska och pratar direkt med Ollamas REST‑API på `http://ollama:11434` (Docker) eller `http://localhost:11434` (bare‑metal).

## Snabbstart (Docker Compose – rekommenderas)

1. **Installera Docker & Compose** på din Raspberry Pi (64‑bitars OS).
2. Klona detta repo och kör:
   ```bash
   docker compose up -d --build
   ```
3. Öppna WebUI i din webbläsare: http://<pi-ip>:8000

Första gången behöver du hämta en modell (t.ex. en liten som fungerar bra på Pi):

```bash
docker exec -it ollama ollama pull llama3.2:1b-instruct
```

> **Tips:** `llama3.2:1b-instruct` och `qwen2:0.5b-instruct` är små och brukar fungera på Pi, även med mindre RAM. Du kan byta modell i WebUI eller i `.env`.

## Alternativ: Bare‑metal (utan Docker)

```bash
bash scripts/install_pi.sh
source .venv/bin/activate
python -m app.main
```
Öppna: http://<pi-ip>:8000

## Svenska stöd

- WebUI är lokaliserad till svenska (texter i `i18n/sv.json`).
- För bästa svenska resultat: använd en modern flerspråkig modell (t.ex. `llama3.2:1b-instruct`). Modellen kan väljas i UI:t.
- Vill du lägga till talsyntes/ASR? Se kommentarerna i `app/main.py` för hur du kan lägga till Whisper och TTS senare.

## Miljövariabler

Skapa en `.env` (eller använd `.env.example`):

```
OLLAMA_HOST=http://ollama:11434
LLM_MODEL=llama3.2:1b-instruct
APP_HOST=0.0.0.0
APP_PORT=8000
```

## Endpoints (enkelt REST‑API)

- `POST /api/chat` – Skicka `{ "messages": [{ "role":"user", "content":"Hej!" }], "model":"llama3.2:1b-instruct" }`
- `GET /api/models` – Lista lokalt installerade modeller via Ollama
- `GET /` – WebUI (HTML/JS)

## Licens

MIT


## Röst till text (Whisper)

Projektet har inbyggt stöd för **Whisper (ASR)** via `faster-whisper`. I webUI finns en mikrofonknapp som spelar in och skickar ljud till `/api/transcribe` – resultatet klistras in i textrutan.

### Modell och prestanda
- Standard: `WHISPER_MODEL=tiny`, `WHISPER_COMPUTE_TYPE=int8` (snabbt och lätt på Raspberry Pi 5).
- Andra val: `tiny`, `base`, `small` – större = bättre kvalitet men kräver mer CPU/RAM.
- På Pi rekommenderas `tiny` eller `base`.

### Docker
`ffmpeg` finns i Docker-bilden så att ljudformat (t.ex. webm/ogg) kan konverteras till wav.

### Bare-metal
Installationsscriptet installerar `ffmpeg`. Se `.env.example` för konfig.

## GitHub-repo

1. Skapa ett nytt repo på GitHub (t.ex. `raspi-ollama-webui`).
2. Lägg till detta projekt:
   ```bash
   git init
   git add .
   git commit -m "Initial commit: WebUI + Ollama + Whisper (svenska)"
   git branch -M main
   git remote add origin git@github.com:<ditt-användarnamn>/raspi-ollama-webui.git
   git push -u origin main
   ```
3. En CI-workflow finns i `.github/workflows/ci.yml` som testar import och bygger Docker-bilden.


## Klona från GitHub till Raspberry Pi (Terminal)

> Förutsätter att du har skapat ett repo på GitHub, t.ex. `github.com/<ditt-användarnamn>/raspi-ollama-webui`

```bash
# 1) SSH:a in på din Pi (byt IP/användarnamn vid behov)
ssh pi@<pi-ip>

# 2) Installera git om det saknas
sudo apt-get update && sudo apt-get install -y git

# 3) Klona projektet
git clone https://github.com/<ditt-användarnamn>/raspi-ollama-webui.git
cd raspi-ollama-webui

# 4) (Om Docker) starta allt
docker compose up -d --build
docker exec -it ollama ollama pull llama3.2:1b-instruct

# 5) Öppna i webbläsare (på din dator): http://<pi-ip>:8000
```

### Alternativ: SSH-nyckel och push från din dator
```bash
# På din dator
ssh-keygen -t ed25519 -C "<din e-post>"
cat ~/.ssh/id_ed25519.pub

# Lägg till nyckeln i GitHub -> Settings -> SSH and GPG keys

# Lägg till origin och pusha kod
git remote add origin git@github.com:<ditt-användarnamn>/raspi-ollama-webui.git
git push -u origin main
# På din Pi, klona med SSH:
git clone git@github.com:<ditt-användarnamn>/raspi-ollama-webui.git
```
