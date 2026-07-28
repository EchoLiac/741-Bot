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

# Datum & Wochentag ermitteln (0 = Montag, 4 = Freitag)
now = datetime.datetime.now()
today_str = now.strftime("%d.%m.%Y")
weekday = now.weekday()

# Dynamischen Prompt je nach Wochentag aufbauen
if weekday == 0:  # MONTAG
    day_instructions = """
    Heute ist MONTAG!
    • Fasse die wichtigsten Finanz-, Markt- und Krypto-News des vergangenen WOCHENENDES zusammen.
    • Gib einen klaren Ausblick auf die kommende Trading-Woche und den heutigen Montag.
    • Fokus: Worauf achten Händler heute nach dem Wochenende?
    """
elif weekday == 4:  # FREITAG
    day_instructions = """
    Heute ist FREITAG!
    • Fokus auf den heutigen Wochenabschluss (Weekly Close).
    • Gib einen kurzen Ausblick auf Risiken und Krypto-Entwicklungen über das bevorstehende WOCHENENDE.
    • Worauf muss man vor dem Weekend-Close achten?
    """
else:  # DIENSTAG BIS DONNERSTAG
    day_instructions = """
    Heute ist ein gewöhnlicher Handelstag unter der Woche.
    • Fokus auf Pre-Market, heutige Makro-Daten/Earnings und den heutigen Tagesausblick.
    """

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
• ⏰ **Makro-Daten:** [Wichtigste Wirtschaftsdaten/Fed-Sprecher heute inkl. Uhrzeiten]
• 📊 **Earnings:** [Relevanteste Unternehmenszahlen]

### 🎯 3. Focus Asset des Tages
• **Asset / Ticker:** [Ein spannendes Asset]
• **Setup / Ausblick:** [1-2 Sätze zur Lage]

---
*Guten Start in den Trading-Tag!*
"""

def generate_briefing():
    print("Sende dynamische Anfrage an Gemini API...")
    response = client.models.generate_content(
        model='gemini-1.5-flash',
        contents=f"Generiere das heutige Briefing für den {today_str}.",
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
        "avatar_url": "https://i.imgur.com/4M34hi2.png"
    }
    response = requests.post(DISCORD_WEBHOOK_URL, json=payload)
    if response.status_code in [200, 204]:
        print("Erfolgreich in Discord gepostet!")
    else:
        print(f"Fehler beim Senden: {response.status_code} - {response.text}")

if __name__ == "__main__":
    try:
        briefing_text = generate_briefing()
        send_to_discord(briefing_text)
    except Exception as e:
        print(f"Fehler: {e}")
        exit(1)
