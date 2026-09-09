"""
YouTube Video Scanner V2
========================

- Prüft YouTube-Kanäle auf neue Videos UND Shorts
- Erster Lauf: nur merken, keine Analyse
- Danach: nur neue Videos analysieren
- Holt echte/manuelle/automatische YouTube-Untertitel
- Analysiert mit Gemini
- Gemini Retry-System
- Discord Retry-System
- Videos werden erst als "gesehen" markiert,
  wenn Analyse UND Discord erfolgreich waren
- Speichert Ergebnisse dauerhaft unter video_summaries/
- Fehlerhafte Analysen bleiben für einen späteren Versuch offen
- Strukturierte Ausgabe für Trading Second Brain
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

GEMINI_MODEL = os.environ.get(
    "GEMINI_MODEL",
    "gemini-3.6-flash"
)

CHANNELS_FILE = "channels.json"
SEEN_FILE = "seen_videos.json"

OUTPUT_DIR = Path("video_summaries")

MAX_RESULTS_PER_SECTION = 10

MAX_TRANSCRIPT_CHARS = int(
    os.environ.get("MAX_TRANSCRIPT_CHARS", "60000")
)

GEMINI_MAX_RETRIES = 3
DISCORD_MAX_RETRIES = 3


# ============================================================
# ANALYSE PROMPT
# ============================================================

ANALYSIS_PROMPT = """
Du bist ein erfahrener Trading-Assistent.

Analysiere den gegebenen Videoinhalt vollständig,
konkret und strukturiert.

Deine Aufgabe ist NICHT, selbst Trading-Signale zu erfinden.

Du extrahierst ausschließlich:
- Aussagen des Sprechers
- genannte Aktien / Ticker
- konkrete Levels
- Bedingungen
- Ziele
- Risiken
- Trading-Setups
- Methoden
- zeitliche Aussagen

Wenn etwas nicht eindeutig aus dem Material hervorgeht,
schreibe ausdrücklich:

„nicht eindeutig genannt“

Erfinde keine Informationen.


==================================================
ZUERST DEN VIDEO-TYP BESTIMMEN
==================================================

Wähle genau einen Typ:

A) Einzelaktie / Einzelsetup

B) Mehrere Aktien / mehrere Setups

C) Markt / Makro / Index
   Keine einzelne Aktie steht klar im Fokus.

D) Bildung / Trading-Methode / Psychologie
   Schwerpunkt liegt auf Lernen und nicht auf
   konkreten aktuellen Trade-Levels.


==================================================
PFLICHT – UNABHÄNGIG VOM TYP
==================================================

- Alle genannten Ticker UND Firmennamen nennen.

Beispiel:

NVDA – Nvidia
NOW – ServiceNow

Wenn kein konkreter Ticker genannt wird:

„kein konkreter Ticker genannt“

- Unterstützungen
- Widerstände
- Kursziele
- Fibonacci-Level
- Volumenprofil-Level
- Breakout-Level
- Trigger
- Invalidierungen
- Zonen

immer mit konkreter Zahl nennen,
falls sie im Material genannt werden.

Bei jedem Level kurz erklären,
WARUM es laut Sprecher relevant ist.

Mehrere Aktien niemals zusammenwerfen.

Wenn zehn Aktien behandelt werden,
müssen zehn getrennte Aktienblöcke erscheinen.


==================================================
AUSGABESTRUKTUR
==================================================

📌 **Typ**
A/B/C/D – kurze Begründung


📌 **Kernaussage**

1–3 Sätze.


🏷️ **Erwähnte Ticker / Themen**

- Ticker – Unternehmen
- Ticker – Unternehmen

oder:

- keine konkreten Ticker genannt


🎯 **Handelsrichtung**

Pro Aktie / Markt:

- Bullish
- Bearish
- Neutral
- Bedingt bullish
- Bedingt bearish
- nicht eindeutig genannt


🔍 **Levels & Setups**

Wenn Typ A:

### TICKER – Unternehmen

- Aktuelle Aussage:
  ...

- Support:
  ...
  Begründung:
  ...

- Resistance:
  ...
  Begründung:
  ...

- Trigger:
  ...

- Ziel:
  ...

- Invalidierung:
  ...

- Setup:
  ...


Wenn Typ B:

Für JEDE Aktie einen eigenen Block.

Beispiel:

### NVDA – Nvidia

