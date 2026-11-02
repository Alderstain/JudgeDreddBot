import asyncio
import datetime
import logging
from typing import List, Dict, Any, Optional
import discord
from discord.ui import Button, View

from src.database import (
    get_guild_settings,
    create_case,
    update_case_channel,
    close_case,
    CATEGORIES
)
from src.llm_judge import LLMJudge, VerdictResult
from src.llm_advocate import LLMAdvocate, AdvocateSpeechResult

logger = logging.getLogger(__name__)


class JuryVoteView(View):
    """Интерактивное голосование коллегии присяжных заседателей (зрителей зала суда)."""
    def __init__(self, accused_id: int, accuser_ids: List[int], timeout_seconds: int = 60):
        super().__init__(timeout=timeout_seconds)
        self.accused_id = accused_id
        self.accuser_ids = set(accuser_ids)
        self.votes: Dict[int, str] = {}  # user_id -> 'guilty' | 'innocent'
        self.message: Optional[discord.Message] = None

    def get_counts(self) -> Dict[str, int]:
        guilty = sum(1 for v in self.votes.values() if v == "guilty")
        innocent = sum(1 for v in self.votes.values() if v == "innocent")
        return {"guilty": guilty, "innocent": innocent}

    def build_embed(self, is_closed: bool = False, time_left: Optional[int] = None) -> discord.Embed:
        counts = self.get_counts()
        total = counts["guilty"] + counts["innocent"]

        color = discord.Color.gold() if not is_closed else discord.Color.dark_grey()
        status_line = (
            f"⏱️ До окончания голосования: **{max(0, time_left or 0)} сек.**"
            if not is_closed
            else "🔒 **Голосование присяжных завершено! Результаты переданы Судье.**"
        )

        embed = discord.Embed(
            title="👥 СЛОВО КОЛЛЕГИИ ПРИСЯЖНЫХ ЗАСЕДАТЕЛЕЙ",
            description=(
                f"Граждане и зрители судебного процесса могут выразить волю сервера!\n"
                f"{status_line}\n\n"
                f"🔴 **Виновен:** `{counts['guilty']}`\n"
                f"🟢 **Невиновен:** `{counts['innocent']}`\n"
                f"📊 Всего голосов присяжных: **{total}**\n\n"
                f"*(Обвиняемый и прямые обвинители от голосования отстранены во избежание конфликта интересов)*"
            ),
            color=color
        )
        embed.set_footer(text="Судья Дредд учтет голос народа при оглашении приговора.")
        return embed

    @discord.ui.button(label="Виновен 🔴", style=discord.ButtonStyle.danger, custom_id="jury_guilty")
    async def guilty_button(self, interaction: discord.Interaction, button: Button):
        await self._process_vote(interaction, "guilty")

    @discord.ui.button(label="Невиновен 🟢", style=discord.ButtonStyle.success, custom_id="jury_innocent")
    async def innocent_button(self, interaction: discord.Interaction, button: Button):
        await self._process_vote(interaction, "innocent")

    async def _process_vote(self, interaction: discord.Interaction, choice: str):
        voter_id = interaction.user.id

        if voter_id == self.accused_id:
            await interaction.response.send_message("❌ Подсудимый не может входить в состав присяжных по своему делу!", ephemeral=True)
            return

        if voter_id in self.accuser_ids:
            await interaction.response.send_message("❌ Обвинители являются стороной процесса и не имеют голоса в коллегии присяжных!", ephemeral=True)
            return

        already_voted = self.votes.get(voter_id)
        if already_voted == choice:
            await interaction.response.send_message("ℹ️ Вы уже отдали этот голос.", ephemeral=True)
            return

        self.votes[voter_id] = choice
        choice_text = "ВИНОВЕН 🔴" if choice == "guilty" else "НЕВИНОВЕН 🟢"
        await interaction.response.send_message(f"✅ Ваш голос присяжного зафиксирован: **{choice_text}**.", ephemeral=True)

        try:
            if self.message:
                await self.message.edit(embed=self.build_embed(is_closed=False))
        except Exception:
            pass


