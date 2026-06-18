---
name: aiogram
description: Aiogram 3.x patterns for Telegram bot development — FSM, routers, middleware, keyboards, filters, and media handling. Use when working with bot/ directory.
---

# Aiogram 3.x Patterns (NURA)

## Architecture
```
bot/
├── handlers/     # Message/Callback/Inquiry handlers
├── keyboards/    # Inline/Reply keyboards
├── middlewares/  # Throttling, auth, logging
├── states/       # FSM states (Groups)
└── __init__.py   # Dispatcher setup
```

## Router Pattern
```python
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command

router = Router()

@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer("Welcome!")
```

## Dispatcher Setup
```python
from aiogram import Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from bot.handlers import start, profile, payment

dp = Dispatcher(storage=RedisStorage.from_url(REDIS_URL))
dp.include_routers(
    start.router,
    profile.router,
    payment.router,
)
```

## FSM (Finite State Machine)
```python
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

class ProfileForm(StatesGroup):
    name = State()
    age = State()
    photo = State()

@router.message(Command("profile"))
async def start_profile(message: Message, state: FSMContext):
    await state.set_state(ProfileForm.name)
    await message.answer("Send your name:")

@router.message(ProfileForm.name)
async def process_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(ProfileForm.age)
    await message.answer("Send your age:")

@router.message(ProfileForm.age)
async def process_age(message: Message, state: FSMContext):
    await state.update_data(age=int(message.text))
    data = await state.get_data()
    await message.answer(f"Profile: {data}")
    await state.clear()
```

## Inline Keyboards
```python
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

def tariff_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Basic — 990₽", callback_data="tariff_basic")
    builder.button(text="Pro — 2990₽", callback_data="tariff_pro")
    builder.button(text="Back", callback_data="menu_main")
    builder.adjust(1)
    return builder.as_markup()

@router.callback_query(F.data.startswith("tariff_"))
async def tariff_selected(callback: CallbackQuery, state: FSMContext):
    tariff = callback.data.replace("tariff_", "")
    await state.update_data(tariff=tariff)
    await callback.message.edit_text(
        f"Selected: {tariff}",
        reply_markup=payment_keyboard(),
    )
    await callback.answer()
```

## Callback Data Factory
```python
from aiogram.filters.callback_data import CallbackData

class PaymentCallback(CallbackData, prefix="pay"):
    tariff: str
    amount: int

@router.callback_query(PaymentCallback.filter())
async def process_payment(
    callback: CallbackQuery,
    callback_data: PaymentCallback,
):
    await callback.message.answer(f"Pay {callback_data.amount} for {callback_data.tariff}")
```

## Media Handling
```python
from aiogram.types import Message, FSInputFile

# Send file
await message.answer_document(FSInputFile("report.pdf"))

# Receive photo
@router.message(F.photo)
async def handle_photo(message: Message):
    file_id = message.photo[-1].file_id
    file = await bot.get_file(file_id)
    # Download: await bot.download(file)
```

## Middleware
```python
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from collections import defaultdict
import time

class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, rate_limit: float = 0.5):
        self.limit = rate_limit
        self.users = defaultdict(float)

    async def __call__(self, handler, event: TelegramObject, data: dict):
        user_id = data["event_from_user"].id
        now = time.time()
        if now - self.users[user_id] < self.limit:
            return  # Skip
        self.users[user_id] = now
        return await handler(event, data)
```

## Error Handling
```python
from aiogram.types import ErrorEvent

@dp.error()
async def error_handler(event: ErrorEvent):
    logger.error(f"Bot error: {event.exception}", exc_info=True)
    if event.update.message:
        await event.update.message.answer("Something went wrong")
```

## Filters
```python
from aiogram.filters import Filter

class AdminFilter(Filter):
    async def __call__(self, message: Message) -> bool:
        return message.from_user.id in ADMIN_IDS

@router.message(Command("admin"), AdminFilter())
async def admin_panel(message: Message):
    await message.answer("Admin panel")
```

## Anti-patterns
- ❌ Хранить состояние в глобальных dict → используй FSM + RedisStorage
- ❌ Обращаться к БД напрямую из хендлера → через сервисы
- ❌ Жёстко закодированные тексты → используй отдельные строки/переводы
- ❌ await message.answer() без try/except → добавь обработку ошибок
- ❌ Не вызывать callback.answer() → висит "часики" на кнопке