- Richtung:
- Support:
- Resistance:
- Trigger:
- Ziel:
- Invalidierung:
- Setup:
- Begründung:

### PLTR – Palantir

- Richtung:
- Support:
- Resistance:
- Trigger:
- Ziel:
- Invalidierung:
- Setup:
- Begründung:


Wenn Typ C:

### Markt / Index

- Markt:
- Richtung:
- Support:
- Resistance:
- Trigger:
- Ziel:
- Invalidierung:
- Begründung:


Wenn Typ D:

### Methode / Learning

- Kernmethode:
- wichtigste Regeln:
- Entry-Regeln:
- Exit-Regeln:
- Risiko-Regeln:
- typische Fehler:
- Checkliste:


💡 **Meinung des Sprechers**

Kurze Zusammenfassung der Einschätzung des Sprechers.

Nicht deine eigene Meinung.


⚠️ **Risiken / Einschränkungen**

Welche Risiken oder Unsicherheiten
werden im Video genannt?


⏱️ **Zeithorizont**

Falls genannt:

- Intraday
- kurzfristig
- Swing
- mittelfristig
- langfristig

Wenn nicht klar:

„nicht eindeutig genannt“


🔄 **Trigger & Invalidierung**

Für relevante Setups:

- Was muss passieren,
  damit das Setup aktiv wird?

- Wann wäre die These laut Sprecher ungültig?


⭐ **Relevanz**

Bewerte ausschließlich die Informationsdichte:

- Hoch
- Mittel
- Niedrig

Kurze Begründung.


📅 **Zeitliche Einordnung**

Falls Aussagen nur für einen bestimmten Zeitraum gelten,
klar kennzeichnen.


==================================================
WICHTIG
==================================================

Keine eigenen Kursziele erfinden.

Keine Ticker ergänzen,
die nicht im gegebenen Inhalt vorkommen.

Keine Analyse so formulieren,
als hättest du das Video gesehen,
wenn nur Titelinformationen vorhanden sind.

⚠️ Keine Anlageberatung.
"""


# ============================================================
# HILFSFUNKTIONEN
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

    tmp_path = path.with_suffix(
        path.suffix + ".tmp"
    )

    with open(
        tmp_path,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            indent=2,
            ensure_ascii=False
        )

    tmp_path.replace(path)


# ============================================================
# YOUTUBE
# ============================================================

def fetch_section(
    url: str,
    max_results: int
) -> list[dict]:

    ydl_opts = {
        "quiet": True,
        "extract_flat": True,
        "playlistend": max_results,
        "ignoreerrors": True,
    }

    videos = []

    try:

        with yt_dlp.YoutubeDL(
            ydl_opts
        ) as ydl:

            info = ydl.extract_info(
                url,
                download=False
            )

        if not info:
            return []

        entries = info.get(
            "entries",
            []
        )

        for entry in entries:

            if not entry:
                continue

            vid = entry.get("id")

            if not vid:
                continue

            videos.append({
                "id": vid,
                "title": (
                    entry.get("title")
                    or "Ohne Titel"
                ),
                "url": (
                    "https://www.youtube.com/"
                    f"watch?v={vid}"
                ),
                "published": (
                    entry.get("upload_date")
                    or entry.get("timestamp")
                )
            })

    except Exception as e:

        print(
            f"YouTube Fehler bei "
            f"{url}: {e}"
        )

    return videos


def get_recent_videos(
    handle: str,
    max_results: int = 10
) -> list[dict]:

    """
    Holt sowohl normale Videos
    als auch Shorts.
    """

    base = (
        f"https://www.youtube.com/"
        f"{handle}"
    )

    normal_videos = fetch_section(
        f"{base}/videos",
        max_results
    )

    shorts = fetch_section(
        f"{base}/shorts",
        max_results
    )

    combined = {}

    for video in normal_videos + shorts:

        vid = video.get("id")

        if vid:
            combined[vid] = video

    return list(
        combined.values()
    )


# ============================================================
# TRANSKRIPT
# ============================================================

def get_transcript(
    video_id: str
) -> tuple[str | None, bool]:

    """
    Rückgabe:

    (Transcript, wurde_abgeschnitten)
    """

    if not HAS_TRANSCRIPT:
        print(
            "youtube-transcript-api "
            "nicht installiert"
        )
        return None, False

    text = None

    try:

        api = YouTubeTranscriptApi()

        transcript = api.fetch(
            video_id,
            languages=[
                "de",
                "en"
            ]
        )

        parts = []

        for snippet in transcript:

            if hasattr(
                snippet,
                "text"
            ):

                parts.append(
                    snippet.text
                )

            elif isinstance(
                snippet,
                dict
            ):

                parts.append(
                    snippet.get(
                        "text",
                        ""
                    )
                )

        text = " ".join(
            parts
        ).strip()

    except Exception as first_error:

        try:

            transcript_list = (
                YouTubeTranscriptApi
                .get_transcript(
                    video_id,
                    languages=[
                        "de",
                        "en"
                    ]
                )
            )

            text = " ".join(
                item.get(
                    "text",
                    ""
                )
                for item
                in transcript_list
            ).strip()

        except Exception:

            print(
                f"  Kein Transkript für "
                f"{video_id}: "
                f"{first_error}"
            )

            return None, False

    if not text:
        return None, False

    truncated = False

    if len(text) > MAX_TRANSCRIPT_CHARS:

        print(
            "    ⚠️ Transkript sehr lang: "
            f"{len(text)} Zeichen"
        )

        print(
            "    Kürze auf "
            f"{MAX_TRANSCRIPT_CHARS} Zeichen"
        )

        text = text[
            :MAX_TRANSCRIPT_CHARS
        ]

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

        return (
            False,
            "",
            "Kein GEMINI_API_KEY gesetzt."
        )

    client = genai.Client(
        api_key=GEMINI_API_KEY
    )

    if transcript:

        content_block = f"""
