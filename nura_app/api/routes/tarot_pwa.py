import uuid
from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from api.deps import limiter
from core.database import get_async_sessionmaker
from core.repositories.user import UserRepository
from core.services.ai import AIService
from core.services.daily_arcana import calculate_daily_arcana

router = APIRouter(prefix="/api/v1/tarot")

ARCANA_DATA = {
    1:  {"name": "Маг",               "symbol": "🪄", "phrase": "Воля и мастерство",      "interpretation": "Сегодня твоя воля особенно сильна. Используй её осознанно — всё начатое имеет шанс завершиться успехом.", "advice": "Возьмись за дело, которое откладывал. Сейчас подходящий момент.", "affirmation": "Я создаю реальность силой намерения"},
    2:  {"name": "Жрица",             "symbol": "🌙", "phrase": "Интуиция и тайна",        "interpretation": "День для внутреннего голоса. Не торопись с решениями — дай интуиции подсказать путь.", "advice": "Посвяти время тишине и наблюдению, а не действию.", "affirmation": "Я доверяю своей интуиции"},
    3:  {"name": "Императрица",       "symbol": "🌸", "phrase": "Изобилие и творчество",   "interpretation": "Благоприятный день для творчества и заботы о близких. Позволь себе получать, не только отдавать.", "advice": "Создай что-то красивое или побалуй себя.", "affirmation": "Я открыта для изобилия и красоты"},
    4:  {"name": "Император",         "symbol": "👑", "phrase": "Стабильность и власть",   "interpretation": "Время структурировать планы и взять ответственность. Твои решения сегодня заложат фундамент.", "advice": "Составь список приоритетов и следуй ему.", "affirmation": "Я принимаю ответственность за свою жизнь"},
    5:  {"name": "Иерофант",          "symbol": "🔑", "phrase": "Традиции и мудрость",     "interpretation": "Обратись к проверенному опыту — своему или наставника. День традиций и устойчивых ценностей.", "advice": "Поговори с кем-то мудрым или перечитай важный текст.", "affirmation": "Я учусь у прошлого и уважаю свой путь"},
    6:  {"name": "Влюблённые",        "symbol": "❤️", "phrase": "Выбор и союз",            "interpretation": "Важный день для отношений и выборов. Прислушайся к сердцу, а не только к разуму.", "advice": "Скажи близкому человеку то, что давно хотел сказать.", "affirmation": "Мои выборы отражают мои истинные ценности"},
    7:  {"name": "Колесница",         "symbol": "⚔️", "phrase": "Победа и движение",       "interpretation": "Двигайся вперёд несмотря на препятствия. Сегодня побеждает тот, кто не останавливается.", "advice": "Сделай один конкретный шаг к цели, даже если всё сложно.", "affirmation": "Я движусь вперёд с силой и уверенностью"},
    8:  {"name": "Сила",              "symbol": "🦁", "phrase": "Сила духа",               "interpretation": "Внутренняя сила важнее внешней. Мягкость и спокойствие решают больше, чем напор.", "advice": "Реагируй на вызовы дня спокойствием, не борьбой.", "affirmation": "Моя истинная сила — в мягкости и стойкости"},
    9:  {"name": "Отшельник",         "symbol": "🕯️", "phrase": "Уединение и поиск",       "interpretation": "День для уединения и размышлений. Найди момент тишины — там ответ.", "advice": "Отключись от шума хотя бы на час и побудь наедине с собой.", "affirmation": "В тишине я нахожу свой путь"},
    10: {"name": "Колесо Судьбы",     "symbol": "☸️", "phrase": "Циклы перемен",           "interpretation": "Перемены не случайны — они часть твоего пути. Прими происходящее как возможность.", "advice": "Замечай совпадения и знаки вокруг тебя сегодня.", "affirmation": "Я доверяю течению жизни"},
    11: {"name": "Справедливость",    "symbol": "⚖️", "phrase": "Баланс и карма",          "interpretation": "День честных решений. Всё вернётся — действуй так, чтобы не было стыдно.", "advice": "Разберись с делом, которое требует честного взгляда.", "affirmation": "Я действую честно и принимаю справедливые решения"},
    12: {"name": "Повешенный",        "symbol": "🌊", "phrase": "Жертва ради роста",        "interpretation": "Пауза и принятие. Иногда остановиться — значит продвинуться.", "advice": "Отпусти то, за что держишься из страха.", "affirmation": "Я позволяю жизни течь через меня"},
    13: {"name": "Смерть",            "symbol": "🦋", "phrase": "Трансформация",            "interpretation": "Что-то завершается, чтобы открылось новое. Не держись за уходящее.", "advice": "Отпусти одну привычку или убеждение, которое тебя ограничивает.", "affirmation": "Я принимаю перемены как естественную часть жизни"},
    14: {"name": "Умеренность",       "symbol": "🏺", "phrase": "Гармония и терпение",     "interpretation": "Гармония в деталях. Не торопись — найди золотую середину.", "advice": "Смешай два противоположных подхода — в этом и есть решение.", "affirmation": "Я нахожу баланс между крайностями"},
    15: {"name": "Дьявол",            "symbol": "🔗", "phrase": "Искушение и цепи",         "interpretation": "Замечай, что держит тебя в ловушке. Осознание — первый шаг к свободе.", "advice": "Назови одну вещь, которая тебя контролирует. Это начало освобождения.", "affirmation": "Я замечаю ограничения и выбираю свободу"},
    16: {"name": "Башня",             "symbol": "⚡", "phrase": "Внезапные перемены",      "interpretation": "Неожиданность освобождает. Разрушение старого — пространство для нового.", "advice": "Прими сегодняшние сюрпризы как освобождение, не как катастрофу.", "affirmation": "Я открыт переменам, которые несут обновление"},
    17: {"name": "Звезда",            "symbol": "⭐", "phrase": "Надежда и вдохновение",   "interpretation": "Верь в лучшее. Сегодня особенно сильно работает намерение.", "advice": "Запиши свою мечту или намерение на сегодня.", "affirmation": "Я верю в лучшее и притягиваю его"},
    18: {"name": "Луна",              "symbol": "🌕", "phrase": "Иллюзии и страхи",        "interpretation": "Будь внимателен к иллюзиям — своим и чужим. День тонкой интуиции.", "advice": "Не принимай важных решений — сначала убедись, что видишь ситуацию ясно.", "affirmation": "Я различаю реальность и иллюзию"},
    19: {"name": "Солнце",            "symbol": "☀️", "phrase": "Радость и успех",          "interpretation": "Яркий, тёплый день. Позволь себе радоваться и делиться светом.", "advice": "Сделай что-то, что приносит тебе настоящую радость.", "affirmation": "Я сияю и делюсь своим светом с миром"},
    20: {"name": "Суд",               "symbol": "🎺", "phrase": "Пробуждение",              "interpretation": "Прошлое просит переосмысления. Честный взгляд назад открывает путь вперёд.", "advice": "Примирись с чем-то из прошлого — это освободит энергию.", "affirmation": "Я принимаю прошлое и иду вперёд обновлённым"},
    21: {"name": "Мир",               "symbol": "🌍", "phrase": "Завершение цикла",         "interpretation": "Цикл завершён. Прими результат и готовься к новому витку.", "advice": "Отметь своё достижение, даже маленькое.", "affirmation": "Я завершаю циклы с благодарностью"},
    22: {"name": "Шут",               "symbol": "🃏", "phrase": "Начало пути",              "interpretation": "Начало чего-то неизведанного. Доверяй процессу, даже если путь не ясен.", "advice": "Сделай один шаг в неизвестность — без плана.", "affirmation": "Я доверяю пути, даже не зная, куда он ведёт"},
}


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
    except Exception as e:
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
    except Exception as e:
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
    sphere_names = {"Деньги и реализация", "Отношения", "Предназначение"}
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
    today = date.today()
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
