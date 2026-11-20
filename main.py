# -*- coding: utf-8 -*-
"""
Tele4U Lite - نسخه Render
یوزربات تلگرام سازگار با Render Free Tier

تفاوت‌ها با نسخه محلی:
1. استفاده از StringSession (به‌جای فایل) - برای حل مشکل ephemeral disk
2. Flask keep-alive سرور برای جلوگیری از sleep
3. خواندن تنظیمات از environment variables
4. ذخیره session در environment variable (SESSION_STRING)
"""

import asyncio
import html
import logging
import os
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession
from telethon.tl.types import (
    ChannelParticipantsAdmins,
    ChatBannedRights,
    UserStatusOffline,
)
from telethon.tl.functions.channels import EditBannedRequest

# -------------------- تنظیمات از environment variables --------------------
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
SESSION_STRING = os.environ.get("SESSION_STRING", "")
BOT_OWNER_ID = int(os.environ.get("BOT_OWNER_ID", "0"))

# تنظیمات عملکرد
TAG_BATCH_SIZE = int(os.environ.get("TAG_BATCH_SIZE", "15"))
TAG_DELAY = int(os.environ.get("TAG_DELAY", "2"))
DELETE_BATCH_SIZE = int(os.environ.get("DELETE_BATCH_SIZE", "100"))
DELETE_DELAY = float(os.environ.get("DELETE_DELAY", "0.7"))
SPAMBOT_CHECK_DAYS = int(os.environ.get("SPAMBOT_CHECK_DAYS", "7"))
PORT = int(os.environ.get("PORT", "10000"))  # Render خودش PORT رو set می‌کنه

# -------------------- لاگ --------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("tele4u_render")

if not API_ID or not API_HASH:
    logger.error("❌ API_ID و API_HASH در environment variables تنظیم نشدن!")
    logger.error("   در Render: Settings → Environment → Add Variable")
    raise SystemExit(1)

if not SESSION_STRING:
    logger.error("❌ SESSION_STRING در environment variables تنظیم نشده!")
    logger.error("   اول session رو local بساز، بعد StringSession رو در Render بذار")
    raise SystemExit(1)

# ساخت کلاینت با StringSession
client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)


# ==================== Flask Keep-Alive سرور ====================
def start_keep_alive():
    """سرور Flask کوچک برای جلوگیری از sleep روی Render."""
    try:
        from flask import Flask
    except ImportError:
        logger.warning("⚠️ Flask نصب نیست؛ keep-alive فعال نمیشه.")
        return

    app = Flask(__name__)

    @app.route("/")
    def home():
        return "✅ Tele4U Lite is running!", 200

    @app.route("/ping")
    def ping():
        return "pong", 200

    @app.route("/health")
    def health():
        return {"status": "ok", "time": datetime.now().isoformat()}, 200

    def run():
        try:
            # Render پورت رو خودش تعیین می‌کنه
            app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)
        except Exception as exc:
            logger.exception("Flask سرور خطا داد: %s", exc)

    # اجرای Flask در thread جداگانه
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    logger.info("🌐 Keep-alive سرور روی پورت %s شروع شد", PORT)


# ==================== ابزارهای کمکی ====================
async def is_admin(event, user_id):
    try:
        me = await client.get_me()
        if user_id == me.id:
            return True
        admins = await client.get_participants(
            event.chat_id,
            filter=ChannelParticipantsAdmins,
        )
        return any(a.id == user_id for a in admins)
    except Exception:
        logger.exception("خطا در بررسی ادمین بودن")
        return False


def is_owner(event):
    return event.sender_id == BOT_OWNER_ID


async def check_command(event, owner_only=False):
    if not event.is_group:
        await event.reply("❌ این دستور فقط داخل گروه قابل استفاده است.")
        return False
    if owner_only and not is_owner(event):
        await event.reply("❌ این دستور فقط برای سازنده ربات مجاز است.")
        return False
    if not await is_admin(event, event.sender_id):
        await event.reply("❌ فقط ادمین‌های گروه و اکانت یوزربات مجازند.")
        return False
    return True


async def delete_in_batches(chat_id, message_ids, status_msg=None):
    deleted = 0
    ids = list(message_ids)
    for start in range(0, len(ids), DELETE_BATCH_SIZE):
        batch = ids[start:start + DELETE_BATCH_SIZE]
        while True:
            try:
                result = await client.delete_messages(chat_id, batch)
                deleted += len(batch) if result is not None else 0
                break
            except FloodWaitError as exc:
                if status_msg:
                    await status_msg.edit(f"⏳ محدودیت تلگرام؛ {exc.seconds} ثانیه صبر می‌کنم...")
                await asyncio.sleep(exc.seconds + 1)
            except Exception:
                logger.exception("حذف پیام‌ها ناموفق بود.")
                break
        await asyncio.sleep(DELETE_DELAY)
    return deleted


