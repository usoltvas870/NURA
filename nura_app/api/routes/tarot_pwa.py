from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.deps import limiter
from api.dependencies import get_current_web_user
from core.models import User
from core.services.ai import AIService
from core.database import get_async_sessionmaker
from core.repositories.daily_tarot_draw import DailyTarotDrawRepository
from core.repositories.user import UserRepository
from core.services.daily_tarot_application import (
    DailyTarotApplicationService,
    DailyTarotRequest,
    DailyTarotResultKind,
)
from core.loop_specs.tarot_loop import generate_tarot_text
from core.arcana_data import ARCANA
from core.services.daily_arcana import calculate_daily_arcana

router = APIRouter(prefix="/api/v1/tarot")

ARCANA_DATA = ARCANA  # alias from unified source


def get_daily_tarot_application_service() -> DailyTarotApplicationService:
    session_factory = get_async_sessionmaker()
    return DailyTarotApplicationService(
        user_repository=UserRepository(session_factory),
        draw_repository=DailyTarotDrawRepository(session_factory),
        ai_service=AIService(),
    )


class DailyCardResponse(BaseModel):
    arcana_number: int
    arcana_name: str
    arcana_symbol: str
    key_phrase: str
    interpretation: str
    advice: str
    affirmation: str
    date_label: str
    user_archetype_name: str | None = None
    user_archetype_number: int | None = None


class SpreadRequest(BaseModel):
    spread_type: str = Field(..., pattern=r"^(weekly|question|mini|life|doubles|portal|yesno)$")
    question: str | None = Field(None, max_length=200)


class SpreadCard(BaseModel):
    position_name: str
    arcana_number: int
    arcana_name: str
    interpretation: str
    advice: str | None = None


class SpreadResponse(BaseModel):
    spread_type: str
    spread_name: str
    cards: list[SpreadCard]
    summary: str | None = None
    affirmation: str | None = None


SPREAD_NAMES = {
    "weekly": "Расклад недели",
    "question": "По вопросу",
    "mini": "Мини-расклад",
    "life": "Сферы жизни",
    "doubles": "Двойники",
    "portal": "Портал месяца",
    "yesno": "Да / Нет",
}


@router.get("/daily-card", response_model=DailyCardResponse)
@limiter.limit("30/minute")
async def get_daily_card(
    request: Request,
    user: User = Depends(get_current_web_user),
):
    result = await get_daily_tarot_application_service().get_daily_card(
        DailyTarotRequest(user_id=user.id, allow_retry=True)
    )
    if result.kind == DailyTarotResultKind.PROFILE_INCOMPLETE:
        raise HTTPException(status_code=400, detail="profile_incomplete")
    if result.kind == DailyTarotResultKind.USER_UNAVAILABLE:
        raise HTTPException(status_code=401, detail="session_not_found")
    if result.kind == DailyTarotResultKind.IN_PROGRESS:
        raise HTTPException(status_code=409, detail="daily_card_in_progress")
    if result.kind in {
        DailyTarotResultKind.FAILED_RETRYABLE,
        DailyTarotResultKind.FAILED_NON_RETRYABLE,
    }:
        raise HTTPException(status_code=503, detail="daily_card_unavailable")
    if result.arcana_number is None or result.interpretation is None or result.local_date is None:
        raise HTTPException(status_code=503, detail="daily_card_unavailable")
    return _daily_card_response(user, result.arcana_number, result.interpretation, result.local_date)


def _daily_card_response(
    user: User, arcana_num: int, card_text: str, local_date: str
) -> DailyCardResponse:
    arcana = ARCANA_DATA.get(arcana_num, ARCANA_DATA[1])
    paragraphs = [p.strip() for p in card_text.split("\n\n") if p.strip()]
    advice = paragraphs[-1] if len(paragraphs) >= 3 else card_text
    today = date.fromisoformat(local_date)
    months = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
    return DailyCardResponse(
        arcana_number=arcana_num,
        arcana_name=arcana["name"],
        arcana_symbol=arcana["symbol"],
        key_phrase=arcana.get("phrase", arcana.get("key", "")),
        interpretation=card_text,
        advice=advice,
        affirmation=arcana.get("affirmation", ""),
        date_label=f"{today.day} {months[today.month - 1]}",
        user_archetype_name=user.main_archetype,
        user_archetype_number=user.main_archetype_number,
    )


