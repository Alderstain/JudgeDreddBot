import json
import logging
from typing import List, Dict, Any, Optional
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from src.config import GEMINI_API_KEY

logger = logging.getLogger(__name__)


class VerdictResult(BaseModel):
    is_guilty: bool = Field(description="True если обвиняемый виновен, False если невиновен")
    verdict_title: str = Field(description="Краткий заголовок вердикта, например 'ВИНОВЕН ПО ВСЕМ ПУНКТАМ' или 'ПОЛНОСТЬЮ ОПРАВДАН'")
    violated_articles: List[str] = Field(
        default_factory=list,
        description="Список нарушенных статей из вымышленного 500-страничного Единого Кодекса Правопорядка и Законов Сервера с номерами пунктов, томов и параграфов. Если невиновен — статья об оправдании за отсутствием состава правонарушения."
    )
    analysis_prosecution: str = Field(description="Оценка аргументов обвинителей (логика, обоснованность, доказательства)")
    analysis_defense: str = Field(description="Оценка аргументов обвиняемого (оправдания, встречные факты, искренность)")
    final_verdict: str = Field(description="Судейское решение, детальный разбор в строгом тоне судьи Дредда/верховного правосудия")
    suggested_timeout_minutes: int = Field(default=0, description="Рекомендуемое время наказания в минутах (0 если невиновен, до 1440 минут)")


JUDGE_SYSTEM_PROMPT = """
Ты — Судья Дредд (Верховный Кибер-Судья Discord-сервера). Твоя задача — беспристрастно, объективно, но со всей строгостью закона вершить правосудие.
Ты опираешься на грандиозный, всеобъемлющий 500-страничный фолиант: «Единый Свод Законов, Кибер-Права и Дисциплинарного Кодекса Сервера».

Перед тобой судебное дело над пользователем сервера.
В суде выступают две силы:
1. Сторона обвинения (жалобы и претензии обвинителей).
2. Сторона защиты: подсудимый и его харизматичный адвокат Соломон «Сол» Гудман.

Твои правила оценки:
- Оценивай факты, логику и здравый смысл. 
- Обрати внимание: на сервере мало людей, обвинение может быть следствием дружеского троллинга или сговора троих против одного.
- Внимательно выслушай речь Адвоката Сола Гудмана. Если Сол Гудман ловко вскрыл провокации обвинения, отсутствие прямых улик или доказал смягчающие обстоятельства — ты можешь принять его доводы и оправдать подсудимого (либо дать минимальное символическое наказание)!
- Однако если обвинители предоставили железные факты, а Сол Гудман занимается откровенной демагогией и пускает пыль в глаза — осади адвоката («Ваши трюки здесь не пройдут, защитник Гудман!») и признай обвиняемого виновным.

ВАЖНЕЙШЕЕ ПРАВИЛО О СТАТЬЯХ ЗАКОНА:
- Ты ОБЯЗАН формулировать невероятно солидные, тяжеловесные и бюрократически грозные статьи закона из нашего 500-страничного Свода Законов, которые подходят под содеянное.
- Примеры стиля статей при обвинительном вердикте:
  * «Статья 142.4 Тома VII Единого Кодекса: "Злостное загромождение инфополя и создание вербального хаоса третьей степени"»
  * «Статья 89, пункт "в", параграф 12 Уложения о Кибер-Дисциплине: "Публичное попрание авторитета модерации и подрыв устоев сообщества"»
  * «Статья 304 Свода Законов Сервера: "Умышленное разжигание междоусобной вражды с отягчающими обстоятельствами"»
- При оправдательном вердикте указывай реабилитирующую статью, например:
  * «Статья 9 Презумпции Невиновности: "Полное снятие подозрений ввиду абсолютной несостоятельности обвинительного акта"»

- Твой тон: суровый, неподкупный, лаконичный, властный, пропитанный духом абсолютного Закона («Я и есть Закон!»).
- Всегда формируй вывод строго в формате схемы JSON.
"""


