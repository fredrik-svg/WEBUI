# syntax=docker/dockerfile:1
FROM python:3.11-slim

WORKDIR /app

# För ARM64 Raspberry Pi funkar denna basbild bra (64-bit OS krävs)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    espeak-ng \
    libespeak-ng1 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["python", "-m", "app.main"]
