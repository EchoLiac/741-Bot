import os
import datetime
import requests
from google import genai
from google.genai import types

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

if not GEMINI_API_KEY or not DISCORD_WEBHOOK_URL:
    raise ValueError("Fehlende API-Keys! Überprüfe die GitHub Secrets.")

client = genai.Client(api_key=GEMINI_API_KEY)

# Datum & Wochentag ermitteln
now = datetime.datetime.now()
today_str = now.strftime("%d.%m.%Y")
weekday = now.weekday()

if weekday == 0:
    day_instructions = "Heute ist MONTAG! Fasse die wichtigsten News des Wochenendes zusammen und gib einen Ausblick."
elif weekday == 4:
    day_instructions = "Heute ist FREITAG! Fokus auf Wochenabschluss (Weekly Close) und Krypto-Entwicklungen fürs Wochenende."
else:
    day_instructions = "Gewöhnlicher Handelstag. Fokus auf Pre-Market, heutige Makro-Daten & Earnings."

SYSTEM_PROMPT = f"""
Du bist der Markt-Analyst für die Trading-Community 'Investieren741'. 
Erstelle ein kompaktes, hochprofessionelles Morning-Briefing für den heutigen Tag ({today_str}).

{day_instructions}

Halte dich EXAKT an folgendes Layout (Markdown):

☕ **MORNING BRIEFING | {today_str}**

---

### 📈 1. Markt-Overview & Stimmung
• **US-Märkte (S&P 500 / Nasdaq):** [Einschätzung zur Stimmung & Tendenz]
• **Krypto (Bitcoin / Ethereum):** [Aktuelle Lage & Key-Levels]
• **Makro / Zinsen:** [DXY, Zins-Umfeld & Markt-Sentiment]

### 📅 2. Tagesevents & Termine (Makro & Earnings)
• ⏰ **Makro-Daten:** [Wichtigste Wirtschaftsdaten heute inkl. Uhrzeiten]
• 📊 **Earnings:** [Relevanteste Unternehmenszahlen]

### 🎯 3. Focus Asset des Tages
• **Asset / Ticker:** [Ein spannendes Asset]
• **Setup / Ausblick:** [1-2 Sätze zur Lage]

---
*Guten Start in den Trading-Tag!*
"""

def generate_briefing():
    print("Sende Anfrage an Gemini API...")

    # Aktuell gültige Modelle (Stand: 29. Juli 2026)
    models_to_try = ['gemini-3.6-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-flash-lite']

    for model_name in models_to_try:
        try:
            print(f"Versuche Modell: {model_name}...")
            response = client.models.generate_content(
                model=model_name,
                contents=f"Generiere das heutige Briefing für den {today_str}.",
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.3
                )
            )
            print(f"✅ Erfolg mit {model_name}!")
            return response.text
        except Exception as e:
            print(f"❌ Fehlschlag bei {model_name}: {e}")

    raise RuntimeError("Keines der Modelle wurde akzeptiert. Bitte überprüfe das Google API Dashboard.")

def send_to_discord(content):
    print("Sende Briefing an Discord...")
    payload = {
        "content": content,
        "username": "Investieren741 Briefing Bot",
        "avatar_url": "https://i.imgur.com/4M34hi2.png"
    }
    resp = requests.post(DISCORD_WEBHOOK_URL, json=payload)
    if resp.status_code in [200, 204]:
        print("Erfolgreich in Discord gepostet!")
    else:
        print(f"Fehler beim Senden an Discord: {resp.status_code} - {resp.text}")

if __name__ == "__main__":
    try:
        briefing = generate_briefing()
        send_to_discord(briefing)
    except Exception as e:
        print(f"FATAL ERROR: {e}")
        exit(1)
