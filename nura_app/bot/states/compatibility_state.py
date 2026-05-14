from aiogram.fsm.state import State, StatesGroup


class CompatibilityStates(StatesGroup):
    waiting_first_date = State()
    waiting_second_date = State()