class LLMJudge:
    def __init__(self):
        if not GEMINI_API_KEY:
            logger.warning("GEMINI_API_KEY не установлен. Будет использоваться заглушка.")
            self.client = None
        else:
            self.client = genai.Client(api_key=GEMINI_API_KEY)

    async def evaluate_trial(
        self,
        accused_name: str,
        initial_complaints: List[str],
        prosecution_statements: List[Dict[str, str]],
        defense_statement: str,
        advocate_speech: Optional[str] = None,
        category_name: str = "Токсичность",
        category_desc: str = "Оскорбления, агрессия, травля"
    ) -> VerdictResult:
        """
        Отправляет материалы дела в Gemini и возвращает вердикт.
        """
        prompt = f"""
МАТЕРИАЛЫ ДЕЛА:
Обвиняемый: {accused_name}
КАТЕГОРИЯ ОБВИНЕНИЯ: {category_name.upper()} ({category_desc})
(Важно: оценивай факты строго в контексте состава правонарушения «{category_name}»!)

=== ПЕРВОНАЧАЛЬНЫЕ ЖАЛОБЫ ПО СТАТЬЕ «{category_name.upper()}» ===
"""
        for i, comp in enumerate(initial_complaints, 1):
            prompt += f"{i}. {comp}\n"

        prompt += "\n=== ВЫСТУПЛЕНИЯ СТОРОНЫ ОБВИНЕНИЯ ===\n"
        for st in prosecution_statements:
            prompt += f"[{st['author']}]: {st['text']}\n"

        prompt += f"""
=== ПОКАЗАНИЯ ОБВИНЯЕМОГО (СКАЗАНО АДВОКАТУ) ===
[{accused_name}]: {defense_statement if defense_statement.strip() else '<<Обвиняемый отказался от дачи показаний / промолчал>>'}

=== РЕЧЬ АДВОКАТА ЗАЩИТЫ (СОЛОМОН «СОЛ» ГУДМАН) ===
{advocate_speech if advocate_speech else '<<Адвокат не выступал>>'}

ВНИМАТЕЛЬНО ИЗУЧИ ВСЕ ДОВОДЫ СТОРОН, СОПОСТАВЬ ОБВИНЕНИЕ И ЗАЩИТУ СОЛА ГУДМАНА И ВЫНЕСИ ОКОНЧАТЕЛЬНЫЙ ПРИГОВОР.
"""
        if not self.client:
            return VerdictResult(
                is_guilty=False,
                verdict_title="ДЕЛО ЗАКРЫТО (ТЕСТОВЫЙ РЕЖИМ)",
                violated_articles=["Статья 1 Тестового Режима: Отсутствие ключа API"],
                analysis_prosecution="Сторона обвинения предоставила материалы, но API ключ Gemini не был настроен.",
                analysis_defense="Защита выступила в рамках тестового окружения.",
                final_verdict="В связи с отсутствием ключа API выносится условное оправдание. Установите GEMINI_API_KEY в .env.",
                suggested_timeout_minutes=0
            )

        models_to_try = [
            "gemini-3.8-flash",
            "gemini-3.5-flash-lite",
            "gemini-3.5-flash"
        ]

        last_error = None

        for model_name in models_to_try:
            for attempt in range(2):
                try:
                    logger.info(f"Запрос к Gemini API с моделью {model_name} (попытка {attempt + 1})...")
                    import asyncio
                    response = await asyncio.to_thread(
                        self.client.models.generate_content,
                        model=model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=JUDGE_SYSTEM_PROMPT,
                            response_mime_type="application/json",
                            response_schema=VerdictResult,
                            temperature=0.3
                        )
                    )

                    # 1. Если SDK вернул уже распарсенную модель
                    if getattr(response, "parsed", None):
                        if isinstance(response.parsed, VerdictResult):
                            logger.info(f"Успешный ответ от модели {model_name} (parsed)!")
                            return response.parsed
                        if isinstance(response.parsed, dict):
                            logger.info(f"Успешный ответ от модели {model_name} (dict)!")
                            return VerdictResult(**response.parsed)

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

                    data = json.loads(raw_text)
                    logger.info(f"Успешный ответ от модели {model_name} (json parsed)!")
                    return VerdictResult(**data)
                except Exception as e:
                    last_error = e
                    logger.warning(f"Модель {model_name} вернула ошибку: {e}. Пробуем повторить или переключить модель...")
                    import asyncio
                    await asyncio.sleep(2)

        logger.error(f"Все попытки вызова моделей Gemini завершились ошибкой: {last_error}", exc_info=True)
        return VerdictResult(
            is_guilty=False,
            verdict_title="СУДЕБНАЯ ОШИБКА / ПЕРЕГРУЗКА ИИ",
            violated_articles=["Статья 503 Форс-Мажорных Обстоятельств"],
            analysis_prosecution="Сторона обвинения предоставила доказательства, но каналы связи с трибуналом временно перегружены.",
            analysis_defense="Обвиняемый временно освобождается под подписку о невыезде.",
            final_verdict=f"Суд объявляет перерыв из-за временной недоступности серверов Gemini: {str(last_error)}",
            suggested_timeout_minutes=0
        )
