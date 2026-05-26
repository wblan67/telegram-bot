import asyncio
from datetime import datetime, timedelta
from typing import Dict, Tuple, Optional
import re

from telegram import Update, ChatPermissions, Chat
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackContext,
    ConversationHandler,
)
from telegram.constants import ChatType

# ========== КОНФИГУРАЦИЯ ==========
TOKEN = "ВАШ_TELEGRAM_BOT_TOKEN"
OWNER_IDS = [123456789]  # ID владельца (можно несколько)

# Хранилище данных (в продакшене замените на БД)
user_ranks: Dict[int, Dict[int, int]] = {}  # {chat_id: {user_id: rank}}
user_warns: Dict[int, Dict[int, int]] = {}  # {chat_id: {user_id: warns}}
muted_users: Dict[int, Dict[int, datetime]] = {}  # {chat_id: {user_id: unmute_time}}
chat_locked: Dict[int, bool] = {}  # {chat_id: is_locked}

# Ранги
RANK_USER = 0
RANK_MODER_MIN = 1
RANK_MODER_MAX = 5
RANK_ADMIN = 10

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def get_user_rank(chat_id: int, user_id: int) -> int:
    return user_ranks.get(chat_id, {}).get(user_id, RANK_USER)

def set_user_rank(chat_id: int, user_id: int, rank: int):
    if chat_id not in user_ranks:
        user_ranks[chat_id] = {}
    user_ranks[chat_id][user_id] = rank

def remove_user_rank(chat_id: int, user_id: int):
    if chat_id in user_ranks and user_id in user_ranks[chat_id]:
        del user_ranks[chat_id][user_id]

def get_warns(chat_id: int, user_id: int) -> int:
    return user_warns.get(chat_id, {}).get(user_id, 0)

def add_warn(chat_id: int, user_id: int) -> int:
    if chat_id not in user_warns:
        user_warns[chat_id] = {}
    warns = user_warns[chat_id].get(user_id, 0) + 1
    user_warns[chat_id][user_id] = warns
    return warns

def clear_warns(chat_id: int, user_id: int):
    if chat_id in user_warns and user_id in user_warns[chat_id]:
        del user_warns[chat_id][user_id]

def is_muted(chat_id: int, user_id: int) -> bool:
    if chat_id not in muted_users or user_id not in muted_users[chat_id]:
        return False
    return muted_users[chat_id][user_id] > datetime.now()

def get_unmute_time(chat_id: int, user_id: int) -> Optional[datetime]:
    return muted_users.get(chat_id, {}).get(user_id)

def mute_user(chat_id: int, user_id: int, until: datetime):
    if chat_id not in muted_users:
        muted_users[chat_id] = {}
    muted_users[chat_id][user_id] = until

def unmute_user(chat_id: int, user_id: int):
    if chat_id in muted_users and user_id in muted_users[chat_id]:
        del muted_users[chat_id][user_id]

def is_admin_or_owner(user_id: int, chat_id: int) -> bool:
    rank = get_user_rank(chat_id, user_id)
    return rank == RANK_ADMIN or user_id in OWNER_IDS

def is_moderator(user_id: int, chat_id: int) -> bool:
    rank = get_user_rank(chat_id, user_id)
    return RANK_MODER_MIN <= rank <= RANK_MODER_MAX or rank == RANK_ADMIN or user_id in OWNER_IDS

def parse_time(time_str: str) -> Optional[timedelta]:
    """Парсит время: 5м, 2ч, 3д, 1н, 1г"""
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
    return None

# ========== ПРОВЕРКА ПРАВ ==========
async def check_moderator(update: Update, context: CallbackContext) -> bool:
    """Проверяет, является ли пользователь модератором/админом"""
    if not update.effective_chat or not update.effective_user:
        return False
    
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if not is_moderator(user_id, chat_id):
        await update.message.reply_text("❌ У вас нет прав для этой команды.")
        return False
    return True

async def check_admin(update: Update, context: CallbackContext) -> bool:
    """Проверяет, является ли пользователь администратором"""
    if not update.effective_chat or not update.effective_user:
        return False
    
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if not is_admin_or_owner(user_id, chat_id):
        await update.message.reply_text("❌ Требуются права администратора.")
        return False
    return True

