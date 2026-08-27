"""
YouTube Video Scanner (yt-dlp + Transcript + Gemini)
- Prüft Kanäle auf neue Videos (inkl. Shorts)
- Erster Lauf: nur merken, keine Analyse
- Danach: nur neue Videos analysieren
- Bevorzugt echte Untertitel, sonst Titel + URL
- Postet kurze Zusammenfassung in Discord
- Speichert strukturierte Daten für Second Brain
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import yt_dlp
from google import genai

try:
    from youtube_transcript_api import YouTubeTranscriptApi
    HAS_TRANSCRIPT = True
except ImportError:
    HAS_TRANSCRIPT = False

# === Konfiguration ===
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_VIDEOS")
GEMINI_MODEL = "gemini-2.0-flash"

CHANNELS_FILE = "channels.json"
SEEN_FILE = "seen_videos.json"
OUTPUT_DIR = Path("video_summaries")

ANALYSIS_PROMPT = """Du bist ein erfahrener Trading-Assistent.
Analysiere das YouTube-Video so vollständig und konkret wie möglich.

Regeln:
- Nichts Wichtiges auslassen
- Alle genannten Kursziele, Support/Resistance, Fibonacci, Volumenprofil-Levels, Zonen etc. explizit aufführen
- Bei jedem Level kurz sagen, WARUM es relevant ist
- Die Zusammenfassung muss schnell lesbar sein
- Frage NIEMALS nach einem Transkript oder zusätzlichem Text. Arbeite mit dem, was du hast.

Strukturiere die Antwort exakt so:

📌 **Kernaussage**
(1–3 Sätze)

🔍 **Wichtige Levels & Setups**
- Level / Zone: ...
  Begründung: ...
- ...

💡 **Meinung des Sprechers**
...

⚠️ **Risiken / Einschränkungen**
...

📅 **Zeitliche Einordnung**
(Wann ungefähr gilt die Aussage / für welchen Zeitraum)

Am Ende immer:
⚠️ Keine Anlageberatung.
"""


def load_json(path, default):
    if Path(path).exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_recent_videos(handle: str, max_results: int = 2) -> list[dict]:
    """Holt die neuesten Videos eines Kanals über yt-dlp (nur Metadaten)."""
    url = f"https://www.youtube.com/{handle}/videos"
    ydl_opts = {
        "quiet": True,
        "extract_flat": True,
        "playlistend": max_results,
        "ignoreerrors": True,
    }
    videos = []
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info or "entries" not in info:
                return []
            for entry in info["entries"]:
                if not entry:
                    continue
                videos.append({
                    "id": entry.get("id"),
                    "title": entry.get("title"),
                    "url": f"https://www.youtube.com/watch?v={entry.get('id')}",
                    "published": entry.get("upload_date") or entry.get("timestamp"),
                })
    except Exception as e:
        print(f"Fehler bei {handle}: {e}")
    return videos


def get_transcript(video_id: str) -> str | None:
    """Holt automatische/manuelle Untertitel, falls vorhanden."""
    if not HAS_TRANSCRIPT:
        return None
    try:
        # Neue API (youtube-transcript-api >= 1.0)
        ytt = YouTubeTranscriptApi()
        transcript = ytt.fetch(video_id, languages=["de", "en"])
        texts = []
        for snip in transcript:
            if hasattr(snip, "text"):
                texts.append(snip.text)
            elif isinstance(snip, dict):
                texts.append(snip.get("text", ""))
        text = " ".join(texts).strip()
        return text[:12000] if text else None
    except Exception:
        try:
            # Fallback ältere API
            transcript_list = YouTubeTranscriptApi.get_transcript(
                video_id, languages=["de", "en"]
            )
            text = " ".join(x["text"] for x in transcript_list).strip()
            return text[:12000] if text else None
        except Exception as e:
            print(f"  Kein Transkript für {video_id}: {e}")
            return None


def analyze_with_gemini(title: str, video_url: str, transcript: str | None = None) -> str:
    if not GEMINI_API_KEY:
        return "❌ Kein GEMINI_API_KEY gesetzt."
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)

        if transcript:
            content_block = f"Transkript/Untertitel des Videos:\n{transcript}"
        else:
            content_block = (
                "Kein Transkript verfügbar.\n"
                f"Analysiere das Video so gut wie möglich anhand von Titel und URL.\n"
                f"URL: {video_url}\n"
                "Frage nicht nach zusätzlichem Text."
            )

        prompt = f"""{ANALYSIS_PROMPT}

Titel: {title}
YouTube-URL: {video_url}

{content_block}
"""

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt
        )
        return response.text
    except Exception as e:
        return f"❌ Gemini-Fehler: {e}"


def post_to_discord(content: str):
    if not DISCORD_WEBHOOK:
        print("Kein DISCORD_WEBHOOK_VIDEOS gesetzt")
        return
    for i in range(0, len(content), 1900):
        chunk = content[i:i + 1900]
        try:
            requests.post(DISCORD_WEBHOOK, json={"content": chunk}, timeout=15)
        except Exception as e:
            print(f"Discord Fehler: {e}")


def main():
    channels = load_json(CHANNELS_FILE, [])
    seen = load_json(SEEN_FILE, {})
    OUTPUT_DIR.mkdir(exist_ok=True)

    first_run = len(seen) == 0
    if first_run:
        print(">>> ERSTER LAUF: Videos werden nur gemerkt, keine Analyse <<<")

    new_count = 0

    for ch in channels:
        name = ch["name"]
        handle = ch["handle"]
        print(f"Prüfe {name} ({handle})...")

        videos = get_recent_videos(handle, max_results=2)

        for v in videos:
            vid = v.get("id")
            if not vid or vid in seen:
                continue

            print(f"  → Neues Video: {v['title']}")

            if first_run:
                seen[vid] = {
                    "title": v["title"],
                    "channel": name,
                    "scraped_at": datetime.now(timezone.utc).isoformat()
                }
                print("    (erster Lauf – nur gemerkt)")
                continue

            # 1) Transkript versuchen
            transcript = get_transcript(vid)
            if transcript:
                print("    Transkript gefunden")
            else:
                print("    Kein Transkript – nutze Titel + URL")

            # 2) Gemini
            summary = analyze_with_gemini(v["title"], v["url"], transcript)

            msg = f"🎬 **{name}**\n**{v['title']}**\n{v['url']}\n\n{summary}"
            post_to_discord(msg)

            # 3) Für Second Brain speichern
            out = {
                "channel": name,
                "handle": handle,
                "video_id": vid,
                "title": v["title"],
                "url": v["url"],
                "published": v.get("published"),
                "has_transcript": bool(transcript),
                "summary": summary,
                "scraped_at": datetime.now(timezone.utc).isoformat()
            }
            with open(OUTPUT_DIR / f"{vid}.json", "w", encoding="utf-8") as f:
                json.dump(out, f, indent=2, ensure_ascii=False)

            seen[vid] = {
                "title": v["title"],
                "channel": name,
                "scraped_at": datetime.now(timezone.utc).isoformat()
            }
            new_count += 1
            time.sleep(3)

    save_json(SEEN_FILE, seen)
    print(f"Fertig. {new_count} neue Videos verarbeitet.")


if __name__ == "__main__":
    main()