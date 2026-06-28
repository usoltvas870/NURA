from aiogram.fsm.state import State, StatesGroup


class OnboardingStates(StatesGroup):
    waiting_for_birth_date = State()
    waiting_for_pd_consent = State()
