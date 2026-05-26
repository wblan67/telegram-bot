import os
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Optional

from telegram import Update, ChatPermissions
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ========== CONFIG ==========
BOT_TOKEN = os.getenv("8944720190:AAEiEGzRnvHZtwaWepB0BLNCKIKRI4Io5WQ")
OWNER_IDS = [int(os.getenv("OWNER_ID"))] if os.getenv("OWNER_ID") else []

# User ranks (0=banned, 1=user, 5=moderator, 10=admin)
user_ranks: Dict[int, int] = {}

# Mute timers
mute_timers: Dict[int, datetime] = {}

# ========== HELPER FUNCTIONS ==========
def get_rank(user_id: int) -> int:
    return user_ranks.get(user_id, 1)

def set_rank(user_id: int, rank: int):
    if rank < 0:
        rank = 0
    if rank > 10:
        rank = 10
    user_ranks[user_id] = rank

def has_permission(user_id: int, required_rank: int) -> bool:
    return get_rank(user_id) >= required_rank

def parse_time(time_str: str) -> Optional[timedelta]:
    """Convert 5m, 2h, 1d to timedelta"""
    if not time_str:
        return None
    unit = time_str[-1]
    try:
        value = int(time_str[:-1])
    except ValueError:
        return None
    
    if unit == 'm':
        return timedelta(minutes=value)
    elif unit == 'h':
        return timedelta(hours=value)
    elif unit == 'd':
        return timedelta(days=value)
    else:
        return None

