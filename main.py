import time
from typing import Optional, Tuple

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.client.default import DefaultBotProperties

from config import CONFIG, PRODUCTS, RATE_LIMIT_SECONDS, MAX_RECEIPTS_PER_PURCHASE
from db import (
    init_db, upsert_user, ensure_default_card, get_card,
    has_pending_purchase, create_purchase,
    get_latest_pending_purchase, attach_receipt,
    set_purchase_status, get_purchase, get_users_count, get_all_user_ids,
    get_stats, set_setting, find_user_id_by_username, add_balance,
    receipt_is_used, mark_receipt_used
)
from keyboards import (
    kb_start, kb_subjects, kb_payment, kb_admin,
    kb_admin_review, kb_broadcast_confirm
)
from texts import (
    start_text, buy_hint_text, payment_text, already_pending_text,
    ask_receipt_text, receipt_received_text, access_granted_text,
    access_denied_text, admin_panel_text, stats_text,
    card_updated_text, broadcast_intro_text, broadcast_confirm_text,
    broadcast_done_text, balance_prompt_user_text, balance_prompt_amount_text,
    balance_done_text, receipt_reused_text
)

bot = Bot(
    CONFIG.token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

# -------- антифлуд (в памяти) ----------
_last_action = {}
def rate_limited(user_id: int) -> bool:
    now = time.time()
    last = _last_action.get(user_id, 0.0)
    if now - last < RATE_LIMIT_SECONDS:
        return True
    _last_action[user_id] = now
    return False

def is_admin(user_id: int) -> bool:
    return user_id == CONFIG.admin_id

# -------- FSM ----------
class PayFlow(StatesGroup):
    waiting_receipt = State()

class AdminCard(StatesGroup):
    waiting_card = State()
    waiting_owner = State()

class AdminBroadcast(StatesGroup):
    waiting_content = State()
    waiting_confirm = State()

class AdminBalance(StatesGroup):
    waiting_user = State()
    waiting_amount = State()

def ts() -> int:
    return int(time.time())

def get_receipt_ids(msg: Message) -> Tuple[Optional[str], Optional[str]]:
    # returns (file_id, file_unique_id)
    if msg.photo:
        p = msg.photo[-1]
        return p.file_id, p.file_unique_id
    if msg.document:
        d = msg.document
        return d.file_id, d.file_unique_id
    return None, None

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await upsert_user(
        user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        ts=ts()
    )
    await message.answer(start_text(), reply_markup=kb_start(is_admin(message.from_user.id)))

@dp.callback_query(F.data == "start_back")
async def cb_start_back(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text(start_text(), reply_markup=kb_start(is_admin(call.from_user.id)))
    await call.answer()

@dp.callback_query(F.data == "buy_open")
async def cb_buy_open(call: CallbackQuery):
    await call.message.edit_text(buy_hint_text(), reply_markup=kb_subjects())
    await call.answer()

@dp.callback_query(F.data.startswith("buy_"))
async def cb_buy_subject(call: CallbackQuery, state: FSMContext):
    if rate_limited(call.from_user.id):
        await call.answer("Слишком часто 🙏", show_alert=True)
        return

    slug = call.data.replace("buy_", "", 1)
    if slug not in PRODUCTS:
        await call.answer("Товар не найден.", show_alert=True)
        return

    # Антиабуз: нельзя создать новую покупку, если есть pending
    if await has_pending_purchase(call.from_user.id):
        await call.answer()
        await call.message.edit_text(already_pending_text(), reply_markup=kb_payment())
        return

    card_number, card_owner = await get_card()
    purchase_id = await create_purchase(
        user_id=call.from_user.id,
        product_slug=slug,
        amount=PRODUCTS[slug]["price"],
        ts=ts()
    )

    await state.set_state(PayFlow.waiting_receipt)
    await state.update_data(purchase_id=purchase_id)

    await call.message.edit_text(payment_text(slug, card_number, card_owner), reply_markup=kb_payment())

    attempt_left = MAX_RECEIPTS_PER_PURCHASE
    await call.message.answer(ask_receipt_text(slug, attempt_left))
    await call.answer()

@dp.message(PayFlow.waiting_receipt)
async def on_receipt(message: Message, state: FSMContext):
    if rate_limited(message.from_user.id):
        return

    data = await state.get_data()
    purchase_id = data.get("purchase_id")
    if not purchase_id:
        await message.answer("Сессия оплаты потерялась. Нажмите /start и попробуйте снова.")
        await state.clear()
        return

    purchase = await get_purchase(int(purchase_id))
    if not purchase or purchase["status"] != "pending":
        await message.answer("Заявка уже обработана или не найдена. Нажмите /start.")
        await state.clear()
        return

    # лимит попыток отправки чека
    left = MAX_RECEIPTS_PER_PURCHASE - purchase["receipt_count"]
    if left <= 0:
        await message.answer("⚠️ Лимит отправки чеков по этой заявке исчерпан. Напишите в поддержку.")
        return

    file_id, file_uid = get_receipt_ids(message)
    if not file_id or not file_uid:
        await message.answer("Отправьте чек как <b>фото</b> или <b>документ</b> (скрин).")
        return

    # антифрод: запрет повторного использования одного file_unique_id
    if await receipt_is_used(file_uid):
        await message.answer(receipt_reused_text())
        # уведомим админа о попытке
        try:
            uname = f"@{message.from_user.username}" if message.from_user.username else "(без username)"
            await bot.send_message(
                CONFIG.admin_id,
                "⚠️ <b>Подозрительная активность</b>\n"
                f"Пользователь: <b>{message.from_user.first_name}</b> {uname}\n"
                f"user_id: <code>{message.from_user.id}</code>\n"
                f"Попытка повторно использовать чек (file_unique_id). Заявка: <code>#{purchase_id}</code>"
            )
        except Exception:
            pass
        return

    # сохраняем чек
    await attach_receipt(int(purchase_id), file_id, file_uid, ts=ts())
    await mark_receipt_used(file_uid, int(purchase_id), message.from_user.id, ts=ts())

    # обновим left после инкремента
    purchase = await get_purchase(int(purchase_id))
    left = MAX_RECEIPTS_PER_PURCHASE - purchase["receipt_count"]

    # уведомление админу
    p = PRODUCTS[purchase["product_slug"]]
    user = message.from_user
    uname = f"@{user.username}" if user.username else "(без username)"
    admin_text = (
        "🧾 <b>Новая оплата на проверку</b>\n\n"
        f"👤 Пользователь: <b>{user.first_name}</b> {uname}\n"
        f"🆔 user_id: <code>{user.id}</code>\n"
        f"📦 Товар: <b>{p['name']}</b>\n"
        f"💰 Сумма: <b>{p['price']} ₽</b>\n"
        f"🧾 Заявка: <code>#{purchase_id}</code>\n"
        f"🔁 Попыток осталось: <b>{left}</b>"
    )

    try:
        await bot.send_message(CONFIG.admin_id, admin_text, reply_markup=kb_admin_review(int(purchase_id)))
        if message.photo:
            await bot.send_photo(CONFIG.admin_id, file_id, caption=f"Чек по заявке #{purchase_id}")
        else:
            await bot.send_document(CONFIG.admin_id, file_id, caption=f"Чек по заявке #{purchase_id}")
    except Exception:
        pass

    await message.answer(receipt_received_text())

@dp.callback_query(F.data.startswith("admin_approve_"))
async def admin_approve(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа.", show_alert=True)
        return

    purchase_id = int(call.data.replace("admin_approve_", "", 1))
    purchase = await get_purchase(purchase_id)
    if not purchase:
        await call.answer("Заявка не найдена.", show_alert=True)
        return
    if purchase["status"] != "pending":
        await call.answer("Заявка уже обработана.", show_alert=True)
        return

    await set_purchase_status(purchase_id, "approved", ts=ts())

    user_id = purchase["user_id"]
    slug = purchase["product_slug"]
    link = PRODUCTS[slug]["link"]

    try:
        await bot.send_message(user_id, access_granted_text(link))
    except Exception:
        pass

    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("Подтверждено ✅")

@dp.callback_query(F.data.startswith("admin_deny_"))
async def admin_deny(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа.", show_alert=True)
        return

    purchase_id = int(call.data.replace("admin_deny_", "", 1))
    purchase = await get_purchase(purchase_id)
    if not purchase:
        await call.answer("Заявка не найдена.", show_alert=True)
        return
    if purchase["status"] != "pending":
        await call.answer("Заявка уже обработана.", show_alert=True)
        return

    await set_purchase_status(purchase_id, "denied", ts=ts())

    try:
        await bot.send_message(purchase["user_id"], access_denied_text())
    except Exception:
        pass

    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("Отклонено ❌")

# -------- админка ----------
@dp.callback_query(F.data == "admin_open")
async def admin_open(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа.", show_alert=True)
        return
    await state.clear()
    await call.message.edit_text(admin_panel_text(), reply_markup=kb_admin())
    await call.answer()

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа.", show_alert=True)
        return

    users = await get_users_count()
    st = await get_stats()
    await call.message.edit_text(
        stats_text(users, st["purchases_total"], st["approved"], st["pending"], st["denied"], st["revenue"]),
        reply_markup=kb_admin()
    )
    await call.answer()

@dp.callback_query(F.data == "admin_set_card")
async def admin_set_card(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа.", show_alert=True)
        return
    await state.set_state(AdminCard.waiting_card)
    await call.message.edit_text(
        "💳 <b>Реквизиты</b>\n\nОтправьте номер карты (строкой).",
        reply_markup=kb_admin()
    )
    await call.answer()

@dp.message(AdminCard.waiting_card)
async def admin_card_number(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    card = message.text.strip()
    if len(card) < 8:
        await message.answer("Слишком коротко. Отправьте номер карты ещё раз.")
        return
    await state.update_data(card_number=card)
    await state.set_state(AdminCard.waiting_owner)
    await message.answer("Теперь отправьте <b>ФИО получателя</b>.")

@dp.message(AdminCard.waiting_owner)
async def admin_card_owner(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    owner = message.text.strip()
    if len(owner) < 2:
        await message.answer("Слишком коротко. Отправьте ФИО ещё раз.")
        return
    data = await state.get_data()
    card = data.get("card_number", "")
    await set_setting("card_number", card)
    await set_setting("card_owner", owner)
    await state.clear()
    await message.answer(card_updated_text(card, owner), reply_markup=kb_admin())

@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа.", show_alert=True)
        return
    await state.set_state(AdminBroadcast.waiting_content)
    await call.message.edit_text(broadcast_intro_text(), reply_markup=kb_admin())
    await call.answer()

@dp.message(AdminBroadcast.waiting_content)
async def broadcast_get_content(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.update_data(broadcast_message_id=message.message_id, broadcast_chat_id=message.chat.id)
    users = await get_users_count()
    await state.set_state(AdminBroadcast.waiting_confirm)
    await message.answer(broadcast_confirm_text(users), reply_markup=kb_broadcast_confirm())

@dp.callback_query(F.data == "broadcast_cancel")
async def broadcast_cancel(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа.", show_alert=True)
        return
    await state.clear()
    await call.message.edit_text("❌ Рассылка отменена.", reply_markup=kb_admin())
    await call.answer()

@dp.callback_query(F.data == "broadcast_send")
async def broadcast_send(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа.", show_alert=True)
        return

    data = await state.get_data()
    mid = data.get("broadcast_message_id")
    cid = data.get("broadcast_chat_id")
    if not mid or not cid:
        await call.answer("Нет данных для рассылки.", show_alert=True)
        await state.clear()
        return

    user_ids = await get_all_user_ids()
    ok, fail = 0, 0

    for uid in user_ids:
        try:
            await bot.copy_message(chat_id=uid, from_chat_id=cid, message_id=mid)
            ok += 1
        except Exception:
            fail += 1

    await state.clear()
    await call.message.edit_text(broadcast_done_text(ok, fail), reply_markup=kb_admin())
    await call.answer("Готово ✅")

@dp.callback_query(F.data == "admin_give_balance")
async def admin_give_balance(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа.", show_alert=True)
        return
    await state.set_state(AdminBalance.waiting_user)
    await call.message.edit_text(balance_prompt_user_text(), reply_markup=kb_admin())
    await call.answer()

@dp.message(AdminBalance.waiting_user)
async def admin_balance_user(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    raw = message.text.strip()
    user_id: Optional[int] = None

    if raw.isdigit():
        user_id = int(raw)
    elif raw.startswith("@"):
        user_id = await find_user_id_by_username(raw)

    if not user_id:
        await message.answer("Не нашёл. Отправьте <code>@username</code> (если он запускал бота) или <code>user_id</code>.")
        return

    await state.update_data(target_user_id=user_id)
    await state.set_state(AdminBalance.waiting_amount)
    await message.answer(balance_prompt_amount_text())

@dp.message(AdminBalance.waiting_amount)
async def admin_balance_amount(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    raw = message.text.strip()
    if not raw.lstrip("-").isdigit():
        await message.answer("Отправьте целое число (например: 100).")
        return
    amount = int(raw)
    if amount == 0 or abs(amount) > 10_000_000:
        await message.answer("Сумма выглядит странно. Отправьте адекватное число.")
        return

    data = await state.get_data()
    user_id = int(data["target_user_id"])
    new_balance = await add_balance(user_id, amount)
    await state.clear()

    try:
        sign = "+" if amount > 0 else ""
        await bot.send_message(user_id, f"💰 Вам начислен баланс: <b>{sign}{amount}</b>\nТекущий баланс: <b>{new_balance}</b>")
    except Exception:
        pass

    await message.answer(balance_done_text(user_id, new_balance), reply_markup=kb_admin())

async def main():
    await init_db()
    await ensure_default_card()
    await dp.start_polling(bot)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
