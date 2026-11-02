from aiogram.fsm.state import State, StatesGroup


class AdminStates(StatesGroup):
    broadcast_text = State()
    add_admin_id = State()
    ban_id = State()
    unban_id = State()


class DownloadStates(StatesGroup):
    waiting_link = State()
    downloading = State()