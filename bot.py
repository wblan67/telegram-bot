import asyncio
import re
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, ChatPermissions

# --- CONFIG ---
BOT_TOKEN = "8944720190:AAEiEGzRnvHZtwaWepB0BLNCKIKRI4Io5WQ"
OWNER_IDS = [6034090849]  # Replace with your Telegram ID

# Time units: 7m, 2h, 3d, 1w
TIME_UNITS = {
    "s": "seconds",
    "m": "minutes", 
    "h": "hours",
    "d": "days",
    "w": "weeks"
}

# Rank permissions (1-5)
# 1 = Junior Mod, 2 = Mod, 3 = Senior Mod, 4 = Admin, 5 = Owner
RANK_PERMS = {
    1: {"warn": True, "mute": True, "ban": False, "kick": True, "promote": False, "demote": False},
    2: {"warn": True, "mute": True, "ban": True, "kick": True, "promote": 1, "demote": False},
    3: {"warn": True, "mute": True, "ban": True, "kick": True, "promote": 2, "demote": True},
    4: {"warn": True, "mute": True, "ban": True, "kick": True, "promote": 3, "demote": True},
    5: {"warn": True, "mute": True, "ban": True, "kick": True, "promote": 4, "demote": True, "full": True}
}

# Storage (use database for production)
user_ranks: Dict[int, int] = {}
user_warns: Dict[int, list] = {}
temp_mutes: Dict[int, datetime] = {}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


def parse_time(time_str: str) -> Optional[int]:
    match = re.match(r"(\d+)([smhdw])", time_str.lower())
    if not match:
        return None
    value = int(match.group(1))
    unit = match.group(2)
    if unit in TIME_UNITS:
        seconds = value * {
            "seconds": 1, "minutes": 60, "hours": 3600,
            "days": 86400, "weeks": 604800
        }.get(TIME_UNITS[unit], 0)
        return seconds
    return None


def get_rank(user_id: int) -> int:
    return user_ranks.get(user_id, 0)


def has_perm(mod_id: int, action: str, target_rank: int = 0) -> bool:
    mod_rank = get_rank(mod_id)
    if mod_rank >= 5 or mod_id in OWNER_IDS:
        return True
    
    perms = RANK_PERMS.get(mod_rank, {})
    
    if action == "promote":
        max_promote = perms.get("promote", False)
        if isinstance(max_promote, int):
            return target_rank <= max_promote
        return False
    if action == "demote":
        return perms.get("demote", False) and mod_rank > target_rank
    
    return perms.get(action, False)


def can_mod(mod_id: int, target_id: int) -> Tuple[bool, str]:
    mod_rank = get_rank(mod_id)
    target_rank = get_rank(target_id)
    
    if target_id in OWNER_IDS and mod_id not in OWNER_IDS:
        return False, "Cannot moderate owner!"
    if mod_rank <= target_rank and mod_rank != 5:
        return False, f"Cannot moderate rank {target_rank} (you have {mod_rank})"
    return True, ""


@dp.message(Command("start"))
async def start_cmd(message: Message):
    await message.answer(
        "Moderation Bot Ready!\n\n"
        "Commands:\n"
        "!mute @user 7m - mute for 7 minutes\n"
        "!ban @user 3d - ban for 3 days\n"
        "!warn @user reason - warn user\n"
        "!unmute @user - unmute\n"
        "!unban user_id - unban\n"
        "!setrank @user 3 - set rank (1-5)\n"
        "!warns @user - show warns\n"
        "!kick @user - kick\n"
        "!clear N - delete N messages"
    )


@dp.message(Command("mute"))
async def mute_cmd(message: Message):
    if not message.reply_to_message:
        return await message.answer("Reply to a user message!")
    
    mod_id = message.from_user.id
    target = message.reply_to_message.from_user
    args = message.text.split()
    time_str = args[1] if len(args) > 1 else None
    
    if not time_str:
        return await message.answer("Specify time: !mute @user 10m")
    
    seconds = parse_time(time_str)
    if not seconds:
        return await message.answer("Invalid format. Examples: 10m, 2h, 3d, 1w")
        allowed, err = can_mod(mod_id, target.id)
    if not allowed:
        return await message.answer(err)
    
    if not has_perm(mod_id, "mute"):
        return await message.answer("You don't have mute permission!")
    
    until_date = datetime.now() + timedelta(seconds=seconds)
    
    try:
        await bot.restrict_chat_member(
            message.chat.id,
            target.id,
            ChatPermissions(can_send_messages=False),
            until_date=until_date
        )
        temp_mutes[target.id] = until_date
        await message.answer(f"Muted {target.mention} for {time_str}")
    except Exception as e:
        await message.answer(f"Error: {e}")


@dp.message(Command("unmute"))
async def unmute_cmd(message: Message):
    if not message.reply_to_message:
        return await message.answer("Reply to a user message!")
    
    mod_id = message.from_user.id
    target = message.reply_to_message.from_user
    
    allowed, err = can_mod(mod_id, target.id)
    if not allowed:
        return await message.answer(err)
    
    try:
        await bot.restrict_chat_member(
            message.chat.id,
            target.id,
            ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True
            )
        )
        temp_mutes.pop(target.id, None)
        await message.answer(f"Unmuted {target.mention}")
    except Exception as e:
        await message.answer(f"Error: {e}")


