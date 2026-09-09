"""
YouTube Video Scanner V2
========================

- Prüft YouTube-Kanäle ausschließlich auf normale Videos
- Shorts werden ignoriert
- Erster Lauf: nur merken, keine Analyse
- Danach: nur neue Videos analysieren
- Holt YouTube-Untertitel
- Analysiert mit Gemini
- 3 Gemini-Retries bei Fehlern
- Discord Retry-System
- Erst nach erfolgreicher Analyse + Discord als gesehen markieren
- Speichert Ergebnisse unter video_summaries/
- Fehlgeschlagene Videos werden beim nächsten Lauf erneut versucht
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


# ============================================================
# KONFIGURATION
# ============================================================

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_VIDEOS")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")

CHANNELS_FILE = "channels.json"
SEEN_FILE = "seen_videos.json"
OUTPUT_DIR = Path("video_summaries")

# Nur die letzten normalen Videos jedes Kanals prüfen
MAX_RESULTS = 10

# Lange Videos nicht mehr schon bei 12.000 Zeichen abschneiden
MAX_TRANSCRIPT_CHARS = int(
    os.environ.get("MAX_TRANSCRIPT_CHARS", "60000")
)

GEMINI_MAX_RETRIES = 3
DISCORD_MAX_RETRIES = 3


# ============================================================
# ANALYSE-PROMPT
# ============================================================

ANALYSIS_PROMPT = """
Du bist ein erfahrener Trading-Assistent.

Analysiere den gegebenen Videoinhalt vollständig,
konkret und strukturiert.

Deine Aufgabe ist NICHT, selbst Trading-Signale zu erfinden.

Extrahiere ausschließlich Informationen,
die tatsächlich aus dem gegebenen Inhalt hervorgehen.

### ZUERST TYP BESTIMMEN

Wähle genau einen Typ:

A) Einzelaktie / Einzelsetup
B) Mehrere Aktien / mehrere Setups
C) Markt / Makro / Index
D) Bildung / Methode / Psychologie


### PFLICHT – unabhängig vom Typ

- Alle genannten Ticker UND Firmennamen explizit nennen.
- Wenn kein Ticker fällt:
  „kein konkreter Ticker genannt“
- Kursziele, Support, Resistance, Fibonacci,
  Volumenprofil, Zonen und Trigger mit Zahlen nennen,
  soweit sie tatsächlich genannt werden.
- Bei jedem Level erklären, warum es laut Sprecher relevant ist.
- Mehrere Aktien niemals zusammenwerfen.
- Wenn 10 Aktien behandelt werden,
  müssen alle 10 separat aufgeführt werden.
- Keine Ticker oder Levels erfinden.
- Unsicherheiten ausdrücklich kennzeichnen.


### STRUKTUR

📌 **Typ**
A/B/C/D – kurze Begründung


📌 **Kernaussage**
1–3 Sätze.


🏷️ **Erwähnte Ticker / Themen**
- Ticker – Unternehmen

oder:

- kein konkreter Ticker genannt


🎯 **Handelsrichtung**

Pro Aktie / Markt:

- Bullish
- Bearish
- Neutral
- Bedingt bullish
- Bedingt bearish
- nicht eindeutig genannt


🔍 **Levels & Setups**

Bei Einzelaktie:

### TICKER – Unternehmen

- Richtung:
- Support:
- Resistance:
- Trigger:
- Ziel:
- Invalidierung:
- Setup:
- Begründung:


Bei mehreren Aktien:

Für JEDE Aktie einen eigenen Block:

### TICKER – Unternehmen

- Richtung:
- Support:
- Resistance:
- Trigger:
- Ziel:
- Invalidierung:
- Setup:
- Begründung:


Bei Markt / Index:

### Markt / Index

- Richtung:
- Support:
- Resistance:
- Trigger:
- Ziel:
- Invalidierung:
- Begründung:


Bei Bildung / Methode:

### Methode / Learning

