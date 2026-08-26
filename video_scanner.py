"""
YouTube Video Scanner
- Prüft Kanäle auf neue Videos
- Analysiert vollständig mit Gemini (Levels + Begründung)
- Postet kurze Zusammenfassung in Discord
- Speichert Rohdaten für späteres Second Brain
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from google import genai

# === Konfiguration ===
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_VIDEOS")  # neuer Webhook
GEMINI_MODEL = "gemini-3.6-flash"

CHANNELS_FILE = "channels.json"
SEEN_FILE = "seen_videos.json"
OUTPUT_DIR = Path("video_summaries")  # für Second Brain später

# === Prompt ===
ANALYSIS_PROMPT = """Du bist ein erfahrener Trading-Assistent.
Analysiere das folgende YouTube-Video (Titel + Transkript/Beschreibung) vollständig.

Wichtige Regeln:
- Nichts Wichtiges auslassen
- Alle genannten Kursziele, Support/Resistance, Fibonacci, Volumenprofil-Levels etc. explizit aufführen
- Bei jedem Level kurz sagen, WARUM es relevant ist
- Die Zusammenfassung muss trotzdem schnell lesbar sein (max. 1–2 Bildschirmseiten)

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
(Wann wurde das Video gemacht / für welchen Zeitraum gilt die Aussage ungefähr)

Am Ende:
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

def get_recent_videos(handle: str, max_results: int = 3) -> list[dict]:
    """
    Holt die neuesten Videos eines Kanals über die YouTube RSS-Feed Methode
    (kein API-Key nötig, sehr stabil).
    """
    # Handle zu Channel-ID auflösen wäre ideal, RSS über Handle geht so:
    # Wir nutzen yt-dlp oder requests auf die Channel-Seite.
    # Einfachste robuste Variante für den Start:
    try:
        url = f"https://www.youtube.com/{handle}/videos"
        # Für den Start nutzen wir eine einfache Methode.
        # In der Praxis empfehle ich yt-dlp oder YouTube Data API.
        # Hier Platzhalter-Logik – wird im nächsten Schritt konkretisiert.
        return []
    except Exception as e:
        print(f"Fehler bei {handle}: {e}")
        return []

def analyze_with_gemini(title: str, transcript_or_desc: str) -> str:
    client = genai.Client(api_key=GEMINI_API_KEY)
    content = f"Titel: {title}\n\nInhalt:\n{transcript_or_desc}"
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=ANALYSIS_PROMPT + "\n\n" + content
    )
    return response.text

def post_to_discord(content: str):
    if not DISCORD_WEBHOOK:
        print("Kein Webhook gesetzt")
        return
    # Discord Limit beachten
    for i in range(0, len(content), 1900):
        chunk = content[i:i+1900]
        requests.post(DISCORD_WEBHOOK, json={"content": chunk})

def main():
    channels = load_json(CHANNELS_FILE, [])
    seen = load_json(SEEN_FILE, {})

    OUTPUT_DIR.mkdir(exist_ok=True)

    new_count = 0
    for ch in channels:
        handle = ch["handle"]
        name = ch["name"]
        print(f"Prüfe {name}...")

        videos = get_recent_videos(handle)
        for v in videos:
            vid = v["id"]
            if vid in seen:
                continue

            print(f"  Neues Video: {v['title']}")
            # Hier kommt später: Transkript holen + Gemini
            # summary = analyze_with_gemini(v["title"], transcript)

            # Dummy für den Start
            summary = f"**{name}** – {v['title']}\n\n(Analyse folgt in der nächsten Version)"

            # Discord
            post_to_discord(f"🎬 **{name}**\n{summary}")

            # Für Second Brain speichern
            out = {
                "channel": name,
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
            time.sleep(2)

    save_json(SEEN_FILE, seen)
    print(f"Fertig. {new_count} neue Videos verarbeitet.")

if __name__ == "__main__":
    main()
