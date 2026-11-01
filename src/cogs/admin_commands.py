import discord
from discord import app_commands
from discord.ext import commands

from src.database import (
    get_guild_settings,
    update_guild_settings,
    get_pending_complaints,
    CATEGORIES
)


class AdminCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    config_group = app_commands.Group(
        name="judge-config",
        description="Настройка судебной системы на сервере (только для администрации)",
        default_permissions=discord.Permissions(administrator=True)
    )

    @config_group.command(name="threshold", description="Установить необходимое количество жалоб X для запуска суда")
    @app_commands.describe(value="Количество жалоб (от 1 до 50)")
    async def set_threshold(self, interaction: discord.Interaction, value: int):
        if value < 1 or value > 50:
            await interaction.response.send_message("❌ Порог должен быть в диапазоне от 1 до 50.", ephemeral=True)
            return

        await update_guild_settings(interaction.guild.id, report_threshold=value)
        await interaction.response.send_message(
            f"⚖️ Порог жалоб для инициации судебного процесса успешно установлен на **{value}**.",
            ephemeral=True
        )

    @config_group.command(name="category", description="Установить категорию для создания каналов заседаний")
    @app_commands.describe(category="Категория, в которой бот будет создавать судебные залы")
    async def set_category(self, interaction: discord.Interaction, category: discord.CategoryChannel):
        await update_guild_settings(interaction.guild.id, court_category_id=category.id)
        await interaction.response.send_message(
            f"🏛️ Категория для судебных залов установлена: **{category.name}**.",
            ephemeral=True
        )

    @config_group.command(name="speech_time", description="Время в секундах, отведенное на выступление каждой стороны")
    @app_commands.describe(seconds="Время в секундах (например, 120 = 2 минуты, максимум 600)")
    async def set_speech_time(self, interaction: discord.Interaction, seconds: int):
        if seconds < 30 or seconds > 600:
            await interaction.response.send_message("❌ Время на речь должно быть от 30 до 600 секунд.", ephemeral=True)
            return

        await update_guild_settings(interaction.guild.id, statement_timeout=seconds)
        await interaction.response.send_message(
            f"⏱️ Время на речь каждой стороны установлено на **{seconds} сек.** ({seconds // 60} мин. {seconds % 60} сек.).",
            ephemeral=True
        )

    @config_group.command(name="view", description="Показать текущие настройки суда на сервере")
    async def view_settings(self, interaction: discord.Interaction):
        settings = await get_guild_settings(interaction.guild.id)
        category_name = "Не установлена (в корне сервера)"
        if settings.get("court_category_id"):
            cat = interaction.guild.get_channel(settings["court_category_id"])
            if cat:
                category_name = cat.name

        embed = discord.Embed(
            title="⚙️ Настройки судебной системы Дредда",
            color=discord.Color.blue()
        )
        embed.add_field(name="Порог жалоб (X)", value=str(settings.get("report_threshold", 3)), inline=True)
        embed.add_field(name="Время на речь", value=f"{settings.get('statement_timeout', 180)} сек.", inline=True)
        embed.add_field(name="Категория судов", value=category_name, inline=False)
        embed.set_footer(text="Изменить настройки можно командами /judge-config <параметр>")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="dossier", description="Посмотреть досье и активные жалобы на гражданина")
    @app_commands.describe(user="Пользователь для проверки")
    async def view_dossier(self, interaction: discord.Interaction, user: discord.Member):
        settings = await get_guild_settings(interaction.guild.id)
        threshold = settings.get("report_threshold", 3)
        pending = await get_pending_complaints(interaction.guild.id, user.id)

        embed = discord.Embed(
            title=f"📁 Досье гражданина: {user.display_name}",
            description=f"Всего активных жалоб: **{len(pending)}** (Порог суда: **{threshold}** по статье)",
            color=discord.Color.dark_orange()
        )

        for cat_key, cat_meta in CATEGORIES.items():
            cat_complaints = [c for c in pending if c.get("category", "toxicity") == cat_key]
            field_name = f"{cat_meta['emoji']} {cat_meta['title']} ({len(cat_complaints)}/{threshold})"
            if cat_complaints:
                lines = [f"• <@{c['accuser_id']}>: *{c['reason']}*" for c in cat_complaints]
                field_val = "\n".join(lines)[:1024]
            else:
                field_val = "✅ Жалоб нет"
            embed.add_field(name=field_name, value=field_val, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCommands(bot))
