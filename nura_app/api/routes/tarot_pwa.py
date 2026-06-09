import uuid
from datetime import date

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from api.deps import limiter
from core.database import get_async_sessionmaker
from core.repositories.user import UserRepository
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
