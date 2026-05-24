from aiogram.fsm.state import State, StatesGroup


class TarotStates(StatesGroup):
    waiting_question = State()