async def finish_status(status_msg, message, delay=5):
    try:
        await status_msg.edit(message)
        if delay:
            await asyncio.sleep(delay)
            await status_msg.delete()
    except Exception:
        logger.exception("به‌روزرسانی پیام وضعیت ناموفق بود.")


def is_spambot_suspicious(user):
    """تشخیص تبچی بودن کاربر بر اساس چند شرط ساده."""
    reasons = []

    if not getattr(user, "username", None):
        reasons.append("بدون یوزرنیم")

    if not getattr(user, "photo", None):
        reasons.append("بدون عکس پروفایل")

    first = (getattr(user, "first_name", None) or "").strip()
    if not first or first.lower() in ("telegram user", "tg user", "user"):
        reasons.append("نام دیفالت")

    status = getattr(user, "status", None)
    if isinstance(status, UserStatusOffline):
        try:
            was_online = status.was_online
            threshold = datetime.now() - timedelta(days=SPAMBOT_CHECK_DAYS)
            if was_online < threshold:
                reasons.append(f"آخرین آنلاین: {was_online:%Y-%m-%d}")
        except Exception:
            pass

    if getattr(user, "deleted", False):
        reasons.append("اکانت حذف‌شده")

    return reasons


# ==================== ۱. تگ اعضا ====================
@client.on(events.NewMessage(pattern=r"^!tagall$|^تگ همه$|^تگ اعضا$"))
async def tag_all(event):
    if not await check_command(event):
        return
    status = await event.reply("⏳ در حال دریافت اعضا...")
    try:
        mentions = []
        total = 0
        async for member in client.iter_participants(event.chat_id):
            total += 1
            if getattr(member, "bot", False):
                continue
            name = html.escape(member.first_name or "کاربر")
            if member.last_name:
                name += " " + html.escape(member.last_name)
            if member.username:
                mentions.append("@" + member.username)
            else:
                mentions.append(f'<a href="tg://user?id={member.id}">{name}</a>')

        if not mentions:
            await status.edit("❌ عضوی برای تگ کردن پیدا نشد.")
            return

        await status.edit(f"✅ {len(mentions)} عضو پیدا شد؛ ارسال تگ‌ها شروع شد...")
        batch = []
        current_length = 0
        sent = 0

        async def send_batch(items):
            nonlocal sent
            if not items:
                return
            message = "📢 " + " ".join(items)
            while True:
                try:
                    await client.send_message(event.chat_id, message, parse_mode="html")
                    sent += len(items)
                    break
                except FloodWaitError as exc:
                    await status.edit(f"⏳ محدودیت ارسال؛ {exc.seconds} ثانیه صبر می‌کنم...")
                    await asyncio.sleep(exc.seconds + 1)

        for mention in mentions:
            if batch and (len(batch) >= TAG_BATCH_SIZE or current_length + len(mention) + 1 > 3500):
                await send_batch(batch)
                batch = []
                current_length = 0
                await asyncio.sleep(TAG_DELAY)
                if sent % 60 == 0:
                    await status.edit(f"⏳ {sent} نفر تگ شدند...")
            batch.append(mention)
            current_length += len(mention) + 1

        if batch:
            await send_batch(batch)

        await finish_status(status, f"✅ عملیات پایان یافت. {sent} نفر تگ شدند.", 5)
    except Exception as exc:
        logger.exception("خطا در tagall")
        await status.edit(f"❌ عملیات تگ کامل نشد: {html.escape(str(exc))[:700]}")


