FROM python:3.11-slim

# FFmpeg + polices
RUN apt-get update && apt-get install -y \
    ffmpeg \
    fonts-liberation \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# Dossier vidéos temporaires
RUN mkdir -p /tmp/videos

EXPOSE 5000

CMD ["python", "app.py"]
