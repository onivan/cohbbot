from aiogram.fsm.state import State, StatesGroup

class UserState(StatesGroup):
    """Стани первинної реєстрації користувача"""
    waiting_for_name = State()    # Очікування введення імені
    waiting_for_center = State()  # Очікування введення назви центру/підрозділу

class SettingsState(StatesGroup):
    """Стани зміни налаштувань"""
    waiting_for_new_center = State()  # Очікування нової назви центру

class ReceiptState(StatesGroup):
    """Стани підтвердження та редагування розпізнаного чека"""
    waiting_for_confirmation = State()        # Головний екран картки чека
    waiting_for_edit_date = State()           # Введення нової дати текстом
    waiting_for_edit_amount = State()         # Введення нової суми текстом
    waiting_for_edit_name = State()           # Введення нової назви текстом
    waiting_for_edit_category = State()       # Введення нової категорії текстом
    waiting_for_category_selection = State()  # Вибір категорії кнопками