# ==================== ۲. لیست اعضا ====================
@client.on(events.NewMessage(pattern=r"^!members$|^اعضا$|^لیست اعضا$"))
async def get_members(event):
    if not await check_command(event):
        return
    status = await event.reply("⏳ در حال دریافت لیست اعضا...")
    filename = None
    try:
        lines = []
        count = 0
        async for member in client.iter_participants(event.chat_id):
            count += 1
            username = f"@{member.username}" if member.username else "ندارد"
            first = member.first_name or ""
            last = member.last_name or ""
            full_name = " ".join(x for x in [first, last] if x) or "بدون نام"
            bot_flag = " 🤖" if getattr(member, "bot", False) else ""
            lines.append(f"آیدی: {member.id} | یوزرنیم: {username} | نام: {full_name}{bot_flag}")
            if count % 100 == 0:
                await status.edit(f"⏳ {count} نفر دریافت شدند...")

        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".txt", delete=False
        ) as f:
            filename = f.name
            f.write("\n".join(lines) if lines else "عضوی پیدا نشد.")

        await status.edit(f"✅ لیست {count} نفر آماده شد؛ در حال ارسال...")
        await client.send_file(
            event.chat_id,
            filename,
            caption=f"📋 لیست اعضا ({count} نفر)",
        )
        await status.delete()
    except Exception as exc:
        logger.exception("خطا در دریافت لیست اعضا")
        await status.edit(f"❌ خطا: {html.escape(str(exc))[:700]}")
    finally:
        if filename and os.path.exists(filename):
            os.remove(filename)


# ==================== ۳. پاکسازی پیام‌ها ====================
@client.on(events.NewMessage(pattern=r"^!purge$|^پاکسازی$"))
async def purge_messages(event):
    if not await check_command(event):
        return
    if not event.is_reply:
        await event.reply(
            "❌ روی آخرین پیامی که می‌خواهی پاک شود ریپلای کن و دستور !purge را بفرست."
        )
        return
    reply = await event.get_reply_message()
    status = await event.reply("⏳ در حال جمع‌آوری پیام‌ها...")
    try:
        ids = [m.id async for m in client.iter_messages(event.chat_id, min_id=reply.id - 1)]
        count = await delete_in_batches(event.chat_id, ids, status)
        await finish_status(status, f"✅ تعداد پیام‌های حذف‌شده: {count}")
    except Exception as exc:
        logger.exception("خطا در purge")
        await status.edit(f"❌ پاکسازی کامل نشد: {html.escape(str(exc))[:700]}")


@client.on(events.NewMessage(pattern=r"^!cleanall$|^پاکسازی کل$"))
async def clean_all(event):
    if not await check_command(event):
        return
    status = await event.reply("⏳ در حال جمع‌آوری پیام‌های گروه...")
    try:
        ids = [m.id async for m in client.iter_messages(event.chat_id)]
        count = await delete_in_batches(event.chat_id, ids, status)
        await finish_status(status, f"✅ تعداد پیام‌های حذف‌شده: {count}")
    except Exception as exc:
        logger.exception("خطا در cleanall")
        await status.edit(f"❌ پاکسازی کامل نشد: {html.escape(str(exc))[:700]}")


@client.on(events.NewMessage(pattern=r"^!cleanuser$|^پاکسازی کاربر$"))
async def clean_user(event):
    if not await check_command(event):
        return
    if not event.is_reply:
        await event.reply("❌ روی یکی از پیام‌های کاربر موردنظر ریپلای کن.")
        return
    replied = await event.get_reply_message()
    target = replied.sender_id
    if not target:
        await event.reply("❌ فرستنده پیام قابل تشخیص نیست.")
        return
    status = await event.reply("⏳ در حال پیدا کردن پیام‌های این کاربر...")
    try:
        ids = [m.id async for m in client.iter_messages(event.chat_id, from_user=target)]
        count = await delete_in_batches(event.chat_id, ids, status)
        await finish_status(status, f"✅ تعداد {count} پیام از کاربر حذف شد.")
    except Exception as exc:
        logger.exception("خطا در cleanuser")
        await status.edit(f"❌ پاکسازی کامل نشد: {html.escape(str(exc))[:700]}")


# ==================== ۴. حذف ربات‌ها ====================
@client.on(events.NewMessage(pattern=r"^!kickbots$|^حذف ربات ها$|^اخراج ربات ها$"))
async def kick_bots(event):
    if not await check_command(event):
        return
    chat = await event.get_input_chat()
    status = await event.reply("⏳ در حال شناسایی ربات‌های گروه...")
    bots = []
    total = 0
    try:
        async for member in client.iter_participants(event.chat_id):
            total += 1
            if getattr(member, "bot", False):
                bots.append(member)
            if total % 200 == 0:
                await status.edit(f"🔎 بررسی {total} عضو؛ {len(bots)} ربات پیدا شد...")
    except Exception as exc:
        logger.exception("دریافت اعضا ناموفق بود.")
        await status.edit(f"❌ دریافت اعضا ناموفق بود: {html.escape(str(exc))[:700]}")
        return

    if not bots:
        await finish_status(status, f"✅ هیچ رباتی پیدا نشد. اعضای بررسی‌شده: {total}", 3)
        return

    kicked = 0
    failed = 0
    for bot in bots:
        while True:
            try:
                await client(EditBannedRequest(
                    channel=chat,
                    participant=bot.id,
                    banned_rights=ChatBannedRights(
                        view_messages=True,
                        until_date=None,
                    ),
                ))
                kicked += 1
                break
            except FloodWaitError as exc:
                await status.edit(f"⏳ محدودیت تلگرام؛ {exc.seconds} ثانیه صبر می‌کنم...")
                await asyncio.sleep(exc.seconds + 1)
            except Exception as exc:
                failed += 1
                logger.warning("اخراج %s ناموفق بود: %s", bot.id, exc)
                break
        await asyncio.sleep(1)

    await finish_status(
        status,
        f"✅ عملیات پایان یافت.\n"
        f"👥 اعضای بررسی‌شده: {total}\n"
        f"🤖 ربات‌های پیدا‌شده: {len(bots)}\n"
        f"✅ اخراج‌شده: {kicked}\n"
        f"❌ ناموفق: {failed}",
        10,
    )


