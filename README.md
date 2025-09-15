# Raspi Ollama WebUI (svenska)

En superlätt WebUI för att köra Ollama på Raspberry Pi (ARM64). UI:t är på svenska och pratar direkt med Ollamas REST‑API på `http://ollama:11434` (Docker) eller `http://localhost:11434` (bare‑metal).

## Snabbstart (Docker Compose – rekommenderas)

1. **Installera Docker & Compose** på din Raspberry Pi (64‑bitars OS, se instruktionerna nedan).
2. Klona detta repo och kör:
   ```bash
   docker compose up -d --build
   ```
3. Öppna WebUI i din webbläsare: http://<pi-ip>:8000

Första gången behöver du hämta en modell (t.ex. en liten som fungerar bra på Pi):

```bash
docker exec -it ollama ollama pull llama3.2:1b
```

### Anslut från en annan dator i nätverket

1. Se till att Raspberry Pi och datorn du vill ansluta ifrån är på samma lokala nätverk (t.ex. samma wifi/router).
2. På din Pi: kör `hostname -I` eller `ip addr` för att se Pi:ns IP-adress.
3. Öppna adressen i en webbläsare på din dator, t.ex. `http://<pi-ip>:8000`.
4. Om du kör via Docker används port 8000 automatiskt. På bare-metal styrs porten av variabeln `APP_PORT` i `.env`.

> **Tips:** WebUI:t visar en ruta "Anslut från en annan dator" med klickbara länkar när servern är igång. Dela en av dessa adresser med användare i samma nätverk.

> **Tips:** `llama3.2:1b` och `qwen2:0.5b-instruct` är små och brukar fungera på Pi, även med mindre RAM. Du kan byta modell i WebUI eller i `.env`.

### Installera Docker & Compose på Raspberry Pi

Följ stegen nedan på din Raspberry Pi (64-bitars Raspberry Pi OS eller Debian-baserad distribution):

```bash
# 1) Uppdatera paketindex
sudo apt-get update

# 2) Installera Docker via officiella skriptet
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# 3) Lägg till ditt användarkonto i docker-gruppen (så slipper du sudo)
sudo usermod -aG docker $USER

# 4) Aktivera nya gruppen utan att starta om (alt. logga ut/in)
newgrp docker

# 5) Installera Docker Compose-pluginet
sudo apt-get install -y docker-compose-plugin

# 6) Kontrollera att allt fungerar
docker --version
docker compose version
```

> **Behörigheter:** `usermod -aG docker $USER` ser till att ditt konto har rättigheter att prata med Docker-daemonen. Om du hoppar över detta måste du prefixa kommandon med `sudo`.

> **Tips:** På äldre system kan paketet heta `docker-compose`. Då kan du installera det via `sudo apt-get install -y docker-compose`.

## Alternativ: Bare‑metal (utan Docker)

```bash
bash scripts/install_pi.sh
source .venv/bin/activate
python -m app.main
```
Öppna: http://<pi-ip>:8000

## Svenska stöd

- WebUI är lokaliserad till svenska (texter i `i18n/sv.json`).
- För bästa svenska resultat: använd en modern flerspråkig modell (t.ex. `llama3.2:1b`). Modellen kan väljas i UI:t.
- Vill du lägga till talsyntes/ASR? Se kommentarerna i `app/main.py` för hur du kan lägga till Whisper och TTS senare.

## Miljövariabler

Skapa en `.env` (eller använd `.env.example`):

```
OLLAMA_HOST=http://ollama:11434
LLM_MODEL=llama3.2:1b
APP_HOST=0.0.0.0
APP_PORT=8000
```

## Endpoints (enkelt REST‑API)

- `POST /api/chat` – Skicka `{ "messages": [{ "role":"user", "content":"Hej!" }], "model":"llama3.2:1b" }`
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
docker exec -it ollama ollama pull llama3.2:1b

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
