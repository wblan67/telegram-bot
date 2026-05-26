import os
import asyncio
import re
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Tuple

from telegram import Update, ChatPermissions
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ========== КОНФИГ ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_IDS = [int(os.getenv("OWNER_ID"))] if os.getenv("OWNER_ID") else []

# Ранги:
# 0 = обычный пользователь (без модерации)
# 1-5 = модератор (уровень 1-5, где 5 - главный модератор)
# 10 = админ
user_ranks: Dict[int, int] = {}

# Таймеры мутов
mute_timers: Dict[int, datetime] = {}

# Состояние чата (закрыт/открыт)
chat_locked: Dict[int, bool] = {}

# Названия рангов
RANK_NAMES = {
    0: "👤 Пользователь",
    1: "🟢 Модератор 1 ур.",
    2: "🔵 Модератор 2 ур.",
    3: "🟠 Модератор 3 ур.",
    4: "🟣 Модератор 4 ур.",
    5: "⭐ Модератор 5 ур.",
    10: "👑 Администратор"
}

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def get_rank(user_id: int) -> int:
    return user_ranks.get(user_id, 0)

def get_rank_name(rank: int) -> str:
    return RANK_NAMES.get(rank, "👤 Пользователь")

def set_rank(user_id: int, rank: int):
    if rank < 0:
        rank = 0
    if rank > 10:
        rank = 10
    if rank not in [0, 1, 2, 3, 4, 5, 10]:
        rank = 0
    user_ranks[user_id] = rank

def has_permission(user_id: int, required_rank: int) -> bool:
    """Проверка прав. required_rank: 1-5 для модера, 10 для админа"""
    user_rank = get_rank(user_id)
    if user_rank >= 10:
        return True
    if required_rank <= 5:
        return user_rank >= required_rank and user_rank >= 1
    return False

def is_owner(user_id: int) -> bool:
    return user_id in OWNER_IDS

def can_assign_rank(giver_id: int, target_rank: int) -> bool:
    """Кто кому может назначать ранги"""
    giver_rank = get_rank(giver_id)
    if is_owner(giver_id):
        return True
    if giver_rank >= 10:
        return target_rank < 10
    if giver_rank >= 5:
        return 1 <= target_rank <= 4
    return False

def parse_time(time_str: str) -> Optional[timedelta]:
    """Преобразует 5м, 2ч, 3д, 1н, 1г в timedelta"""
    if not time_str:
        return None
    
    match = re.match(r'(\d+)([мчднг])', time_str.lower())
    if not match:
        return None
    
    value = int(match.group(1))
    unit = match.group(2)
    
    if unit == 'м':
        return timedelta(minutes=value)
    elif unit == 'ч':
        return timedelta(hours=value)
    elif unit == 'д':
        return timedelta(days=value)
    elif unit == 'н':
        return timedelta(weeks=value)
    elif unit == 'г':
        return timedelta(days=value * 365)
    else:
        return None

def format_duration(delta: timedelta) -> str:
    """Красивый вывод времени"""
    days = delta.days
    hours = delta.seconds // 3600
    minutes = (delta.seconds % 3600) // 60
    
    if days >= 365:
        years = days // 365
        return f"{years} г"
    elif days >= 7:
        weeks = days // 7
        return f"{weeks} н"
    elif days > 0:
        return f"{days} д"
    elif hours > 0:
        return f"{hours} ч"
    else:
        return f"{minutes} м"