# ==================== ۵. شناسایی و حذف تبچی‌ها ====================
@client.on(events.NewMessage(pattern=r"^!scan$|^شناسایی تبچی$"))
async def scan_spambots(event):
    if not await check_command(event):
        return
    status = await event.reply("⏳ در حال اسکن اعضا برای تشخیص تبچی‌ها...")
    suspicious = []
    total = 0
    bots_count = 0
    try:
        async for member in client.iter_participants(event.chat_id):
            total += 1
            if getattr(member, "bot", False):
                bots_count += 1
                continue
            reasons = is_spambot_suspicious(member)
            if len(reasons) >= 3:
                first = member.first_name or "بدون نام"
                last = member.last_name or ""
                name = " ".join(x for x in [first, last] if x)
                username = f"@{member.username}" if member.username else "ندارد"
                suspicious.append({
                    "id": member.id,
                    "name": name,
                    "username": username,
                    "reasons": reasons,
                })
            if total % 200 == 0:
                await status.edit(f"🔎 بررسی {total} عضو؛ {len(suspicious)} مشکوک پیدا شد...")
    except Exception as exc:
        logger.exception("خطا در scan")
        await status.edit(f"❌ خطا: {html.escape(str(exc))[:700]}")
        return

    if not suspicious:
        await finish_status(status, f"✅ هیچ تبچی مشکوکی پیدا نشد.\nاعضای بررسی‌شده: {total}", 5)
        return

    report_lines = [
        f"🔍 گزارش اسکن تبچی‌ها",
        f"━━━━━━━━━━━━━━━━━━━━",
        f"👥 کل اعضای بررسی‌شده: {total}",
        f"🤖 ربات‌ها: {bots_count}",
        f"⚠️ مشکوک به تبچی: {len(suspicious)}",
        f"━━━━━━━━━━━━━━━━━━━━",
        "",
    ]
    for i, s in enumerate(suspicious[:50], 1):
        report_lines.append(
            f"{i}. {s['name']} ({s['username']})\n"
            f"   🆔 {s['id']}\n"
            f"   📝 دلایل: {', '.join(s['reasons'])}"
        )

    if len(suspicious) > 50:
        report_lines.append(f"\n... و {len(suspicious) - 50} نفر دیگر")

    report_lines.append("")
    report_lines.append("💡 برای حذف همه: `!kickspam`")

    await status.delete()
    text = "\n".join(report_lines)
    if len(text) > 4000:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".txt", delete=False
        ) as f:
            f.write(text)
            filename = f.name
        try:
            await client.send_file(
                event.chat_id,
                filename,
                caption=f"🔍 گزارش اسکن تبچی‌ها ({len(suspicious)} نفر مشکوک)",
            )
            os.remove(filename)
        except Exception as exc:
            await event.reply(f"❌ خطا در ارسال گزارش: {html.escape(str(exc))[:700]}")
    else:
        await event.reply(text, parse_mode="md")


