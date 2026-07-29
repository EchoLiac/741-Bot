import os
import datetime
from zoneinfo import ZoneInfo
import requests
from google import genai
from google.genai import types

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

if not GEMINI_API_KEY or not DISCORD_WEBHOOK_URL:
    raise ValueError("Fehlende API-Keys! Überprüfe die GitHub Secrets.")

client = genai.Client(api_key=GEMINI_API_KEY)

# Datum & Wochentag ermitteln (fest auf Berlin/CEST, unabhängig von Server-Zeitzone)
now = datetime.datetime.now(ZoneInfo("Europe/Berlin"))
today_str = now.strftime("%d.%m.%Y")
weekday = now.weekday()

if weekday == 0:
    day_instructions = "Heute ist MONTAG! Fasse die wichtigsten News des Wochenendes zusammen und gib einen Ausblick."
elif weekday == 4:
    day_instructions = "Heute ist FREITAG! Fokus auf Wochenabschluss (Weekly Close) und Krypto-Entwicklungen fürs Wochenende."
else:
    day_instructions = "Gewöhnlicher Handelstag. Fokus auf Pre-Market, heutige Makro-Daten & Earnings."


def get_crypto_prices():
    """Holt exakte, aktuelle BTC/ETH-Kurse von CoinGecko (kein API-Key nötig)."""
    try:
        url = "https://api.coingecko.com/api/v3/simple/price"
        params = {
            "ids": "bitcoin,ethereum",
            "vs_currencies": "usd",
            "include_24hr_change": "true"
        }
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        btc_price = data["bitcoin"]["usd"]
        btc_change = data["bitcoin"]["usd_24h_change"]
        eth_price = data["ethereum"]["usd"]
        eth_change = data["ethereum"]["usd_24h_change"]

        return (
            f"Bitcoin (BTC): {btc_price:,.0f} USD ({btc_change:+.2f}% in 24h)\n"
            f"Ethereum (ETH): {eth_price:,.0f} USD ({eth_change:+.2f}% in 24h)"
        )
    except Exception as e:
        print(f"⚠️ Konnte Krypto-Kurse nicht laden: {e}")
        return "Krypto-Kurse aktuell nicht verfügbar."


crypto_data = get_crypto_prices()
print(f"Live-Krypto-Daten:\n{crypto_data}")

SYSTEM_PROMPT = f"""
Du bist der präzise Markt-Analyst für die Trading-Community 'Investieren741'. 
Erstelle ein übersichtliches, extrem hochwertiges Morning-Briefing für den heutigen Tag ({today_str}).

{day_instructions}

WICHTIG: Nutze die Google-Suche, um dir aktuelle, verifizierte Informationen zu 
US-Indizes (S&P 500, Nasdaq), Makrodaten, Zinsen (DXY, US-Anleiherenditen) und 
den heutigen Earnings-Terminen zu beschaffen. Erfinde KEINE Zahlen. Wenn du für 
einen Punkt keine verlässliche aktuelle Information findest, formuliere vorsichtiger 
(z.B. "tendenziell", "laut letzten verfügbaren Daten") statt eine exakte Zahl zu raten.

Für den Krypto-Abschnitt nutze AUSSCHLIESSLICH folgende verifizierte Live-Daten, 
erfinde hierzu keine eigenen Kurse:
{crypto_data}

Halte dich EXAKT an folgendes Layout:

☕ **MORNING BRIEFING | {today_str}**
───────────────────────────────

📊 **1. MARKTLAGE & SENTIMENT**
• **US-Indizes:** [1-2 Sätze zur Vorbörse S&P 500 / Nasdaq]
• **Krypto:** [Bitcoin & Ethereum Key-Levels / Zonen, basierend auf den Live-Daten oben]
• **Makro & Zinsen:** [DXY & Renditen-Einschätzung]

📅 **2. HEUTIGE KEY-EVENTS**
• ⏰ **Makro-Daten:** [Wichtigste Termine mit Uhrzeit]
• 📊 **Earnings:** [Relevanteste Q-Zahlen vor-/nachbörslich]

🎯 **3. FOCUS ASSET DES TAGES**
• **Ticker:** [Asset-Name / Symbol]
• **Key-Zone / Setup:** [Prägnantes Level & Ausblick]

───────────────────────────────
💬 *Welche Setups beobachtet ihr heute? Schreibt es in den Chat!*
"""

def generate_briefing():
    print("Sende Anfrage an Gemini API...")

    models_to_try = ['gemini-3.6-flash', 'gemini-3.5-flash-lite', 'gemini-3.1-flash-lite']

    for model_name in models_to_try:
        try:
            print(f"Versuche Modell: {model_name}...")
            response = client.models.generate_content(
                model=model_name,
                contents=f"Generiere das heutige Briefing für den {today_str}.",
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.3,
                    tools=[types.Tool(google_search=types.GoogleSearch())]
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