@router.post("/spread", response_model=SpreadResponse)
@limiter.limit("10/minute")
async def get_tarot_spread(
    request: Request,
    body: SpreadRequest,
    user: User = Depends(get_current_web_user),
):
    free_spread_types = {"question", "yesno", "mini"}
    if not user.tarot_subscription and body.spread_type not in free_spread_types:
        raise HTTPException(status_code=402, detail="Требуется подписка Таро")
    if not user.birth_date:
        raise HTTPException(status_code=400, detail="Дата рождения не указана")

    birth_date = user.birth_date
    spread_type = body.spread_type
    user_name = user.first_name or user.name or "пользователь"

    if spread_type == "weekly":
        return await _handle_weekly_spread(user, birth_date, user_name)
    elif spread_type == "question":
        if not body.question:
            raise HTTPException(status_code=400, detail="Вопрос обязателен для spread_type=question")
        return await _handle_question_spread(user, birth_date, body.question, user_name)
    elif spread_type == "mini":
        if not body.question:
            raise HTTPException(status_code=400, detail="Тема обязательна для spread_type=mini")
        return await _handle_mini_spread(user, birth_date, body.question, user_name)
    elif spread_type == "life":
        return await _handle_life_spread(user, birth_date, user_name)
    elif spread_type == "doubles":
        return await _handle_doubles_spread(user, birth_date, user_name)
    elif spread_type == "portal":
        return await _handle_portal_spread(user, birth_date, user_name)
    elif spread_type == "yesno":
        if not body.question:
            raise HTTPException(status_code=400, detail="Вопрос обязателен для spread_type=yesno")
        return await _handle_yesno_spread(user, birth_date, body.question, user_name)
    else:
        raise HTTPException(status_code=400, detail="Неверный тип расклада")


async def _handle_weekly_spread(user, birth_date: str, user_name: str) -> SpreadResponse:
    try:
        result = await AIService.generate_tarot_weekly_spread(birth_date, user)
    except Exception:
        raise HTTPException(status_code=503, detail="AI временно недоступен")

    b = result.get("body", {})
    m = result.get("mind", {})
    s = result.get("spirit", {})

    cards = [
        SpreadCard(position_name="Тело", arcana_number=b.get("card_number", 0), arcana_name=b.get("card_name", ""), interpretation=b.get("interpretation", ""), advice=b.get("practice")),
        SpreadCard(position_name="Ум", arcana_number=m.get("card_number", 0), arcana_name=m.get("card_name", ""), interpretation=m.get("interpretation", ""), advice=m.get("practice")),
        SpreadCard(position_name="Дух", arcana_number=s.get("card_number", 0), arcana_name=s.get("card_name", ""), interpretation=s.get("interpretation", ""), advice=s.get("practice")),
    ]

    return SpreadResponse(spread_type="weekly", spread_name="Расклад недели", cards=cards, summary=result.get("overall"))


async def _handle_question_spread(user, birth_date: str, question: str, user_name: str) -> SpreadResponse:
    try:
        result = await AIService.generate_tarot_question(birth_date, question, user)
    except Exception:
        raise HTTPException(status_code=503, detail="AI временно недоступен")

    past = result.get("past", {})
    present = result.get("present", {})
    future = result.get("future", {})

    cards = [
        SpreadCard(position_name="Прошлое", arcana_number=past.get("card_number", 0), arcana_name=past.get("card_name", ""), interpretation=past.get("how_it_relates", "")),
        SpreadCard(position_name="Настоящее", arcana_number=present.get("card_number", 0), arcana_name=present.get("card_name", ""), interpretation=present.get("how_it_relates", "")),
        SpreadCard(position_name="Будущее", arcana_number=future.get("card_number", 0), arcana_name=future.get("card_name", ""), interpretation=future.get("how_it_relates", "")),
    ]

    summary_parts = [result.get("summary", "")]
    if result.get("advice"):
        summary_parts.append(f"Совет: {result['advice']}")

    return SpreadResponse(spread_type="question", spread_name="По вопросу", cards=cards, summary="\n".join(summary_parts))