@client.on(events.NewMessage(pattern=r"^!kickspam$|^حذف تبچی$|^پاکسازی تبچی$"))
async def kick_spambots(event):
    if not await check_command(event):
        return
    status = await event.reply("⏳ در حال اسکن و حذف تبچی‌ها...")
    chat = await event.get_input_chat()
    candidates = []
    total = 0
    bots_count = 0
    try:
        async for member in client.iter_participants(event.chat_id):
            total += 1
            if getattr(member, "bot", False):
                bots_count += 1
                continue
            try:
                admins = await client.get_participants(
                    event.chat_id, filter=ChannelParticipantsAdmins
                )
                admin_ids = {a.id for a in admins}
            except Exception:
                admin_ids = set()
            if member.id in admin_ids:
                continue
            reasons = is_spambot_suspicious(member)
            if len(reasons) >= 3:
                candidates.append(member)
            if total % 200 == 0:
                await status.edit(f"🔎 بررسی {total} عضو؛ {len(candidates)} تبچی پیدا شد...")
    except Exception as exc:
        logger.exception("خطا در kickspam")
        await status.edit(f"❌ خطا: {html.escape(str(exc))[:700]}")
        return

    if not candidates:
        await finish_status(status, f"✅ هیچ تبچی مشکوکی پیدا نشد.\nاعضای بررسی‌شده: {total}", 5)
        return

    kicked = 0
    failed = 0
    for member in candidates:
        try:
            await client(EditBannedRequest(
                channel=chat,
                participant=member.id,
                banned_rights=ChatBannedRights(
                    view_messages=True,
                    until_date=datetime.now() + timedelta(seconds=30),
                ),
            ))
            kicked += 1
        except FloodWaitError as exc:
            await status.edit(f"⏳ محدودیت تلگرام؛ {exc.seconds} ثانیه صبر می‌کنم...")
            await asyncio.sleep(exc.seconds + 1)
        except Exception as exc:
            failed += 1
            logger.warning("اخراج تبچی %s ناموفق بود: %s", member.id, exc)
        await asyncio.sleep(0.5)

    await finish_status(
        status,
        f"✅ عملیات حذف تبچی‌ها پایان یافت.\n"
        f"👥 اعضای بررسی‌شده: {total}\n"
        f"⚠️ مشکوک‌های پیدا‌شده: {len(candidates)}\n"
        f"✅ اخراج‌شده: {kicked}\n"
        f"❌ ناموفق: {failed}",
        10,
    )


# ==================== راهنما ====================
HELP_TEXT = """📋 **راهنمای Tele4U Lite**

━━━━━━━━━━━━━━━━━━━━
👥 **تگ اعضا**
━━━━━━━━━━━━━━━━━━━━
`!tagall` / `تگ همه` / `تگ اعضا` - تگ همه اعضای گروه

━━━━━━━━━━━━━━━━━━━━
📋 **لیست اعضا**
━━━━━━━━━━━━━━━━━━━━
`!members` / `اعضا` / `لیست اعضا` - دریافت لیست اعضا به‌صورت فایل

━━━━━━━━━━━━━━━━━━━━
🧹 **پاکسازی پیام‌ها**
━━━━━━━━━━━━━━━━━━━━
`!purge` / `پاکسازی` - حذف پیام‌ها از ریپلای به بعد
`!cleanall` / `پاکسازی کل` - پاک کردن همه پیام‌های گروه
`!cleanuser` / `پاکسازی کاربر` - پاک کردن پیام‌های یک کاربر

━━━━━━━━━━━━━━━━━━━━
🤖 **حذف ربات‌ها**
━━━━━━━━━━━━━━━━━━━━
`!kickbots` / `حذف ربات ها` - اخراج همه ربات‌های گروه

━━━━━━━━━━━━━━━━━━━━
⚠️ **شناسایی و حذف تبچی‌ها**
━━━━━━━━━━━━━━━━━━━━
`!scan` / `شناسایی تبچی` - اسکن اعضا و گزارش کاربران مشکوک
`!kickspam` / `حذف تبچی` - حذف خودکار تبچی‌های مشکوک

📌 **نکته:** دستورات فارسی و انگلیسی هر دو کار می‌کنن.
"""


@client.on(events.NewMessage(pattern=r"^!help$|^راهنما$"))
async def show_help(event):
    try:
        await event.reply(HELP_TEXT, parse_mode="md", link_preview=False)
    except Exception as exc:
        logger.exception("خطا در نمایش راهنما")
        await event.reply(f"❌ خطا: {html.escape(str(exc))[:400]}")


# ==================== اجرای برنامه ====================
async def main():
    # شروع keep-alive سرور
    start_keep_alive()

    # شروع کلاینت Telethon
    await client.start()
    me = await client.get_me()
    logger.info("✅ Tele4U Lite اجرا شد: %s (ID: %s)", me.first_name, me.id)
    logger.info("🌐 Keep-alive: http://0.0.0.0:%s", PORT)
    logger.info("🛑 برای توقف Ctrl+C را بزن.")
    await client.run_until_disconnected()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nربات متوقف شد.")