class TrialSession:
    def __init__(
        self,
        bot: discord.Client,
        guild: discord.Guild,
        accused: discord.Member,
        accusers: List[discord.Member],
        complaints: List[Dict[str, Any]],
        llm_judge: LLMJudge,
        category: str = "toxicity"
    ):
        self.bot = bot
        self.guild = guild
        self.accused = accused
        self.accusers = accusers
        self.complaints = complaints
        self.llm_judge = llm_judge
        self.advocate = LLMAdvocate()
        self.category = category

        self.channel: Optional[discord.TextChannel] = None
        self.case_number: int = 0
        self.prosecution_records: List[Dict[str, str]] = []
        self.defense_record: str = ""
        self.advocate_speech: str = ""
        self.jury_votes: Dict[str, int] = {"guilty": 0, "innocent": 0}

    async def start(self):
        try:
            settings = await get_guild_settings(self.guild.id)
            speech_timeout = settings.get("statement_timeout", 180)

            # 1. Создаем запись о деле в БД с категорией
            complaint_ids = [c["id"] for c in self.complaints]
            self.case_number = await create_case(self.guild.id, self.accused.id, complaint_ids, category=self.category)

            # 2. Создаем открытый канал суда
            cat_obj = None
            if settings.get("court_category_id"):
                cat_obj = self.guild.get_channel(settings["court_category_id"])

            channel_name = f"дело-{self.case_number}-{self.category}"
            
            # Настройка прав: публичный просмотр для всех, но писать никому нельзя
            overwrites = {
                self.guild.default_role: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=False,
                    add_reactions=False
                ),
                self.guild.me: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    manage_channels=True,
                    manage_permissions=True,
                    embed_links=True
                ),
                self.accused: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=False
                )
            }
            for accuser in self.accusers:
                overwrites[accuser] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=False
                )

            self.channel = await self.guild.create_text_channel(
                name=channel_name,
                category=cat_obj,
                overwrites=overwrites,
                topic=f"Судебный процесс №{self.case_number} ({self.category}) над {self.accused.display_name}. Публичные слушания."
            )

            await update_case_channel(self.guild.id, self.case_number, self.channel.id)

            # 3. Вступительная часть
            await self._announce_trial()

            # 4. Выступление обвинителей по очереди
            await self._run_prosecution_phase(speech_timeout)

            # 5. Выступление защиты и адвоката Сола Гудмана
            await self._run_defense_phase(speech_timeout)

            # 6. Голосование коллегии присяжных (зрителей)
            jury_enabled = bool(settings.get("jury_voting_enabled", 1))
            if jury_enabled:
                jury_duration = settings.get("jury_voting_duration", 60)
                await self._run_jury_phase(jury_duration)

            # 7. Совещание суда и вынесение вердикта
            await self._deliberate_and_judge()

        except Exception as e:
            logger.error(f"Ошибка во время судебного заседания: {e}", exc_info=True)
            if self.channel:
                await self.channel.send(f"⚠️ **В процессе заседания произошла ошибка:** {e}")

    async def _announce_trial(self):
        cat_meta = CATEGORIES.get(self.category, {
            "title": self.category,
            "description": "Нарушение порядка",
            "emoji": "⚖️"
        })

        embed = discord.Embed(
            title=f"⚖️ СУДЕБНОЕ ЗАСЕДАНИЕ: ДЕЛО №{self.case_number}",
            description=(
                f"В отношении гражданина **{self.accused.mention}** открыто судебное производство!\n"
                f"Статья обвинения: **{cat_meta['emoji']} {cat_meta['title'].upper()}**\n"
                f"*{cat_meta['description']}*\n\n"
                f"Накопилось жалоб по данной статье: **{len(self.complaints)}**.\n"
                f"🏛️ **Суд объявляется открытым! Все граждане могут наблюдать за процессом.**"
            ),
            color=discord.Color.dark_red(),
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )

        accusers_mentions = ", ".join([a.mention for a in self.accusers])
        embed.add_field(name="Обвинители", value=accusers_mentions, inline=False)
        embed.add_field(name="Обвиняемый", value=self.accused.mention, inline=False)

        reasons_text = ""
        for i, c in enumerate(self.complaints, 1):
            reasons_text += f"**{i}.** {c['reason']}\n"
        embed.add_field(name=f"Суть жалоб ({cat_meta['title']})", value=reasons_text or "Причина не указана", inline=False)

        embed.set_footer(text="Закон есть Закон. Судья Дредд следит за процессом.")

        pings = f"{self.accused.mention} " + " ".join([a.mention for a in self.accusers])
        await self.channel.send(content=pings, embed=embed)
        await asyncio.sleep(4)

    async def _collect_user_statements(self, user: discord.Member, timeout_seconds: int) -> str:
        """Включает пользователю право писать. Как только он отправляет сообщение — фиксирует его и сразу передает ход дальше."""
        await self.channel.set_permissions(user, overwrite=discord.PermissionOverwrite(send_messages=True, view_channel=True))

        prompt_msg = await self.channel.send(
            f"🎙️ **{user.mention}**, трибуна ваша! Отправьте сообщение с вашей позицией в этот чат.\n"
            f"⏱️ Время на ответ: **{timeout_seconds // 60} мин. {timeout_seconds % 60} сек.** "
            f"*(суд продолжит заседание сразу после вашего сообщения)*"
        )

        def check(m: discord.Message):
            return m.author.id == user.id and m.channel.id == self.channel.id and bool(m.content.strip())

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=timeout_seconds)
            speech = msg.content.strip()
            try:
                await msg.add_reaction("⚖️")
            except Exception:
                pass
        except asyncio.TimeoutError:
            speech = "*(Участник промолчал)*"

        # Забираем права писать обратно
        await self.channel.set_permissions(user, overwrite=discord.PermissionOverwrite(send_messages=False, view_channel=True))
        
        try:
            await prompt_msg.edit(content=f"🔒 Показания **{user.display_name}** приобщены к делу.")
        except Exception:
            pass

        return speech

    async def _run_prosecution_phase(self, timeout_seconds: int):
        phase_embed = discord.Embed(
            title="📜 ЭТАП 1: СЛОВО ОБВИНЕНИЯ",
            description="Каждый из обвинителей по очереди вызывается для дачи показаний и разъяснения сути претензий.",
            color=discord.Color.gold()
        )
        await self.channel.send(embed=phase_embed)
        await asyncio.sleep(2)

        for i, accuser in enumerate(self.accusers, 1):
            if accuser.id == self.bot.user.id:
                complaints_summary = "\n".join([f"• {c['reason']}" for c in self.complaints])
                speech = f"Сторона обвинения заявляет о грубых правонарушениях со стороны обвиняемого:\n{complaints_summary}\nТребуем признать виновным и изолировать от общества!"
                await self.channel.send(f"📢 **Обвинитель (Гособвинение) зачитывает обвинительный акт:**\n> {speech}")
                self.prosecution_records.append({
                    "author": "Гособвинитель (Сторона Закона)",
                    "text": speech
                })
                await asyncio.sleep(3)
                continue

            await self.channel.send(f"📢 **Обвинитель #{i} — {accuser.mention}, к барьеру!**")
            speech = await self._collect_user_statements(accuser, timeout_seconds)
            self.prosecution_records.append({
                "author": f"{accuser.display_name} ({accuser.id})",
                "text": speech
            })
            await asyncio.sleep(2)

    async def _run_defense_phase(self, timeout_seconds: int):
        cat_meta = CATEGORIES.get(self.category, {"title": self.category})

        advocate_intro = discord.Embed(
            title="💼 В ДЕЛО ВСТУПАЕТ АДВОКАТ СОЛ ГУДМАН!",
            description=(
                f"**Конституция Сервера гарантирует каждому гражданину право на защиту!**\n"
                f"Интересы гражданина {self.accused.mention} в суде представляет частный кибер-адвокат "
                f"**Соломон «Сол» Гудман** (*«Лучше звоните Солу!»*).\n\n"
                f"🤫 **Сол Гудман берет слово:**\n"
                f"> *«Спокойно, дружище {self.accused.display_name}! Дядя Сол здесь, а значит Закон на нашей стороне. "
                f"Черкни мне прямо сюда в чат, как всё было на самом деле. Не стесняйся в выражениях — "
                f"я упакую твои слова в несокрушимый юридический титановый щит!»*"
            ),
            color=discord.Color.gold()
        )
        advocate_intro.set_footer(text="У подсудимого есть время, чтобы объяснить ситуацию адвокату.")
        await self.channel.send(embed=advocate_intro)
        await asyncio.sleep(2)

        raw_defense = await self._collect_user_statements(self.accused, timeout_seconds)
        self.defense_record = raw_defense

        preparing_msg = await self.channel.send("💼 *Сол Гудман изучает материалы дела, листает кодексы и выходит к трибуне...*")

        advocate_result: AdvocateSpeechResult = await self.advocate.prepare_defense(
            accused_name=f"{self.accused.display_name} (@{self.accused.name})",
            category_name=cat_meta["title"],
            prosecution_statements=self.prosecution_records,
            client_raw_story=self.defense_record
        )

        full_advocate_text = (
            f"**{advocate_result.catchphrase}**\n\n"
            f"{advocate_result.main_speech}\n\n"
            f"⚖️ **Требование защиты:** {advocate_result.closing_demand}"
        )
        self.advocate_speech = full_advocate_text

        speech_embed = discord.Embed(
            title=f"💼 РЕЧЬ АДВОКАТА СОЛА ГУДМАНА В ЗАЩИТУ {self.accused.display_name.upper()}",
            description=f"*{advocate_result.catchphrase}*",
            color=discord.Color.from_rgb(255, 191, 0)
        )
        speech_embed.add_field(
            name="📜 Слово Защиты",
            value=advocate_result.main_speech[:1024],
            inline=False
        )
        speech_embed.add_field(
            name="⚡ Итоговое требование адвоката",
            value=advocate_result.closing_demand[:1024],
            inline=False
        )
        speech_embed.set_footer(text="Адвокатское бюро 'Сол Гудман и Партнёры' | Megacity-1")

        await preparing_msg.delete()
        await self.channel.send(embed=speech_embed)
        await asyncio.sleep(4)

    async def _run_jury_phase(self, duration_seconds: int):
        """Фаза голосования зрителей зала суда (коллегии присяжных)."""
        accuser_ids = [a.id for a in self.accusers]
        jury_view = JuryVoteView(
            accused_id=self.accused.id,
            accuser_ids=accuser_ids,
            timeout_seconds=duration_seconds
        )

        initial_embed = jury_view.build_embed(is_closed=False, time_left=duration_seconds)
        jury_msg = await self.channel.send(
            content="📢 **Внимание зала суда! Начинается голосование коллегии присяжных.**\n"
                    "Все зрители процесса могут отдать свой голос кнопками ниже:",
            embed=initial_embed,
            view=jury_view
        )
        jury_view.message = jury_msg

        # Обратный отсчет с обновлением таймера каждые 5-10 секунд
        time_left = duration_seconds
        step = 5 if duration_seconds <= 30 else 10
        while time_left > 0:
            sleep_for = min(step, time_left)
            await asyncio.sleep(sleep_for)
            time_left -= sleep_for
            if time_left > 0:
                try:
                    await jury_msg.edit(embed=jury_view.build_embed(is_closed=False, time_left=time_left), view=jury_view)
                except Exception:
                    pass

        # Отключаем кнопки и подводим итоги
        jury_view.stop()
        for item in jury_view.children:
            if isinstance(item, Button):
                item.disabled = True

        self.jury_votes = jury_view.get_counts()
        total_votes = self.jury_votes["guilty"] + self.jury_votes["innocent"]

        try:
            await jury_msg.edit(
                content="🔒 **Голосование коллегии присяжных окончено!**",
                embed=jury_view.build_embed(is_closed=True),
                view=jury_view
            )
        except Exception:
            pass

        if total_votes > 0:
            if self.jury_votes["guilty"] > self.jury_votes["innocent"]:
                summary_lead = "Большинство присяжных склоняются к признанию **ВИНЫ**."
            elif self.jury_votes["innocent"] > self.jury_votes["guilty"]:
                summary_lead = "Большинство присяжных требуют **ОПРАВДАНИЯ**."
            else:
                summary_lead = "Голоса присяжных разделились **поровну**."

            await self.channel.send(
                f"⚖️ **Итог голосования присяжных ({total_votes} голосов):** "
                f"Виновен: `{self.jury_votes['guilty']}` | Невиновен: `{self.jury_votes['innocent']}`.\n"
                f"> *{summary_lead} Результаты передаются Судье Дредду.*"
            )
        else:
            await self.channel.send("⚖️ Присяжные воздержались от голосования. Судья Дредд выносит решение единолично.")

        await asyncio.sleep(3)

    async def _deliberate_and_judge(self):
        deliberation_embed = discord.Embed(
            title="⚖️ СУД УДАЛЯЕТСЯ НА СОВЕЩАНИЕ...",
            description="Кибер-Судья Дредд сопоставляет нападки обвинения и аргументы защиты адвоката Сола Гудмана.",
            color=discord.Color.dark_grey()
        )
        delib_msg = await self.channel.send(embed=deliberation_embed)

        complaint_texts = [c["reason"] for c in self.complaints]

        cat_meta = CATEGORIES.get(self.category, {
            "title": self.category,
            "description": "Нарушение порядка"
        })

        verdict: VerdictResult = await self.llm_judge.evaluate_trial(
            accused_name=f"{self.accused.display_name} (@{self.accused.name})",
            initial_complaints=complaint_texts,
            prosecution_statements=self.prosecution_records,
            defense_statement=self.defense_record,
            advocate_speech=self.advocate_speech,
            category_name=cat_meta["title"],
            category_desc=cat_meta["description"],
            jury_votes=self.jury_votes
        )

        verdict_color = discord.Color.red() if verdict.is_guilty else discord.Color.green()
        result_embed = discord.Embed(
            title=f"⚖️ ПРИГОВОР ИМЕНЕМ ЗАКОНА: {verdict.verdict_title}",
            description=f"По делу №{self.case_number} в отношении {self.accused.mention} вынесено решение.",
            color=verdict_color,
            timestamp=datetime.datetime.now(datetime.timezone.utc)
        )

        result_embed.add_field(
            name="📊 Оценка обвинения",
            value=verdict.analysis_prosecution[:1024],
            inline=False
        )
        result_embed.add_field(
            name="🛡️ Оценка защиты",
            value=verdict.analysis_defense[:1024],
            inline=False
        )

        total_jury_voted = self.jury_votes.get("guilty", 0) + self.jury_votes.get("innocent", 0)
        if total_jury_voted > 0:
            jury_field_val = (
                f"Голоса: 🔴 Виновен — `{self.jury_votes['guilty']}` | 🟢 Невиновен — `{self.jury_votes['innocent']}`\n"
            )
            if verdict.jury_reaction:
                jury_field_val += f"> *{verdict.jury_reaction}*"
            result_embed.add_field(
                name="👥 Вердикт коллегии присяжных",
                value=jury_field_val[:1024],
                inline=False
            )

        if verdict.violated_articles:
            articles_text = "\n".join([f"⚖️ {art}" for art in verdict.violated_articles])
            field_name = "📕 Вменяемые статьи Единого Свода Законов" if verdict.is_guilty else "📘 Правовое основание оправдания"
            result_embed.add_field(
                name=field_name,
                value=articles_text[:1024],
                inline=False
            )

        result_embed.add_field(
            name="📜 Мотивировочная часть вердикта",
            value=verdict.final_verdict[:1024],
            inline=False
        )

        punishment_str = "Оправдан. Все обвинения сняты."
        if verdict.is_guilty:
            mins = verdict.suggested_timeout_minutes or 60
            punishment_str = f"Признан виновным. Назначен таймаут на **{mins} мин.**"
            try:
                timeout_delta = datetime.timedelta(minutes=mins)
                await self.accused.timeout(timeout_delta, reason=f"Приговор суда по делу №{self.case_number}")
                punishment_str += "\n✅ *Таймаут успешно применен автоматически.*"
            except Exception as e:
                punishment_str += f"\n⚠️ *Не удалось автоматически выдать таймаут: {e}*"

        result_embed.add_field(name="⚡ Исполнение приговора", value=punishment_str, inline=False)
        result_embed.set_footer(text="СУД ОКОНЧЕН. СУДЬЯ ДРЕДД.")

        await delib_msg.delete()
        await self.channel.send(content=f"🔔 {self.accused.mention} оглашается окончательный вердикт!", embed=result_embed)

        status_code = "guilty" if verdict.is_guilty else "innocent"
        await close_case(
            guild_id=self.guild.id,
            case_number=self.case_number,
            verdict=status_code,
            verdict_text=f"{verdict.verdict_title}\n{verdict.final_verdict}"
        )

        await self.channel.send("📁 *Данный канал останется доступным для чтения 10 минут, после чего будет автоматически удален.*")
        self.bot.loop.create_task(self._auto_cleanup_channel(600))

    async def _auto_cleanup_channel(self, delay: int):
        await asyncio.sleep(delay)
        try:
            if self.channel:
                await self.channel.delete(reason=f"Архивация судебного дела №{self.case_number}")
        except Exception as e:
            logger.warning(f"Не удалось удалить судебный канал: {e}")
