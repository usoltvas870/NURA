from aiogram.fsm.state import State, StatesGroup


class TarotStates(StatesGroup):
    waiting_for_question = State()  # Расклад по вопросу и Да/Нет
    waiting_for_sphere = State()    # Сферы жизни (выбор через callback)
