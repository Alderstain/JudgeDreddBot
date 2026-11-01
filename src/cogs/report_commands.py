import logging
import discord
from discord import app_commands
from discord.ext import commands

from src.database import (
    get_guild_settings,
    add_complaint,
    get_pending_complaints,
    CATEGORIES
)
from src.trial_manager import TrialSession
from src.llm_judge import LLMJudge

logger = logging.getLogger(__name__)


class ReportModal(discord.ui.Modal, title="Жалоба в Верховный Суд"):
    def __init__(self, target_user: discord.Member, category: str, cog: "ReportCommands"):
        super().__init__()
        self.target_user = target_user
        self.category = category
        self.cog = cog

        cat_title = CATEGORIES.get(category, {}).get("title", category)
        self.reason_input = discord.ui.TextInput(
            label=f"Суть по статье «{cat_title}»",
            style=discord.TextStyle.paragraph,
            placeholder="Опишите факты правонарушения...",
            required=True,
            min_length=10,
            max_length=1000
        )
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.process_report(
            interaction=interaction,
            accused=self.target_user,
            reason=self.reason_input.value,
            category=self.category
        )


class CategorySelectView(discord.ui.View):
    """Меню выбора категории правонарушения перед открытием формы."""
    def __init__(self, target_user: discord.Member, cog: "ReportCommands"):
        super().__init__(timeout=60)
        self.target_user = target_user
        self.cog = cog

    @discord.ui.select(
        placeholder="Выберите статью правонарушения...",
        options=[
            discord.SelectOption(
                label="Токсичность",
                value="toxicity",
                description="Оскорбления, агрессия, травля, провокации",
                emoji="☣️"
            ),
            discord.SelectOption(
                label="Дебош",
                value="disorder",
                description="Спам, флуд, помехи в чате или голосовых каналах",
                emoji="📢"
            ),
            discord.SelectOption(
                label="Вредительство",
                value="sabotage",
                description="Спойлеры, слив информации, порча игр или мероприятий",
                emoji="💣"
            )
        ]
    )
    async def select_category(self, interaction: discord.Interaction, select: discord.ui.Select):
        category = select.values[0]
        modal = ReportModal(target_user=self.target_user, category=category, cog=self.cog)
        await interaction.response.send_modal(modal)