async def check_owner(update: Update, context: CallbackContext) -> bool:
    """Проверяет, является ли пользователь владельцем"""
    if not update.effective_user:
        return False
    
    if update.effective_user.id not in OWNER_IDS:
        await update.message.reply_text("❌ Только владелец может использовать эту команду.")
        return False
    return True

def get_replied_user(update: Update) -> Optional[int]:
    """Получает ID пользователя, на чье сообщение ответили"""
    if not update.message or not update.message.reply_to_message:
        return None
    return update.message.reply_to_message.from_user.id

# ========== КОМАНДЫ МОДЕРАЦИИ ==========
async def cmd_mute(update: Update, context: CallbackContext):
    """Мут пользователя: мут 5м"""
    if not await check_moderator(update, context):
        return
    
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Ответьте на сообщение пользователя, которого хотите замутить.")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Укажите время. Пример: `мут 5м`", parse_mode='Markdown')
        return
    
    target_id = get_replied_user(update)
    admin_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    # Проверка на мута админа/владельца
    if is_admin_or_owner(target_id, chat_id):
        await update.message.reply_text("❌ Нельзя замутить администратора или владельца.")
        return
    
    time_delta = parse_time(context.args[0])
    if not time_delta:
        await update.message.reply_text("❌ Неверный формат. Примеры: `5м`, `2ч`, `3д`, `1н`, `1г`", parse_mode='Markdown')
        return
    
    until = datetime.now() + time_delta
    
    try:
        # Ограничиваем права (can_send_messages = False)
        await update.effective_chat.restrict_member(
            user_id=target_id,
            permissions=ChatPermissions(
                can_send_messages=False,
                can_send_media_messages=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
            ),
            until_date=until,
        )
        
        mute_user(chat_id, target_id, until)
        
        # Форматируем время для вывода
        time_str = context.args[0]
        await update.message.reply_text(
            f"🔇 Пользователь замучен на {time_str}\n"
            f"Размут: {until.strftime('%d.%m.%Y %H:%M')}"
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

async def cmd_unmute(update: Update, context: CallbackContext):
    """Размут пользователя"""
    if not await check_moderator(update, context):
        return
    
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Ответьте на сообщение пользователя, которого хотите размутить.")
        return
    
    target_id = get_replied_user(update)
    chat_id = update.effective_chat.id
    
    try:
        # Восстанавливаем права
        await update.effective_chat.restrict_member(
            user_id=target_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
            ),
        )
        
        unmute_user(chat_id, target_id)
        await update.message.reply_text("✅ Пользователь размучен.")
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

async def cmd_ban(update: Update, context: CallbackContext):
    """Бан пользователя"""
    if not await check_moderator(update, context):
        return
    
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Ответьте на сообщение пользователя, которого хотите забанить.")
        return
    
    target_id = get_replied_user(update)
    chat_id = update.effective_chat.id
    
    if is_admin_or_owner(target_id, chat_id):
        await update.message.reply_text("❌ Нельзя забанить администратора или владельца.")
        return
    
    try:
        await update.effective_chat.ban_member(user_id=target_id)
        await update.message.reply_text("🔨 Пользователь забанен.")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

async def cmd_unban(update: Update, context: CallbackContext):
    """Разбан по ID"""
    if not await check_moderator(update, context):
        return
    
    if not context.args:
        await update.message.reply_text("❌ Укажите ID пользователя. Пример: `разбан 123456789`", parse_mode='Markdown')
        return
    
    try:
        user_id = int(context.args[0])
        chat_id = update.effective_chat.id
        
        await update.effective_chat.unban_member(user_id=user_id)
        await update.message.reply_text(f"✅ Пользователь {user_id} разбанен.")
    except ValueError:
        await update.message.reply_text("❌ Неверный ID.")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

