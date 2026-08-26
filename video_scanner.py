"""
YouTube Video Scanner (yt-dlp + Gemini)
- Prüft Kanäle auf neue Videos (inkl. Shorts)
- Analysiert vollständig mit Gemini
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

# === Konfiguration ===
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_VIDEOS")
GEMINI_MODEL = "gemini-3.6-flash"

CHANNELS_FILE = "channels.json"
SEEN_FILE = "seen_videos.json"
OUTPUT_DIR = Path("video_summaries")

ANALYSIS_PROMPT = """Du bist ein erfahrener Trading-Assistent.
Analysiere das folgende YouTube-Video vollständig anhand von Titel und Transkript/Beschreibung.

Regeln:
- Nichts Wichtiges auslassen
- Alle genannten Kursziele, Support/Resistance, Fibonacci, Volumenprofil-Levels, Zonen etc. explizit aufführen
- Bei jedem Level kurz sagen, WARUM es relevant ist
- Die Zusammenfassung muss trotzdem schnell lesbar sein

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

def get_recent_videos(handle: str, max_results: int = 5) -> list[dict]:
    """Holt die neuesten Videos eines Kanals über yt-dlp."""
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

def get_transcript_or_description(video_url: str) -> str:
    """Versucht Transkript zu holen, sonst Beschreibung."""
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "writesubtitles": False,
        "writeautomaticsub": False,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            # Beschreibung
            desc = info.get("description") or ""
            # Manche Videos haben automatische Untertitel in info
            # Für den Start nehmen wir Beschreibung + Titel (Gemini kommt damit relativ gut klar)
            # Später können wir echte Untertitel ergänzen
            return desc[:8000]  # begrenzen
    except Exception as e:
        print(f"Transcript/Desc Fehler: {e}")
        return ""

def analyze_with_gemini(title: str, content: str) -> str:
    if not GEMINI_API_KEY:
        return "❌ Kein GEMINI_API_KEY gesetzt."
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        full_prompt = f"{ANALYSIS_PROMPT}\n\nTitel: {title}\n\nInhalt:\n{content}"
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=full_prompt
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

    new_count = 0
    for ch in channels:
        name = ch["name"]
        handle = ch["handle"]
        print(f"Prüfe {name} ({handle})...")

        videos = get_recent_videos(handle, max_results=4)
        for v in videos:
            vid = v.get("id")
            if not vid or vid in seen:
                continue

            print(f"  → Neues Video: {v['title']}")
            content = get_transcript_or_description(v["url"])
            summary = analyze_with_gemini(v["title"], content)

            # Discord-Nachricht
            msg = f"🎬 **{name}**\n**{v['title']}**\n{v['url']}\n\n{summary}"
            post_to_discord(msg)

            # Für Second Brain speichern
            out = {
                "channel": name,
                "handle": handle,
                "video_id": vid,
                "title": v["title"],
                "url": v["url"],
                "published": v.get("published"),
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
            time.sleep(3)  # etwas Abstand

    save_json(SEEN_FILE, seen)
    print(f"Fertig. {new_count} neue Videos verarbeitet.")

if __name__ == "__main__":
    main()