async def _handle_mini_spread(user, birth_date: str, topic: str, user_name: str) -> SpreadResponse:
    try:
        result = await AIService.generate_tarot_mini_spread(birth_date, topic, user)
    except Exception:
        raise HTTPException(status_code=503, detail="AI временно недоступен")

    context = result.get("context", {})
    inner_resource = result.get("inner_resource", {})
    next_step = result.get("next_step", {})
    cards = [
        SpreadCard(position_name="Контекст", arcana_number=context.get("card_number", 0), arcana_name=context.get("card_name", ""), interpretation=context.get("interpretation", ""), advice=context.get("advice")),
        SpreadCard(position_name="Внутренний ресурс", arcana_number=inner_resource.get("card_number", 0), arcana_name=inner_resource.get("card_name", ""), interpretation=inner_resource.get("interpretation", ""), advice=inner_resource.get("advice")),
        SpreadCard(position_name="Следующий шаг", arcana_number=next_step.get("card_number", 0), arcana_name=next_step.get("card_name", ""), interpretation=next_step.get("interpretation", ""), advice=next_step.get("advice")),
    ]
    return SpreadResponse(
        spread_type="mini",
        spread_name="Мини-расклад",
        cards=cards,
        summary=result.get("summary"),
    )


async def _handle_life_spread(user, birth_date: str, user_name: str) -> SpreadResponse:
    today = date.today()
    arcana_num = calculate_daily_arcana(birth_date)
    arcana = ARCANA_DATA.get(arcana_num, ARCANA_DATA[1])

    prompt = AIService._load_prompt("tarot_spheres.txt")
    sphere_name = "Деньги и реализация"
    filled = prompt.format(
        sphere_name=sphere_name,
        arcana_number=arcana_num,
        arcana_name=arcana["name"],
        date=today.strftime("%d.%m.%Y"),
    )

    try:
        interpretation = await generate_tarot_text(
            messages=[
                {"role": "system", "content": "Ты — NURA, AI-проводник самопознания."},
                {"role": "user", "content": filled},
            ],
            api_params={"max_tokens": 500, "temperature": 0.7},
            timeout=120.0,
            max_words=200,
        )
    except Exception:
        raise HTTPException(status_code=503, detail="AI временно недоступен")

    cards = [
        SpreadCard(position_name=sphere_name, arcana_number=arcana_num, arcana_name=arcana["name"], interpretation=interpretation, advice=arcana.get("advice")),
    ]

    return SpreadResponse(spread_type="life", spread_name="Сферы жизни", cards=cards)


async def _handle_doubles_spread(user, birth_date: str, user_name: str) -> SpreadResponse:
    today = date.today()
    base = calculate_daily_arcana(birth_date)
    arcana_one = base
    arcana_two = base % 22 + 1
    dominant = arcana_one if arcana_one >= arcana_two else arcana_two
    a1 = ARCANA_DATA.get(arcana_one, ARCANA_DATA[1])
    a2 = ARCANA_DATA.get(arcana_two, ARCANA_DATA[1])
    ad = ARCANA_DATA.get(dominant, ARCANA_DATA[1])

    prompt = AIService._load_prompt("tarot_doubles.txt")
    filled = prompt.format(
        arcana_one_number=arcana_one,
        arcana_one_name=a1["name"],
        arcana_two_number=arcana_two,
        arcana_two_name=a2["name"],
        dominant_arcana_name=ad["name"],
        date=today.strftime("%d.%m.%Y"),
    )

    try:
        interpretation = await generate_tarot_text(
            messages=[
                {"role": "system", "content": "Ты — NURA, AI-проводник самопознания."},
                {"role": "user", "content": filled},
            ],
            api_params={"max_tokens": 500, "temperature": 0.7},
            timeout=120.0,
            max_words=220,
        )
    except Exception:
        raise HTTPException(status_code=503, detail="AI временно недоступен")

    cards = [
        SpreadCard(position_name="Первый импульс", arcana_number=arcana_one, arcana_name=a1["name"], interpretation="", advice=None),
        SpreadCard(position_name="Второй импульс", arcana_number=arcana_two, arcana_name=a2["name"], interpretation=interpretation, advice=None),
    ]

    return SpreadResponse(spread_type="doubles", spread_name="Двойники", cards=cards)