@dp.message(Command("ban"))
async def ban_cmd(message: Message):
    if not message.reply_to_message:
        return await message.answer("Reply to a user message!")
    
    mod_id = message.from_user.id
    target = message.reply_to_message.from_user
    args = message.text.split()
    time_str = args[1] if len(args) > 1 else None
    
    if not has_perm(mod_id, "ban"):
        return await message.answer("You don't have ban permission!")
    
    allowed, err = can_mod(mod_id, target.id)
    if not allowed:
        return await message.answer(err)
    
    until_date = None
    if time_str:
        seconds = parse_time(time_str)
        if seconds:
            until_date = datetime.now() + timedelta(seconds=seconds)
    
    try:
        await bot.ban_chat_member(message.chat.id, target.id, until_date=until_date)
        msg = f"Banned {target.mention}"
        if until_date:
            msg += f" for {time_str}"
        await message.answer(msg)
    except Exception as e:
        await message.answer(f"Error: {e}")


@dp.message(Command("unban"))
async def unban_cmd(message: Message):
    args = message.text.split()
    if len(args) < 2:
        return await message.answer("Usage: !unban user_id")
    
    mod_id = message.from_user.id
    user_id = int(args[1])
    
    if not has_perm(mod_id, "ban"):
        return await message.answer("You don't have unban permission!")
    
    try:
        await bot.unban_chat_member(message.chat.id, user_id)
        await message.answer(f"Unbanned user {user_id}")
    except Exception as e:
        await message.answer(f"Error: {e}")


@dp.message(Command("kick"))
async def kick_cmd(message: Message):
    if not message.reply_to_message:
        return await message.answer("Reply to a user message!")
    
    mod_id = message.from_user.id
    target = message.reply_to_message.from_user
    
    if not has_perm(mod_id, "kick"):
        return await message.answer("You don't have kick permission!")
    
    allowed, err = can_mod(mod_id, target.id)
    if not allowed:
        return await message.answer(err)
    
    try:
        await bot.ban_chat_member(message.chat.id, target.id)
        await bot.unban_chat_member(message.chat.id, target.id)
        await message.answer(f"Kicked {target.mention}")
    except Exception as e:
        await message.answer(f"Error: {e}")
        @dp.message(Command("warn"))
async def warn_cmd(message: Message):
    if not message.reply_to_message:
        return await message.answer("Reply to a user message!")
    
    mod_id = message.from_user.id
    target = message.reply_to_message.from_user
    reason = " ".join(message.text.split()[1:]) if len(message.text.split()) > 1 else "No reason"
    
    if not has_perm(mod_id, "warn"):
        return await message.answer("You don't have warn permission!")
    
    allowed, err = can_mod(mod_id, target.id)
    if not allowed:
        return await message.answer(err)
    
    if target.id not in user_warns:
        user_warns[target.id] = []
    
    warn_id = len(user_warns[target.id]) + 1
    user_warns[target.id].append({
        "id": warn_id,
        "reason": reason,
        "mod": message.from_user.full_name,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M")
    })
    
    await message.answer(f"Warned {target.mention}\nReason: {reason}\nTotal warns: {len(user_warns[target.id])}")
    
    if len(user_warns[target.id]) >= 3:
        await message.answer(f"{target.mention} has 3 warns! Consider mute or ban.")


@dp.message(Command("warns"))
async def warns_cmd(message: Message):
    if not message.reply_to_message:
        return await message.answer("Reply to a user message!")
    
    target = message.reply_to_message.from_user
    
    if not has_perm(message.from_user.id, "view_warns"):
        return await message.answer("You don't have permission to view warns!")
    
    warns = user_warns.get(target.id, [])
    if not warns:
        return await message.answer(f"{target.mention} has no warns")
    
    text = f"Warns for {target.mention}:\n"
    for w in warns:
        text += f"#{w['id']} - {w['reason']} (by {w['mod']} on {w['date']})\n"
    
    await message.answer(text[:4000])


@dp.message(Command("setrank"))
async def setrank_cmd(message: Message):
    args = message.text.split()
    if len(args) < 3:
        return await message.answer("Usage: !setrank @user 1-5")
    
    mod_id = message.from_user.id
    
    if not message.reply_to_message:
        return await message.answer("Reply to a user message!")
    
    target = message.reply_to_message.from_user
    
    try:
        new_rank = int(args[2])
        if new_rank < 1 or new_rank > 5:
            return await message.answer("Rank must be 1-5")
    except ValueError:
        return await message.answer("Rank must be a number 1-5")
    
    if not has_perm(mod_id, "promote", new_rank):
        return await message.answer(f"You cannot set rank {new_rank}")
    
    if target.id in OWNER_IDS and mod_id not in OWNER_IDS:
        return await message.answer("Cannot change owner rank")
    
    user_ranks[target.id] = new_rank
    await message.answer(f"Set rank {new_rank} for {target.mention}")


@dp.message(Command("rank"))
async def rank_cmd(message: Message):
    target = message.reply_to_message.from_user if message.reply_to_message else message.from_user
    rank = get_rank(target.id)
    await message.answer(f"{target.mention} rank: {rank if rank > 0 else '0 (User)'}")


@dp.message(Command("clear"))
async def clear_cmd(message: Message):
    args = message.text.split()
    if len(args) < 2:
        return await message.answer("Usage: !clear 10")
    
    try:
        count = int(args[1])
        if count < 1 or count > 100:
            return await message.answer("Count must be 1-100")
    except ValueError:
        return await message.answer("Count must be a number")
    
    if not has_perm(message.from_user.id, "kick"):
        return await message.answer("No permission to delete messages")
    
    try:
        deleted = await message.chat.purge(limit=count + 1)
        msg = await message.answer(f"Deleted {len(deleted)-1} messages")
        await asyncio.sleep(3)
        await msg.delete()
    except Exception as e:
        await message.answer(f"Error: {e}")


# --- ЗАПУСК (ВАЖНО ДЛЯ RENDER.COM) ---
async def main():
    print("Bot started! Polling for updates...")
    await dp.start_polling(bot)
    if name == "main":
    asyncio.run(main())