async def get_members_list(update: Update) -> List[Tuple[int, str, int]]:
    """Получить список участников чата с их рангами"""
    members = []
    for user_id, rank in user_ranks.items():
        if rank > 0:
            try:
                user = await update.message.chat.get_member(user_id)
                name = user.user.first_name
                if user.user.username:
                    name += f" (@{user.user.username})"
                members.append((user_id, name, rank))
            except:
                members.append((user_id, f"ID: {user_id}", rank))
    members.sort(key=lambda x: x[2], reverse=True)
    return members
    # ========== КОМАНДЫ ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Приветствие"""
    await update.message.reply_text(
        "🤖 *Модерационный бот*\n\n"
        "Доступные команды:\n"
        "• /start - показать это сообщение\n"
        "• /помощь - помощь\n"
        "• /инфо - информация о пользователе\n"
        "• /мой ранг - ваш уровень\n"
        "• /кто модеры - список модераторов и админов\n\n"
        "*Модерация:*\n"
        "• мут 5м - замутить (ответом или @username)\n"
        "• размут - размутить\n"
        "• бан - забанить\n"
        "• разбан ID - разбанить\n"
        "• варн - предупреждение (3 = мут)\n"
        "• очисти 10 - очистить чат\n"
        "• -чат - закрыть чат для всех, кроме админов\n"
        "• +чат - открыть чат для всех\n\n"
        "*Назначение ролей (ответом на сообщение):*\n"
        "• +модер 3 - назначить модератора (уровень 1-5)\n"
        "• -модер - снять модерацию\n"
        "• +админ - назначить админа\n"
        "• -админ - снять админа\n\n"
        "Время: м (минуты), ч (часы), д (дни), н (недели), г (годы)",
        parse_mode="Markdown"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Информация о пользователе"""
    user = update.effective_user
    rank = get_rank(user.id)
    
    await update.message.reply_text(
        f"📋 *Информация о пользователе*\n\n"
        f"ID: {user.id}\n"
        f"Имя: {user.first_name}\n"
        f"Ранг: {get_rank_name(rank)}\n"
        f"Уровень: {rank if rank > 0 else 'Нет'}",
        parse_mode="Markdown"
    )

async def my_rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Мой ранг"""
    user = update.effective_user
    rank = get_rank(user.id)
    await update.message.reply_text(
        f"📊 *Ваш ранг:* {get_rank_name(rank)}",
        parse_mode="Markdown"
    )

async def list_moders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список всех модераторов и админов"""
    members = await get_members_list(update)
    
    if not members:
        await update.message.reply_text("📋 В этом чате нет назначенных модераторов или админов.")
        return
    
    admins = []
    moderators = []
    
    for _, name, rank in members:
        if rank >= 10:
            admins.append(f"👑 {name}")
        elif rank >= 1:
            moderators.append(f"{RANK_NAMES.get(rank, 'Модератор')} {name}")
    
    text = "📋 *Список модераторов и админов:*\n\n"
    if admins:
        text += "*Администраторы:*\n" + "\n".join(admins) + "\n\n"
    if moderators:
        text += "*Модераторы:*\n" + "\n".join(moderators)
    
    await update.message.reply_text(text, parse_mode="Markdown")

# ========== УПРАВЛЕНИЕ ЧАТОМ ==========
async def close_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """-чат - закрыть чат для всех, кроме админов"""
    chat_id = update.effective_chat.id
    caller_id = update.effective_user.id
    
    if not has_permission(caller_id, 10):
        await update.message.reply_text("❌ Только администраторы могут закрывать чат")
        return
    
    try:
        # Устанавливаем права: все, кроме отправки сообщений
        await update.message.chat.set_permissions(
            ChatPermissions(
                can_send_messages=False,
                can_send_media_messages=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False
            )
        )
        chat_locked[chat_id] = True
        await update.message.reply_text("🔒 *Чат закрыт!*\nПисать могут только администраторы.", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")
        async def open_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """+чат - открыть чат для всех"""
    chat_id = update.effective_chat.id
    caller_id = update.effective_user.id
    
    if not has_permission(caller_id, 10):
        await update.message.reply_text("❌ Только администраторы могут открывать чат")
        return
    
    try:
        # Восстанавливаем права
        await update.message.chat.set_permissions(
            ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True
            )
        )
        chat_locked[chat_id] = False
        await update.message.reply_text("🔓 *Чат открыт!*\nВсе пользователи могут писать.", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

# Фильтр для проверки, может ли пользователь писать в закрытом чате
async def chat_lock_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка, может ли пользователь писать в закрытом чате"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    # Если чат не закрыт - пропускаем
    if not chat_locked.get(chat_id, False):
        return True
    
    # Если пользователь админ или модератор - пропускаем
    if has_permission(user_id, 1):
        return True
    
    # Иначе - блокируем сообщение
    await update.message.delete()
    await update.message.reply_text("🔒 Чат закрыт. Писать могут только модераторы и администраторы.")
    return False

# ========== НАЗНАЧЕНИЕ РОЛЕЙ ==========
async def add_moder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """+модер 3 - назначить модератора"""
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Ответьте на сообщение пользователя, которому хотите назначить модератора")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Укажите уровень модератора: +модер 3 (1-5)", parse_mode="Markdown")
        return
    
    try:
        level = int(context.args[0])
        if level < 1 or level > 5:
            await update.message.reply_text("❌ Уровень модератора должен быть от 1 до 5")
            return
    except ValueError:
        await update.message.reply_text("❌ Уровень должен быть числом: +модер 3", parse_mode="Markdown")
        return
    
    caller_id = update.effective_user.id
    if not can_assign_rank(caller_id, level):
        await update.message.reply_text("❌ У вас нет прав назначить модератора этого уровня")
        return
    
    target = update.message.reply_to_message.from_user
    
    if get_rank(target.id) >= 10:
        await update.message.reply_text("❌ Нельзя изменить ранг администратора")
        return
    
    set_rank(target.id, level)
    await update.message.reply_text(f"✅ {target.first_name} назначен {get_rank_name(level)}")

async def remove_moder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """-модер - снять модерацию"""
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Ответьте на сообщение пользователя, у которого хотите снять модерацию")
        return
    
    caller_id = update.effective_user.id
    target = update.message.reply_to_message.from_user
    target_rank = get_rank(target.id)
    
    if target_rank == 0:
        await update.message.reply_text("❌ У этого пользователя нет модерации")
        return
    
    if target_rank >= 10:
        await update.message.reply_text("❌ Нельзя снять модерацию с администратора")
        return
    
    if not can_assign_rank(caller_id, 0) and not has_permission(caller_id, 10):
        await update.message.reply_text("❌ У вас нет прав снимать модерацию")
        return
    
    set_rank(target.id, 0)
    await update.message.reply_text(f"✅ У {target.first_name} снята модерация")
    