async def _handle_portal_spread(user, birth_date: str, user_name: str) -> SpreadResponse:
    now = datetime.now()
    month_num = now.month
    teach = (month_num * 3) % 22 + 1
    release = (month_num * 7) % 22 + 1
    strengthen = (month_num * 11) % 22 + 1
    t_a = ARCANA_DATA.get(teach, ARCANA_DATA[1])
    r_a = ARCANA_DATA.get(release, ARCANA_DATA[1])
    s_a = ARCANA_DATA.get(strengthen, ARCANA_DATA[1])

    month_names = {1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель", 5: "Май", 6: "Июнь",
                   7: "Июль", 8: "Август", 9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"}
    month_name = month_names[month_num]

    prompt = AIService._load_prompt("tarot_portal.txt")
    filled = prompt.format(
        month_name=month_name,
        teach_arcana_number=teach,
        teach_arcana_name=t_a["name"],
        release_arcana_number=release,
        release_arcana_name=r_a["name"],
        strengthen_arcana_number=strengthen,
        strengthen_arcana_name=s_a["name"],
    )

    try:
        interpretation = await generate_tarot_text(
            messages=[
                {"role": "system", "content": "Ты — NURA, AI-проводник самопознания."},
                {"role": "user", "content": filled},
            ],
            api_params={"max_tokens": 500, "temperature": 0.7},
            timeout=120.0,
            max_words=230,
            use_cache=True,
            cache_ttl=31 * 86400,
        )
    except Exception:
        raise HTTPException(status_code=503, detail="AI временно недоступен")

    cards = [
        SpreadCard(position_name="Чему научит", arcana_number=teach, arcana_name=t_a["name"], interpretation="", advice=None),
        SpreadCard(position_name="Что отпустить", arcana_number=release, arcana_name=r_a["name"], interpretation=interpretation, advice=None),
        SpreadCard(position_name="Что усилить", arcana_number=strengthen, arcana_name=s_a["name"], interpretation="", advice=None),
    ]

    return SpreadResponse(spread_type="portal", spread_name="Портал месяца", cards=cards)


async def _handle_yesno_spread(user, birth_date: str, question: str, user_name: str) -> SpreadResponse:
    base_arcana = calculate_daily_arcana(birth_date)
    arcana = ARCANA_DATA.get(base_arcana, ARCANA_DATA[1])
    yes_or_no = "Да" if base_arcana % 2 == 1 else "Нет"

    prompt = AIService._load_prompt("tarot_yes_no.txt")
    filled = prompt.format(
        question=question,
        arcana_number=base_arcana,
        arcana_name=arcana["name"],
        yes_or_no=yes_or_no,
    )

    try:
        interpretation = await generate_tarot_text(
            messages=[
                {"role": "system", "content": "Ты — NURA, AI-проводник самопознания."},
                {"role": "user", "content": filled},
            ],
            api_params={"max_tokens": 500, "temperature": 0.7},
            timeout=120.0,
            max_words=150,
        )
    except Exception:
        raise HTTPException(status_code=503, detail="AI временно недоступен")

    cards = [
        SpreadCard(position_name="Ответ", arcana_number=base_arcana, arcana_name=arcana["name"], interpretation=interpretation, advice=arcana.get("advice")),
    ]

    return SpreadResponse(spread_type="yesno", spread_name="Да / Нет", cards=cards, summary=yes_or_no)