- Kernmethode:
- wichtigste Regeln:
- Entry-Regeln:
- Exit-Regeln:
- Risiko-Regeln:
- typische Fehler:
- Checkliste:


💡 **Meinung des Sprechers**
Nur die Meinung des Sprechers wiedergeben.


⚠️ **Risiken / Einschränkungen**
Genannte Risiken und Unsicherheiten.


⏱️ **Zeithorizont**

- Intraday
- kurzfristig
- Swing
- mittelfristig
- langfristig
- nicht eindeutig genannt


🔄 **Trigger & Invalidierung**

- Was muss passieren, damit das Setup aktiv wird?
- Wann wäre die These laut Sprecher ungültig?


⭐ **Relevanz**

- Hoch
- Mittel
- Niedrig

Kurze Begründung anhand der Informationsdichte.


📅 **Zeitliche Einordnung**
Falls die Aussage nur für einen bestimmten Zeitraum gilt.


WICHTIG:

Keine eigenen Kursziele erfinden.
Keine nicht genannten Ticker ergänzen.
Keine Aussagen als Tatsache darstellen,
die nicht im gegebenen Inhalt vorkommen.

⚠️ Keine Anlageberatung.
"""


# ============================================================
# JSON
# ============================================================

def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_json(path, default):
    path = Path(path)

    if not path.exists():
        return default

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Fehler beim Laden von {path}: {e}")
        return default


def save_json(path, data):
    path = Path(path)
    tmp_path = path.with_suffix(path.suffix + ".tmp")

    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    tmp_path.replace(path)


# ============================================================
# YOUTUBE – NUR NORMALE VIDEOS
# ============================================================

def get_recent_videos(handle: str, max_results: int = MAX_RESULTS) -> list[dict]:
    """
    Holt ausschließlich normale Videos über /videos.
    Shorts werden NICHT abgefragt.
    """

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

            vid = entry.get("id")

            if not vid:
                continue

            videos.append({
                "id": vid,
                "title": entry.get("title") or "Ohne Titel",
                "url": f"https://www.youtube.com/watch?v={vid}",
                "published": (
                    entry.get("upload_date")
                    or entry.get("timestamp")
                ),
            })

    except Exception as e:
        print(f"Fehler bei {handle}: {e}")

    return videos


# ============================================================
# TRANSKRIPT
# ============================================================

def get_transcript(video_id: str) -> tuple[str | None, bool]:

    if not HAS_TRANSCRIPT:
        print("youtube-transcript-api nicht installiert")
        return None, False

    text = None

    try:
        api = YouTubeTranscriptApi()

        transcript = api.fetch(
            video_id,
            languages=["de", "en"]
        )

        parts = []

        for snippet in transcript:
            if hasattr(snippet, "text"):
                parts.append(snippet.text)
            elif isinstance(snippet, dict):
                parts.append(snippet.get("text", ""))

        text = " ".join(parts).strip()

    except Exception as first_error:
        try:
            transcript_list = YouTubeTranscriptApi.get_transcript(
                video_id,
                languages=["de", "en"]
            )

            text = " ".join(
                item.get("text", "")
                for item in transcript_list
            ).strip()

        except Exception:
            print(
                f"  Kein Transkript für {video_id}: "
                f"{first_error}"
            )
            return None, False

    if not text:
        return None, False

    truncated = False

    if len(text) > MAX_TRANSCRIPT_CHARS:
        print(
            f"    ⚠️ Transkript hat {len(text)} Zeichen "
            f"und wird auf {MAX_TRANSCRIPT_CHARS} gekürzt."
        )

        text = text[:MAX_TRANSCRIPT_CHARS]
        truncated = True

    return text, truncated


# ============================================================
# GEMINI
# ============================================================

def analyze_with_gemini(
    title: str,
    video_url: str,
    transcript: str | None = None,
    max_retries: int = GEMINI_MAX_RETRIES
) -> tuple[bool, str, str | None]:

    if not GEMINI_API_KEY:
        return False, "", "Kein GEMINI_API_KEY gesetzt."

    client = genai.Client(api_key=GEMINI_API_KEY)

    if transcript:
        content_block = f"""
