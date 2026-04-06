import os
import discord
from discord.ext import commands
import requests
from gtts import gTTS
from discord import FFmpegPCMAudio

# -----------------------
# Konfiguration
# -----------------------
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")  # Dein Bot-Token
AGENT_URL = os.getenv("AGENT_URL", "http://agent-layer:8080/v1")  # Agent-Layer URL
VOICE_CHANNEL_ID = int(os.getenv("VOICE_CHANNEL_ID", 0))  # Optional: default Voice-Channel

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

# -----------------------
# Hilfsfunktionen
# -----------------------
def ask_agent(prompt: str) -> str:
    """Sendet Prompt an den Agent-Layer und holt die Antwort."""
    try:
        response = requests.post(f"{AGENT_URL}/generate", json={"prompt": prompt})
        data = response.json()
        return data.get("output_text", "Keine Antwort erhalten.")
    except Exception as e:
        return f"Fehler beim Agent-Layer: {e}"

def speak_text(channel: discord.VoiceChannel, text: str):
    """Konvertiert Text in TTS und spielt ihn im Voice-Channel ab."""
    tts = gTTS(text=text, lang="de")
    tts.save("speech.mp3")
    source = FFmpegPCMAudio("speech.mp3")
    if not channel.guild.voice_client:
        channel.connect()  # Erst verbinden, falls noch nicht
    vc = channel.guild.voice_client
    vc.play(source)

# -----------------------
# Events & Commands
# -----------------------
@bot.event
async def on_ready():
    print(f"Bot ist online als {bot.user}!")

@bot.command()
async def ask(ctx, *, prompt: str):
    """Fragt den Agent-Layer und antwortet per Text und optional TTS."""
    answer = ask_agent(prompt)
    await ctx.send(answer)

    # Optional TTS
    if VOICE_CHANNEL_ID:
        channel = bot.get_channel(VOICE_CHANNEL_ID)
        if channel and isinstance(channel, discord.VoiceChannel):
            vc = await channel.connect() if not channel.guild.voice_client else channel.guild.voice_client
            speak_text(channel, answer)

# -----------------------
# Bot starten
# -----------------------
if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)