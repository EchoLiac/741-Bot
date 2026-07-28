import os
import datetime
import requests
from google import genai
from google.genai import types

# API Keys aus den Environment Variables laden
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

if not GEMINI_API_KEY or not DISCORD_WEBHOOK_URL:
    raise ValueError("Fehlende API-Keys! Überprüfe die GitHub Secrets.")

# Gemini Client initialisieren
client = genai.Client(api_key=GEMINI_API_KEY)

# Datum formatieren
today_str = datetime.datetime.now().strftime("%d.%m.%Y")

# Prompt für das Tages-Briefing
SYSTEM_PROMPT = """
Du bist der Markt-Analyst für die Trading-Community 'Investieren741'. 
Erstelle ein kompaktes, hochprofessionelles Morning-Briefing für den heutigen Trading-Tag.

Halte dich EXAKT an folgendes Layout (Markdown):

☕ **MORNING BRIEFING | {datum}**

---

### 📈 1. Markt-Overview (Pre-Market)
• **US-Märkte (S&P 500 / Nasdaq):** [Einschätzung zur Stimmung & Tendenz]
• **Krypto (Bitcoin / Ethereum):** [Aktuelle Lage & Key-Levels]
• **Makro / Zinsen:** [US-Dollar-Index (DXY) & Zins-Umfeld]

### 📅 2. Wichtige Tagesevents (Makro & Earnings)
• ⏰ **Makro-Daten:** [Wichtigste Wirtschaftsdaten & Fed-Sprecher heute inkl. Uhrzeiten]
• 📊 **Earnings:** [Relevanteste Unternehmenszahlen heute]

### 🎯 3. Focus Asset des Tages
• **Asset / Ticker:** [Ein spannendes Asset für den Tag]
• **Setup / Ausblick:** [1-2 Sätze zur Lage]

---
*Guten Start in den Trading-Tag!*
""".format(datum=today_str)

USER_PROMPT = f"Generiere das Morning-Briefing für heute, den {today_str}. Berücksichtige die aktuellen weltweiten Marktgegebenheiten."

def generate_briefing():
    print("Sende Anfrage an Gemini API...")
    # Nutze das aktuelle gemini-2.5-flash Modell
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=USER_PROMPT,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.3
        )
    )
    return response.text

def send_to_discord(content):
    print("Sende Briefing an Discord...")
    payload = {
        "content": content,
        "username": "Investieren741 Briefing Bot",
        "avatar_url": "https://i.imgur.com/4M34hi2.png" # Optionales Avatar-Bild
    }
    response = requests.post(DISCORD_WEBHOOK_URL, json=payload)
    if response.status_code in [200, 204]:
        print("Erfolgreich in Discord gepostet!")
    else:
        print(f"Fehler beim Senden an Discord: {response.status_code} - {response.text}")

if __name__ == "__main__":
    try:
        briefing_text = generate_briefing()
        send_to_discord(briefing_text)
    except Exception as e:
        print(f"Fehler beim Ausführen des Briefings: {e}")
        exit(1)