TRANSKRIPT / UNTERTITEL:

{transcript}
"""

    else:
        content_block = f"""
Für dieses Video konnte KEIN Transkript geladen werden.

Titel:
{title}

URL:
{video_url}

Du hast ausschließlich Titel und URL als Text erhalten.
Du hast das Video NICHT gesehen.

Erfinde deshalb:
- keine Ticker
- keine Levels
- keine Kursziele
- keine Aussagen
- keine Trading-Setups

Wenn etwas nicht eindeutig aus dem Titel hervorgeht:
„nicht bestimmbar ohne Transkript“
"""

    prompt = f"""
{ANALYSIS_PROMPT}

==================================================

VIDEO

Titel:
{title}

YouTube-URL:
{video_url}

==================================================

{content_block}

==================================================

Zusätzliche Pflicht:

Bei mehreren Aktien:
JEDE Aktie separat behandeln.

Keine Aktie auslassen.
Keine Levels erfinden.
Unsicherheit ausdrücklich markieren.
"""

    wait_times = [10, 30, 60]
    last_error = None

    for attempt in range(1, max_retries + 1):

        try:
            print(
                f"    Gemini Versuch "
                f"{attempt}/{max_retries}"
            )

            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt
            )

            text = getattr(response, "text", None)

            if text and text.strip():
                return True, text.strip(), None

            raise RuntimeError(
                "Gemini lieferte eine leere Antwort."
            )

        except Exception as e:
            last_error = str(e)

            print(f"    ❌ Gemini Fehler: {e}")

            if attempt < max_retries:
                wait = wait_times[
                    min(attempt - 1, len(wait_times) - 1)
                ]

                print(
                    f"    Neuer Versuch in "
                    f"{wait} Sekunden..."
                )

                time.sleep(wait)

    return (
        False,
        "",
        last_error or "Unbekannter Gemini-Fehler"
    )


# ============================================================
# DISCORD
# ============================================================

def post_to_discord(
    content: str,
    max_retries: int = DISCORD_MAX_RETRIES
) -> bool:

    if not DISCORD_WEBHOOK:
        print("❌ Kein DISCORD_WEBHOOK_VIDEOS gesetzt")
        return False

    chunks = [
        content[i:i + 1900]
        for i in range(0, len(content), 1900)
    ]

    for index, chunk in enumerate(chunks, start=1):

        sent = False

        for attempt in range(1, max_retries + 1):

            try:
                response = requests.post(
                    DISCORD_WEBHOOK,
                    json={"content": chunk},
                    timeout=20
                )

                response.raise_for_status()
                sent = True
                break

            except Exception as e:
                print(
                    f"    Discord Fehler "
                    f"Chunk {index}, "
                    f"Versuch {attempt}: {e}"
                )

                if attempt < max_retries:
                    time.sleep(5 * attempt)

        if not sent:
            print("    ❌ Discord endgültig fehlgeschlagen.")
            return False

    return True


# ============================================================
# VIDEO-ERGEBNIS SPEICHERN
# ============================================================

def save_video_result(video_id: str, data: dict):

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    path = OUTPUT_DIR / f"{video_id}.json"

    save_json(path, data)


# ============================================================
# MAIN
# ============================================================

def main():

    channels = load_json(
        CHANNELS_FILE,
        []
    )

    seen = load_json(
        SEEN_FILE,
        {}
    )

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    if not channels:
        print("❌ Keine Kanäle in channels.json gefunden.")
        return

    first_run = len(seen) == 0

    if first_run:
        print(">>> ERSTER LAUF <<<")
        print("Videos werden nur als Ausgangsbestand gemerkt.")
        print("Keine Analyse.")

    new_count = 0
    failed_count = 0

    for channel in channels:

        name = channel["name"]
        handle = channel["handle"]

        print()
        print(f"Prüfe {name} ({handle})...")

        # NUR NORMALE VIDEOS
        videos = get_recent_videos(
            handle,
            max_results=MAX_RESULTS
        )

        print(
            f"  {len(videos)} normale Videos gefunden"
        )

        for video in videos:

            vid = video.get("id")

            if not vid:
                continue

            if vid in seen:
                continue

            title = video.get(
                "title",
                "Ohne Titel"
            )

            print()
            print(f"  → Neues Video: {title}")

            # --------------------------------
            # ERSTER LAUF
            # --------------------------------

            if first_run:

                seen[vid] = {
                    "title": title,
                    "channel": name,
                    "scraped_at": now_iso(),
                    "baseline": True
                }

                print("    Baseline – nur gemerkt")
                continue

            # --------------------------------
            # TRANSKRIPT
            # --------------------------------

            transcript, truncated = get_transcript(vid)

            if transcript:
                print(
                    f"    ✅ Transkript gefunden "
                    f"({len(transcript)} Zeichen)"
                )
            else:
                print("    ⚠️ Kein Transkript")

            # --------------------------------
            # ROHDATEN SICHERN
            # --------------------------------

            base_record = {
                "channel": name,
                "handle": handle,
                "video_id": vid,
                "title": title,
                "url": video["url"],
                "published": video.get("published"),
                "has_transcript": bool(transcript),
                "transcript_truncated": truncated,
                "transcript_chars": (
                    len(transcript)
                    if transcript
                    else 0
                ),
                "transcript": transcript,
                "status": "pending",
                "scraped_at": now_iso()
            }

            save_video_result(
                vid,
                base_record
            )

            # --------------------------------
            # GEMINI
            # --------------------------------

            success, summary, error = analyze_with_gemini(
                title,
                video["url"],
                transcript
            )

            if not success:

                print("    ❌ Analyse fehlgeschlagen.")
                print(
                    "    Video wird NICHT als gesehen markiert."
                )

                base_record["status"] = "analysis_failed"
                base_record["error"] = error
                base_record["last_attempt"] = now_iso()

                save_video_result(
                    vid,
                    base_record
                )

                failed_count += 1
                continue

            # --------------------------------
            # ANALYSE SICHERN
            # --------------------------------

            base_record["summary"] = summary
            base_record["status"] = "analyzed"
            base_record["analyzed_at"] = now_iso()

            save_video_result(
                vid,
                base_record
            )

            # --------------------------------
            # DISCORD
            # --------------------------------

            message = (
                f"🎬 **{name}**\n"
                f"**{title}**\n"
                f"{video['url']}\n\n"
                f"{summary}"
            )

            discord_success = post_to_discord(
                message
            )

            if not discord_success:

                print("    ❌ Discord fehlgeschlagen.")
                print(
                    "    Video wird NICHT als gesehen markiert."
                )

                base_record["status"] = "discord_failed"
                base_record["last_attempt"] = now_iso()

                save_video_result(
                    vid,
                    base_record
                )

                failed_count += 1
                continue

            # --------------------------------
            # ERFOLGREICH
            # --------------------------------

            base_record["status"] = "complete"
            base_record["discord_sent_at"] = now_iso()

            save_video_result(
                vid,
                base_record
            )

            seen[vid] = {
                "title": title,
                "channel": name,
                "scraped_at": now_iso()
            }

            save_json(
                SEEN_FILE,
                seen
            )

            print("    ✅ Komplett verarbeitet")

            new_count += 1

            time.sleep(3)

    save_json(
        SEEN_FILE,
        seen
    )

    print()
    print("==============================")
    print("VIDEO SCANNER FERTIG")
    print(f"Erfolgreich: {new_count}")
    print(f"Fehlgeschlagen/offen: {failed_count}")
    print("==============================")


if __name__ == "__main__":
    main()
