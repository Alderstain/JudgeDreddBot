import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
DEV_GUILD_ID = os.getenv("DEV_GUILD_ID", None)

# Настройки по умолчанию
DEFAULT_REPORT_THRESHOLD = 3      # Сколько жалоб нужно для запуска суда
DEFAULT_STATEMENT_TIMEOUT = 180   # Время на выступление одной стороны в секундах (3 минуты)
DEFAULT_DELIBERATION_TIME = 15    # Имитация раздумий суда перед оглашением
DEFAULT_CHANNEL_ARCHIVE_TIMEOUT = 600 # 10 минут перед удалением/архивацией канала после вердикта
