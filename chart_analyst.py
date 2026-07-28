import os
import discord
from discord.ext import commands
from google import genai
from google.genai import types

# 1. API-Keys & Tokens aus Umgebungsvariablen laden
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")

if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY fehlt in den Umgebungsvariablen!")

# 2. Gemini Client initialisieren (neues SDK)
client = genai.Client(api_key=GEMINI_API_KEY)

# 3. Discord Bot Client aufsetzen
intents = discord.Intents.default()
intents.message_content = True  # Erlaubt dem Bot, Nachrichten und Bilder zu lesen
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"✅ Chart Analyst Bot ist online als {bot.user}")


@bot.event
async def on_message(message):
    # Ignoriere eigene Nachrichten des Bots
    if message.author == bot.user:
        return

    # Reagiere nur, wenn ein Bild angehängt ist
    if message.attachments:
        for attachment in message.attachments:
            if any(
                attachment.filename.lower().endswith(ext)
                for ext in [".png", ".jpg", ".jpeg", ".webp"]
            ):
                await message.channel.send("🔍 *Chart erhalten! Analysiere mit Gemini 2.5 Flash...*")

                try:
                    # Bild herunterladen
                    image_data = await attachment.read()

                    # System-Prompt für die Chart-Analyse
                    prompt = (
                        "Du bist ein erfahrener Trading-Analyst. "
                        "Analysiere diesen Chart präzise. Bestimme den Trend, wichtige Support/Resistance-Zonen, "
                        "gleitende Durchschnitte (falls sichtbar) und gebe ein kurzes, sachliches Feedback."
                    )

                    # An Gemini schicken (multimodal)
                    response = client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=[
                            types.Part.from_bytes(
                                data=image_data,
                                mime_type=attachment.content_type
                                or "image/png",
                            ),
                            prompt,
                        ],
                    )

                    # Antwort im Discord-Kanal posten
                    await message.channel.send(f"📊 **Chart-Analyse:**\n\n{response.text}")

                except Exception as e:
                    await message.channel.send(f"❌ Fehler bei der Analyse: {e}")
                
                break  # Nur das erste Bild analysieren

    await bot.process_commands(message)


if __name__ == "__main__":
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        print("❌ CRITICAL: Kein DISCORD_TOKEN gefunden!")
