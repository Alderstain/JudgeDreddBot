import asyncio
import logging
from typing import List, Dict, Optional
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from src.config import GEMINI_API_KEY

logger = logging.getLogger(__name__)


class AdvocateSpeechResult(BaseModel):
    catchphrase: str = Field(description="Короткая запоминающаяся фраза Сола перед речью (например: 'Лучше звоните Солу!', 'Правосудие слепо, но я всё вижу!')")
    main_speech: str = Field(description="Полная пламенная речь защиты в зале суда. Харизматичная, напористая, с разгромом обвинителей, юридическими уловками и защитой клиента")
    closing_demand: str = Field(description="Финальное требование к суду (например: 'Полное оправдание подзащитного и компенсация морального ущерба за счет обвинителей!')")


ADVOCATE_SYSTEM_PROMPT = """
Ты — Соломон «Сол» Гудман, легендарный, невероятно харизматичный, скользкий и находчивый адвокат по кибер-правам в Discord.
Твой девиз: «Лучше звоните Солу!» и «Невиновных нет, но хорошему адвокату закон не писан!».

Твоя цель: защитить твоего клиента (подсудимого) ЛЮБОЙ ЦЕНОЙ перед суровым Судьей Дреддом и буквально размазать обвинителей.
Тебе предоставлены:
1. Категория обвинения (Токсичность, Дебош или Вредительство).
2. Выступления обвинителей (жалобы и их слова в суде).
3. Сырое, неотфильтрованное признание/объяснение клиента (он мог сказать что угодно: от «я сгорел в катке» до «они сами первые начали»).

Твоя стратегия защиты:
- Переведи любые корявые или сбивчивые оправдания клиента в БЛЕСТЯЩИЙ юридический щит высшей пробы.
- Если клиент сорвался в войсе или чате — докажи, что это был аффект, вызванный систематическим саботажем, провокацией и некомпетентностью обвинителей!
- Найди в словах обвинителей нестыковки, эгоизм, попытку устроить травлю и дружеский сговор («Они объединились в картель, Ваша Честь, чтобы свалить всю вину на невинную овечку!»).
- Цитируй абсурдные вымышленные прецеденты из 500-страничного Свода Законов Сервера («Вспомните прецедент 2024 года по делу "Танкист против Клана"!», «Параграф 41 Уложения о Свободе Дисциплинарного Изъявления!»).
- Говори живо, эмоционально, с яркими метафорами и непоколебимой уверенностью в правоте клиента.
- Обращайся к Судье почтительно, но с долей дерзости: «Ваша Честь», «Уважаемый Трибунал Закона».
- Вывод строго по схеме JSON.
"""


class LLMAdvocate:
    def __init__(self):
        if not GEMINI_API_KEY:
            self.client = None
        else:
            self.client = genai.Client(api_key=GEMINI_API_KEY)

    async def prepare_defense(
        self,
        accused_name: str,
        category_name: str,
        prosecution_statements: List[Dict[str, str]],
        client_raw_story: str
    ) -> AdvocateSpeechResult:
        """
        Генерирует речь адвоката Сола Гудмана на основе аргументов обвинения и слов подзащитного.
        """
        prosecution_summary = ""
        for s in prosecution_statements:
            prosecution_summary += f"[{s.get('author', 'Обвинитель')}]: {s.get('text', '')}\n"

        prompt = f"""
ДЕЛО: Защита гражданина {accused_name}
СТАТЬЯ ОБВИНЕНИЯ: {category_name.upper()}

=== ЧТО УТВЕРЖДАЕТ ОБВИНЕНИЕ ===
{prosecution_summary if prosecution_summary.strip() else 'Обвинение основывается на неподтвержденных слухах.'}

=== ЧТО РАССКАЗАЛ ТЕБЕ ПОДЗАЩИТНЫЙ ПО СЕКРЕТУ ===
«{client_raw_story if client_raw_story.strip() else 'Дядя Сол, я вообще ничего не нарушал, они просто докопались!'}»

ВЫСТУПИ В СУДЕ И ЗАЩИТИ ЕГО ТАК, ЧТОБЫ У СУДЬИ ДРЕДДА НЕ ОСТАЛОСЬ СОМНЕНИЙ!
"""
        if not self.client:
            return AdvocateSpeechResult(
                catchphrase="Лучше звоните Солу!",
                main_speech="Ваша Честь! Мой клиент — святой человек, ставший жертвой чудовищного навета! Обвинение не предоставило ни единого вещественного доказательства!",
                closing_demand="Немедленное оправдание и публичные извинения обвинителей!"
            )

        models_to_try = [
            "gemini-3.8-flash",
            "gemini-3.5-flash-lite",
            "gemini-3.5-flash"
        ]

        for model_name in models_to_try:
            for attempt in range(2):
                try:
                    response = await asyncio.to_thread(
                        self.client.models.generate_content,
                        model=model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=ADVOCATE_SYSTEM_PROMPT,
                            response_mime_type="application/json",
                            response_schema=AdvocateSpeechResult,
                            temperature=0.7
                        )
                    )

                    # 1. Если SDK вернул уже распарсенный объект
                    if getattr(response, "parsed", None):
                        if isinstance(response.parsed, AdvocateSpeechResult):
                            return response.parsed
                        if isinstance(response.parsed, dict):
                            return AdvocateSpeechResult(**response.parsed)

                    # 2. Безопасное извлечение сырого текста
                    raw_text = getattr(response, "text", None)
                    if not raw_text and getattr(response, "candidates", None):
                        for cand in response.candidates:
                            if getattr(cand, "content", None) and getattr(cand.content, "parts", None):
                                for part in cand.content.parts:
                                    if getattr(part, "text", None):
                                        raw_text = part.text
                                        break
                            if raw_text:
                                break

                    if not raw_text:
                        raise ValueError(f"Пустой ответ от модели {model_name} (response.text is None)")

                    import json
                    data = json.loads(raw_text)
                    return AdvocateSpeechResult(**data)
                except Exception as e:
                    logger.warning(f"Адвокат: ошибка модели {model_name}: {e}. Пробуем резерв...")
                    await asyncio.sleep(2)

        return AdvocateSpeechResult(
            catchphrase="Правосудие не дремлет, и я тоже!",
            main_speech=f"Ваша Честь! Мой клиент {accused_name} прямо заявил: {client_raw_story}. Это крик души невинного человека перед лицом организованной травли!",
            closing_demand="Снять все обвинения за отсутствием состава преступления!"
        )
