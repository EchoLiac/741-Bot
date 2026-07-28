import os
import discord
from google import genai
from google.genai import types

# --- CONFIGURATION ---
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TARGET_CHANNEL_NAME = "ki-chart-check"

if not DISCORD_TOKEN or not GEMINI_API_KEY:
    raise ValueError("FEHLER: DISCORD_TOKEN oder GEMINI_API_KEY fehlt in den Environment Variables!")

# Gemini Setup (neue Bibliothek)
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# Discord Setup
intents = discord.Intents.default()
intents.message_content = True
discord_client = discord.Client(intents=intents)

SYSTEM_PROMPT = """
Du bist ein hochprofessioneller KI-Chart-Analyst für die Community "Investieren741". 
Analysiere das hochgeladene Chart-Bild und antworte EXAKT in folgendem strukturierten Schema:

📊 **KI CHART-CHECK | [ASSET / TICKER]**
*Analysierter Trend & Aufbau*

---

### 1. 📐 Fibonacci & Trendlinien Check
• **Ankerpunkte:** [Identifizierte Swing Highs / Lows]
• **Key-Levels:** Golden Pocket (61,8% - 65%) bei [Preis], 0.382 bei [Preis]
• **Trendlinien:** [Verlauf & Touchpoints der Haupttrendlinie]
• **Status:** [✅ KORREKT / ⚠️ ANPASSEN] – *[1 Satz Begründung]*

### 2. 💡 Indikatoren & Konfluenz
• **200 EMA:** Kurs notiert [über/unter] der 200 EMA bei [Preis]
• **Konfluenz-Zone:** Starker Support/Resistance im Bereich [Preis-Range]
• **Status:** [✅ KORREKT / ⚠️ ANPASSEN] – *[1 Satz Begründung]*

### 3. 🎯 Trade-Setup ([LONG / SHORT])
• **Trigger:** [Voraussetzung für Bestätigung]
• 📥 **Entry:** [Preis-Range]
• 🛑 **Stop Loss (SL):** [Preis]
• 🎯 **Take Profit 1:** [Preis]
• 🎯 **Take Profit 2:** [Preis]

---
🚦 **GESAMT-RATING:** [✅ APPROVED / ⚠️ REVISION REQUIRED]
"""

@discord_client.event
async def on_ready():
    print(f"✅ Bot ist online und eingeloggt als {discord_client.user}")

@discord_client.event
async def on_message(message):
    # Ignoriere eigene Nachrichten
    if message.author == discord_client.user:
        return

    # Prüfen, ob die Nachricht im richtigen Kanal gepostet wurde
    if message.channel.name != TARGET_CHANNEL_NAME:
        return

    # Prüfe auf Bilder-Uploads
    image_attachments = [
        att for att in message.attachments 
        if any(att.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.webp'])
    ]

    if not image_attachments:
        return

    # Nachricht signalisieren, dass der Bot "tippt"
    async with message.channel.typing():
        try:
            attachment = image_attachments[0]
            image_bytes = await attachment.read()
            user_text = message.content if message.content else "Keine gesonderte These angegeben."

            full_prompt = f"{SYSTEM_PROMPT}\n\nUser-Kommentar zum Bild: '{user_text}'"

            # Bild & Prompt an Gemini senden (mit Part-Objekt für Inline-Data)
            response = gemini_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[
                    full_prompt,
                    types.Part.from_bytes(
                        data=image_bytes,
                        mime_type=attachment.content_type or 'image/png'
                    )
                ]
            )

            # Antwort als Reply an den User senden
            await message.reply(response.text)
            print(f"Chart-Check ausgeführt für {message.author}")

        except Exception as e:
            print(f"Fehler bei der Chart-Analyse: {e}")
            await message.reply("⚠️ *Fehler bei der Bildanalyse. Bitte versuche es erneut.*")

if __name__ == "__main__":
    discord_client.run(DISCORD_TOKEN)
