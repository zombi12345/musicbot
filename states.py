from aiogram.fsm.state import State, StatesGroup


class AdminStates(StatesGroup):
    # Рассылка
    broadcast_text = State()
    broadcast_confirm = State()
    # Пользователи
    user_search = State()
    user_msg = State()
    user_sub_days = State()
    user_sub_custom = State()
    user_trial_action = State()
    # Триал
    trial_days = State()
    # Прайс
    price_days = State()
    price_stars = State()
    # Админы
    admin_add_id = State()
    # Разовые фичи
    feature_add_name = State()
    feature_add_desc = State()
    feature_add_price = State()
    feature_add_uses = State()
    feature_grant_uses = State()


class DownloadStates(StatesGroup):
    waiting_link = State()
    downloading = State()

class AdminBillingStates(StatesGroup):
    withdraw_amount = State()
    withdraw_note = State()
    bill_free_count = State()
    price_action_edit = State()
    balance_custom = State()