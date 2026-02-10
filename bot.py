import json
import sys
import asyncio
import random
import string
import io
from datetime import datetime, timedelta

try:
    from captcha.image import ImageCaptcha
except ImportError:
    print("❌ ОШИБКА: Не установлена библиотека captcha. Выполните: pip install captcha")
    sys.exit()

from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton, ChatMember
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, CallbackContext
from telegram.error import BadRequest, Forbidden

print("Python version:", sys.version)

# --- КОНФИГУРАЦИЯ ---
DATA_FILE = "data.json"
SUPER_ADMIN_IDS = [7635015201] 
TOKEN = "7872046358:AAHnneGHEKw5xanQakSwePb-omQRnNO4_OE"

# ПРАВА ДОСТУПА
PERM_BAN = 'ban_users'
PERM_BROADCAST = 'broadcast'
PERM_ACCS = 'manage_accs'
PERM_PROMOS = 'manage_promos'
PERM_CHANNELS = 'manage_channels'
PERM_ADD_ADMIN = 'add_admin'
PERM_SETTINGS = 'manage_settings'
PERM_REVIEWS = 'moderate_reviews'

DEFAULT_PERMISSIONS = {
    PERM_BAN: True,
    PERM_BROADCAST: True,
    PERM_ACCS: True,
    PERM_PROMOS: True,
    PERM_CHANNELS: True,
    PERM_ADD_ADMIN: True,
    PERM_SETTINGS: True,
    PERM_REVIEWS: True
}

# ИГРЫ
GAME_TANKS = 'tanks'
GAME_BLITZ = 'blitz'
GAME_NAMES = {
    GAME_TANKS: "TanksBlitz",
    GAME_BLITZ: "WoT Blitz"
}

# Флаг остановки бота
BOT_STOPPED = False

# Структура данных по умолчанию
default_data = {
    "accounts_common_tanks": [],
    "accounts_promo_tanks": [],
    "accounts_common_blitz": [],
    "users": {}, 
    "channels": [],
    "admins": {},
    "promocodes": {}, 
    "reviews": [],
    "pending_reviews": [],
    "banned_users": [],
    "settings": {
        "coin_reward": 1,
        "exchange_price": 10,
        "faq_text": """ℹ️ <b>FAQ</b>

🔹 <b>Лимит:</b> 1 бесплатный аккаунт в 24 часа.
🔹 <b>Монеты:</b> Даются ТОЛЬКО за приглашение друзей.
🔹 <b>Условия:</b> Друг должен перейти по вашей ссылке и пройти регистрацию.
🔹 <b>Награда:</b> 1 монет за друга (начисляется сразу после регистрации).
🔹 <b>Обмен:</b> 10 монет = 1 аккаунт.
🔹 <b>Промокоды:</b> Дают аккаунты бесплатно (только из TanksBlitz).
🔹 <b>Поддержка:</b> @texpoddergka2026_bot"""
    }
}

# Загрузка данных
try:
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
        migrated = False
        
        if "pending_reviews" not in data:
            data["pending_reviews"] = []
            migrated = True
            
        if "accounts" in data:
            if not data.get("accounts_common_tanks"):
                data["accounts_common_tanks"] = data["accounts"]
            del data["accounts"]
            migrated = True
            
        if "accounts_common" in data:
            if not data.get("accounts_common_tanks"):
                data["accounts_common_tanks"] = data["accounts_common"]
            del data["accounts_common"]
            migrated = True
            
        if "accounts_promo" in data:
            if not data.get("accounts_promo_tanks"):
                data["accounts_promo_tanks"] = data["accounts_promo"]
            del data["accounts_promo"]
            migrated = True
        
        for game in [GAME_TANKS, GAME_BLITZ]:
            for acc_type in ["common"]:
                key = f"accounts_{acc_type}_{game}"
                if key not in data:
                    data[key] = []
                    migrated = True
        
        if "accounts_promo_tanks" not in data:
            data["accounts_promo_tanks"] = []
            migrated = True

        if "settings" not in data:
            data["settings"] = default_data["settings"]
            migrated = True
        else:
            if "support_text" in data["settings"]:
                del data["settings"]["support_text"]
                migrated = True
                
            if "faq_text" not in data["settings"]:
                data["settings"]["faq_text"] = default_data["settings"]["faq_text"]
                migrated = True

        for key, value in default_data.items():
            if key not in data:
                data[key] = value
                migrated = True
        
        for admin_id, admin_data in data.get("admins", {}).items():
            if "notifications" not in admin_data:
                admin_data["notifications"] = {}
                migrated = True
            if PERM_REVIEWS not in admin_data.get("permissions", {}):
                admin_data["permissions"][PERM_REVIEWS] = True
                migrated = True

        for user_id, user_data in data.get("users", {}).items():
            if "captcha_passed" not in user_data:
                user_data["captcha_passed"] = True
                migrated = True
        
        if migrated:
            print("⚠️ Произведена миграция структуры базы данных.")
            
except FileNotFoundError:
    data = default_data
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
except Exception as e:
    print(f"Ошибка чтения данных: {e}")
    data = default_data

def save():
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def is_admin(user_id: int) -> bool:
    if user_id in SUPER_ADMIN_IDS:
        return True
    return str(user_id) in data.get("admins", {})

def check_perm(user_id: int, perm: str) -> bool:
    if user_id in SUPER_ADMIN_IDS:
        return True
    admin_data = data.get("admins", {}).get(str(user_id))
    if not admin_data: return False
    return admin_data.get("permissions", {}).get(perm, False)

def get_user_link(user):
    if hasattr(user, 'id'):
        return f'<a href="tg://user?id={user.id}">{user.full_name}</a> (ID: <code>{user.id}</code>)'
    return f'<a href="tg://user?id={user}">Пользователь</a> (ID: <code>{user}</code>)'

async def notify_super_admins(context: CallbackContext, text: str):
    """Уведомление только супер-админов"""
    if not SUPER_ADMIN_IDS:
        return
    
    for owner_id in SUPER_ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=owner_id,
                text=f"🔔 <b>Уведомление</b>\n\n{text}",
                parse_mode='HTML'
            )
            await asyncio.sleep(0.1)
        except Exception as e:
            print(f"Ошибка отправки уведомления {owner_id}: {e}")

def generate_captcha():
    image = ImageCaptcha(width=280, height=90)
    captcha_text = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
    data_img = image.generate(captcha_text)
    return captcha_text, data_img

def menu(user_id: int):
    kb = [
        ["🎮 Получить аккаунт", "📜 История"],
        ["💎 Обменять монеты", "🎟 Промокод"],
        ["ℹ️ О боте", "⭐ Отзывы"],
        ["✅ Проверить подписку", "👤 Мой профиль"]
    ]
    if is_admin(user_id):
        kb.append(["👑 Админ"])

    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

