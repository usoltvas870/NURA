"""
Анимированные индикаторы загрузки для сообщений бота.
"""

import asyncio
from contextlib import asynccontextmanager

from aiogram.types import Message

_FRAMES = ["◐", "◓", "◑", "◒"]


@asynccontextmanager
async def animated_loading(message: Message, text: str):
    """
    Контекстный менеджер: пока выполняется async-операция,
    циклически обновляет текст сообщения с вращающимся индикатором.
    """
    stop = asyncio.Event()

    async def animate():
        i = 0
        while not stop.is_set():
            try:
                await message.edit_text(
                    f"{text}  {_FRAMES[i % len(_FRAMES)]}",
                    reply_markup=message.reply_markup,
                )
            except Exception:
                pass
            i += 1
            await asyncio.sleep(0.5)

    task = asyncio.create_task(animate())
    try:
        yield
    finally:
        stop.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