class ReportCommands(commands.Cog):
    def __init__(self, bot: commands.Bot, llm_judge: LLMJudge):
        self.bot = bot
        self.llm_judge = llm_judge
        self.active_trials = set()

        self.ctx_menu = app_commands.ContextMenu(
            name="Подать жалобу в суд",
            callback=self.context_report
        )
        self.bot.tree.add_command(self.ctx_menu)

    async def context_report(self, interaction: discord.Interaction, member: discord.Member):
        if member.id == interaction.user.id:
            await interaction.response.send_message("❌ Нельзя подать жалобу на самого себя!", ephemeral=True)
            return
        if member.bot:
            await interaction.response.send_message("❌ Боты неподсудны трибуналу!", ephemeral=True)
            return

        view = CategorySelectView(target_user=member, cog=self)
        await interaction.response.send_message(
            f"⚖️ Выберите категорию правонарушения для подачи жалобы на {member.mention}:",
            view=view,
            ephemeral=True
        )

    @app_commands.command(name="test-trial", description="[ТЕСТ] Запустить симуляцию суда над собой с виртуальными обвинителями")
    @app_commands.describe(scenario="Статья правонарушения для проверки ИИ-судьи")
    @app_commands.choices(scenario=[
        app_commands.Choice(name="☣️ Токсичность (оскорбления, травля)", value="toxicity"),
        app_commands.Choice(name="📢 Дебош (спам, флуд, оффтоп)", value="disorder"),
        app_commands.Choice(name="💣 Вредительство (спойлеры, слив, срыв)", value="sabotage")
    ])
    async def test_trial(self, interaction: discord.Interaction, scenario: app_commands.Choice[str]):
        """Тестовая команда для проверки всего цикла суда в одиночку."""
        guild = interaction.guild
        user = interaction.user

        if user.id in self.active_trials:
            await interaction.response.send_message("❌ Над вами уже идет судебный процесс!", ephemeral=True)
            return

        scenarios_data = {
            "disorder": [
                "Отправил 40 стикеров подряд за 10 секунд и зафлудил важный анонс.",
                "Пинговал всех участников сервера посреди ночи без уважительной причины.",
                "Игнорировал устные предупреждения прекратить флуд и громко кричал в голосовом канале."
            ],
            "toxicity": [
                "Публично назвал администрацию сервера некомпетентными бюрократами.",
                "Спровоцировал агрессивный конфликт на ровном месте в общем чате.",
                "Употреблял ненормативную лексику и унижал новичков сообщества."
            ],
            "sabotage": [
                "Опубликовал в общем чате ключевые спойлеры к финалу без защитного тега.",
                "Намеренно разрушил постройки союзников во время игрового ивента.",
                "Слил закрытую информацию из приватного модераторского канала."
            ]
        }

        category_key = scenario.value
        reasons = scenarios_data.get(category_key, scenarios_data["toxicity"])
        mock_complaints = [
            {"id": -(i + 1), "reason": r, "accuser_id": interaction.client.user.id, "category": category_key}
            for i, r in enumerate(reasons)
        ]

        await interaction.response.send_message(
            f"🚀 **Запуск тестового судебного процесса!**\n"
            f"Статья обвинения: **{scenario.name}**\n"
            f"Создается зал суда. Вы выступаете в роли обвиняемого.",
            ephemeral=True
        )

        self.active_trials.add(user.id)

        session = TrialSession(
            bot=self.bot,
            guild=guild,
            accused=user,
            accusers=[guild.me],
            complaints=mock_complaints,
            llm_judge=self.llm_judge,
            category=category_key
        )

        async def run_trial():
            try:
                await session.start()
            finally:
                self.active_trials.discard(user.id)

        self.bot.loop.create_task(run_trial())

    @app_commands.command(name="report", description="Подать официальную жалобу на пользователя сервера")
    @app_commands.describe(
        user="Пользователь, нарушивший порядок",
        category="Статья правонарушения",
        reason="Подробная причина жалобы (минимум 10 символов)"
    )
    @app_commands.choices(category=[
        app_commands.Choice(name="☣️ Токсичность (оскорбления, агрессия, травля)", value="toxicity"),
        app_commands.Choice(name="📢 Дебош (спам, флуд, помехи в чате/войсе)", value="disorder"),
        app_commands.Choice(name="💣 Вредительство (спойлеры, слив информации, порча игр)", value="sabotage")
    ])
    async def report_command(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        category: app_commands.Choice[str],
        reason: str
    ):
        if user.id == interaction.user.id:
            await interaction.response.send_message("❌ Вы не можете подать жалобу на самого себя!", ephemeral=True)
            return

        if user.bot:
            await interaction.response.send_message("❌ Нельзя подать жалобу на бота!", ephemeral=True)
            return

        if len(reason.strip()) < 10:
            await interaction.response.send_message("❌ Причина жалобы должна содержать не менее 10 символов.", ephemeral=True)
            return

        await self.process_report(interaction, user, reason, category=category.value)

    async def process_report(self, interaction: discord.Interaction, accused: discord.Member, reason: str, category: str = "toxicity"):
        guild = interaction.guild
        accuser = interaction.user

        if accused.id in self.active_trials:
            await interaction.response.send_message(
                f"⚖️ В отношении {accused.mention} прямо сейчас уже идет судебное заседание!",
                ephemeral=True
            )
            return

        success = await add_complaint(
            guild_id=guild.id,
            accuser_id=accuser.id,
            accused_id=accused.id,
            category=category,
            reason=reason.strip()
        )

        cat_meta = CATEGORIES.get(category, {"title": category, "emoji": "⚖️"})

        if not success:
            await interaction.response.send_message(
                f"⚠️ Вы уже подавали активную жалобу на {accused.mention} по статье **{cat_meta['emoji']} {cat_meta['title']}**. Дождитесь рассмотрения текущего дела.",
                ephemeral=True
            )
            return

        settings = await get_guild_settings(guild.id)
        threshold = settings.get("report_threshold", 3)
        pending_complaints = await get_pending_complaints(guild.id, accused.id, category=category)
        current_count = len(pending_complaints)

        await interaction.response.send_message(
            f"✅ Ваша жалоба на {accused.mention} по статье **{cat_meta['emoji']} {cat_meta['title']}** зарегистрирована канцелярией суда!\n"
            f"📊 Накоплено жалоб по данной статье: **{current_count} / {threshold}** для инициации открытого процесса.",
            ephemeral=True
        )

        if current_count >= threshold and accused.id not in self.active_trials:
            self.active_trials.add(accused.id)
            
            accuser_members = []
            for c in pending_complaints:
                m = guild.get_member(c["accuser_id"])
                if m and m not in accuser_members:
                    accuser_members.append(m)

            session = TrialSession(
                bot=self.bot,
                guild=guild,
                accused=accused,
                accusers=accuser_members,
                complaints=pending_complaints,
                llm_judge=self.llm_judge,
                category=category
            )

            async def run_trial_wrapper():
                try:
                    await session.start()
                finally:
                    self.active_trials.discard(accused.id)

            self.bot.loop.create_task(run_trial_wrapper())


async def setup(bot: commands.Bot):
    llm_judge = getattr(bot, "llm_judge", LLMJudge())
    await bot.add_cog(ReportCommands(bot, llm_judge))
