import os
import re
from datetime import datetime, timedelta
from typing import Dict, Optional

from telegram import Update, ChatPermissions
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackContext,
)

# ========== КОНФИГУРАЦИЯ ==========
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
PORT = int(os.environ.get("PORT", 8080))

# ID владельцев (формат: "123456789,987654321")
OWNER_IDS = [int(id) for id in os.environ.get("OWNER_IDS", "").split(",") if id]

if not OWNER_IDS:
    OWNER_IDS = [123456789]  # Заглушка для тестов

# Хранилище данных (в продакшене замените на БД)
user_ranks: Dict[int, Dict[int, int]] = {}
user_warns: Dict[int, Dict[int, int]] = {}
muted_users: Dict[int, Dict[int, datetime]] = {}
chat_locked: Dict[int, bool] = {}

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
    if not update.effective_chat or not update.effective_user:
        return False
    
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if not is_moderator(user_id, chat_id):
        await update.message.reply_text("❌ У вас нет прав для этой команды.")
        return False
    return True

async def check_admin(update: Update, context: CallbackContext) -> bool:
    if not update.effective_chat or not update.effective_user:
        return False
    
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    if not is_admin_or_owner(user_id, chat_id):
        await update.message.reply_text("❌ Требуются права администратора.")
        return False
    return True

async def check_owner(update: Update, context: CallbackContext) -> bool:
    if not update.effective_user:
        return False
    
    if update.effective_user.id not in OWNER_IDS:
        await update.message.reply_text("❌ Только владелец может использовать эту команду.")
        return False
    return True

def get_replied_user(update: Update) -> Optional[int]:
    if not update.message or not update.message.reply_to_message:
        return None
    return update.message.reply_to_message.from_user.id

