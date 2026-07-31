"""Fallback-тексты для AI-сервисов NURA.

Содержит все FALLBACK_* словари, вынесенные из core/services/ai.py
для улучшения читаемости и поддержки.
"""

from core.config import settings

# ── Mini-analysis ────────────────────────────────────────────────

FALLBACK_MINI = {
    "main_archetype": "Персональная интерпретация сейчас не сформирована.",
    "core_strength": "Данные сохранены, но provider-generated разбор сейчас недоступен.",
    "emotional_conflict": "Я не буду заменять отсутствующий анализ догадкой.",
    "relationship_pattern": "Попробуй повторить запрос позже — без повторного ввода данных.",
    "financial_block": "Это технический fallback, а не вывод о твоих ресурсах или деньгах.",
}

# ── Full report ──────────────────────────────────────────────────

FALLBACK_FULL = {
    key: "Раздел не сформирован: это технический fallback, а не персональный вывод."
    for key in (
        "main_archetype",
        "strengths",
        "shadow_side",
        "relationship_dynamics",
        "financial_scenario",
        "recurring_mistakes",
        "internal_conflicts",
        "life_cycles",
        "ai_recommendations",
        "karmic_tail_analysis",
        "ancestral_programs",
        "life_purpose",
        "life_forecast",
        "psychological_blocks",
        "health_analysis",
    )
}

# ── Kitchen report ───────────────────────────────────────────────

FALLBACK_KITCHEN: dict[str, dict] = {
    key: {
        "positions": [],
        "energies": [],
        "logic": "Не удалось подготовить объяснение. Попробуй ещё раз.",
    }
    for key in [
        "main_archetype",
        "strengths",
        "shadow_side",
        "relationship_dynamics",
        "financial_scenario",
        "recurring_mistakes",
        "internal_conflicts",
        "life_cycles",
        "karmic_tail_analysis",
        "ancestral_programs",
        "life_purpose",
        "life_forecast",
        "psychological_blocks",
        "health_analysis",
    ]
}

# ── Compatibility ────────────────────────────────────────────────

FALLBACK_COMPATIBILITY = {
    "portrait_user": "Не удалось загрузить разбор. Попробуй позже.",
    "portrait_partner": "Не удалось загрузить разбор. Попробуй позже.",
    "how_you_interact": "Не удалось загрузить разбор. Попробуй позже.",
    "tension_zones": "Не удалось загрузить разбор. Попробуй позже.",
    "pair_strengths": "Не удалось загрузить разбор. Попробуй позже.",
    "recommendation": "Попробуй запустить расклад ещё раз.",
}

# ── Chat ─────────────────────────────────────────────────────────

FALLBACK_CHAT = "Мне нужно чуть больше времени. Спроси ещё раз?"

# ── Tarot ─────────────────────────────────────────────────────────

TAROT_DAILY_MODEL = settings.deepseek_model
TAROT_SPREAD_MODEL = settings.deepseek_model
TAROT_QUESTION_MODEL = settings.deepseek_model

FALLBACK_TAROT_DAILY = {
    "card_number": 0,
    "card_name": "Аркан не определён",
    "key_phrase": "Сегодня — день тишины и внутреннего внимания.",
    "interpretation": (
        "Энергия дня не поддаётся точному определению. "
        "Прислушайся к себе — твой внутренний компас подскажет верное направление."
    ),
    "matrix_link": "",
    "advice": "Сделай паузу и задай себе вопрос: «Что для меня сейчас важнее всего?»",
    "affirmation": "Я доверяю своему внутреннему знанию.",
}

FALLBACK_TAROT_SPREAD = {
    "body": {
        "card_number": 0,
        "card_name": "Аркан не определён",
        "energy": "Энергия тела требует внимания.",
        "interpretation": "Прислушайся к своему телу — оно знает ответы.",
        "practice": "Сделай несколько глубоких вдохов и почувствуй своё тело.",
    },
    "mind": {
        "card_number": 0,
        "card_name": "Аркан не определён",
        "energy": "Энергия ума ищет ясность.",
        "interpretation": "Твои мысли ищут порядок — дай им время сложиться в картину.",
        "practice": "Запиши три главные мысли дня.",
    },
    "spirit": {
        "card_number": 0,
        "card_name": "Аркан не определён",
        "energy": "Энергия духа зовёт к тишине.",
        "interpretation": "Твой дух просит паузы — остановись на минуту и просто будь.",
        "practice": "Побудь в тишине 5 минут.",
    },
    "overall": (
        "Неделя приглашает тебя замедлиться и прислушаться к себе. "
        "Твоё тело, ум и дух ищут гармонию — дай им время найти её."
    ),
}

FALLBACK_TAROT_QUESTION = {
    "past": {
        "card_number": 0,
        "card_name": "Аркан не определён",
        "meaning": "Прошлое содержит ключи к твоему вопросу.",
        "how_it_relates": "Оглянись назад — паттерн уже был в твоей жизни.",
    },
    "present": {
        "card_number": 0,
        "card_name": "Аркан не определён",
        "meaning": "Настоящее показывает, где ты сейчас.",
        "how_it_relates": "Ты в процессе — и это нормально.",
    },
    "future": {
        "card_number": 0,
        "card_name": "Аркан не определён",
        "meaning": "Будущее открывается через твой выбор.",
        "how_it_relates": "То, что ты делаешь сейчас, формирует следующий шаг.",
    },
    "summary": "У тебя есть всё, чтобы найти ответ внутри себя.",
    "advice": "Сделай один маленький шаг в направлении, которое чувствуется правильным.",
}

# ── AI API Params ────────────────────────────────────────────────

DEFAULT_PARAMS = {
    "temperature": 0.7,
    "max_tokens": 4000,
    "top_p": 0.9,
    "frequency_penalty": 0.0,
    "presence_penalty": 0.0,
}

FULL_REPORT_PARAMS = {
    "temperature": 0.8,
    "max_tokens": 32000,
    "top_p": 0.95,
    "frequency_penalty": 0.0,
    "presence_penalty": 0.0,
}

CHAT_PARAMS = {
    "temperature": 0.8,
    "max_tokens": 1000,
    "top_p": 0.95,
    "frequency_penalty": 0.1,
    "presence_penalty": 0.1,
}
