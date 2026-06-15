from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from api.deps import limiter
from core.database import get_async_sessionmaker
from core.repositories.user import UserRepository
from core.services.ai import AIService
from core.arcana_data import ARCANA
from core.services.daily_arcana import calculate_daily_arcana

router = APIRouter(prefix="/api/v1/tarot")

ARCANA_DATA = ARCANA  # alias from unified source


class DailyCardResponse(BaseModel):
    arcana_number: int
    arcana_name: str
    arcana_symbol: str
    key_phrase: str
    interpretation: str
    advice: str
    affirmation: str
    date_label: str


class SpreadRequest(BaseModel):
    session_id: str
    spread_type: str = Field(..., pattern=r"^(weekly|question|life|doubles|portal|yesno)$")
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
    "life": "Сферы жизни",
    "doubles": "Двойники",
    "portal": "Портал месяца",
    "yesno": "Да / Нет",
}


@router.get("/daily-card", response_model=DailyCardResponse)
@limiter.limit("30/minute")
async def get_daily_card(request: Request, session_id: str):
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)

    user = await user_repo.get_by_web_session_id(session_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Сессия не найдена")

    birth_date = user.birth_date
    if not birth_date:
        raise HTTPException(status_code=400, detail="Дата рождения не указана")

    arcana_num = calculate_daily_arcana(birth_date)
    arcana = ARCANA_DATA.get(arcana_num, ARCANA_DATA[1])

    today = date.today()
    months = ["января","февраля","марта","апреля","мая","июня",
              "июля","августа","сентября","октября","ноября","декабря"]
    date_label = f"{today.day} {months[today.month - 1]}"

    return DailyCardResponse(
        arcana_number=arcana_num,
        arcana_name=arcana["name"],
        arcana_symbol=arcana["symbol"],
        key_phrase=arcana["phrase"],
        interpretation=arcana["interpretation"],
        advice=arcana["advice"],
        affirmation=arcana["affirmation"],
        date_label=date_label,
    )


@router.post("/spread", response_model=SpreadResponse)
@limiter.limit("10/minute")
async def get_tarot_spread(request: Request, body: SpreadRequest):
    session_factory = get_async_sessionmaker()
    user_repo = UserRepository(session_factory)

    user = await user_repo.get_by_web_session_id(body.session_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Сессия не найдена")
    if not user.tarot_subscription:
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
        interpretation = await AIService.chat(
            messages=[
                {"role": "system", "content": "Ты — NURA, AI-проводник самопознания."},
                {"role": "user", "content": filled},
            ],
            api_params={"max_tokens": 500, "temperature": 0.7},
            timeout=120.0,
        )
        interpretation = interpretation.strip().strip('"')
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
        interpretation = await AIService.chat(
            messages=[
                {"role": "system", "content": "Ты — NURA, AI-проводник самопознания."},
                {"role": "user", "content": filled},
            ],
            api_params={"max_tokens": 500, "temperature": 0.7},
            timeout=120.0,
        )
        interpretation = interpretation.strip().strip('"')
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
        interpretation = await AIService.chat(
            messages=[
                {"role": "system", "content": "Ты — NURA, AI-проводник самопознания."},
                {"role": "user", "content": filled},
            ],
            api_params={"max_tokens": 500, "temperature": 0.7},
            timeout=120.0,
        )
        interpretation = interpretation.strip().strip('"')
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
        interpretation = await AIService.chat(
            messages=[
                {"role": "system", "content": "Ты — NURA, AI-проводник самопознания."},
                {"role": "user", "content": filled},
            ],
            api_params={"max_tokens": 500, "temperature": 0.7},
            timeout=120.0,
        )
        interpretation = interpretation.strip().strip('"')
    except Exception:
        raise HTTPException(status_code=503, detail="AI временно недоступен")

    cards = [
        SpreadCard(position_name="Ответ", arcana_number=base_arcana, arcana_name=arcana["name"], interpretation=interpretation, advice=arcana.get("advice")),
    ]

    return SpreadResponse(spread_type="yesno", spread_name="Да / Нет", cards=cards, summary=yes_or_no)