# ========== КОМАНДЫ МОДЕРАЦИИ ==========
async def cmd_mute(update: Update, context: CallbackContext):
    """Мут пользователя: /mute 5м"""
    if not await check_moderator(update, context):
        return
    
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Ответьте на сообщение пользователя, которого хотите замутить.")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Укажите время. Пример: `/mute 5м`", parse_mode='Markdown')
        return
    
    target_id = get_replied_user(update)
    chat_id = update.effective_chat.id
    
    if is_admin_or_owner(target_id, chat_id):
        await update.message.reply_text("❌ Нельзя замутить администратора или владельца.")
        return
    
    time_delta = parse_time(context.args[0])
    if not time_delta:
        await update.message.reply_text("❌ Неверный формат. Примеры: `5м`, `2ч`, `3д`, `1н`, `1г`", parse_mode='Markdown')
        return
    
    until = datetime.now() + time_delta
    
    try:
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
        
        await update.message.reply_text(
            f"🔇 Пользователь замучен на {context.args[0]}\n"
            f"Размут: {until.strftime('%d.%m.%Y %H:%M')}"
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

async def cmd_unmute(update: Update, context: CallbackContext):
    """Размут пользователя: /unmute"""
    if not await check_moderator(update, context):
        return
    
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Ответьте на сообщение пользователя, которого хотите размутить.")
        return
    
    target_id = get_replied_user(update)
    chat_id = update.effective_chat.id
    
    try:
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
    """Бан пользователя: /ban"""
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
    """Разбан по ID: /unban 123456789"""
    if not await check_moderator(update, context):
        return
    
    if not context.args:
        await update.message.reply_text("❌ Укажите ID пользователя. Пример: `/unban 123456789`", parse_mode='Markdown')
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
    """Выдать предупреждение: /warn (3 = мут на 1 час)"""
    if not await check_moderator(update, context):
        return
    
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Ответьте на сообщение пользователя.")
        return
    
    target_id = get_replied_user(update)
    chat_id = update.effective_chat.id
    admin_name = update.effective_user.first_name
    
    if is_admin_or_owner(target_id, chat_id):
        await update.message.reply_text("❌ Нельзя выдавать предупреждения администратору.")
        return
    
    warns_count = add_warn(chat_id, target_id)
    
    await update.message.reply_text(
        f"⚠️ Пользователь получил предупреждение #{warns_count}/3\n"
        f"Выдал: {admin_name}"
    )
    
    if warns_count >= 3:
        until = datetime.now() + timedelta(hours=1)
        
        try:
            await update.effective_chat.restrict_member(
                user_id=target_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until,
            )
            
            mute_user(chat_id, target_id, until)
            clear_warns(chat_id, target_id)
            
            await update.message.reply_text(
                f"🔇 Пользователь автоматически замучен на 1 час (3 предупреждения)"
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка при автоматическом муте: {str(e)}")

async def cmd_clear(update: Update, context: CallbackContext):
    """Очистка чата: /clear 10"""
    if not await check_moderator(update, context):
        return
    
    if not context.args:
        await update.message.reply_text("❌ Укажите количество сообщений. Пример: `/clear 10`", parse_mode='Markdown')
        return
    
    try:
        count = int(context.args[0])
        if count <= 0 or count > 100:
            await update.message.reply_text("❌ Укажите число от 1 до 100.")
            return
        
        chat_id = update.effective_chat.id
        message_id = update.message.message_id
        
        deleted = 0
        for i in range(min(count, 100)):
            try:
                await update.effective_chat.delete_message(message_id - i)
                deleted += 1
            except:
                pass
        
        await update.message.reply_text(f"🧹 Удалено {deleted} сообщений.")
        
    except ValueError:
        await update.message.reply_text("❌ Укажите число.")

async def cmd_lock_chat(update: Update, context: CallbackContext):
    """Закрыть чат: -чат"""
    if not await check_moderator(update, context):
        return
    
    chat_id = update.effective_chat.id
    chat_locked[chat_id] = True
    
    try:
        await update.effective_chat.set_permissions(
            permissions=ChatPermissions(can_send_messages=False)
        )
        await update.message.reply_text("🔒 Чат закрыт. Писать могут только модераторы и админы.")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

async def cmd_unlock_chat(update: Update, context: CallbackContext):
    """Открыть чат: +чат"""
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
        
        if admin_rank == RANK_MODER_MAX:
            if level >= RANK_MODER_MAX:
                await update.message.reply_text("❌ Вы не можете назначать модераторов 5 уровня.")
                return
        elif admin_rank != RANK_ADMIN and admin_id not in OWNER_IDS:
            await update.message.reply_text("❌ Только администраторы и модераторы 5 уровня могут назначать модераторов.")
            return
        
        set_user_rank(chat_id, target_id, level)
        
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
    """Список модераторов: /moders"""
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
    """Мой ранг: /rank"""
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
    """Информация о пользователе: /info (ответом или без)"""
    if not await check_moderator(update, context):
        return
    
    target = None
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
    else:
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
    # Проверяем, есть ли токен
    if not TOKEN:
        print("❌ ОШИБКА: Не указан TELEGRAM_BOT_TOKEN в переменных окружения!")
        return
    
    print(f"🤖 Запуск бота с токеном: {TOKEN[:15]}...")
    
    # Создаем приложение
    application = Application.builder().token(TOKEN).build()
    
    # Команды модерации
    application.add_handler(CommandHandler("mute", cmd_mute))
    application.add_handler(CommandHandler("unmute", cmd_unmute))
    application.add_handler(CommandHandler("ban", cmd_ban))
    application.add_handler(CommandHandler("unban", cmd_unban))
    application.add_handler(CommandHandler("warn", cmd_warn))
    application.add_handler(CommandHandler("clear", cmd_clear))
    
    # Отдельные обработчики для +чат и -чат
    application.add_handler(MessageHandler(filters.Regex(r'^\-чат$'), cmd_lock_chat))
    application.add_handler(MessageHandler(filters.Regex(r'^\+чат$'), cmd_unlock_chat))
    
    # Назначение ролей
    application.add_handler(MessageHandler(filters.Regex(r'^\+модер\s+\d+$'), cmd_add_moder))
    application.add_handler(MessageHandler(filters.Regex(r'^\-модер$'), cmd_remove_moder))
    application.add_handler(MessageHandler(filters.Regex(r'^\+админ$'), cmd_add_admin))
    application.add_handler(MessageHandler(filters.Regex(r'^\-админ$'), cmd_remove_admin))
    
    # Просмотр информации
    application.add_handler(CommandHandler("moders", cmd_moder_list))
    application.add_handler(CommandHandler("rank", cmd_my_rank))
    application.add_handler(CommandHandler("info", cmd_info))
    
    # Фильтр для закрытого чата
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, filter_locked_chat), group=0)
    
    # ЗАПУСК В РЕЖИМЕ LONG POLLING
    print("✅ Бот успешно запущен и работает в режиме Long Polling!")
    print("📡 Ожидание команд от Telegram...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
