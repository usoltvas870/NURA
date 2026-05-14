from aiogram.fsm.state import State, StatesGroup


class MatrixState(StatesGroup):
    waiting_for_birth_date = State()
