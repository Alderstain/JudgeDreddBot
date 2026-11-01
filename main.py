import asyncio
import logging
import sys
import discord
from discord.ext import commands

from src.config import DISCORD_TOKEN, DEV_GUILD_ID
from src.database import init_db
from src.llm_judge import LLMJudge

# Настройка логирования в консоль и в файл bot.log
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("JudgeDredd")


class JudgeBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True          # Требуется для управления участниками и мутами
        intents.message_content = True  # Требуется для сбора речей участников в суде

        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None
        )
        self.llm_judge = LLMJudge()

    async def setup_hook(self):
        logger.info("Инициализация базы данных SQLite...")
        await init_db()

        # Загружаем коги
        logger.info("Загрузка расширений (cogs)...")
        await self.load_extension("src.cogs.report_commands")
        logger.info("Cog report_commands загружен.")
        await self.load_extension("src.cogs.admin_commands")
        logger.info("Cog admin_commands загружен.")

        # Синхронизация slash-команд в фоновом режиме, чтобы не задерживать старт бота
        async def sync_commands():
            try:
                if DEV_GUILD_ID:
                    guild_obj = discord.Object(id=int(DEV_GUILD_ID))
                    self.tree.copy_global_to(guild=guild_obj)
                    await self.tree.sync(guild=guild_obj)
                    logger.info(f"Slash-команды синхронизированы для гильдии {DEV_GUILD_ID}")
                else:
                    logger.info("Начало фоновой глобальной синхронизации команд...")
                    await self.tree.sync()
                    logger.info("Глобальные slash-команды успешно синхронизированы!")
            except Exception as e:
                logger.warning(f"Ошибка при синхронизации команд: {e}")

        # Запуск синка в фоне, чтобы бот подключился к Discord мгновенно
        self.loop.create_task(sync_commands())

    async def on_ready(self):
        logger.info(f"Судья Дредд заступил на службу! Авторизован как: {self.user} (ID: {self.user.id})")
        logger.info(f"Активных серверов: {len(self.guilds)}")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="за порядком | /report"
            )
        )


bot = JudgeBot()


@bot.command(name="sync")
@commands.has_permissions(administrator=True)
async def sync_cmd(ctx: commands.Context):
    """Принудительная ручная синхронизация слэш-команд по команде !sync."""
    msg = await ctx.send("⏳ Синхронизация команд с Discord...")
    try:
        synced = await ctx.bot.tree.sync()
        await msg.edit(content=f"✅ Успешно синхронизировано {len(synced)} слэш-команд!")
    except Exception as e:
        await msg.edit(content=f"❌ Ошибка синхронизации: {e}")


async def main():
    if not DISCORD_TOKEN:
        logger.error("КРИТИЧЕСКАЯ ОШИБКА: DISCORD_TOKEN не указан в .env файле!")
        logger.error("Создайте файл .env на основе .env.example и укажите токен вашего бота.")
        return

    async with bot:
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