def reviews_keyboard():
    keyboard = [
        [InlineKeyboardButton("📝 Посмотреть отзывы", callback_data="view_reviews")],
        [InlineKeyboardButton("⭐ Оставить отзыв", callback_data="leave_review")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_sub_keyboard(channels_list):
    kb = []
    for ch in channels_list:
        url = ch
        if ch.startswith("@"):
            url = f"https://t.me/{ch[1:]}"
        elif "t.me" not in ch:
            url = f"https://t.me/{ch}"
        kb.append([InlineKeyboardButton(f"Подписаться", url=url)])
    kb.append([InlineKeyboardButton("✅ Я подписался", callback_data="check_sub_confirm")])
    return InlineKeyboardMarkup(kb)

def exchange_keyboard():
    kb = [
        [InlineKeyboardButton("💎 Обменять монеты", callback_data="exchange_coins")],
        [InlineKeyboardButton("❌ Отмена", callback_data="delete_msg")]
    ]
    return InlineKeyboardMarkup(kb)

def game_selection_keyboard():
    kb = [
        [InlineKeyboardButton("• TanksBlitz", callback_data=f"select_game_{GAME_TANKS}")],
        [InlineKeyboardButton("• WoT Blitz", callback_data=f"select_game_{GAME_BLITZ}")]
    ]
    return InlineKeyboardMarkup(kb)

def admin_kb_main(user_id):
    """Админ-панель: супер-админу ВСЕ кнопки, обычным админам - по правам"""
    status_icon = "▶️" if not BOT_STOPPED else "⏸"
    
    # Для супер-админа - ВСЕ кнопки всегда
    if user_id in SUPER_ADMIN_IDS:
        keyboard = [
            [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
            [
                InlineKeyboardButton("📦 Аккаунты", callback_data="admin_menu_accs"),
                InlineKeyboardButton("🎟 Промокоды", callback_data="admin_menu_promo")
            ],
            [
                InlineKeyboardButton("⭐ Отзывы", callback_data="admin_menu_reviews"),
                InlineKeyboardButton("👥 Пользователи", callback_data="admin_menu_users")
            ],
            [
                InlineKeyboardButton("📣 Рассылка", callback_data="admin_broadcast_start"),
                InlineKeyboardButton("✉️ ЛС", callback_data="admin_pm")
            ],
            [
                InlineKeyboardButton("📢 Каналы", callback_data="admin_menu_channels"),
                InlineKeyboardButton("🛡 Админы", callback_data="admin_menu_admins")
            ],
            [InlineKeyboardButton("⚙️ Настройки", callback_data="admin_menu_settings")],
            [InlineKeyboardButton(f"{status_icon} Стоп/Старт Бот", callback_data="admin_toggle_bot")],
            [InlineKeyboardButton("❌ Закрыть", callback_data="admin_close")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    # Для обычных админов - проверка прав
    kb = []
    kb.append([InlineKeyboardButton("📊 Полная Статистика", callback_data="admin_stats")])
    
    row2 = []
    if check_perm(user_id, PERM_ACCS):
        row2.append(InlineKeyboardButton("📦 Аккаунты", callback_data="admin_menu_accs"))
    if check_perm(user_id, PERM_PROMOS):
        row2.append(InlineKeyboardButton("🎟 Промокоды", callback_data="admin_menu_promo"))
    if row2: 
        kb.append(row2)
    else:
        # Если нет ни одного права из row2, добавляем пустую строку
        if check_perm(user_id, PERM_ACCS) or check_perm(user_id, PERM_PROMOS):
            kb.append([])

    row3 = []
    if check_perm(user_id, PERM_REVIEWS):
        row3.append(InlineKeyboardButton("⭐ Отзывы", callback_data="admin_menu_reviews"))
    if check_perm(user_id, PERM_BAN):
        row3.append(InlineKeyboardButton("👥 Пользователи", callback_data="admin_menu_users"))
    if row3: 
        kb.append(row3)
    else:
        if check_perm(user_id, PERM_REVIEWS) or check_perm(user_id, PERM_BAN):
            kb.append([])

    row4 = []
    if check_perm(user_id, PERM_BROADCAST):
        row4.append(InlineKeyboardButton("📣 Рассылка", callback_data="admin_broadcast_start"))
    row4.append(InlineKeyboardButton("✉️ ЛС", callback_data="admin_pm"))
    if row4: 
        kb.append(row4)
    else:
        if check_perm(user_id, PERM_BROADCAST):
            kb.append([])

    row5 = []
    if check_perm(user_id, PERM_CHANNELS):
        row5.append(InlineKeyboardButton("📢 Каналы", callback_data="admin_menu_channels"))
    if check_perm(user_id, PERM_ADD_ADMIN):
        row5.append(InlineKeyboardButton("🛡 Админы", callback_data="admin_menu_admins"))
    if row5: 
        kb.append(row5)
    else:
        if check_perm(user_id, PERM_CHANNELS) or check_perm(user_id, PERM_ADD_ADMIN):
            kb.append([])

    if check_perm(user_id, PERM_SETTINGS):
        kb.append([InlineKeyboardButton("⚙️ Настройки", callback_data="admin_menu_settings")])

    kb.append([InlineKeyboardButton(f"{status_icon} Стоп/Старт Бот", callback_data="admin_toggle_bot")])
    kb.append([InlineKeyboardButton("❌ Закрыть", callback_data="admin_close")])
    
    return InlineKeyboardMarkup(kb)

def admin_kb_accounts():
    total_accounts = (len(data['accounts_common_tanks']) + len(data['accounts_promo_tanks']) +
                     len(data['accounts_common_blitz']))
    
    text = f"""📦 <b>Управление аккаунтами</b>

📊 <b>Статистика аккаунтов:</b>
• Всего аккаунтов в наличии: {total_accounts}
• TanksBlitz (Общая): {len(data['accounts_common_tanks'])} шт.
• TanksBlitz (Промо): {len(data['accounts_promo_tanks'])} шт.
• WoT Blitz (Общая): {len(data['accounts_common_blitz'])} шт.

Выберите действие:"""
    
    kb = [
        [InlineKeyboardButton("🔄 Загрузить (TXT)", callback_data="admin_acc_load")],
        [InlineKeyboardButton("🎯 Выбрать игру", callback_data="admin_select_game")],
        [InlineKeyboardButton("🔙 Назад", callback_data="admin_main")]
    ]
    return InlineKeyboardMarkup(kb)

def admin_kb_acc_game_selection():
    kb = [
        [InlineKeyboardButton("• TanksBlitz", callback_data=f"admin_game_{GAME_TANKS}")],
        [InlineKeyboardButton("• WoT Blitz", callback_data=f"admin_game_{GAME_BLITZ}")],
        [InlineKeyboardButton("🔙 Назад", callback_data="admin_menu_accs")]
    ]
    return InlineKeyboardMarkup(kb)

def admin_kb_acc_actions_for_game(game):
    game_name = GAME_NAMES[game]
    
    if game == GAME_TANKS:
        kb = [
            [InlineKeyboardButton(f"📦 Загрузить в Общую ({game_name})", callback_data=f"upload_to_common_{game}")],
            [InlineKeyboardButton(f"🎟 Загрузить в Промо ({game_name})", callback_data=f"upload_to_promo_{game}")],
            [InlineKeyboardButton(f"❌ Удалить ВСЕ Общие ({game_name})", callback_data=f"admin_acc_del_common_{game}")],
            [InlineKeyboardButton(f"❌ Удалить ВСЕ Промо ({game_name})", callback_data=f"admin_acc_del_promo_{game}")],
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_menu_accs")]
        ]
    else:
        kb = [
            [InlineKeyboardButton(f"📦 Загрузить в Общую ({game_name})", callback_data=f"upload_to_common_{game}")],
            [InlineKeyboardButton(f"❌ Удалить ВСЕ Общие ({game_name})", callback_data=f"admin_acc_del_common_{game}")],
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_menu_accs")]
        ]
    return InlineKeyboardMarkup(kb)

def admin_kb_settings():
    kb = [
        [InlineKeyboardButton("💰 Изменить цену аккаунта", callback_data="set_price")],
        [InlineKeyboardButton("🤝 Изменить награду за реферала", callback_data="set_reward")],
        [InlineKeyboardButton("📝 Изменить текст FAQ", callback_data="set_faq_text")],
        [InlineKeyboardButton("🔙 Назад", callback_data="admin_main")]
    ]
    return InlineKeyboardMarkup(kb)

def admin_kb_promo_source_choice():
    kb = [
        [InlineKeyboardButton("📦 С ОБЩЕЙ базы (TanksBlitz)", callback_data="promo_src_common")],
        [InlineKeyboardButton("🎟 С ПРОМО базы (TanksBlitz)", callback_data="promo_src_promo")],
        [InlineKeyboardButton("❌ Отмена", callback_data="admin_main")]
    ]
    return InlineKeyboardMarkup(kb)

def admin_kb_channels():
    kb = [
        [InlineKeyboardButton("➕ Добавить канал", callback_data="admin_channel_add")],
        [InlineKeyboardButton("➖ Удалить канал", callback_data="admin_channel_del")],
        [InlineKeyboardButton("📋 Список каналов", callback_data="admin_channel_list")],
        [InlineKeyboardButton("🔙 Назад", callback_data="admin_main")]
    ]
    return InlineKeyboardMarkup(kb)

def admin_kb_admins_list():
    kb = []
    for adm_id, adm_data in data.get("admins", {}).items():
        name = adm_data.get("name", f"ID: {adm_id}")
        kb.append([InlineKeyboardButton(f"👤 {name}", callback_data=f"adm_edit:{adm_id}")])
    kb.append([InlineKeyboardButton("➕ Назначить админа", callback_data="admin_add_new")])
    kb.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_main")])
    return InlineKeyboardMarkup(kb)

def admin_kb_admin_rights(target_id):
    perms = data.get("admins", {}).get(str(target_id), {}).get("permissions", {})
    def p_btn(key, text):
        status = "✅" if perms.get(key, False) else "❌"
        return InlineKeyboardButton(f"{status} {text}", callback_data=f"adm_toggle:{target_id}:{key}")
    kb = [
        [p_btn(PERM_ACCS, "Аккаунты"), p_btn(PERM_PROMOS, "Промо")],
        [p_btn(PERM_BAN, "Бан"), p_btn(PERM_BROADCAST, "Рассылка")],
        [p_btn(PERM_CHANNELS, "Каналы"), p_btn(PERM_ADD_ADMIN, "Админы")],
        [p_btn(PERM_SETTINGS, "Настройки"), p_btn(PERM_REVIEWS, "Модерация")],
        [InlineKeyboardButton("🗑 УДАЛИТЬ АДМИНА", callback_data=f"adm_delete:{target_id}")],
        [InlineKeyboardButton("🔙 К списку", callback_data="admin_menu_admins")]
    ]
    return InlineKeyboardMarkup(kb)

def admin_kb_promo():
    kb = [
        [InlineKeyboardButton("🎟 Создать промокод", callback_data="admin_promo_create")],
        [InlineKeyboardButton("📋 Список активных", callback_data="admin_promo_list")],
        [InlineKeyboardButton("🔙 Назад", callback_data="admin_main")]
    ]
    return InlineKeyboardMarkup(kb)

def admin_kb_reviews():
    kb = [
        [InlineKeyboardButton("📝 Модерация отзывов", callback_data="admin_review_moderate")],
        [InlineKeyboardButton("📋 Читать все", callback_data="admin_review_all")],
        [InlineKeyboardButton("🗑 Очистить ВСЕ", callback_data="admin_review_clear_all")],
        [InlineKeyboardButton("❌ Удалить по номеру", callback_data="admin_review_del_one")],
        [InlineKeyboardButton("🔙 Назад", callback_data="admin_main")]
    ]
    return InlineKeyboardMarkup(kb)

def admin_kb_users():
    kb = [
        [InlineKeyboardButton("⛔ Забанить ID", callback_data="admin_user_ban")],
        [InlineKeyboardButton("✅ Разбанить ID", callback_data="admin_user_unban")],
        [InlineKeyboardButton("🔙 Назад", callback_data="admin_main")]
    ]
    return InlineKeyboardMarkup(kb)

def broadcast_add_btn_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добавить кнопку", callback_data="bc_add_btn_yes")],
        [InlineKeyboardButton("➡️ Нет, далее", callback_data="bc_add_btn_no")]
    ])

def broadcast_confirm_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 ЗАПУСТИТЬ", callback_data="bc_confirm_send")],
        [InlineKeyboardButton("✏️ Изм. сообщение", callback_data="bc_edit_msg")],
        [InlineKeyboardButton("✏️ Изм. кнопку", callback_data="bc_add_btn_yes")],
        [InlineKeyboardButton("❌ Отмена", callback_data="admin_main")]
    ])

def back_btn(callback_data="admin_main"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data=callback_data)]])

def moderation_review_kb(review_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Одобрить", callback_data=f"mod_approve:{review_id}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"mod_reject:{review_id}")
        ],
        [InlineKeyboardButton("📋 К списку", callback_data="admin_review_moderate")]
    ])

def admin_kb_review_moderation():
    pending_count = len(data["pending_reviews"])
    approved_count = len(data["reviews"])
    
    kb = []
    
    if pending_count > 0:
        kb.append([InlineKeyboardButton(f"⏳ Ожидают ({pending_count})", callback_data="mod_view_pending")])
    
    kb.append([InlineKeyboardButton(f"✅ Опубликованные ({approved_count})", callback_data="mod_view_approved")])
    kb.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_menu_reviews")])
    
    return InlineKeyboardMarkup(kb)

async def start(update: Update, context: CallbackContext):
    global BOT_STOPPED
    if BOT_STOPPED and not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Бот временно остановлен.")
        return

    user = update.effective_user
    user_id = str(user.id)
    
    new_referrer = None
    if context.args and len(context.args) > 0:
        possible_id = context.args[0]
        if possible_id != user_id and possible_id in data["users"]:
            new_referrer = possible_id

    is_new = False
    if user_id not in data["users"]:
        is_new = True
        data["users"][user_id] = {
            "name": user.full_name,
            "username": user.username,
            "coins": 0,
            "received": 0,
            "used_promocodes": [],
            "history": [],
            "join_date": datetime.now().isoformat(),
            "referrer_id": new_referrer,
            "captcha_passed": False
        }
        save()
    else:
        if new_referrer and not data["users"][user_id].get("captcha_passed", False):
            data["users"][user_id]["referrer_id"] = new_referrer
            save()

    user_data = data["users"][user_id]
    
    if not user_data.get("captcha_passed", False):
        captcha_text, captcha_image = generate_captcha()
        
        context.user_data["captcha_correct"] = captcha_text
        context.user_data["awaiting_captcha"] = True
        
        captcha_image.seek(0)
        await update.message.reply_photo(
            photo=captcha_image,
            caption="🔒 <b>Проверка на бота</b>\nВведите код с картинки, чтобы продолжить:",
            parse_mode='HTML'
        )
        return
    
    if is_new or context.user_data.get("just_passed_captcha"):
        if "just_passed_captcha" in context.user_data:
            del context.user_data["just_passed_captcha"]
        
        ref_id = user_data.get("referrer_id")
        
        await notify_super_admins(
            context,
            f"👤 <b>НОВЫЙ ПОЛЬЗОВАТЕЛЬ!</b>\nИмя: {get_user_link(user)}\nПригласил: {ref_id if ref_id else 'Никто'}"
        )
        
        # НАЧИСЛЕНИЕ МОНЕТ СРАЗУ ПОСЛЕ РЕГИСТРАЦИИ
        if ref_id and ref_id in data["users"]:
            reward = data["settings"]["coin_reward"]
            data["users"][ref_id]["coins"] += reward
            
            try:
                await context.bot.send_message(
                    chat_id=int(ref_id),
                    text=f"💰 <b>Реферальный бонус начислен!</b>\nПо вашей ссылке зарегистрировался новый пользователь: {user.full_name}\nВам начислено: {reward} монет.",
                    parse_mode='HTML'
                )
            except: pass
            
            await notify_super_admins(
                context,
                f"🤝 <b>РЕФЕРАЛЬНОЕ НАЧИСЛЕНИЕ</b>\nРефовод: {ref_id}\nРеферал: {get_user_link(user)}\nНачислено: {reward} монет"
            )
            
            save()

    await send_main_menu(update, context)

async def send_main_menu(update: Update, context: CallbackContext):
    user = update.effective_user
    user_id = str(user.id)
    coin_reward = data["settings"]["coin_reward"]
    exchange_price = data["settings"]["exchange_price"]

    text = f"""🎮 <b>Добро пожаловать!</b>

🤖 Я бот по бесплатной раздаче аккаунтов!

🔹 <b>Лимит:</b> 1 аккаунт в 24 часа.
🔹 <b>Монеты:</b> Зарабатываются ТОЛЬКО приглашением друзей!
🔹 <b>Рефералка:</b> {coin_reward} монета за друга (начисляется сразу после регистрации).
🔹 <b>Обмен:</b> {exchange_price} монет = 1 аккаунт.

🔗 <b>Ваша реферальная ссылка:</b>
<code>https://t.me/{context.bot.username}?start={user_id}</code>

Выберите действие из меню ниже:"""

    if update.message:
        await update.message.reply_text(text, parse_mode='HTML', reply_markup=menu(user.id))
    elif update.callback_query:
        await update.callback_query.message.reply_text(text, parse_mode='HTML', reply_markup=menu(user.id))

async def panel_command(update: Update, context: CallbackContext):
    user = update.effective_user
    if is_admin(user.id):
        await update.message.reply_text("👑 <b>Админ панель</b>\nВыберите раздел:", parse_mode='HTML', reply_markup=admin_kb_main(user.id))
    else:
        await update.message.reply_text("❌ У вас нет доступа.", reply_markup=menu(user.id))