TRANSKRIPT / UNTERTITEL:

{transcript}
"""

    else:

        content_block = f"""
Für dieses Video konnte KEIN
Transkript geladen werden.

Titel:
{title}

URL:
{video_url}

Du hast ausschließlich Titel und URL
als Text erhalten.

Du hast das Video NICHT gesehen.

Erfinde deshalb:

- keine Ticker
- keine Levels
- keine Kursziele
- keine Aussagen
- keine Trading-Setups

Wenn etwas nicht aus dem Titel
eindeutig hervorgeht:

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

    wait_times = [
        10,
        30,
        60
    ]

    last_error = None

    for attempt in range(
        1,
        max_retries + 1
    ):

        try:

            print(
                f"    Gemini Versuch "
                f"{attempt}/"
                f"{max_retries}"
            )

            response = (
                client.models
                .generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt
                )
            )

            text = getattr(
                response,
                "text",
                None
            )

            if (
                text
                and text.strip()
            ):

                return (
                    True,
                    text.strip(),
                    None
                )

            raise RuntimeError(
                "Gemini lieferte "
                "eine leere Antwort."
            )

        except Exception as e:

            last_error = str(e)

            print(
                f"    ❌ Gemini Fehler: "
                f"{e}"
            )

            if attempt < max_retries:

                wait = wait_times[
                    min(
                        attempt - 1,
                        len(
                            wait_times
                        ) - 1
                    )
                ]

                print(
                    f"    Neuer Versuch "
                    f"in {wait} Sekunden..."
                )

                time.sleep(
                    wait
                )

    return (
        False,
        "",
        last_error
        or "Unbekannter Gemini Fehler"
    )


# ============================================================
# DISCORD
# ============================================================

def post_to_discord(
    content: str,
    max_retries: int = DISCORD_MAX_RETRIES
) -> bool:

    if not DISCORD_WEBHOOK:

        print(
            "❌ Kein "
            "DISCORD_WEBHOOK_VIDEOS "
            "gesetzt"
        )

        return False

    chunks = [
        content[
            i:i + 1900
        ]

        for i in range(
            0,
            len(content),
            1900
        )
    ]

    for index, chunk in enumerate(
        chunks,
        start=1
    ):

        sent = False

        for attempt in range(
            1,
            max_retries + 1
        ):

            try:

                response = requests.post(
                    DISCORD_WEBHOOK,
                    json={
                        "content": chunk
                    },
                    timeout=20
                )

                response.raise_for_status()

                sent = True
                break

            except Exception as e:

                print(
                    f"    Discord Fehler "
                    f"Chunk {index}, "
                    f"Versuch {attempt}: "
                    f"{e}"
                )

                if (
                    attempt
                    < max_retries
                ):

                    time.sleep(
                        5 * attempt
                    )

        if not sent:

            print(
                "    ❌ Discord "
                "endgültig fehlgeschlagen."
            )

            return False

    return True


