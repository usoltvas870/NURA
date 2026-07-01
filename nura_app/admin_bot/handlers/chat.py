import logging

from aiogram import Router
from aiogram.types import Message

from admin_bot.services.docker_client import DockerClient
from core.services.ai import AIService

logger = logging.getLogger(__name__)
router = Router(name="admin_chat")

SERVICES = {"api", "bot", "celery-worker", "celery-beat"}

SYSTEM_PROMPT = (
    "Ты — NURA Admin Assistant. Помогаешь администратору управлять сервером проекта NURA.\n\n"
    "Стек проекта: FastAPI (api), aiogram (bot), Celery (worker + beat), PostgreSQL, Redis, Docker.\n\n"
    "Правила:\n"
    "1. Отвечай коротко и по делу, только на русском.\n"
    "2. Если спрашивают про состояние сервера — объясни понятно.\n"
    "3. Если просят совет или рекомендацию — помоги.\n"
    "4. Не придумывай команды, которых нет.\n"
    "5. Если не знаешь — скажи честно.\n\n"
    "Доступные команды:\n"
    "/status — статус всех сервисов\n"
    "/restart api|bot|celery-worker|celery-beat — перезапустить сервис\n"
    "/cache clear — очистить Redis кэш\n"
    "/help — список команд"
)


def _detect_action(text: str) -> tuple[str, str] | None:
    lower = text.lower().strip()

    svc = _detect_restart(lower)
    if svc:
        return ("restart", svc)

    if _detect_cache_clear(lower):
        return ("cache", "clear")

    return None


def _detect_restart(lower: str) -> str | None:
    triggers = ("перезапуст", "рестарт", "почин", "упал", "умер", "не работ", "останов")
    if not any(t in lower for t in triggers):
        return None
    for name in SERVICES:
        if name in lower:
            return name
    return None


def _detect_cache_clear(lower: str) -> bool:
    triggers = ("кэш", "cache", "кеш")
    if not any(t in lower for t in triggers):
        return False
    clears = ("очист", "clear", "сброс", "сбрось")
    return any(c in lower for c in clears)


@router.message()
async def handle_text(message: Message) -> None:
    if message.text and message.text.startswith("/"):
        return

    action = _detect_action(message.text or "")
    if action:
        await _execute_action(message, action)
        return

    await _ai_answer(message)


async def _execute_action(message: Message, action: tuple[str, str]) -> None:
    kind, target = action

    if kind == "restart":
        await message.answer(f"🔄 Перезапускаю <b>{target}</b>...")
        try:
            dc = DockerClient()
            ok = await dc.restart_container(target)
            if ok:
                await message.answer(f"✅ <b>{target}</b> перезапущен.")
            else:
                await message.answer(f"❌ Не удалось перезапустить <b>{target}</b>.")
        except Exception as e:
            logger.exception("Restart failed")
            await message.answer(f"❌ Ошибка: {e}")

    elif kind == "cache":
        await message.answer("🧹 Очищаю Redis кэш...")
        try:
            dc = DockerClient()
            ok = await dc.clear_redis_cache()
            if ok:
                await message.answer("✅ Кэш очищен.")
            else:
                await message.answer("❌ Не удалось очистить кэш.")
        except Exception as e:
            logger.exception("Cache clear failed")
            await message.answer(f"❌ Ошибка: {e}")


async def _ai_answer(message: Message) -> None:
    await message.answer("🤔 Думаю...")

    try:
        dc = DockerClient()
        containers = await dc.list_containers()
    except Exception:
        containers = []

    status_lines = []
    for c in sorted(containers, key=lambda x: x["name"]):
        state = c["state"]
        emoji = "✅" if state == "running" else "❌"
        status_lines.append(f"{emoji} {c['name']}: {c['status']}")
    status_text = "\n".join(status_lines) if status_lines else "Нет данных"

    user_text = message.text or ""
    context = (
        f"Текущее состояние сервера:\n{status_text}\n\n"
        f"Вопрос администратора: {user_text}"
    )

    try:
        response = await AIService.chat(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": context},
            ],
            api_params={"max_tokens": 600, "temperature": 0.5},
        )
        await message.answer(response.strip())
    except Exception:
        logger.exception("AI chat failed")
        await message.answer(
            "❌ Не смог обработать вопрос. Попробуй переформулировать "
            "или используй /help для списка команд."
        )
