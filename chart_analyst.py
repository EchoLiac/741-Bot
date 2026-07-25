import json
import os
import discord
import google.generativeai as genai

# --- CONFIGURATION ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TARGET_CHANNEL_NAME = "ki-chart-check"
SEEN_FILE = "processed_chart_checks.json"

# Gemini setup
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# Discord Setup
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

def load_seen_ids():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, 'r') as f:
            return set(json.load(f))
    return set()

def save_seen_ids(seen_ids):
    with open(SEEN_FILE, 'w') as f:
        json.dump(list(seen_ids), f)

@client.event
async def on_ready():
    print(f'Bot eingeloggt als {client.user}')
    seen_ids = load_seen_ids()
    
    # Kanal suchen
    channel = discord.utils.get(client.guilds[0].channels, name=TARGET_CHANNEL_NAME)
    if not channel:
        print(f"Kanal '{TARGET_CHANNEL_NAME}' nicht gefunden!")
        await client.close()
        return

    # Letzte 20 Nachrichten durchsuchen
    async for message in channel.history(limit=20, oldest_first=True):
        if message.id in seen_ids or message.author == client.user:
            continue
            
        # Prüfen, ob Bild im Beitrag vorhanden ist
        image_attachments = [
            att for att in message.attachments 
            if any(att.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.webp'])
        ]
        
        if image_attachments:
            print(f"Verarbeite Nachricht von {message.author} (ID: {message.id})...")
            attachment = image_attachments[0]
            image_bytes = await attachment.read()
            
            user_text = message.content if message.content else "Keine gesonderte These angegeben."
            
            # System-Prompt für Gemini
            prompt = f"""
Du bist ein professioneller Trading-Coach mit Schwerpunkt auf Price Action, Fibonacci & Volume Profile.
Der User hat ein Chart-Bild hochgeladen und folgende These / Text dazu geschrieben:
"{user_text}"

Analysiere das Bild und antworte kurz und strukturiert:

1. 📏 **Fibo-Check**: Sind die Fibonacci-Level richtig gezogen? (Stimmen Swing Low / Swing High Anchor-Punkte für die Trendrichtung?)
2. 🎯 **Thesen-Prüfung**: Ist die Idee valide? Liegt der Bereich an einer wichtigen Zone (Golden Pocket 61.8%, POC, Support/Resistance)?
3. 🚥 **Bewertung**: Gib eine klare Einstufung: [🟢 KORREKT] oder [🔴 KORREKTURBEDARF].
4. 💡 **Setup-Idee & Tipp**: Gib kurze Vorschläge für Entry-Zone, Stop-Loss-Bereich und nächstes Target oder wie die Fibos korrigiert werden müssen.
            """
            
            try:
                response = model.generate_content([
                    prompt, 
                    {"mime_type": attachment.content_type, "data": image_bytes}
                ])
                
                # Antwort in Discord posten
                await message.reply(f"🤖 **KI Chart-Analyse:**\n\n{response.text}")
                seen_ids.add(message.id)
                
            except Exception as e:
                print(f"Fehler bei der Gemini-Analyse: {e}")
                
    save_seen_ids(seen_ids)
    print("Testdurchlauf beendet.")
    await client.close()

client.run(DISCORD_TOKEN)