async def user_info_command(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id): 
        await update.message.reply_text("❌ У вас нет доступа к этой команде.")
        return
    
    if context.args:
        target_id = context.args[0]
        
        if target_id in data["users"]:
            user_data = data["users"][target_id]
            
            history = user_data.get('history', [])
            if history:
                last_activity = datetime.fromisoformat(history[-1]["date"]).strftime('%d.%m.%Y %H:%M')
            else:
                last_activity = "Никогда"
            
            tanks_count = sum(1 for item in history if item.get("game") == GAME_TANKS)
            blitz_count = sum(1 for item in history if item.get("game") == GAME_BLITZ)
            
            referrer_id = user_data.get("referrer_id", "Нет")
            
            info = f"""📊 <b>СТАТИСТИКА ПОЛЬЗОВАТЕЛЯ</b>

👤 <b>Основная информация:</b>
🆔 ID: <code>{target_id}</code>
👤 Имя: {user_data['name']}
📅 Дата регистрации: {datetime.fromisoformat(user_data['join_date']).strftime('%d.%m.%Y %H:%M')}
🕐 Последняя активность: {last_activity}
👥 Реферер: {referrer_id}

💰 <b>Экономика:</b>
💎 Монеты: {user_data['coins']}
🎮 Всего получено аккаунтов: {user_data['received']}
🎟 Использовано промокодов: {len(user_data.get('used_promocodes', []))}

🎮 <b>Статистика по играм:</b>
• TanksBlitz: {tanks_count} аккаунтов
• WoT Blitz: {blitz_count} аккаунтов

📜 <b>История (последние 5 аккаунтов):</b>"""
            
            if history:
                for i, item in enumerate(history[-5:], 1):
                    date = datetime.fromisoformat(item["date"]).strftime('%d.%m.%Y %H:%M')
                    game = GAME_NAMES.get(item.get("game", GAME_TANKS), "Unknown")
                    acc_type = "🎁 Бесплатно" if item.get("type") == "daily_free" else ("💎 За монеты" if item.get("type") == "exchange" else "🎟 Промокод")
                    info += f"\n{i}. {date} | {game} | {acc_type}\n   <code>{item['account']}</code>"
            else:
                info += "\n📭 История пуста"
            
            info += f"\n\n🔨 <b>Статус:</b> {'⛔ ЗАБАНЕН' if target_id in data.get('banned_users', []) else '✅ АКТИВЕН'}"
            
            await update.message.reply_text(info, parse_mode='HTML')
        else:
            await update.message.reply_text(f"❌ Пользователь с ID <code>{target_id}</code> не найден.", parse_mode='HTML')
    else:
        await update.message.reply_text(
            "ℹ️ <b>Использование команды:</b>\n<code>/info ID_ПОЛЬЗОВАТЕЛЯ</code>\n\n📌 <b>Пример:</b>\n<code>/info 123456789</code>",
            parse_mode='HTML'
        )

async def about_bot(update: Update, context: CallbackContext):
    faq_text = data["settings"]["faq_text"]
    await update.message.reply_text(faq_text, parse_mode='HTML', reply_markup=menu(update.effective_user.id))

async def get_account(update: Update, context: CallbackContext):
    global BOT_STOPPED
    if BOT_STOPPED and not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Бот временно остановлен.")
        return

    user = update.effective_user
    user_id = str(user.id)

    if user_id in data.get("banned_users", []):
        await update.message.reply_text("❌ Вы заблокированы.")
        return

    is_sub, not_sub_list = await check_subscription_logic(user.id, context)
    if not is_sub:
        await update.message.reply_text(
            f"🛑 <b>Доступ ограничен!</b>\n\nДля получения аккаунтов необходимо подписаться на наших спонсоров:",
            parse_mode='HTML',
            reply_markup=get_sub_keyboard(not_sub_list)
        )
        return

    user_data = data["users"][user_id]
    if user_data.get("last_receive"):
        last_time = datetime.fromisoformat(user_data["last_receive"])
        if datetime.now() - last_time < timedelta(hours=24):
            next_time = last_time + timedelta(hours=24)
            wait = next_time - datetime.now()
            hours = wait.seconds // 3600
            minutes = (wait.seconds % 3600) // 60
            await update.message.reply_text(
                f"⏰ <b>Лимит: 1 аккаунт в 24 часа</b>\n\nСледующий аккаунт можно получить через:\n<b>{hours} часов {minutes} минут</b>",
                parse_mode='HTML',
                reply_markup=menu(user.id)
            )
            return

    await update.message.reply_text(
        "🎮 <b>Выберите игру для получения аккаунта:</b>\n\n👇 Нажмите на кнопку с нужной игрой:",
        parse_mode='HTML',
        reply_markup=game_selection_keyboard()
    )
    context.user_data["awaiting_game_selection"] = True
    context.user_data["awaiting_account_action"] = "get"

async def process_game_selection(update: Update, context: CallbackContext, game):
    """Обработка выбора игры для получения аккаунта"""
    query = update.callback_query
    await query.answer()
    user = query.from_user
    user_id = str(user.id)
    user_data = data["users"][user_id]
    
    game_accounts = data.get(f"accounts_common_{game}", [])
    
    if not game_accounts:
        await query.edit_message_text(f"❌ В базе {GAME_NAMES[game]} пока нет аккаунтов. Попробуйте позже.")
        await context.bot.send_message(chat_id=user.id, text="Возвращаю меню...", reply_markup=menu(user.id))
        return

    account = game_accounts.pop(0)
    data[f"accounts_common_{game}"] = game_accounts

    user_data["received"] += 1
    user_data["last_receive"] = datetime.now().isoformat()
    user_data["history"] = user_data.get("history", []) + [{
        "date": datetime.now().isoformat(),
        "account": account,
        "type": "daily_free",
        "game": game
    }]
    
    await notify_super_admins(
        context,
        f"🎁 <b>ВЫДАН БЕСПЛАТНЫЙ АККАУНТ</b>\nКому: {get_user_link(user)}\nИгра: {GAME_NAMES[game]}\nАккаунт: <code>{account}</code>"
    )

    save()

    await query.edit_message_text(
        f"✅ <b>Аккаунт получен!</b>\n\n🎮 Игра: {GAME_NAMES[game]}\n🔐 <code>{account}</code>\n\n⚠️ <b>Следующий через 24 часа</b>\n💡 Приглашай друзей, чтобы получать монеты!",
        parse_mode='HTML'
    )
    await context.bot.send_message(chat_id=user.id, text="Выберите действие:", reply_markup=menu(user.id))

async def profile(update: Update, context: CallbackContext):
    global BOT_STOPPED
    if BOT_STOPPED and not is_admin(update.effective_user.id):
        return

    user = update.effective_user
    user_id = str(user.id)

    if user_id in data["users"]:
        user_data = data["users"][user_id]
        used_promo = len(user_data.get("used_promocodes", []))
        exchange_price = data["settings"]["exchange_price"]
        coin_reward = data["settings"]["coin_reward"]

        time_text = ""
        if user_data.get("last_receive"):
            last = datetime.fromisoformat(user_data["last_receive"])
            next_time = last + timedelta(hours=24)
            if datetime.now() < next_time:
                wait = next_time - datetime.now()
                hours = wait.seconds // 3600
                minutes = (wait.seconds % 3600) // 60
                time_text = f"\n⏰ Следующий через: {hours}ч {minutes}м"
            else:
                time_text = "\n✅ Можете получить аккаунт"

        text = f"""👤 <b>Профиль</b>

🆔 ID: {user_id}
👤 Имя: {user_data['name']}
📅 Регистрация: {datetime.fromisoformat(user_data['join_date']).strftime('%d.%m.%Y')}
🎮 Получено аккаунтов: {user_data['received']}
💎 Монеты: {user_data['coins']}
🎟 Промокоды: {used_promo}{time_text}

🔗 <b>Реферальная ссылка:</b>
<code>https://t.me/{context.bot.username}?start={user_id}</code>
(Награда за друга: {coin_reward} монет СРАЗУ после регистрации)

💎 <b>Обмен монет:</b>
1 аккаунт = {exchange_price} монет

<i>Нажмите "💎 Обменять монеты" в меню, чтобы обменять монеты на аккаунт.</i>"""

        await update.message.reply_text(text, parse_mode='HTML', reply_markup=menu(user.id))
    else:
        await update.message.reply_text("❌ Профиль не найден", reply_markup=menu(user.id))

async def account_history(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)
    if user_id not in data["users"]:
        await update.message.reply_text("❌ Запустите бота /start", reply_markup=menu(int(user_id)))
        return

    user_data = data["users"][user_id]
    history = user_data.get("history", [])

    if not history:
        await update.message.reply_text("📜 История пуста", reply_markup=menu(int(user_id)))
        return

    text = "📜 <b>История (последние 10):</b>\n\n"
    for i, item in enumerate(history[-10:], 1):
        date = datetime.fromisoformat(item["date"]).strftime("%d.%m %H:%M")
        acc_type = item.get("type", "unknown")
        game = item.get("game", "tanks")
        game_name = GAME_NAMES.get(game, "Unknown")
        type_icon = "🎁" if acc_type == "daily_free" else ("💎" if "exchange" in acc_type else "🎟")
        text += f"{i}. {date} {type_icon} ({game_name})\n   <code>{item['account']}</code>\n\n"

    await update.message.reply_text(text, parse_mode='HTML', reply_markup=menu(int(user_id)))

async def exchange_coins(update: Update, context: CallbackContext):
    global BOT_STOPPED
    if BOT_STOPPED and not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Бот временно остановлен.")
        return

    user_id = str(update.effective_user.id)
    user_data = data["users"][user_id]
    coins = user_data["coins"]
    price = data["settings"]["exchange_price"]

    if coins < price:
        await update.message.reply_text(
            f"❌ Недостаточно монет!\n\nВаш баланс: {coins} монет\nНужно для обмена: {price} монет\n\n💡 Приглашайте друзей по реферальной ссылке, чтобы получать монеты!",
            reply_markup=menu(int(user_id))
        )
        return

    await update.message.reply_text(
        "🎮 <b>Выберите игру для обмена монет:</b>\n\n👇 Нажмите на кнопку с нужной игрой:",
        parse_mode='HTML',
        reply_markup=game_selection_keyboard()
    )
    context.user_data["awaiting_game_selection"] = True
    context.user_data["awaiting_account_action"] = "exchange"

async def process_exchange_game_selection(update: Update, context: CallbackContext, game):
    """Обработка выбора игры для обмена монет"""
    query = update.callback_query
    await query.answer()
    user_id = str(query.from_user.id)
    user_data = data["users"][user_id]
    price = data["settings"]["exchange_price"]
    
    game_accounts = data.get(f"accounts_common_{game}", [])
    if not game_accounts:
        await query.edit_message_text(f"❌ В базе {GAME_NAMES[game]} закончились аккаунты! Попробуйте позже.")
        await context.bot.send_message(chat_id=query.from_user.id, text="Возвращаю меню...", reply_markup=menu(int(user_id)))
        return

    account = game_accounts.pop(0)
    data[f"accounts_common_{game}"] = game_accounts
    
    user_data["coins"] -= price
    user_data["history"].append({
        "date": datetime.now().isoformat(),
        "account": account,
        "type": "exchange",
        "game": game
    })
    save()
    
    # УВЕДОМЛЕНИЕ СУПЕР-АДМИНОВ ОБ ОБМЕНЕ
    await notify_super_admins(
        context,
        f"💎 <b>ПОКУПКА ЗА МОНЕТЫ</b>\nПокупатель: {get_user_link(query.from_user)}\nИгра: {GAME_NAMES[game]}\nСтоимость: {price} монет\nАккаунт: <code>{account}</code>"
    )
    
    await query.edit_message_text(
        f"✅ <b>Успешный обмен!</b>\n\n🎮 Игра: {GAME_NAMES[game]}\n💎 Списано: {price} монет\n🔐 Аккаунт:\n<code>{account}</code>\n\n💡 Продолжайте приглашать друзей за монеты!",
        parse_mode='HTML'
    )
    await context.bot.send_message(chat_id=query.from_user.id, text="Выберите действие:", reply_markup=menu(int(user_id)))

