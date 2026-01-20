from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import PRODUCTS, CONFIG

def kb_start(is_admin: bool) -> InlineKeyboardMarkup:
    # Две кнопки рядом: "Купить доступ" (ОГЭ) и "Устное собеседование"
    buttons = [[
        InlineKeyboardButton(text="🛒 Купить доступ", callback_data="buy_open"),
        InlineKeyboardButton(text="🗣 Устное собеседование — 399₽", callback_data="buy_oral"),
    ]]
    if is_admin:
        buttons.append([InlineKeyboardButton(text="🛠 Админка", callback_data="admin_open")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def kb_subjects() -> InlineKeyboardMarkup:
    rows = []
    order = ["math", "rus", "bio", "info", "hist", "soc", "chem", "phys"]
    for slug in order:
        p = PRODUCTS[slug]
        rows.append([InlineKeyboardButton(text=f"{p['name']} — {p['price']}₽", callback_data=f"buy_{slug}")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="start_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def kb_payment() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить заявку", callback_data="cancel_pending")],
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="start_back")],
        [InlineKeyboardButton(text="💬 Оплатить другим способом", url=f"https://t.me/{CONFIG.alt_pay_username}")]
    ])

def kb_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📣 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="💳 Указать карту/ФИО", callback_data="admin_set_card")],
        [InlineKeyboardButton(text="💰 Выдать баланс", callback_data="admin_give_balance")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="start_back")],
    ])

def kb_admin_review(purchase_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"admin_approve_{purchase_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"admin_deny_{purchase_id}"),
        ]
    ])

def kb_broadcast_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Отправить", callback_data="broadcast_send"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel"),
        ]
    ])