# ========== COMMANDS ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message"""
    await update.message.reply_text(
        "🤖 *Moderation Bot*\n\n"
        "Available commands:\n"
        "• /start - show this message\n"
        "• /help - help\n"
        "• /info - user info\n\n"
        "*Moderation:*\n"
        "• !mute @username 5m - mute user\n"
        "• !unmute @username - unmute user\n"
        "• !ban @username - ban user\n"
        "• !unban @username - unban user\n"
        "• !setrank @username 5 - set rank (5=moderator)\n"
        "• !warn @username - warn user\n\n"
        "*For moderators:*\n"
        "• !clear 10 - clear messages",
        parse_mode="Markdown"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help message"""
    await start(update, context)

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User info"""
    user = update.effective_user
    rank = get_rank(user.id)
    
    rank_names = {
        0: "Banned",
        1: "User",
        5: "Moderator",
        10: "Admin"
    }
    
    await update.message.reply_text(
        f"📋 *User Info*\n\n"
        f"ID: {user.id}\n"
        f"Name: {user.first_name}\n"
        f"Rank: {rank_names.get(rank, 'User')}\n"
        f"Level: {rank}",
        parse_mode="Markdown"
    )

# ========== MODERATION ==========
async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mute user !mute @username 5m"""
    if not update.message.reply_to_message and not context.args:
        await update.message.reply_text("❌ Reply to a message or specify user: !mute @username 5m", parse_mode="Markdown")
        return
    
    caller_id = update.effective_user.id
    if not has_permission(caller_id, 5):
        await update.message.reply_text("❌ You don't have permission to mute")
        return
    
    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ Reply to the user's message to mute them")
        return
    
    target = update.message.reply_to_message.from_user
    
    time_str = context.args[-1] if context.args else None
    duration = parse_time(time_str) if time_str else timedelta(minutes=5)
    
    if not duration:
        await update.message.reply_text("❌ Invalid time format. Example: !mute @user 5m (m=minutes, h=hours, d=days)", parse_mode="Markdown")
        return
    
    try:
        until_date = datetime.now() + duration
        await update.message.chat.restrict_member(
            user_id=target.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until_date
        )
        
        mute_timers[target.id] = until_date
        
        await update.message.reply_text(
            f"🔇 User {target.first_name} muted for {time_str or '5 minutes'}\n"
            f"Moderator: {update.effective_user.first_name}"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unmute user"""
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Reply to the user's message to unmute them")
        return
    
    caller_id = update.effective_user.id
    if not has_permission(caller_id, 5):
        await update.message.reply_text("❌ You don't have permission")
        return
    
    target = update.message.reply_to_message.from_user
    
    try:
        await update.message.chat.restrict_member(
            user_id=target.id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True
            )
        )
        
        if target.id in mute_timers:
            del mute_timers[target.id]
        
        await update.message.reply_text(f"🔊 User {target.first_name} unmuted")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ban user"""
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Reply to the user's message to ban them")
        return
    
    caller_id = update.effective_user.id
    if not has_permission(caller_id, 5):
        await update.message.reply_text("❌ You don't have permission")
        return
    
    target = update.message.reply_to_message.from_user
    
    try:
        await update.message.chat.ban_member(user_id=target.id)
        set_rank(target.id, 0)
        await update.message.reply_text(f"⛔ User {target.first_name} banned")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unban user"""
    if not context.args:
        await update.message.reply_text("❌ Specify user ID: !unban 123456789", parse_mode="Markdown")
        return
    
    caller_id = update.effective_user.id
    if not has_permission(caller_id, 5):
        await update.message.reply_text("❌ You don't have permission")
        return
    
    try:
        user_id = int(context.args[0])
        await update.message.chat.unban_member(user_id=user_id)
        set_rank(user_id, 1)
        await update.message.reply_text(f"✅ User {user_id} unbanned")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def setrank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set user rank !setrank @username 5"""
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Reply to the user's message")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Specify rank: !setrank 5 (1-10)", parse_mode="Markdown")
        return
    
    caller_id = update.effective_user.id
    if not has_permission(caller_id, 10):
        await update.message.reply_text("❌ Only admins can change ranks")
        return
    
    try:
        new_rank = int(context.args[0])
        if new_rank < 0 or new_rank > 10:
            await update.message.reply_text("❌ Rank must be between 0 and 10")
            return
        
        target = update.message.reply_to_message.from_user
        set_rank(target.id, new_rank)
        
        rank_names = {0: "banned", 1: "user", 5: "moderator", 10: "admin"}
        await update.message.reply_text(f"✅ {target.first_name} rank changed to {rank_names.get(new_rank, new_rank)}")
    except ValueError:
        await update.message.reply_text("❌ Rank must be a number")

async def warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Warn user"""
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Reply to the user's message")
        return
    
    caller_id = update.effective_user.id
    if not has_permission(caller_id, 5):
        await update.message.reply_text("❌ You don't have permission")
        return
    
    target = update.message.reply_to_message.from_user
    
    if not hasattr(context.chat_data, 'warnings'):
        context.chat_data['warnings'] = {}
    
    warnings = context.chat_data['warnings'].get(target.id, 0) + 1
    context.chat_data['warnings'][target.id] = warnings
    
    await update.message.reply_text(f"⚠️ {target.first_name} received a warning ({warnings}/3)")
    
    if warnings >= 3:
        await mute(update, context)

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear messages !clear 10"""
    if not context.args:
        await update.message.reply_text("❌ Specify amount: !clear 10", parse_mode="Markdown")
        return
    
    caller_id = update.effective_user.id
    if not has_permission(caller_id, 5):
        await update.message.reply_text("❌ You don't have permission")
        return
    
    try:
        amount = int(context.args[0])
        if amount > 100:
            amount = 100
        
        await update.message.delete()
        deleted = await update.message.chat.purge_messages(limit=amount)
        msg = await update.message.reply_text(f"✅ Deleted {len(deleted)} messages")
        
        await asyncio.sleep(3)
        await msg.delete()
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

# ========== MAIN ==========
def main():
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN is not set!")
        return
    
    print("Starting bot...")
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("info", info))
    
    # Commands with ! prefix
    app.add_handler(MessageHandler(filters.Regex(r'^!mute\b'), mute))
    app.add_handler(MessageHandler(filters.Regex(r'^!unmute\b'), unmute))
    app.add_handler(MessageHandler(filters.Regex(r'^!ban\b'), ban))
    app.add_handler(MessageHandler(filters.Regex(r'^!unban\b'), unban))
    app.add_handler(MessageHandler(filters.Regex(r'^!setrank\b'), setrank))
    app.add_handler(MessageHandler(filters.Regex(r'^!warn\b'), warn))
    app.add_handler(MessageHandler(filters.Regex(r'^!clear\b'), clear))
    
    print("Bot is running and ready!")
    app.run_polling()

if __name__ == "__main__":
    main()
