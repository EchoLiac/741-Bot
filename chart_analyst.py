import os
import json
import discord
from discord.ext import commands
import google.generativeai as genai

# --- CONFIGURATION ---
# Secrets aus GitHub Umgebungsvariablen
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")

# Kanal-IDs aus deinen Links
ANALYSE_CHANNEL_ID = 1504371268265447624   # Chart Analyse Kanal
WATCHLIST_CHANNEL_ID = 1527427760908402810 # Watchlist Kanal

SEEN_FILE = "seen_ids_watchlist.json"

# --- GEMINI SETUP ---
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# --- DISCORD SETUP ---
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

def load_seen_ids():
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_seen_ids(seen_ids):
    with open(SEEN_FILE, "w") as f:
        json.dump(seen_ids, f)

@client.event
async def on_ready():
    print(f'Eingeloggt als {client.user}')
    seen_ids = load_seen_ids()
    
    analyse_channel = client.get_channel(ANALYSE_CHANNEL_ID)
    watchlist_channel = client.get_channel(WATCHLIST_CHANNEL_ID)
    
    if not analyse_channel or not watchlist_channel:
        print("Fehler: Mindestens ein Kanal wurde nicht gefunden!")
        await client.close()
        return

    # Letzte Nachrichten aus #chart-analyse abrufen
    async for message in analyse_channel.history(limit=10):
        if str(message.id) in seen_ids or message.author.bot:
            continue
            
        content = message.content
        if not content and not message.attachments:
            continue
            
        # KI-Prompt für exakte Kanal-Tags
        prompt = f"""
        Du bist ein Trading-Assistent für den Discord-Server. Analysiere folgende Nachricht/Analyse:
        "{content}"
        
        Erstelle eine prägnante Zusammenfassung für den Kanal #watchlist.
        Verwende ausschließlich passende Tags aus dieser offiziellen Server-Auswahl:
        - Status: 👀|Beobachten, 🟢🚀|Aktiv, 🔴❌|Invalidiert, 🏆🎯|Ziel / TP, 🔴|Kein Einstieg
        - Asset: 📈|Aktien, 🌕|Krypto, 📊|Indizes & FX, 🛢️|Rohstoffe
        - Richtung: 🟢|Long/Call, 🔴|Short/Put, 📄|Option
        - Typ: 💡|Trading-Setup, 🔍|Analyse, ⏱️|Swingtrade, ⚡|Breakout, 🔄|Rebound, 📅|Earnings, 💼|Langzeit Invest, 📌|Update
        
        Formatiere das Ergebnis übersichtlich (Titel, Key-Levels, Kurzbegründung, Tags).
        """
        
        try:
            response = model.generate_content(prompt)
            
            # In #watchlist posten
            await watchlist_channel.send(response.text)
            
            # ID speichern, damit sie nicht doppelt verarbeitet wird
            seen_ids.append(str(message.id))
            print(f"Nachricht {message.id} erfolgreich verarbeitet.")
        except Exception as e:
            print(f"Fehler bei der KI-Generierung: {e}")

    save_seen_ids(seen_ids)
    await client.close()

if __name__ == "__main__":
    if DISCORD_TOKEN:
        client.run(DISCORD_TOKEN)
    else:
        print("Fehler: Kein DISCORD_TOKEN gefunden!")
