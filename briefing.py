import os
import datetime
import requests
import google.generativeai as genai

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

if not GEMINI_API_KEY or not DISCORD_WEBHOOK_URL:
    raise ValueError("Fehlende API-Keys! Überprüfe die GitHub Secrets.")

# Gemini konfigurieren
genai.configure(api_key=GEMINI_API_KEY)

# Datum & Wochentag
now = datetime.datetime.now()
today_str = now.strftime("%d.%m.%Y")
weekday = now.weekday()

if weekday == 0:
    day_instructions = "Heute ist MONTAG! Fasse die News des Wochenendes zusammen und gib einen Ausblick."
elif weekday == 4:
    day_instructions = "Heute ist FREITAG! Fokus auf Wochenabschluss (Weekly Close) und Krypto-Risiken."
else:
    day_instructions = "Gewöhnlicher Handelstag: Fokus auf Pre-Market, Makro-Daten & Earnings."

SYSTEM_PROMPT = f"""
Du bist der Markt-Analyst für die Trading-Community 'Investieren741'. 
Erstelle ein kompaktes Morning-Briefing für den heutigen Tag ({today_str}).

{day_instructions}

Halte dich EXAKT an folgendes Layout:

☕ **MORNING BRIEFING | {today_str}**

---

### 📈 1. Markt-Overview & Stimmung
• **US-Märkte (S&P 500 / Nasdaq):** [Einschätzung]
• **Krypto (Bitcoin / Ethereum):** [Key-Levels]
• **Makro / Zinsen:** [Sentiment]

### 📅 2. Tagesevents & Termine (Makro & Earnings)
• ⏰ **Makro-Daten:** [Wichtigste Termine mit Uhrzeiten]
• 📊 **Earnings:** [Relevanteste Zahlen]

### 🎯 3. Focus Asset des Tages
• **Asset / Ticker:** [Spannendes Asset]
• **Setup / Ausblick:** [1-2 Sätze]

---
*Guten Start in den Trading-Tag!*
"""

def generate_briefing():
    print("Sende Anfrage an Gemini...")
    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash",
        system_instruction=SYSTEM_PROMPT
    )
    response = model.generate_content(f"Generiere das heutige Briefing für den {today_str}.")
    return response.text

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
        print(f"Fehler beim Senden: {resp.status_code} - {resp.text}")

if __name__ == "__main__":
    try:
        text = generate_briefing()
        send_to_discord(text)
    except Exception as e:
        print(f"Fehler: {e}")
        exit(1)