# ============================================================
# VIDEO-DATENSATZ
# ============================================================

def save_video_result(
    video_id: str,
    data: dict
):

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    path = (
        OUTPUT_DIR
        / f"{video_id}.json"
    )

    save_json(
        path,
        data
    )


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

        print(
            "❌ Keine Kanäle "
            "in channels.json gefunden."
        )

        return

    first_run = (
        len(seen) == 0
    )

    if first_run:

        print(
            ">>> ERSTER LAUF <<<"
        )

        print(
            "Videos werden nur "
            "als Ausgangsbestand gemerkt."
        )

        print(
            "Keine Analyse."
        )

    new_count = 0
    failed_count = 0

    for channel in channels:

        name = channel[
            "name"
        ]

        handle = channel[
            "handle"
        ]

        print()
        print(
            f"Prüfe {name} "
            f"({handle})..."
        )

        videos = get_recent_videos(
            handle,
            max_results=
            MAX_RESULTS_PER_SECTION
        )

        print(
            f"  {len(videos)} "
            f"Videos/Shorts gefunden"
        )

        for video in videos:

            vid = video.get(
                "id"
            )

            if not vid:
                continue

            if vid in seen:
                continue

            title = video.get(
                "title",
                "Ohne Titel"
            )

            print()
            print(
                f"  → Neues Video: "
                f"{title}"
            )

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

                print(
                    "    Baseline – "
                    "nur gemerkt"
                )

                continue

            # --------------------------------
            # TRANSKRIPT
            # --------------------------------

            transcript, truncated = (
                get_transcript(
                    vid
                )
            )

            if transcript:

                print(
                    "    ✅ Transkript "
                    f"gefunden "
                    f"({len(transcript)} Zeichen)"
                )

            else:

                print(
                    "    ⚠️ Kein "
                    "Transkript"
                )

            # --------------------------------
            # ROHDATEN VOR ANALYSE SICHERN
            # --------------------------------

            base_record = {
                "channel": name,
                "handle": handle,
                "video_id": vid,
                "title": title,
                "url": video["url"],
                "published": (
                    video.get(
                        "published"
                    )
                ),
                "has_transcript": (
                    bool(transcript)
                ),
                "transcript_truncated": (
                    truncated
                ),
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

            success, summary, error = (
                analyze_with_gemini(
                    title,
                    video["url"],
                    transcript
                )
            )

            if not success:

                print(
                    "    ❌ Analyse "
                    "fehlgeschlagen."
                )

                print(
                    "    Video wird NICHT "
                    "als gesehen markiert."
                )

                base_record[
                    "status"
                ] = "analysis_failed"

                base_record[
                    "error"
                ] = error

                base_record[
                    "last_attempt"
                ] = now_iso()

                save_video_result(
                    vid,
                    base_record
                )

                failed_count += 1

                continue

            # --------------------------------
            # ANALYSE SICHERN
            # --------------------------------

            base_record[
                "summary"
            ] = summary

            base_record[
                "status"
            ] = "analyzed"

            base_record[
                "analyzed_at"
            ] = now_iso()

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

            discord_success = (
                post_to_discord(
                    message
                )
            )

            if not discord_success:

                print(
                    "    ❌ Discord "
                    "fehlgeschlagen."
                )

                print(
                    "    Video wird NICHT "
                    "als gesehen markiert."
                )

                base_record[
                    "status"
                ] = "discord_failed"

                base_record[
                    "last_attempt"
                ] = now_iso()

                save_video_result(
                    vid,
                    base_record
                )

                failed_count += 1

                continue

            # --------------------------------
            # ERFOLGREICH
            # --------------------------------

            base_record[
                "status"
            ] = "complete"

            base_record[
                "discord_sent_at"
            ] = now_iso()

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

            print(
                "    ✅ Komplett "
                "verarbeitet"
            )

            new_count += 1

            time.sleep(
                3
            )

    save_json(
        SEEN_FILE,
        seen
    )

    print()
    print(
        "=============================="
    )

    print(
        "VIDEO SCANNER FERTIG"
    )

    print(
        f"Erfolgreich: {new_count}"
    )

    print(
        f"Fehlgeschlagen/offen: "
        f"{failed_count}"
    )

    print(
        "=============================="
    )


if __name__ == "__main__":
    main()