async def cmd_warn(update: Update, context: CallbackContext):
    """Выдать предупреждение (3 предупреждения = мут на 1 час)"""
    if not await check_moderator(update, context):
        return
    
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Ответьте на сообщение пользователя.")
        return
    
    target_id = get_replied_user(update)
    chat_id = update.effective_chat.id
    admin_name = update.effective_user.first_name
    
    # Нельзя выдавать варны админам
    if is_admin_or_owner(target_id, chat_id):
        await update.message.reply_text("❌ Нельзя выдавать предупреждения администратору.")
        return
    
    warns_count = add_warn(chat_id, target_id)
    
    await update.message.reply_text(
        f"⚠️ Пользователь получил предупреждение #{warns_count}/3\n"
        f"Выдал: {admin_name}"
    )
    
    # Если 3 предупреждения — мут на 1 час
    if warns_count >= 3:
        until = datetime.now() + timedelta(hours=1)
        
        try:
            await update.effective_chat.restrict_member(
                user_id=target_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until,
            )
            
            mute_user(chat_id, target_id, until)
            clear_warns(chat_id, target_id)  # Очищаем варны после мута
            
            await update.message.reply_text(
                f"🔇 Пользователь автоматически замучен на 1 час (3 предупреждения)"
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка при автоматическом муте: {str(e)}")

async def cmd_clear(update: Update, context: CallbackContext):
    """Очистка чата: очисти 10"""
    if not await check_moderator(update, context):
        return
    
    if not context.args:
        await update.message.reply_text("❌ Укажите количество сообщений. Пример: `очисти 10`", parse_mode='Markdown')
        return
    
    try:
        count = int(context.args[0])
        if count <= 0 or count > 100:
            await update.message.reply_text("❌ Укажите число от 1 до 100.")
            return
        
        chat_id = update.effective_chat.id
        message_id = update.message.message_id
        
        # Удаляем сообщения (бот должен быть администратором)
        for i in range(min(count, 100)):
            try:
                await update.effective_chat.delete_message(message_id - i)
            except:
                pass
        
        await update.message.reply_text(f"🧹 Очищено {count} сообщений.")
        
    except ValueError:
        await update.message.reply_text("❌ Укажите число.")

async def cmd_lock_chat(update: Update, context: CallbackContext):
    """Закрыть чат (-чат)"""
    if not await check_moderator(update, context):
        return
    
    chat_id = update.effective_chat.id
    chat_locked[chat_id] = True
    
    try:
        # Ограничиваем всех пользователей
        await update.effective_chat.set_permissions(
            permissions=ChatPermissions(can_send_messages=False)
        )
        await update.message.reply_text("🔒 Чат закрыт. Писать могут только модераторы и админы.")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

async def cmd_unlock_chat(update: Update, context: CallbackContext):
    """Открыть чат (+чат)"""
    if not await check_moderator(update, context):
        return
    
    chat_id = update.effective_chat.id
    chat_locked[chat_id] = False
    
    try:
        await update.effective_chat.set_permissions(
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
            )
        )
        await update.message.reply_text("🔓 Чат открыт для всех.")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

# ========== НАЗНАЧЕНИЕ РОЛЕЙ ==========
async def cmd_add_moder(update: Update, context: CallbackContext):
    """Назначить модератора: +модер 3 (ответом)"""
    if not await check_moderator(update, context):
        return
    
    if not context.args or len(context.args) < 1:
        await update.message.reply_text("❌ Укажите уровень. Пример: `+модер 3`", parse_mode='Markdown')
        return
    
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Ответьте на сообщение пользователя.")
        return
    
    try:
        level = int(context.args[0])
        if level < 1 or level > 5:
            await update.message.reply_text("❌ Уровень модератора должен быть от 1 до 5.")
            return
        
        target_id = get_replied_user(update)
        chat_id = update.effective_chat.id
        admin_id = update.effective_user.id
        admin_rank = get_user_rank(chat_id, admin_id)
        
        # Проверка прав: модер 5 уровня может назначать модеров 1-4 уровня
        if admin_rank == RANK_MODER_MAX:  # 5 уровень
            if level >= RANK_MODER_MAX:
                await update.message.reply_text("❌ Вы не можете назначать модераторов 5 уровня.")
                return
        elif admin_rank != RANK_ADMIN and admin_id not in OWNER_IDS:
            await update.message.reply_text("❌ Только администраторы и модераторы 5 уровня могут назначать модераторов.")
            return
        
        set_user_rank(chat_id, target_id, level)
        
        # Добавляем пометку в чате (опционально)
        try:
            await update.effective_chat.promote_member(
                user_id=target_id,
                can_delete_messages=True,
                can_restrict_members=True,
                can_pin_messages=True,
            )
        except:
            pass
        
        await update.message.reply_text(f"✅ Пользователь назначен модератором {level} уровня.")
        
    except ValueError:
        await update.message.reply_text("❌ Уровень должен быть числом.")

