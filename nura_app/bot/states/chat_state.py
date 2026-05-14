from aiogram.fsm.state import State, StatesGroup


class ChatStates(StatesGroup):
    idle = State()
    chatting = State()
