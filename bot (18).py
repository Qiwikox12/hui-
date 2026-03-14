import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
SERVER_URL = os.getenv("SERVER_URL", "http://localhost:5000")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


class KeyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔑 Получить ключ", style=discord.ButtonStyle.primary, custom_id="get_key")
    async def get_key(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{SERVER_URL}/generate",
                json={"user_id": str(interaction.user.id)}
            ) as resp:
                data = await resp.json()

        if not data.get("success"):
            await interaction.followup.send("❌ Ошибка. Попробуй позже.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🔑 Получение ключа",
            description=(
                f"**[👉 Нажми сюда чтобы получить ключ]({data['url']})**\n\n"
                "Пройди задание на странице — ключ появится автоматически.\n"
                "⏳ Действует **24 часа**."
            ),
            color=discord.Color.blurple()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


@bot.event
async def on_ready():
    print(f"✅ {bot.user}")
    bot.add_view(KeyView())
    await bot.tree.sync()


@bot.tree.command(name="setup", description="[Админ] Панель выдачи ключей")
@app_commands.checks.has_permissions(administrator=True)
async def setup(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🔑 Получить ключ",
        description=(
            "Нажми кнопку ниже чтобы получить свой ключ.\n\n"
            "• Действует **24 часа**\n"
            "• Вводится в скрипт один раз"
        ),
        color=discord.Color.blurple()
    )
    await interaction.channel.send(embed=embed, view=KeyView())
    await interaction.response.send_message("✅ Готово!", ephemeral=True)


@bot.tree.command(name="getkey", description="Получить ключ")
async def getkey(interaction: discord.Interaction):
    view = KeyView()
    embed = discord.Embed(title="🔑 Ключ", color=discord.Color.blurple())
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


bot.run(BOT_TOKEN)