async def cmd_remove_moder(update: Update, context: CallbackContext):
    """Снять модератора: -модер (ответом)"""
    if not await check_moderator(update, context):
        return
    
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Ответьте на сообщение пользователя.")
        return
    
    target_id = get_replied_user(update)
    chat_id = update.effective_chat.id
    admin_id = update.effective_user.id
    
    if is_admin_or_owner(target_id, chat_id):
        if admin_id not in OWNER_IDS and get_user_rank(chat_id, admin_id) != RANK_ADMIN:
            await update.message.reply_text("❌ Вы не можете снять администратора.")
            return
    
    remove_user_rank(chat_id, target_id)
    
    # Убираем права в чате
    try:
        await update.effective_chat.promote_member(
            user_id=target_id,
            can_delete_messages=False,
            can_restrict_members=False,
            can_pin_messages=False,
        )
    except:
        pass
    
    await update.message.reply_text("✅ Модераторские права сняты.")

async def cmd_add_admin(update: Update, context: CallbackContext):
    """Назначить администратора: +админ (ответом) - только владелец"""
    if not await check_owner(update, context):
        return
    
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Ответьте на сообщение пользователя.")
        return
    
    target_id = get_replied_user(update)
    chat_id = update.effective_chat.id
    
    set_user_rank(chat_id, target_id, RANK_ADMIN)
    
    # Даём полные права в чате
    try:
        await update.effective_chat.promote_member(
            user_id=target_id,
            can_delete_messages=True,
            can_restrict_members=True,
            can_pin_messages=True,
            can_promote_members=True,
            can_change_info=True,
            can_invite_users=True,
        )
    except:
        pass
    
    await update.message.reply_text("✅ Пользователь назначен администратором.")

async def cmd_remove_admin(update: Update, context: CallbackContext):
    """Снять администратора: -админ (ответом) - только владелец"""
    if not await check_owner(update, context):
        return
    
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Ответьте на сообщение пользователя.")
        return
    
    target_id = get_replied_user(update)
    chat_id = update.effective_chat.id
    
    remove_user_rank(chat_id, target_id)
    
    try:
        await update.effective_chat.promote_member(
            user_id=target_id,
            can_delete_messages=False,
            can_restrict_members=False,
            can_pin_messages=False,
            can_promote_members=False,
            can_change_info=False,
            can_invite_users=False,
        )
    except:
        pass
    
    await update.message.reply_text("✅ Администраторские права сняты.")

# ========== ПРОСМОТР ИНФОРМАЦИИ ==========
async def cmd_moder_list(update: Update, context: CallbackContext):
    """Список всех модераторов и админов"""
    if not await check_moderator(update, context):
        return
    
    chat_id = update.effective_chat.id
    moderators = []
    admins = []
    
    for user_id, rank in user_ranks.get(chat_id, {}).items():
        if rank == RANK_ADMIN:
            admins.append(user_id)
        elif RANK_MODER_MIN <= rank <= RANK_MODER_MAX:
            moderators.append((user_id, rank))
    
    text = "👥 **Список модерации:**\n\n"
    
    if admins:
        text += "**Администраторы:**\n"
        for admin_id in admins:
            text += f"• `{admin_id}`\n"
        text += "\n"
    
    if moderators:
        text += "**Модераторы:**\n"
        for mod_id, level in moderators:
            text += f"• `{mod_id}` (уровень {level})\n"
    
    if not admins and not moderators:
        text += "Нет назначенных модераторов или администраторов."
    
    await update.message.reply_text(text, parse_mode='Markdown')

