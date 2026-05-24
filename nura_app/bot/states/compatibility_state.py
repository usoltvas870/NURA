from aiogram.fsm.state import State, StatesGroup


class CompatibilityStates(StatesGroup):
    waiting_partner_date = State()
