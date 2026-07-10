FROM python:3.11-slim

WORKDIR /app

# ffmpeg: required by faster-whisper for audio conversion
# libgomp1: OpenMP runtime used by faster-whisper/CTranslate2 wheels
# ca-certificates: TLS roots for Telegram, Ollama-adjacent HTTP calls, and web search
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    ffmpeg \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