async def cmd_my_rank(update: Update, context: CallbackContext):
    """Мой ранг"""
    if not update.effective_chat or not update.effective_user:
        return
    
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    rank = get_user_rank(chat_id, user_id)
    
    if user_id in OWNER_IDS:
        rank_text = "Владелец"
    elif rank == RANK_ADMIN:
        rank_text = "Администратор"
    elif RANK_MODER_MIN <= rank <= RANK_MODER_MAX:
        rank_text = f"Модератор {rank} уровня"
    else:
        rank_text = "Обычный пользователь"
    
    await update.message.reply_text(f"📊 Ваш ранг: **{rank_text}**", parse_mode='Markdown')

async def cmd_info(update: Update, context: CallbackContext):
    """Информация о пользователе"""
    if not await check_moderator(update, context):
        return
    
    target = None
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
    elif context.args:
        try:
            # Пытаемся получить пользователя по ID
            pass
        except:
            pass
    
    if not target:
        target = update.effective_user
    
    user_id = target.id
    chat_id = update.effective_chat.id
    
    rank = get_user_rank(chat_id, user_id)
    warns = get_warns(chat_id, user_id)
    muted = is_muted(chat_id, user_id)
    unmute_time = get_unmute_time(chat_id, user_id)
    
    if user_id in OWNER_IDS:
        rank_text = "👑 Владелец"
    elif rank == RANK_ADMIN:
        rank_text = "👨‍💼 Администратор"
    elif RANK_MODER_MIN <= rank <= RANK_MODER_MAX:
        rank_text = f"🛡️ Модератор {rank} уровня"
    else:
        rank_text = "👤 Обычный пользователь"
    
    text = f"📋 **Информация о пользователе**\n\n"
    text += f"Имя: {target.first_name}\n"
    text += f"ID: `{user_id}`\n"
    text += f"Ранг: {rank_text}\n"
    text += f"Предупреждения: {warns}/3\n"
    text += f"Мут: {'Да' if muted else 'Нет'}\n"
    
    if muted and unmute_time:
        text += f"Размут: {unmute_time.strftime('%d.%m.%Y %H:%M')}\n"
    
    await update.message.reply_text(text, parse_mode='Markdown')

# ========== ФИЛЬТР СООБЩЕНИЙ ДЛЯ ЗАКРЫТОГО ЧАТА ==========
async def filter_locked_chat(update: Update, context: CallbackContext):
    """Проверяем, может ли пользователь писать в закрытом чате"""
    if not update.message or not update.effective_chat or not update.effective_user:
        return
    
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    # Если чат не закрыт - пропускаем
    if not chat_locked.get(chat_id, False):
        return
    
    # Модераторы, админы и владелец могут писать
    if is_moderator(user_id, chat_id):
        return
    
    # Остальные - удаляем сообщение
    try:
        await update.message.delete()
        await update.message.reply_text(
            "🔒 Чат закрыт. Писать могут только модераторы и администраторы.",
            quote=False
        )
    except:
        pass

# ========== ЗАПУСК БОТА ==========
def main():
    app = Application.builder().token(TOKEN).build()
    
    # Команды модерации
    app.add_handler(CommandHandler("мут", cmd_mute))
    app.add_handler(CommandHandler("размут", cmd_unmute))
    app.add_handler(CommandHandler("бан", cmd_ban))
    app.add_handler(CommandHandler("разбан", cmd_unban))
    app.add_handler(CommandHandler("варн", cmd_warn))
    app.add_handler(CommandHandler("очисти", cmd_clear))
    app.add_handler(CommandHandler("чат", cmd_lock_chat))  # -чат
    app.add_handler(CommandHandler("чат", cmd_unlock_chat))  # +чат
    
    # Назначение ролей
    app.add_handler(CommandHandler("модер", cmd_add_moder))  # +модер
    app.add_handler(CommandHandler("модер", cmd_remove_moder))  # -модер
    app.add_handler(CommandHandler("админ", cmd_add_admin))  # +админ
    app.add_handler(CommandHandler("админ", cmd_remove_admin))  # -админ
    
    # Просмотр информации
    app.add_handler(CommandHandler("кто", cmd_moder_list))  # /кто модеры
    app.add_handler(CommandHandler("мой", cmd_my_rank))  # /мой ранг
    app.add_handler(CommandHandler("инфо", cmd_info))
    
    # Фильтр для закрытого чата (должен быть перед обработкой обычных сообщений)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, filter_locked_chat), group=0)
    
    print("Бот запущен...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
