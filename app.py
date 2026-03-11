import os
import uuid
import subprocess
import requests
import tempfile
import logging
from flask import Flask, request, jsonify
from pathlib import Path

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("/tmp/videos")
OUTPUT_DIR.mkdir(exist_ok=True)

def download_file(url: str, dest: str) -> bool:
    try:
        r = requests.get(url, timeout=60, stream=True)
        r.raise_for_status()
        with open(dest, 'wb') as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        return True
    except Exception as e:
        logger.error(f"Download failed {url}: {e}")
        return False

def generate_eq_video(audio_path: str, cover_path: str, title: str, serie: str, output_path: str, duration: int = 60) -> bool:
    """
    Génère une vidéo 1080x1920 vertical avec :
    - Cover art en fond (floutée + assombrie)
    - Barres EQ animées au centre
    - Titre + série en overlay
    - Logo nikimix en haut
    """
    try:
        # Couleurs nikimix
        bar_color = "0xFF6B35"   # Orange nikimix
        bg_color  = "0x1a1a2e"   # Bleu nuit
        text_color = "white"

        # Filtre FFmpeg complet
        filter_complex = (
            # Input 0 : cover art → fond flouté assombri 1080x1920
            "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,"
            "gblur=sigma=20,"
            "eq=brightness=-0.3[bg];"

            # Input 0 : cover art → vignette centrale carrée 600x600
            "[0:v]scale=600:600:force_original_aspect_ratio=decrease,"
            "pad=600:600:(ow-iw)/2:(oh-ih)/2:color=black@0[cover_sq];"

            # Overlay cover centrée en haut (y=200)
            "[bg][cover_sq]overlay=(W-w)/2:200[with_cover];"

            # Visualiseur EQ : barres fréquences en bas
            "[1:a]showfreqs="
            "s=1080x400:"
            "mode=bar:"
            "fscale=log:"
            "win_size=2048:"
            "colors=" + bar_color[2:] + "@0.9[eq];"

            # Overlay EQ en bas (y=1400)
            "[with_cover][eq]overlay=0:1400[with_eq];"

            # Titre série (petite police, au dessus du titre)
            "[with_eq]drawtext="
            "text='" + serie.replace("'", "\\'") + "':"
            "fontsize=36:"
            "fontcolor=white@0.7:"
            "x=(w-text_w)/2:"
            "y=870:"
            "shadowcolor=black@0.8:shadowx=2:shadowy=2[with_serie];"

            # Titre principal
            "[with_serie]drawtext="
            "text='" + title.replace("'", "\\'") + "':"
            "fontsize=52:"
            "fontcolor=white:"
            "x=(w-text_w)/2:"
            "y=920:"
            "shadowcolor=black@0.9:shadowx=3:shadowy=3[with_title];"

            # Watermark nikimix en bas
            "[with_title]drawtext="
            "text='nikimix.com':"
            "fontsize=28:"
            "fontcolor=white@0.5:"
            "x=(w-text_w)/2:"
            "y=1850[final]"
        )

        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", cover_path,          # Input 0 : image
            "-i", audio_path,                          # Input 1 : audio
            "-filter_complex", filter_complex,
            "-map", "[final]",
            "-map", "1:a",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-t", str(duration),
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            output_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode != 0:
            logger.error(f"FFmpeg error: {result.stderr[-2000:]}")
            return False

        logger.info(f"Video generated: {output_path}")
        return True

    except Exception as e:
        logger.error(f"Generation error: {e}")
        return False


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "nikimix-video-generator"})


@app.route("/generate-video", methods=["POST"])
def generate_video():
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    audio_url = data.get("audio_url")
    cover_url = data.get("cover_url")
    title     = data.get("title", "House Sessions")
    serie     = data.get("serie", "nikimix")
    duration  = int(data.get("duration", 60))

    if not audio_url or not cover_url:
        return jsonify({"error": "audio_url and cover_url are required"}), 400

    job_id = str(uuid.uuid4())[:8]

    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path  = os.path.join(tmpdir, "audio.m4a")
        cover_path  = os.path.join(tmpdir, "cover.jpg")
        output_path = str(OUTPUT_DIR / f"{job_id}.mp4")

        logger.info(f"[{job_id}] Downloading audio: {audio_url}")
        if not download_file(audio_url, audio_path):
            return jsonify({"error": "Failed to download audio"}), 500

        logger.info(f"[{job_id}] Downloading cover: {cover_url}")
        if not download_file(cover_url, cover_path):
            return jsonify({"error": "Failed to download cover"}), 500

        logger.info(f"[{job_id}] Generating video...")
        if not generate_eq_video(audio_path, cover_path, title, serie, output_path, duration):
            return jsonify({"error": "FFmpeg generation failed"}), 500

    # Retourne l'URL publique Railway
    base_url = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "localhost:5000")
    video_url = f"https://{base_url}/video/{job_id}.mp4"

    return jsonify({
        "success": True,
        "job_id": job_id,
        "video_url": video_url,
        "duration": duration,
        "title": title
    })


@app.route("/video/<filename>", methods=["GET"])
def serve_video(filename):
    from flask import send_from_directory
    return send_from_directory(str(OUTPUT_DIR), filename)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