async def check_subscription_logic(user_id: int, context: CallbackContext):
    channels = data.get("channels", [])
    if not channels:
        return True, []
    
    not_subscribed = []
    
    for channel in channels:
        try:
            chat_id = None
            if channel.startswith("@"):
                chat_id = channel
            elif "t.me/" in channel:
                username = channel.split("t.me/")[1].split("/")[0]
                if username:
                    chat_id = f"@{username}"
            else:
                chat_id = channel
            
            if chat_id:
                member = await context.bot.get_chat_member(chat_id, user_id)
                if member.status not in [ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
                    not_subscribed.append(channel)
        except:
            not_subscribed.append(channel)
    
    return len(not_subscribed) == 0, not_subscribed

async def check_subscription(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    is_sub, not_sub_list = await check_subscription_logic(user_id, context)
    
    if is_sub:
        await update.message.reply_text("✅ <b>Вы подписаны на все каналы!</b>", parse_mode='HTML')
    else:
        await update.message.reply_text(
            f"❌ <b>Вы не подписаны на все каналы!</b>\n\nНеобходимо подписаться на:",
            parse_mode='HTML',
            reply_markup=get_sub_keyboard(not_sub_list)
        )

async def main_callback_handler(update: Update, context: CallbackContext):
    global BOT_STOPPED
    
    query = update.callback_query
    cb_data = query.data 
    user_id = query.from_user.id
    str_user_id = str(user_id)
    
    await query.answer()

    if cb_data.startswith("select_game_"):
        game = cb_data.split("_")[2]
        if game in [GAME_TANKS, GAME_BLITZ]:
            
            if context.user_data.get("awaiting_game_selection"):
                action = context.user_data.get("awaiting_account_action")
                
                if action == "get":
                    await process_game_selection(update, context, game)
                elif action == "exchange":
                    await process_exchange_game_selection(update, context, game)
                
                context.user_data["awaiting_game_selection"] = False
                context.user_data["awaiting_account_action"] = None
            else:
                await query.edit_message_text(
                    f"✅ Выбрана игра: <b>{GAME_NAMES[game]}</b>\n\nТеперь вы можете получать аккаунты для этой игры.",
                    parse_mode='HTML'
                )
        return

    if cb_data == "view_reviews":
        reviews = data.get("reviews", [])
        if not reviews:
            await query.message.reply_text("📝 Пока нет отзывов. Будьте первым!", reply_markup=reviews_keyboard())
            return
        
        text = "⭐ <b>Опубликованные отзывы:</b>\n\n"
        for i, review in enumerate(reviews[-10:], 1):
            date = datetime.fromisoformat(review["date"]).strftime("%d.%m.%Y")
            text += f"{i}. {review['text']}\n   👤 {review['user_name']} • {date}\n\n"

        if len(reviews) > 10:
            text += f"\n📊 Всего отзывов: {len(reviews)}"
        
        try:
            await query.edit_message_text(text, parse_mode='HTML', reply_markup=reviews_keyboard())
        except BadRequest:
            pass 
        return

    elif cb_data == "leave_review":
        await query.message.reply_text("⭐ <b>Оставить отзыв</b>\n\nНапишите ваш отзыв одним сообщением (максимум 500 символов):\n\n📝 Ваш отзыв будет отправлен на модерацию.", parse_mode='HTML')
        context.user_data["leaving_review"] = True
        return

    if cb_data == "delete_msg":
        try:
            await query.delete_message()
        except:
            pass
        return

    if cb_data == "check_sub_confirm":
        is_sub, not_sub_list = await check_subscription_logic(user_id, context)
        if is_sub:
            await query.edit_message_text("✅ <b>Отлично! Вы подписаны.</b>\nТеперь можете пользоваться ботом.", parse_mode='HTML')
        else:
            await query.edit_message_text(f"❌ <b>Вы все еще не подписаны!</b>", parse_mode='HTML', reply_markup=get_sub_keyboard(not_sub_list))
        return

    if cb_data == "exchange_coins":
        if update.callback_query.message:
            await update.callback_query.message.reply_text("💎 Обмен монет:", reply_markup=exchange_keyboard())
        return

    if not is_admin(user_id):
        return

    try:
        if cb_data == "admin_main":
            context.user_data.clear()
            await query.edit_message_text("👑 <b>Админ панель</b>", parse_mode='HTML', reply_markup=admin_kb_main(user_id))
        
        elif cb_data == "admin_menu_accs":
            # Для супер-админа доступ всегда, для обычных - проверка прав
            if user_id not in SUPER_ADMIN_IDS and not check_perm(user_id, PERM_ACCS):
                await query.answer("❌ У вас нет прав на управление аккаунтами", show_alert=True)
                return
                
            total_accounts = (len(data['accounts_common_tanks']) + len(data['accounts_promo_tanks']) +
                             len(data['accounts_common_blitz']))
            
            text = f"""📦 <b>Управление аккаунтами</b>

📊 <b>Статистика аккаунтов:</b>
• Всего аккаунтов в наличии: {total_accounts}
• TanksBlitz (Общая): {len(data['accounts_common_tanks'])} шт.
• TanksBlitz (Промо): {len(data['accounts_promo_tanks'])} шт.
• WoT Blitz (Общая): {len(data['accounts_common_blitz'])} шт.

Выберите действие:"""
            await query.edit_message_text(text, parse_mode='HTML', reply_markup=admin_kb_accounts())
            
        elif cb_data == "admin_select_game":
            await query.edit_message_text("🎮 <b>Выберите игру для управления:</b>", parse_mode='HTML', reply_markup=admin_kb_acc_game_selection())
            
        elif cb_data.startswith("admin_game_"):
            game = cb_data.split("_")[2]
            if game in [GAME_TANKS, GAME_BLITZ]:
                context.user_data["selected_admin_game"] = game
                game_name = GAME_NAMES[game]
                
                if game == GAME_TANKS:
                    common_count = len(data.get(f'accounts_common_{game}', []))
                    promo_count = len(data.get(f'accounts_promo_{game}', []))
                    text = f"""📦 <b>Управление аккаунтами для {game_name}</b>
                    
📊 Статистика:
• Общая база: {common_count} шт.
• Промо база: {promo_count} шт.
• Всего: {common_count + promo_count} шт."""
                else:
                    common_count = len(data.get(f'accounts_common_{game}', []))
                    text = f"""📦 <b>Управление аккаунтами для {game_name}</b>
                    
📊 Статистика:
• Общая база: {common_count} шт.
• Промо база: Нет (только общая база)"""
                
                await query.edit_message_text(text, parse_mode='HTML', reply_markup=admin_kb_acc_actions_for_game(game))
            
        elif cb_data == "admin_menu_promo":
            # Для супер-админа доступ всегда, для обычных - проверка прав
            if user_id not in SUPER_ADMIN_IDS and not check_perm(user_id, PERM_PROMOS):
                await query.answer("❌ У вас нет прав на управление промокодами", show_alert=True)
                return
            await query.edit_message_text("🎟 <b>Управление промокодами (только для TanksBlitz)</b>", parse_mode='HTML', reply_markup=admin_kb_promo())

        elif cb_data == "admin_menu_users":
            # Для супер-админа доступ всегда, для обычных - проверка прав
            if user_id not in SUPER_ADMIN_IDS and not check_perm(user_id, PERM_BAN):
                await query.answer("❌ У вас нет прав на управление пользователями", show_alert=True)
                return
            await query.edit_message_text(
                f"👥 <b>Управление пользователями</b>\nВсего юзеров: {len(data['users'])}\nВ бане: {len(data.get('banned_users', []))}", 
                parse_mode='HTML', 
                reply_markup=admin_kb_users()
            )

        elif cb_data == "admin_menu_reviews":
            # Для супер-админа доступ всегда, для обычных - проверка прав
            if user_id not in SUPER_ADMIN_IDS and not check_perm(user_id, PERM_REVIEWS):
                await query.answer("❌ У вас нет прав на модерацию отзывов", show_alert=True)
                return
            pending_count = len(data["pending_reviews"])
            approved_count = len(data["reviews"])
            await query.edit_message_text(
                f"⭐ <b>Управление отзывами</b>\n\n⏳ Ожидают модерации: {pending_count}\n✅ Опубликовано: {approved_count}", 
                parse_mode='HTML', 
                reply_markup=admin_kb_reviews()
            )
            
        elif cb_data == "admin_menu_settings":
            # Для супер-админа доступ всегда, для обычных - проверка прав
            if user_id not in SUPER_ADMIN_IDS and not check_perm(user_id, PERM_SETTINGS):
                await query.answer("❌ У вас нет прав на настройки", show_alert=True)
                return
            stats = f"""⚙️ <b>Настройки бота</b>
            
💰 Цена аккаунта: {data['settings']['exchange_price']} монет
🤝 Награда за реферала: {data['settings']['coin_reward']} монет
📝 Текст FAQ: {len(data['settings']['faq_text'])} символов"""
            await query.edit_message_text(stats, parse_mode='HTML', reply_markup=admin_kb_settings())

        elif cb_data == "admin_close":
            await query.delete_message()
            
        elif cb_data == "admin_acc_load":
            # Проверка прав
            if user_id not in SUPER_ADMIN_IDS and not check_perm(user_id, PERM_ACCS):
                await query.answer("❌ У вас нет прав на загрузку аккаунтов", show_alert=True)
                return
            await query.message.reply_text("🔄 Отправьте .txt файл с аккаунтами (почта:пароль).")
            context.user_data["awaiting_file"] = True

        elif cb_data.startswith("upload_to_common_") or cb_data.startswith("upload_to_promo_"):
            accounts = context.user_data.get("temp_accounts", [])
            if not accounts:
                await query.edit_message_text("❌ Ошибка: список аккаунтов пуст или утерян.")
                return
            
            parts = cb_data.split("_")
            target_type = parts[2]
            game = parts[3]
            
            if game == GAME_BLITZ and target_type == "promo":
                await query.edit_message_text("❌ Для WoT Blitz нет промо-базы. Можно загружать только в общую базу.")
                return
            
            target_key = f"accounts_{target_type}_{game}"
            
            data[target_key].extend(accounts)
            save()
            
            name_map = {"common": "ОБЩУЮ", "promo": "ПРОМО"}
            game_map = {"tanks": "TanksBlitz", "blitz": "WoT Blitz"}
            
            # УВЕДОМЛЕНИЕ СУПЕР-АДМИНОВ О ЗАГРУЗКЕ АККАУНТОВ
            await notify_super_admins(
                context,
                f"📦 <b>ЗАГРУЖЕНЫ АККАУНТЫ</b>\nКем: {get_user_link(query.from_user)}\nИгра: {game_map[game]}\nБаза: {name_map[target_type]}\nКоличество: {len(accounts)} аккаунтов"
            )
            
            await query.edit_message_text(f"✅ Успешно добавлено {len(accounts)} аккаунтов в {name_map[target_type]} базу {game_map[game]}!", 
                                          reply_markup=admin_kb_acc_actions_for_game(game))
            context.user_data["temp_accounts"] = []

        elif cb_data.startswith("admin_acc_del_common_") or cb_data.startswith("admin_acc_del_promo_"):
            parts = cb_data.split("_")
            target_type = parts[3]
            game = parts[4]
            
            if game == GAME_BLITZ and target_type == "promo":
                await query.answer("Для WoT Blitz нет промо-базы", show_alert=True)
                return
            
            target_key = f"accounts_{target_type}_{game}"
            count = len(data[target_key])
            data[target_key] = []
            save()
            
            # УВЕДОМЛЕНИЕ СУПЕР-АДМИНОВ О УДАЛЕНИИ АККАУНТОВ
            game_map = {"tanks": "TanksBlitz", "blitz": "WoT Blitz"}
            await notify_super_admins(
                context,
                f"🗑 <b>УДАЛЕНЫ АККАУНТЫ</b>\nКем: {get_user_link(query.from_user)}\nИгра: {game_map[game]}\nБаза: {target_type}\nКоличество: {count} аккаунтов"
            )
            
            await query.answer(f"Удалено {count} аккаунтов из {target_type} базы {game_map[game]}", show_alert=True)
            await query.edit_message_text("📦 Аккаунты обновлены", reply_markup=admin_kb_acc_actions_for_game(game))

        elif cb_data == "set_price":
            await query.message.reply_text(f"💰 Введите новую цену аккаунта (сейчас: {data['settings']['exchange_price']}):")
            context.user_data["setting_price"] = True
            
        elif cb_data == "set_reward":
            await query.message.reply_text(f"🤝 Введите новую награду за рефа (сейчас: {data['settings']['coin_reward']}):")
            context.user_data["setting_reward"] = True
            
        elif cb_data == "set_faq_text":
            await query.message.reply_text("📝 Отправьте новый текст для FAQ (HTML форматирование поддерживается):")
            context.user_data["setting_faq_text"] = True

        elif cb_data == "admin_promo_create":
            await query.message.reply_text(
                "🎟 <b>Создание промокода (только для TanksBlitz)</b>\nВведите: <code>КОД КОЛИЧЕСТВО ИСПОЛЬЗОВАНИЙ</code>\nПример: <code>SUMMER 5 100</code>", parse_mode='HTML'
            )
            context.user_data["creating_promo"] = True

        elif cb_data.startswith("promo_src_"):
            promo_data = context.user_data.get("temp_promo_data")
            if not promo_data:
                await query.edit_message_text("Ошибка создания промокода.")
                return
            
            source = cb_data.split("_")[2]
            code = promo_data["code"]
            
            data["promocodes"][code] = {
                "reward": promo_data["reward"],
                "max_uses": promo_data["max_uses"],
                "used": 0,
                "source": source,
                "game": GAME_TANKS
            }
            save()
            
            src_name = "ОБЩЕЙ" if source == "common" else "ПРОМО"
            
            # УВЕДОМЛЕНИЕ СУПЕР-АДМИНОВ О СОЗДАНИИ ПРОМОКОДА
            await notify_super_admins(
                context,
                f"🎟 <b>СОЗДАН ПРОМОКОД</b>\nКем: {get_user_link(query.from_user)}\nКод: {code}\nНаграда: {promo_data['reward']} аккаунтов\nЛимит: {promo_data['max_uses']} использований\nБаза: {src_name}"
            )
            
            await query.edit_message_text(f"✅ Промокод {code} создан!\nИгра: TanksBlitz\nИсточник аккаунтов: с {src_name} базы.", reply_markup=back_btn("admin_menu_promo"))
            context.user_data["temp_promo_data"] = {}

        elif cb_data == "admin_stats":
            total_accounts_issued = sum(user.get("received", 0) for user in data["users"].values())
            total_coins = sum(user.get("coins", 0) for user in data["users"].values())
            banned_count = len(data.get("banned_users", []))
            
            total_in_stock = (len(data['accounts_common_tanks']) + 
                              len(data['accounts_promo_tanks']) +
                              len(data['accounts_common_blitz']))
            
            stats = f"""📊 <b>Статистика бота</b>

👥 Пользователей: {len(data["users"])}
⛔️ Забанено: {banned_count}
📦 Аккаунтов в наличии: {total_in_stock}
🎮 Всего выдано аккаунтов: {total_accounts_issued}
💰 Всего монет у пользователей: {total_coins}
🎟 Промокодов: {len(data["promocodes"])}
⭐️ Отзывов: {len(data.get("reviews", []))} (⏳ {len(data["pending_reviews"])} на модерации)
📢 Каналов: {len(data.get("channels", []))}
🛡 Админов (доп): {len(data.get("admins", {}))}
⏸️ Бот {'остановлен' if BOT_STOPPED else 'работает'}"""
            await query.edit_message_text(stats, parse_mode='HTML', reply_markup=back_btn())

        elif cb_data == "admin_channel_list":
            ch_list = "\n".join(data["channels"]) if data["channels"] else "Пусто"
            await query.edit_message_text(f"📢 Каналы:\n{ch_list}", reply_markup=admin_kb_channels())
            
        elif cb_data == "admin_channel_add":
            # Для супер-админа доступ всегда, для обычных - проверка прав
            if user_id not in SUPER_ADMIN_IDS and not check_perm(user_id, PERM_CHANNELS):
                await query.answer("❌ У вас нет прав на управление каналами", show_alert=True)
                return
            await query.message.reply_text("➕ Введите ссылку или @username канала (бот должен быть админом):")
            context.user_data["adding_channel"] = True

        elif cb_data == "admin_channel_del":
            # Для супер-админа доступ всегда, для обычных - проверка прав
            if user_id not in SUPER_ADMIN_IDS and not check_perm(user_id, PERM_CHANNELS):
                await query.answer("❌ У вас нет прав на управление каналами", show_alert=True)
                return
            await query.message.reply_text("➖ Введите ссылку канала для удаления:")
            context.user_data["deleting_channel"] = True

        elif cb_data == "admin_menu_channels":
            # Для супер-админа доступ всегда, для обычных - проверка прав
            if user_id not in SUPER_ADMIN_IDS and not check_perm(user_id, PERM_CHANNELS):
                await query.answer("❌ У вас нет прав на управление каналами", show_alert=True)
                return
            await query.edit_message_text("📢 <b>Управление каналами</b>", parse_mode='HTML', reply_markup=admin_kb_channels())
            
        elif cb_data == "admin_menu_admins":
            # Для супер-админа доступ всегда, для обычных - проверка прав
            if user_id not in SUPER_ADMIN_IDS and not check_perm(user_id, PERM_ADD_ADMIN):
                await query.answer("❌ У вас нет прав на управление админами", show_alert=True)
                return
            await query.edit_message_text("🛡 <b>Управление админами</b>", parse_mode='HTML', reply_markup=admin_kb_admins_list())
            
        elif cb_data == "admin_add_new":
            await query.message.reply_text("👤 Введите ID нового админа:")
            context.user_data["adding_admin"] = True
            
        elif cb_data.startswith("adm_edit:"):
            target_id = cb_data.split(":")[1]
            await query.edit_message_text(f"⚙️ Права для {target_id}", reply_markup=admin_kb_admin_rights(target_id))

        elif cb_data.startswith("adm_toggle:"):
            _, target_id, perm = cb_data.split(":")
            if str(target_id) in data["admins"]:
                curr = data["admins"][str(target_id)]["permissions"].get(perm, False)
                data["admins"][str(target_id)]["permissions"][perm] = not curr
                save()
                await query.edit_message_reply_markup(reply_markup=admin_kb_admin_rights(target_id))

        elif cb_data.startswith("adm_delete:"):
            target_id = cb_data.split(":")[1]
            if str(target_id) in data["admins"]:
                del data["admins"][str(target_id)]
                save()
                
                # УВЕДОМЛЕНИЕ СУПЕР-АДМИНОВ ОБ УДАЛЕНИИ АДМИНА
                await notify_super_admins(
                    context,
                    f"🗑 <b>УДАЛЕН АДМИН</b>\nКем: {get_user_link(query.from_user)}\nID админа: {target_id}"
                )
                
                await query.edit_message_text("Админ удален", reply_markup=admin_kb_admins_list())

        elif cb_data == "admin_promo_list":
            promos = data.get("promocodes", {})
            if not promos:
                await query.edit_message_text("🎟 Нет активных промокодов.")
                return
            
            text = "🎟 <b>Активные промокоды:</b>\n\n"
            for code, details in promos.items():
                uses = f"{details.get('used', 0)}/{details.get('max_uses', 0)}"
                reward = details.get("reward", 1)
                source = details.get("source", "common")
                source_name = "ОБЩАЯ" if source == "common" else "ПРОМО"
                game = details.get("game", GAME_TANKS)
                game_name = GAME_NAMES.get(game, "Unknown")
                
                text += f"• <code>{code}</code> - {reward} акк. ({game_name})\n  Использовано: {uses} | Источник: {source_name}\n\n"
            
            await query.edit_message_text(text, parse_mode='HTML', reply_markup=back_btn("admin_menu_promo"))

        elif cb_data == "admin_user_ban":
            await query.message.reply_text("⛔ Введите ID пользователя для бана:")
            context.user_data["banning_user"] = True

        elif cb_data == "admin_user_unban":
            await query.message.reply_text("✅ Введите ID пользователя для разбана:")
            context.user_data["unbanning_user"] = True

        elif cb_data == "admin_review_moderate":
            await query.edit_message_text("⭐ <b>Модерация отзывов</b>", parse_mode='HTML', reply_markup=admin_kb_review_moderation())

        elif cb_data == "mod_view_pending":
            pending = data.get("pending_reviews", [])
            if not pending:
                await query.edit_message_text("⏳ Нет отзывов на модерации.", reply_markup=admin_kb_review_moderation())
                return
            
            for review in pending[:5]:
                date = datetime.fromisoformat(review["date"]).strftime("%d.%m.%Y %H:%M")
                text = f"⏳ <b>Отзыв на модерации</b>\n\nID: {review['id']}\nДата: {date}\n👤 Пользователь: {review['user_name']} (ID: {review['user_id']})\n\n📝 Текст:\n{review['text']}"
                
                await query.message.reply_text(text, parse_mode='HTML', reply_markup=moderation_review_kb(review['id']))
            
            await query.edit_message_text(f"⏳ Показано {min(5, len(pending))} из {len(pending)} отзывов", reply_markup=admin_kb_review_moderation())

        elif cb_data == "mod_view_approved":
            reviews = data.get("reviews", [])
            if not reviews:
                await query.edit_message_text("✅ Нет опубликованных отзывов.", reply_markup=admin_kb_review_moderation())
                return
            
            text = "✅ <b>Опубликованные отзывы:</b>\n\n"
            for i, review in enumerate(reviews[-10:], 1):
                date = datetime.fromisoformat(review["date"]).strftime("%d.%m.%Y")
                text += f"{i}. {review['text']}\n   👤 {review['user_name']} • {date}\n\n"
            
            if len(reviews) > 10:
                text += f"\n📊 Всего отзывов: {len(reviews)}"
            
            await query.edit_message_text(text, parse_mode='HTML', reply_markup=admin_kb_review_moderation())

        elif cb_data.startswith("mod_approve:"):
            review_id = cb_data.split(":")[1]
            pending = data.get("pending_reviews", [])
            
            for i, review in enumerate(pending):
                if str(review['id']) == review_id:
                    approved_review = pending.pop(i)
                    data["reviews"].append(approved_review)
                    save()
                    
                    # Уведомление пользователю
                    try:
                        await context.bot.send_message(
                            chat_id=int(approved_review['user_id']),
                            text="✅ <b>Ваш отзыв был одобрен и опубликован!</b>\n\nСпасибо за обратную связь!",
                            parse_mode='HTML'
                        )
                    except:
                        pass
                    
                    # УВЕДОМЛЕНИЕ СУПЕР-АДМИНОВ
                    await notify_super_admins(
                        context,
                        f"⭐ <b>ОДОБРЕН ОТЗЫВ</b>\nКем: {get_user_link(query.from_user)}\nОт: {approved_review['user_name']} (ID: {approved_review['user_id']})\nID отзыва: {review_id}"
                    )
                    
                    await query.edit_message_text("✅ Отзыв одобрен и опубликован!", reply_markup=admin_kb_review_moderation())
                    return
            
            await query.answer("Отзыв не найден", show_alert=True)

        elif cb_data.startswith("mod_reject:"):
            review_id = cb_data.split(":")[1]
            pending = data.get("pending_reviews", [])
            
            for i, review in enumerate(pending):
                if str(review['id']) == review_id:
                    rejected_review = pending.pop(i)
                    save()
                    
                    # Уведомление пользователю
                    try:
                        await context.bot.send_message(
                            chat_id=int(rejected_review['user_id']),
                            text="❌ <b>Ваш отзыв был отклонен модератором.</b>\n\nПожалуйста, убедитесь, что отзыв соответствует правилам сообщества.",
                            parse_mode='HTML'
                        )
                    except:
                        pass
                    
                    # УВЕДОМЛЕНИЕ СУПЕР-АДМИНОВ
                    await notify_super_admins(
                        context,
                        f"⭐ <b>ОТКЛОНЕН ОТЗЫВ</b>\nКем: {get_user_link(query.from_user)}\nОт: {rejected_review['user_name']} (ID: {rejected_review['user_id']})\nID отзыва: {review_id}"
                    )
                    
                    await query.edit_message_text("❌ Отзыв отклонен.", reply_markup=admin_kb_review_moderation())
                    return
            
            await query.answer("Отзыв не найден", show_alert=True)

        elif cb_data == "admin_review_all":
            reviews = data.get("reviews", [])
            if not reviews:
                await query.edit_message_text("📝 Нет отзывов.", reply_markup=admin_kb_reviews())
                return
            
            text = "⭐ <b>Все отзывы:</b>\n\n"
            for i, review in enumerate(reviews, 1):
                date = datetime.fromisoformat(review["date"]).strftime("%d.%m.%Y %H:%M")
                text += f"{i}. <b>ID:</b> {review['id']} | <b>Дата:</b> {date}\n<b>👤 Пользователь:</b> {review['user_name']}\n<b>📝 Текст:</b> {review['text']}\n\n"
            
            await query.edit_message_text(text[:4000], parse_mode='HTML', reply_markup=back_btn("admin_menu_reviews"))

        elif cb_data == "admin_review_clear_all":
            count = len(data.get("reviews", []))
            data["reviews"] = []
            save()
            
            # УВЕДОМЛЕНИЕ СУПЕР-АДМИНОВ О ЧИСТКЕ ОТЗЫВОВ
            await notify_super_admins(
                context,
                f"🗑 <b>УДАЛЕНЫ ВСЕ ОТЗЫВЫ</b>\nКем: {get_user_link(query.from_user)}\nКоличество: {count} отзывов"
            )
            
            await query.answer(f"Удалено {count} отзывов", show_alert=True)
            await query.edit_message_text(f"🗑 Удалено {count} отзывов.", reply_markup=admin_kb_reviews())

        elif cb_data == "admin_review_del_one":
            await query.message.reply_text("❌ Введите ID отзыва для удаления:")
            context.user_data["deleting_review"] = True

        elif cb_data == "admin_broadcast_start":
            # Для супер-админа доступ всегда, для обычных - проверка прав
            if user_id not in SUPER_ADMIN_IDS and not check_perm(user_id, PERM_BROADCAST):
                await query.answer("❌ У вас нет прав на рассылку", show_alert=True)
                return
            await query.message.reply_text(
                "📣 <b>Начало рассылки</b>\n\n"
                "Отправьте сообщение для рассылки (текст, фото, видео, документ).\n"
                "Используйте HTML разметку.\n"
                "Кнопки добавляются отдельно после сообщения.",
                parse_mode='HTML'
            )
            context.user_data["broadcasting"] = True
            context.user_data["broadcast_buttons"] = []

        elif cb_data == "bc_add_btn_yes":
            await query.message.reply_text(
                "➕ <b>Добавление кнопки</b>\n\n"
                "Отправьте кнопку в формате:\n"
                "<code>Текст - https://ссылка.com</code>\n\n"
                "Можно добавить несколько кнопок в один ряд:\n"
                "<code>Текст1 - ссылка1 | Текст2 - ссылка2</code>\n\n"
                "Когда закончите, нажмите 'Нет, далее'.",
                parse_mode='HTML'
            )
            context.user_data["adding_button"] = True

        elif cb_data == "bc_add_btn_no":
            if not context.user_data.get("broadcast_message"):
                await query.edit_message_text("❌ Сначала отправьте сообщение для рассылки.")
                return

            msg = context.user_data["broadcast_message"]
            buttons = context.user_data.get("broadcast_buttons", [])

            preview_text = f"📋 <b>ПРЕДПРОСМОТР РАССЫЛКИ</b>\n\n{msg}\n\nКнопок: {len(buttons)}"
            await query.edit_message_text(preview_text, parse_mode='HTML', reply_markup=broadcast_confirm_kb())

        elif cb_data == "bc_edit_msg":
            await query.message.reply_text("✏️ Отправьте исправленное сообщение:")
            context.user_data["editing_broadcast"] = True

        elif cb_data == "bc_confirm_send":
            msg = context.user_data["broadcast_message"]
            buttons = context.user_data.get("broadcast_buttons", [])
            
            if not msg:
                await query.edit_message_text("❌ Нет сообщения для рассылки.")
                return

            keyboard = None
            if buttons:
                keyboard = []
                for row in buttons:
                    kb_row = []
                    for btn in row:
                        parts = btn.split(" - ")
                        if len(parts) == 2:
                            text, url = parts
                            kb_row.append(InlineKeyboardButton(text.strip(), url=url.strip()))
                    if kb_row:
                        keyboard.append(kb_row)
                
                if keyboard:
                    keyboard = InlineKeyboardMarkup(keyboard)

            total_users = len(data["users"])
            sent = 0
            errors = 0
            banned = 0
            
            await query.edit_message_text(f"🚀 <b>Начинаю рассылку...</b>\n\nПолучателей: {total_users}", parse_mode='HTML')
            
            for user_id_str in list(data["users"].keys()):
                try:
                    user_id = int(user_id_str)
                    
                    if user_id_str in data.get("banned_users", []):
                        banned += 1
                        continue
                    
                    if context.user_data.get("broadcast_media_type") == "photo":
                        await context.bot.send_photo(
                            chat_id=user_id,
                            photo=context.user_data["broadcast_media"],
                            caption=msg,
                            parse_mode='HTML',
                            reply_markup=keyboard
                        )
                    elif context.user_data.get("broadcast_media_type") == "video":
                        await context.bot.send_video(
                            chat_id=user_id,
                            video=context.user_data["broadcast_media"],
                            caption=msg,
                            parse_mode='HTML',
                            reply_markup=keyboard
                        )
                    elif context.user_data.get("broadcast_media_type") == "document":
                        await context.bot.send_document(
                            chat_id=user_id,
                            document=context.user_data["broadcast_media"],
                            caption=msg,
                            parse_mode='HTML',
                            reply_markup=keyboard
                        )
                    else:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text=msg,
                            parse_mode='HTML',
                            reply_markup=keyboard
                        )
                    
                    sent += 1
                    if sent % 50 == 0:
                        await query.edit_message_text(f"📤 Отправлено: {sent}/{total_users}")
                    
                    await asyncio.sleep(0.05)
                    
                except Forbidden:
                    errors += 1
                except Exception as e:
                    errors += 1

            # УВЕДОМЛЕНИЕ СУПЕР-АДМИНОВ О РАССЫЛКЕ
            await notify_super_admins(
                context,
                f"📣 <b>РАССЫЛКА ЗАВЕРШЕНА</b>\nКем: {get_user_link(query.from_user)}\nОтправлено: {sent} пользователям\nНе удалось: {errors}\nЗабанено: {banned}"
            )

            result_text = f"""✅ <b>Рассылка завершена!</b>

📊 Результаты:
👥 Всего получателей: {total_users}
✅ Успешно отправлено: {sent}
❌ Не удалось отправить: {errors}
⛔ Пропущено (бан): {banned}"""

            await query.edit_message_text(result_text, parse_mode='HTML', reply_markup=back_btn())
            
            context.user_data.clear()

        elif cb_data == "admin_pm":
            await query.message.reply_text("✉️ <b>Отправка личного сообщения</b>\n\nВведите: <code>ID_ПОЛЬЗОВАТЕЛЯ СООБЩЕНИЕ</code>\nПример: <code>123456789 Привет! Как дела?</code>", parse_mode='HTML')
            context.user_data["sending_pm"] = True

        elif cb_data == "admin_toggle_bot":
            BOT_STOPPED = not BOT_STOPPED
            
            status = "остановлен" if BOT_STOPPED else "запущен"
            
            # УВЕДОМЛЕНИЕ СУПЕР-АДМИНОВ О СМЕНЕ СТАТУСА
            await notify_super_admins(
                context,
                f"⏸ <b>БОТ {'ОСТАНОВЛЕН' if BOT_STOPPED else 'ЗАПУЩЕН'}</b>\nКем: {get_user_link(query.from_user)}"
            )
            
            await query.answer(f"Бот {status}", show_alert=True)
            await query.edit_message_text(f"👑 <b>Админ панель</b>\nБот: {'⏸ ОСТАНОВЛЕН' if BOT_STOPPED else '▶️ ЗАПУЩЕН'}", parse_mode='HTML', reply_markup=admin_kb_main(user_id))

    except Exception as e:
        print(f"Callback error: {e}")
        try:
            await query.edit_message_text(f"❌ Ошибка: {e}")
        except:
            pass

# ========== ОБРАБОТЧИК СООБЩЕНИЙ ==========
async def message_handler(update: Update, context: CallbackContext):
    global BOT_STOPPED
    
    if BOT_STOPPED and not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Бот временно остановлен.")
        return

    user_id = update.effective_user.id
    str_user_id = str(user_id)
    message = update.message
    text = message.text or message.caption or ""
    
    # Проверка на бан
    if str_user_id in data.get("banned_users", []):
        return
    
    # Обработка капчи
    if context.user_data.get("awaiting_captcha"):
        correct = context.user_data.get("captcha_correct", "")
        if text.upper() == correct:
            context.user_data["awaiting_captcha"] = False
            context.user_data["just_passed_captcha"] = True
            data["users"][str_user_id]["captcha_passed"] = True
            save()
            
            await message.reply_text("✅ <b>Проверка пройдена!</b>\n\nДобро пожаловать в бот!", parse_mode='HTML')
            await send_main_menu(update, context)
        else:
            await message.reply_text("❌ Неверный код. Попробуйте ещё раз:")
        return

    # Оставление отзыва
    if context.user_data.get("leaving_review"):
        if len(text) > 500:
            await message.reply_text("❌ Отзыв слишком длинный (макс. 500 символов). Попробуйте снова:")
            return
        
        if len(text) < 5:
            await message.reply_text("❌ Отзыв слишком короткий (мин. 5 символов). Попробуйте снова:")
            return
        
        review_id = random.randint(100000, 999999)
        pending_review = {
            "id": review_id,
            "user_id": str_user_id,
            "user_name": update.effective_user.full_name,
            "text": text,
            "date": datetime.now().isoformat()
        }
        
        data["pending_reviews"].append(pending_review)
        save()
        
        # УВЕДОМЛЕНИЕ СУПЕР-АДМИНОВ О НОВОМ ОТЗЫВЕ
        await notify_super_admins(
            context,
            f"⭐ <b>НОВЫЙ ОТЗЫВ НА МОДЕРАЦИЮ</b>\nОт: {get_user_link(update.effective_user)}\nID отзыва: {review_id}\nТекст: {text[:200]}..."
        )
        
        await message.reply_text("✅ <b>Спасибо за отзыв!</b>\n\nВаш отзыв отправлен на модерацию и скоро будет опубликован.", parse_mode='HTML')
        context.user_data["leaving_review"] = False
        return

    # АДМИН: Загрузка файла с аккаунтами
    if context.user_data.get("awaiting_file") and message.document:
        # Проверка прав для загрузки файлов
        if user_id not in SUPER_ADMIN_IDS and not check_perm(user_id, PERM_ACCS):
            await message.reply_text("❌ У вас нет прав на загрузку аккаунтов.")
            context.user_data["awaiting_file"] = False
            return
            
        file = await message.document.get_file()
        content = await file.download_as_bytearray()
        
        try:
            text_content = content.decode('utf-8').strip()
        except:
            text_content = content.decode('latin-1').strip()
        
        accounts = []
        for line in text_content.split('\n'):
            line = line.strip()
            if line and ':' in line:
                accounts.append(line)
        
        if not accounts:
            await message.reply_text("❌ Не найдено валидных аккаунтов в формате почта:пароль.")
            context.user_data["awaiting_file"] = False
            return
        
        context.user_data["temp_accounts"] = accounts
        
        await message.reply_text(
            f"✅ Загружено {len(accounts)} аккаунтов.\n\nВыберите игру для загрузки:",
            reply_markup=admin_kb_acc_game_selection()
        )
        context.user_data["awaiting_file"] = False
        return

    # АДМИН: Установка цены
    if context.user_data.get("setting_price"):
        # Проверка прав для настроек
        if user_id not in SUPER_ADMIN_IDS and not check_perm(user_id, PERM_SETTINGS):
            await message.reply_text("❌ У вас нет прав на изменение настроек.")
            context.user_data["setting_price"] = False
            return
            
        try:
            price = int(text)
            if price < 1:
                await message.reply_text("❌ Цена должна быть положительным числом.")
                return
            
            data["settings"]["exchange_price"] = price
            save()
            
            # УВЕДОМЛЕНИЕ СУПЕР-АДМИНОВ О СМЕНЕ ЦЕНЫ
            await notify_super_admins(
                context,
                f"💰 <b>ИЗМЕНЕНА ЦЕНА АККАУНТА</b>\nКем: {get_user_link(update.effective_user)}\nНовая цена: {price} монет"
            )
            
            await message.reply_text(f"✅ Цена аккаунта изменена на {price} монет.", reply_markup=back_btn("admin_menu_settings"))
        except ValueError:
            await message.reply_text("❌ Введите число.")
        context.user_data["setting_price"] = False
        return

    # АДМИН: Установка награды
    if context.user_data.get("setting_reward"):
        # Проверка прав для настроек
        if user_id not in SUPER_ADMIN_IDS and not check_perm(user_id, PERM_SETTINGS):
            await message.reply_text("❌ У вас нет прав на изменение настроек.")
            context.user_data["setting_reward"] = False
            return
            
        try:
            reward = int(text)
            if reward < 1:
                await message.reply_text("❌ Награда должна быть положительным числом.")
                return
            
            data["settings"]["coin_reward"] = reward
            save()
            
            # УВЕДОМЛЕНИЕ СУПЕР-АДМИНОВ О СМЕНЕ НАГРАДЫ
            await notify_super_admins(
                context,
                f"🤝 <b>ИЗМЕНЕНА НАГРАДА ЗА РЕФЕРАЛА</b>\nКем: {get_user_link(update.effective_user)}\nНовая награда: {reward} монет"
            )
            
            await message.reply_text(f"✅ Награда за реферала изменена на {reward} монет.", reply_markup=back_btn("admin_menu_settings"))
        except ValueError:
            await message.reply_text("❌ Введите число.")
        context.user_data["setting_reward"] = False
        return

    # АДМИН: Установка FAQ текста
    if context.user_data.get("setting_faq_text"):
        # Проверка прав для настроек
        if user_id not in SUPER_ADMIN_IDS and not check_perm(user_id, PERM_SETTINGS):
            await message.reply_text("❌ У вас нет прав на изменение настроек.")
            context.user_data["setting_faq_text"] = False
            return
            
        data["settings"]["faq_text"] = text
        save()
        
        # УВЕДОМЛЕНИЕ СУПЕР-АДМИНОВ О СМЕНЕ FAQ
        await notify_super_admins(
            context,
            f"📝 <b>ИЗМЕНЕН ТЕКСТ FAQ</b>\nКем: {get_user_link(update.effective_user)}\nДлина текста: {len(text)} символов"
        )
        
        await message.reply_text("✅ Текст FAQ обновлен.", reply_markup=back_btn("admin_menu_settings"))
        context.user_data["setting_faq_text"] = False
        return

    # АДМИН: Создание промокода
    if context.user_data.get("creating_promo"):
        # Проверка прав для промокодов
        if user_id not in SUPER_ADMIN_IDS and not check_perm(user_id, PERM_PROMOS):
            await message.reply_text("❌ У вас нет прав на создание промокодов.")
            context.user_data["creating_promo"] = False
            return
            
        parts = text.split()
        if len(parts) < 3:
            await message.reply_text("❌ Неверный формат. Пример: <code>SUMMER 5 100</code>", parse_mode='HTML')
            return
        
        code = parts[0].upper()
        
        try:
            reward = int(parts[1])
            max_uses = int(parts[2])
        except ValueError:
            await message.reply_text("❌ Количество и лимит должны быть числами.")
            return
        
        if code in data["promocodes"]:
            await message.reply_text("❌ Промокод уже существует.")
            return
        
        context.user_data["temp_promo_data"] = {
            "code": code,
            "reward": reward,
            "max_uses": max_uses
        }
        
        await message.reply_text(
            f"🎟 <b>Выбор базы аккаунтов</b>\n\nПромокод: <code>{code}</code>\nНаграда: {reward} аккаунтов\nЛимит: {max_uses} использований\n\nВыберите источник аккаунтов для промокода:",
            parse_mode='HTML',
            reply_markup=admin_kb_promo_source_choice()
        )
        context.user_data["creating_promo"] = False
        return

    # АДМИН: Добавление канала
    if context.user_data.get("adding_channel"):
        # Проверка прав для каналов
        if user_id not in SUPER_ADMIN_IDS and not check_perm(user_id, PERM_CHANNELS):
            await message.reply_text("❌ У вас нет прав на управление каналами.")
            context.user_data["adding_channel"] = False
            return
            
        channel = text.strip()
        if channel not in data["channels"]:
            data["channels"].append(channel)
            save()
            
            # УВЕДОМЛЕНИЕ СУПЕР-АДМИНОВ О ДОБАВЛЕНИИ КАНАЛА
            await notify_super_admins(
                context,
                f"📢 <b>ДОБАВЛЕН КАНАЛ</b>\nКем: {get_user_link(update.effective_user)}\nКанал: {channel}"
            )
            
            await message.reply_text(f"✅ Канал добавлен: {channel}", reply_markup=admin_kb_channels())
        else:
            await message.reply_text("❌ Канал уже есть в списке.")
        context.user_data["adding_channel"] = False
        return

    # АДМИН: Удаление канала
    if context.user_data.get("deleting_channel"):
        # Проверка прав для каналов
        if user_id not in SUPER_ADMIN_IDS and not check_perm(user_id, PERM_CHANNELS):
            await message.reply_text("❌ У вас нет прав на управление каналами.")
            context.user_data["deleting_channel"] = False
            return
            
        channel = text.strip()
        if channel in data["channels"]:
            data["channels"].remove(channel)
            save()
            
            # УВЕДОМЛЕНИЕ СУПЕР-АДМИНОВ О УДАЛЕНИИ КАНАЛА
            await notify_super_admins(
                context,
                f"📢 <b>УДАЛЕН КАНАЛ</b>\nКем: {get_user_link(update.effective_user)}\nКанал: {channel}"
            )
            
            await message.reply_text(f"✅ Канал удален: {channel}", reply_markup=admin_kb_channels())
        else:
            await message.reply_text("❌ Канал не найден в списке.")
        context.user_data["deleting_channel"] = False
        return

    # АДМИН: Добавление админа
    if context.user_data.get("adding_admin"):
        # Проверка прав для админов
        if user_id not in SUPER_ADMIN_IDS and not check_perm(user_id, PERM_ADD_ADMIN):
            await message.reply_text("❌ У вас нет прав на добавление админов.")
            context.user_data["adding_admin"] = False
            return
            
        try:
            new_admin_id = text.strip()
            
            if not new_admin_id.isdigit():
                await message.reply_text("❌ ID должен состоять из цифр.")
                return
            
            if new_admin_id in data["admins"]:
                await message.reply_text("❌ Этот пользователь уже админ.")
                return
            
            # Пытаемся получить информацию о пользователе
            try:
                user_info = await context.bot.get_chat(int(new_admin_id))
                user_name = user_info.full_name
            except:
                user_name = "Неизвестно"
            
            data["admins"][new_admin_id] = {
                "permissions": DEFAULT_PERMISSIONS.copy(),
                "notifications": {},
                "added_by": user_id,
                "added_date": datetime.now().isoformat(),
                "name": user_name
            }
            save()
            
            # УВЕДОМЛЕНИЕ СУПЕР-АДМИНОВ О ДОБАВЛЕНИИ АДМИНА
            await notify_super_admins(
                context,
                f"🛡 <b>ДОБАВЛЕН НОВЫЙ АДМИН</b>\nКем: {get_user_link(update.effective_user)}\nID админа: {new_admin_id}\nИмя: {user_name}"
            )
            
            # Уведомляем нового админа
            try:
                await context.bot.send_message(
                    chat_id=int(new_admin_id),
                    text=f"🎉 <b>Поздравляем!</b>\n\nВы были назначены администратором бота @{context.bot.username}!\n\nИспользуйте команду /panel для доступа к админ-панели.",
                    parse_mode='HTML'
                )
            except:
                pass
            
            await message.reply_text(f"✅ Пользователь {new_admin_id} ({user_name}) добавлен как админ.", reply_markup=admin_kb_admins_list())
        except Exception as e:
            await message.reply_text(f"❌ Ошибка: {e}")
        context.user_data["adding_admin"] = False
        return

    # АДМИН: Бан пользователя
    if context.user_data.get("banning_user"):
        # Проверка прав для бана
        if user_id not in SUPER_ADMIN_IDS and not check_perm(user_id, PERM_BAN):
            await message.reply_text("❌ У вас нет прав на бан пользователей.")
            context.user_data["banning_user"] = False
            return
            
        target_id = text.strip()
        
        if target_id in data["banned_users"]:
            await message.reply_text("❌ Пользователь уже забанен.")
        elif target_id in data["users"]:
            data["banned_users"].append(target_id)
            save()
            
            # УВЕДОМЛЕНИЕ СУПЕР-АДМИНОВ О БАНЕ
            await notify_super_admins(
                context,
                f"⛔ <b>ЗАБАНЕН ПОЛЬЗОВАТЕЛЬ</b>\nКем: {get_user_link(update.effective_user)}\nID пользователя: {target_id}"
            )
            
            await message.reply_text(f"✅ Пользователь {target_id} забанен.")
        else:
            await message.reply_text("❌ Пользователь не найден.")
        context.user_data["banning_user"] = False
        return

    # АДМИН: Разбан пользователя
    if context.user_data.get("unbanning_user"):
        # Проверка прав для бана
        if user_id not in SUPER_ADMIN_IDS and not check_perm(user_id, PERM_BAN):
            await message.reply_text("❌ У вас нет прав на разбан пользователей.")
            context.user_data["unbanning_user"] = False
            return
            
        target_id = text.strip()
        
        if target_id in data["banned_users"]:
            data["banned_users"].remove(target_id)
            save()
            
            # УВЕДОМЛЕНИЕ СУПЕР-АДМИНОВ О РАЗБАНЕ
            await notify_super_admins(
                context,
                f"✅ <b>РАЗБАНЕН ПОЛЬЗОВАТЕЛЬ</b>\nКем: {get_user_link(update.effective_user)}\nID пользователя: {target_id}"
            )
            
            await message.reply_text(f"✅ Пользователь {target_id} разбанен.")
        else:
            await message.reply_text("❌ Пользователь не забанен.")
        context.user_data["unbanning_user"] = False
        return

    # АДМИН: Удаление отзыва по ID
    if context.user_data.get("deleting_review"):
        # Проверка прав для отзывов
        if user_id not in SUPER_ADMIN_IDS and not check_perm(user_id, PERM_REVIEWS):
            await message.reply_text("❌ У вас нет прав на удаление отзывов.")
            context.user_data["deleting_review"] = False
            return
            
        try:
            review_id = int(text)
            
            # Ищем в опубликованных
            for i, review in enumerate(data["reviews"]):
                if review["id"] == review_id:
                    removed_review = data["reviews"].pop(i)
                    save()
                    
                    # УВЕДОМЛЕНИЕ СУПЕР-АДМИНОВ О УДАЛЕНИИ ОТЗЫВА
                    await notify_super_admins(
                        context,
                        f"🗑 <b>УДАЛЕН ОТЗЫВ</b>\nКем: {get_user_link(update.effective_user)}\nID отзыва: {review_id}\nОт: {removed_review['user_name']} (ID: {removed_review['user_id']})"
                    )
                    
                    await message.reply_text("✅ Отзыв удален.", reply_markup=admin_kb_reviews())
                    context.user_data["deleting_review"] = False
                    return
            
            # Ищем в ожидающих модерации
            for i, review in enumerate(data["pending_reviews"]):
                if review["id"] == review_id:
                    data["pending_reviews"].pop(i)
                    save()
                    
                    # УВЕДОМЛЕНИЕ СУПЕР-АДМИНОВ О УДАЛЕНИИ ОТЗЫВА
                    await notify_super_admins(
                        context,
                        f"🗑 <b>УДАЛЕН ОТЗЫВ (ожидающий)</b>\nКем: {get_user_link(update.effective_user)}\nID отзыва: {review_id}"
                    )
                    
                    await message.reply_text("✅ Отзыв удален из ожидающих.", reply_markup=admin_kb_reviews())
                    context.user_data["deleting_review"] = False
                    return
            
            await message.reply_text("❌ Отзыв с таким ID не найден.")
        except ValueError:
            await message.reply_text("❌ Введите число (ID отзыва).")
        context.user_data["deleting_review"] = False
        return

    # АДМИН: Рассылка - получение сообщения
    if context.user_data.get("broadcasting"):
        # Проверка прав для рассылки
        if user_id not in SUPER_ADMIN_IDS and not check_perm(user_id, PERM_BROADCAST):
            await message.reply_text("❌ У вас нет прав на рассылку.")
            context.user_data["broadcasting"] = False
            return
            
        context.user_data["broadcast_message"] = text if text else ""
        
        # Проверяем медиа
        if message.photo:
            context.user_data["broadcast_media"] = message.photo[-1].file_id
            context.user_data["broadcast_media_type"] = "photo"
            caption = message.caption or ""
            context.user_data["broadcast_message"] = caption
        elif message.video:
            context.user_data["broadcast_media"] = message.video.file_id
            context.user_data["broadcast_media_type"] = "video"
            caption = message.caption or ""
            context.user_data["broadcast_message"] = caption
        elif message.document:
            context.user_data["broadcast_media"] = message.document.file_id
            context.user_data["broadcast_media_type"] = "document"
            caption = message.caption or ""
            context.user_data["broadcast_message"] = caption
        
        await message.reply_text("✅ Сообщение получено. Добавить кнопки?", reply_markup=broadcast_add_btn_kb())
        context.user_data["broadcasting"] = False
        return

    # АДМИН: Редактирование сообщения рассылки
    if context.user_data.get("editing_broadcast"):
        context.user_data["broadcast_message"] = text
        await message.reply_text("✅ Сообщение обновлено.", reply_markup=broadcast_confirm_kb())
        context.user_data["editing_broadcast"] = False
        return

    # АДМИН: Добавление кнопки к рассылке
    if context.user_data.get("adding_button"):
        if " - " not in text:
            await message.reply_text("❌ Неверный формат. Пример: <code>Текст - https://ссылка.com</code>", parse_mode='HTML')
            return
        
        if "broadcast_buttons" not in context.user_data:
            context.user_data["broadcast_buttons"] = []
        
        # Обработка нескольких кнопок в строке
        if " | " in text:
            buttons = text.split(" | ")
            row = []
            for btn in buttons:
                if " - " in btn:
                    row.append(btn.strip())
            
            if row:
                context.user_data["broadcast_buttons"].append(row)
        else:
            # Одна кнопка - добавляем в новый ряд
            context.user_data["broadcast_buttons"].append([text.strip()])
        
        await message.reply_text(f"✅ Кнопка добавлена. Всего кнопок: {len(context.user_data['broadcast_buttons'])}. Добавить ещё кнопку или перейти к отправке?", 
                               reply_markup=broadcast_add_btn_kb())
        return

    # АДМИН: Личное сообщение пользователю
    if context.user_data.get("sending_pm"):
        parts = text.split(maxsplit=1)
        if len(parts) >= 2:
            target_id, message_text = parts[0], parts[1]
            try:
                await context.bot.send_message(
                    chat_id=int(target_id),
                    text=message_text
                )
                
                # УВЕДОМЛЕНИЕ СУПЕР-АДМИНОВ О ЛИЧНОМ СООБЩЕНИИ
                await notify_super_admins(
                    context,
                    f"✉️ <b>ОТПРАВЛЕНО ЛИЧНОЕ СООБЩЕНИЕ</b>\nКем: {get_user_link(update.effective_user)}\nКому: ID {target_id}\nТекст: {message_text[:100]}..."
                )
                
                await message.reply_text(f"✅ Сообщение отправлено пользователю {target_id}.")
            except Exception as e:
                await message.reply_text(f"❌ Ошибка отправки: {e}")
        else:
            await message.reply_text("❌ Формат: ID СООБЩЕНИЕ")
        context.user_data["sending_pm"] = False
        return

    # Пользовательский ввод промокода
    if text.upper() in data["promocodes"]:
        promo_code = text.upper()
        promo_data = data["promocodes"][promo_code]
        
        user_data = data["users"][user_id]
        used_promos = user_data.get("used_promocodes", [])
        
        if promo_code in used_promos:
            await update.message.reply_text("❌ Вы уже использовали этот промокод.")
            return
        
        if promo_data["used"] >= promo_data["max_uses"]:
            await update.message.reply_text("❌ Лимит использований промокода исчерпан.")
            return
        
        source = promo_data.get("source", "common")
        game = promo_data.get("game", GAME_TANKS)
        game_name = GAME_NAMES[game]
        
        if game == GAME_BLITZ and source == "promo":
            await update.message.reply_text("❌ Для WoT Blitz промокоды недоступны.")
            return
            
        source_key = f"accounts_{source}_{game}"
        if source_key not in data or not data[source_key]:
            await update.message.reply_text(f"❌ В базе {game_name} закончились аккаунты! Попробуйте позже.")
            return
        
        accounts_to_give = []
        for _ in range(promo_data["reward"]):
            if data[source_key]:
                accounts_to_give.append(data[source_key].pop(0))
            else:
                break
        
        if not accounts_to_give:
            await update.message.reply_text(f"❌ В базе {game_name} закончились аккаунты! Попробуйте позже.")
            return
        
        promo_data["used"] += 1
        user_data["used_promocodes"].append(promo_code)
        user_data["received"] += len(accounts_to_give)
        
        for account in accounts_to_give:
            user_data["history"] = user_data.get("history", []) + [{
                "date": datetime.now().isoformat(),
                "account": account,
                "type": "promocode",
                "game": game,
                "promocode": promo_code
            }]
        
        if promo_data["used"] >= promo_data["max_uses"]:
            del data["promocodes"][promo_code]
        
        save()
        
        accounts_text = "\n".join([f"🔐 <code>{acc}</code>" for acc in accounts_to_give])
        
        await update.message.reply_text(
            f"✅ <b>Промокод активирован!</b>\n\n🎮 Игра: {game_name}\n🎫 Промокод: {promo_code}\n📦 Получено аккаунтов: {len(accounts_to_give)}\n\n{accounts_text}\n\n💡 Продолжайте пользоваться ботом!",
            parse_mode='HTML',
            reply_markup=menu(update.effective_user.id)
        )
        
        # УВЕДОМЛЕНИЕ СУПЕР-АДМИНОВ О АКТИВАЦИИ ПРОМОКОДА
        await notify_super_admins(
            context,
            f"🎟 <b>АКТИВИРОВАН ПРОМОКОД</b>\nКем: {get_user_link(update.effective_user)}\nПромокод: {promo_code}\nИгра: {game_name}\nПолучено аккаунтов: {len(accounts_to_give)}"
        )
        return

    # Обработка текстовых команд из меню
    if text == "🎮 Получить аккаунт":
        await get_account(update, context)
    elif text == "📜 История":
        await account_history(update, context)
    elif text == "💎 Обменять монеты":
        await exchange_coins(update, context)
    elif text == "🎟 Промокод":
        await update.message.reply_text("🎫 <b>Введите промокод:</b>", parse_mode='HTML')
    elif text == "ℹ️ О боте":
        await about_bot(update, context)
    elif text == "⭐ Отзывы":
        await update.message.reply_text("⭐ <b>Отзывы о боте</b>\n\nВыберите действие:", 
                                       parse_mode='HTML', 
                                       reply_markup=reviews_keyboard())
    elif text == "✅ Проверить подписку":
        await check_subscription(update, context)
    elif text == "👤 Мой профиль":
        await profile(update, context)
    elif text == "👑 Админ" and is_admin(update.effective_user.id):
        await panel_command(update, context)
    else:
        await update.message.reply_text("ℹ️ Используйте кнопки меню для навигации.", 
                                       reply_markup=menu(update.effective_user.id))

async def handle_document(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        return
    
    if not context.user_data.get("awaiting_file"):
        return
    
    document = update.message.document
    
    if not document.file_name.endswith('.txt'):
        await update.message.reply_text("❌ Пожалуйста, отправьте .txt файл.")
        return
    
    # Проверка прав для загрузки файлов
    user_id = update.effective_user.id
    if user_id not in SUPER_ADMIN_IDS and not check_perm(user_id, PERM_ACCS):
        await update.message.reply_text("❌ У вас нет прав на загрузку аккаунтов.")
        context.user_data["awaiting_file"] = False
        return
    
    file = await context.bot.get_file(document.file_id)
    file_bytes = await file.download_as_bytearray()
    
    try:
        content = file_bytes.decode('utf-8')
    except:
        content = file_bytes.decode('cp1251')
    
    accounts = []
    lines = content.strip().split('\n')
    for line in lines:
        line = line.strip()
        if ':' in line and line.count(':') == 1:
            accounts.append(line)
    
    if not accounts:
        await update.message.reply_text("❌ Не найдено аккаунтов в формате почта:пароль.")
        return
    
    context.user_data["temp_accounts"] = accounts
    
    if "selected_admin_game" in context.user_data:
        game = context.user_data["selected_admin_game"]
        await update.message.reply_text(
            f"📦 Найдено {len(accounts)} аккаунтов.\n🎮 Игра: {GAME_NAMES[game]}\n\nВыберите базу для загрузки:",
            reply_markup=admin_kb_acc_actions_for_game(game)
        )
    else:
        await update.message.reply_text(
            f"📦 Найдено {len(accounts)} аккаунтов.\n\n🎮 Выберите игру для загрузки:",
            reply_markup=admin_kb_acc_game_selection()
        )
    
    context.user_data["awaiting_file"] = False

async def delete_review_command(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ У вас нет доступа к этой команде.")
        return
    
    # Проверка прав для отзывов
    user_id = update.effective_user.id
    if user_id not in SUPER_ADMIN_IDS and not check_perm(user_id, PERM_REVIEWS):
        await update.message.reply_text("❌ У вас нет прав на удаление отзывов.")
        return
    
    if not context.args:
        await update.message.reply_text(
            "ℹ️ <b>Использование команды:</b>\n<code>/delete_review НОМЕР</code>\n\n📌 <b>Пример:</b>\n<code>/delete_review 5</code>\n\nЧтобы узнать номер отзыва, используйте '📋 Читать все' в админ панели.",
            parse_mode='HTML'
        )
        return
    
    try:
        review_num = int(context.args[0])
        reviews = data.get("reviews", [])
        
        if review_num < 1 or review_num > len(reviews):
            await update.message.reply_text(f"❌ Номер должен быть от 1 до {len(reviews)}.")
            return
        
        deleted_review = reviews.pop(review_num - 1)
        save()
        
        # УВЕДОМЛЕНИЕ СУПЕР-АДМИНОВ О УДАЛЕНИИ ОТЗЫВА
        await notify_super_admins(
            context,
            f"🗑 <b>УДАЛЕН ОТЗЫВ</b>\nКем: {get_user_link(update.effective_user)}\nНомер отзыва: {review_num}\nПользователь: {deleted_review['user_name']}\nТекст: {deleted_review['text'][:100]}..."
        )
        
        await update.message.reply_text(
            f"✅ Отзыв #{review_num} удален.\n\n👤 От: {deleted_review['user_name']}\n📅 Дата: {datetime.fromisoformat(deleted_review['date']).strftime('%d.%m.%Y')}\n📝 Текст: {deleted_review['text'][:100]}..."
        )
    except ValueError:
        await update.message.reply_text("❌ Номер должен быть целым числом.")

async def handle_media(update: Update, context: CallbackContext):
    if not is_admin(update.effective_user.id):
        return
    
    if context.user_data.get("broadcast_step") == "wait_content":
        # Для медиа-контента (фото, видео и т.д.)
        context.user_data["broadcast_msg_id"] = update.message.message_id
        context.user_data["broadcast_chat_id"] = update.message.chat_id
        
        await update.message.reply_text("Добавить кнопку с ссылкой?", reply_markup=broadcast_add_btn_kb())
        context.user_data["broadcast_step"] = "wait_decision"
        return

# Обработчик ошибок
async def error_handler(update: Update, context: CallbackContext):
    print(f"Ошибка: {context.error}")
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text("❌ Произошла ошибка. Попробуйте позже.")
        except:
            pass

async def add_me_as_admin(update: Update, context: CallbackContext):
    """Добавить себя как админа (только для супер-админов)"""
    user_id = update.effective_user.id
    
    if user_id not in SUPER_ADMIN_IDS:
        await update.message.reply_text("❌ Только супер-админы могут использовать эту команду.")
        return
    
    str_id = str(user_id)
    
    # Добавляем в админы со всеми правами
    data["admins"][str_id] = {
        "permissions": DEFAULT_PERMISSIONS.copy(),
        "notifications": {},
        "added_by": user_id,
        "added_date": datetime.now().isoformat(),
        "name": update.effective_user.full_name
    }
    save()
    
    await update.message.reply_text(
        "✅ <b>Вы добавлены как админ со всеми правами!</b>\n\n"
        "Теперь у вас есть доступ ко всем разделам:\n"
        "• 📦 Аккаунты\n• 🎟 Промокоды\n• ⛔ Бан\n• 📣 Рассылка\n"
        "• 📢 Каналы\n• 🛡 Админы\n• ⚙️ Настройки\n• ⭐ Модерация\n\n"
        "Используйте /panel для доступа к админ-панели",
        parse_mode='HTML'
    )

async def check_admin_status(update: Update, context: CallbackContext):
    """Проверка статуса админа"""
    user_id = update.effective_user.id
    
    status = f"""👑 <b>Проверка статуса админа</b>

🆔 Ваш ID: <code>{user_id}</code>
👑 Супер-админ: {'✅' if user_id in SUPER_ADMIN_IDS else '❌'}
📋 В списке админов: {'✅' if str(user_id) in data.get('admins', {}) else '❌'}
🔐 is_admin(): {'✅' if is_admin(user_id) else '❌'}

📊 <b>Права check_perm:</b>
• 📦 Аккаунты: {'✅' if check_perm(user_id, PERM_ACCS) else '❌'}
• 🎟 Промокоды: {'✅' if check_perm(user_id, PERM_PROMOS) else '❌'}
• ⛔ Бан: {'✅' if check_perm(user_id, PERM_BAN) else '❌'}
• 📣 Рассылка: {'✅' if check_perm(user_id, PERM_BROADCAST) else '❌'}
• 📢 Каналы: {'✅' if check_perm(user_id, PERM_CHANNELS) else '❌'}
• 🛡 Админы: {'✅' if check_perm(user_id, PERM_ADD_ADMIN) else '❌'}
• ⚙️ Настройки: {'✅' if check_perm(user_id, PERM_SETTINGS) else '❌'}
• ⭐ Модерация: {'✅' if check_perm(user_id, PERM_REVIEWS) else '❌'}"""
    
    await update.message.reply_text(status, parse_mode='HTML')

async def cleanup_command(update: Update, context: CallbackContext):
    """Очистка неактивных пользователей"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ У вас нет доступа.")
        return
    
    await update.message.reply_text("🔄 Начинаю проверку неактивных пользователей...")
    
    original_count = len(data["users"])
    users_to_remove = []
    
    # Проверяем случайную выборку пользователей
    sample_size = min(50, len(data["users"]))
    sample_users = random.sample(list(data["users"].keys()), sample_size)
    
    for user_id in sample_users:
        try:
            await context.bot.get_chat(int(user_id))
        except (Forbidden, BadRequest):
            users_to_remove.append(user_id)
    
    # Если в выборке много неактивных, очищаем всю базу
    inactive_percentage = len(users_to_remove) / sample_size if sample_size > 0 else 0
    
    if inactive_percentage > 0.3:  # Если более 30% неактивных
        await update.message.reply_text(
            f"⚠️ Обнаружено {inactive_percentage*100:.1f}% неактивных пользователей.\n"
            f"Начинаю полную очистку базы..."
        )
        
        # Полная проверка всех пользователей
        all_users_to_remove = []
        for user_id in list(data["users"].keys()):
            try:
                await context.bot.get_chat(int(user_id))
            except (Forbidden, BadRequest):
                all_users_to_remove.append(user_id)
        
        # Удаляем неактивных
        for user_id in all_users_to_remove:
            if user_id in data["users"]:
                del data["users"][user_id]
        
        cleaned_count = len(all_users_to_remove)
        save()
        
        await update.message.reply_text(
            f"✅ <b>Очистка завершена!</b>\n\n"
            f"📊 Результаты:\n"
            f"• Было: {original_count} пользователей\n"
            f"• Удалено: {cleaned_count} неактивных\n"
            f"• Осталось: {len(data['users'])} активных\n\n"
            f"<i>База успешно очищена от неактивных пользователей.</i>",
            parse_mode='HTML'
        )
    else:
        await update.message.reply_text(
            f"✅ База в порядке!\n\n"
            f"📊 Проверено: {sample_size} пользователей\n"
            f"✅ Активных: {sample_size - len(users_to_remove)}\n"
            f"❌ Неактивных: {len(users_to_remove)}\n\n"
            f"<i>Очистка не требуется (неактивных менее 30%).</i>",
            parse_mode='HTML'
        )

if __name__ == "__main__":
    import asyncio
    import sys
    
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("panel", panel_command))
    app.add_handler(CommandHandler("info", user_info_command))
    app.add_handler(CommandHandler("delete_review", delete_review_command))
    app.add_handler(CommandHandler("addme", add_me_as_admin))
    app.add_handler(CommandHandler("status", check_admin_status))
    app.add_handler(CommandHandler("cleanup", cleanup_command))
    app.add_handler(CallbackQueryHandler(main_callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(
        filters.PHOTO | filters.VIDEO | filters.VOICE | filters.AUDIO | filters.ANIMATION,
        handle_media
    ))
    
    app.add_error_handler(error_handler)
    
    print("🤖 Бот запущен! Нажмите Ctrl+C для остановки.")
    
    try:
        app.run_polling()
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
