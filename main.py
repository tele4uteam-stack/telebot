# -*- coding: utf-8 -*-
"""
Tele4U Lite - نسخه Render (ساده‌شده)
یوزربات تلگرام سازگار با Render Free Tier

قابلیت‌ها:
  ۱. !tagall - تگ همه اعضای گروه (فقط از @Nitro_plusbot)
  ۲. !delall - پاکسازی همه پیام‌های گروه (فقط از @Nitro_plusbot)
  ۳. گزارش خودکار هر ۳۰ دقیقه به آیدی عددی 258913714
  ۴. پاسخ به کد 3357 با پیام "ربات آنلاینه"
  ۵. !startvch - شروع ویس چت گروه و پین اعلان آبی (فقط از @Nitro_plusbot)
  ۶. !delvch - پایان/حذف ویس چت گروه (فقط از @Nitro_plusbot)
  ۷. !deloff - اخراج اکانت‌های دلیت‌اکانت شده از گروه (فقط از @Nitro_plusbot)
"""

import asyncio
import html
import logging
import os
import random
import threading
from datetime import datetime, timedelta

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.messages import UpdatePinnedMessageRequest
from telethon.tl.functions.phone import (
    CreateGroupCallRequest,
    DiscardGroupCallRequest,
    JoinGroupCallRequest,
)
from telethon.tl.types import InputPeerSelf

# -------------------- تنظیمات از environment variables --------------------
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
SESSION_STRING = os.environ.get("SESSION_STRING", "")

# یوزرنیم رباتی که مجاز به ارسال دستوره (بدون @)
ALLOWED_BOT_USERNAME = os.environ.get("ALLOWED_BOT_USERNAME", "Nitro_plusbot")

# آیدی عددی گیرنده گزارش وضعیت
STATUS_REPORT_RECEIVER_ID = int(os.environ.get("STATUS_REPORT_RECEIVER_ID", "258913714"))

# فاصله گزارش وضعیت (دقیقه)
STATUS_REPORT_INTERVAL_MINUTES = int(os.environ.get("STATUS_REPORT_INTERVAL_MINUTES", "30"))

# کد تأیید برای چک آنلاین بودن
ONLINE_CHECK_CODE = os.environ.get("ONLINE_CHECK_CODE", "3357")

# تنظیمات عملکرد
TAG_BATCH_SIZE = int(os.environ.get("TAG_BATCH_SIZE", "15"))
TAG_DELAY = int(os.environ.get("TAG_DELAY", "2"))
DELETE_BATCH_SIZE = int(os.environ.get("DELETE_BATCH_SIZE", "100"))
DELETE_DELAY = float(os.environ.get("DELETE_DELAY", "0.7"))
PORT = int(os.environ.get("PORT", "10000"))

# زمان شروع ربات (برای محاسبه uptime)
START_TIME = datetime.now()

# -------------------- لاگ --------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("tele4u_lite")

if not API_ID or not API_HASH:
    logger.error("❌ API_ID و API_HASH در environment variables تنظیم نشدن!")
    raise SystemExit(1)

if not SESSION_STRING:
    logger.error("❌ SESSION_STRING در environment variables تنظیم نشده!")
    raise SystemExit(1)

# اعتبارسنجی SESSION_STRING
SESSION_STRING = SESSION_STRING.strip()
if not SESSION_STRING.startswith("1") or len(SESSION_STRING) < 100:
    logger.error("❌ SESSION_STRING معتبر نیست!")
    raise SystemExit(1)

logger.info("📋 SESSION_STRING: %d کاراکتر", len(SESSION_STRING))
logger.info("🤖 ربات مجاز دستور: @%s", ALLOWED_BOT_USERNAME)
logger.info("📨 گیرنده گزارش وضعیت: %s", STATUS_REPORT_RECEIVER_ID)
logger.info("⏱️ فاصله گزارش: هر %d دقیقه", STATUS_REPORT_INTERVAL_MINUTES)

# ساخت کلاینت با StringSession
try:
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
except ValueError as exc:
    logger.error("❌ ساخت StringSession ناموفق بود: %s", exc)
    raise SystemExit(1)


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
            app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)
        except Exception as exc:
            logger.exception("Flask سرور خطا داد: %s", exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    logger.info("🌐 Keep-alive سرور روی پورت %s شروع شد", PORT)


# ==================== ابزارهای کمکی ====================
async def is_allowed_sender(event):
    """
    بررسی اینکه فرستنده پیام ربات مجاز (@Nitro_plusbot) هست یا نه.
    """
    sender = await event.get_sender()
    if sender is None:
        return False

    sender_username = getattr(sender, "username", None)
    if sender_username and sender_username.lower() == ALLOWED_BOT_USERNAME.lower():
        return True

    if getattr(sender, "bot", False):
        try:
            allowed_entity = await client.get_entity(ALLOWED_BOT_USERNAME)
            if allowed_entity and getattr(allowed_entity, "id", None) == sender.id:
                return True
        except Exception:
            pass

    return False


async def check_command(event):
    """بررسی مشترک پیش از اجرای دستور."""
    if not event.is_group:
        return False
    if not await is_allowed_sender(event):
        logger.info("⛔ دستور از فرستنده غیرمجاز نادیده گرفته شد: %s", event.sender_id)
        return False
    return True


async def delete_in_batches(chat_id, message_ids, status_msg=None):
    """حذف دسته‌ای پیام‌ها با مدیریت FloodWait."""
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


def format_uptime():
    """محاسبه و قالب‌بندی زمان روشن بودن ربات."""
    delta = datetime.now() - START_TIME
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days} روز")
    if hours:
        parts.append(f"{hours} ساعت")
    if minutes:
        parts.append(f"{minutes} دقیقه")
    if not parts:
        parts.append(f"{seconds} ثانیه")
    return " ".join(parts)


# ==================== گزارش خودکار وضعیت ====================
async def status_reporter():
    """هر ۳۰ دقیقه یک بار وضعیت ربات رو به آیدی مشخص‌شده می‌فرسته."""
    # اولین گزارش رو بعد از ۲ دقیقه از شروع بفرست (برای اطمینان از اتصال)
    await asyncio.sleep(60)

    while True:
        try:
            uptime = format_uptime()
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            message = (
                "🤖 **گزارش وضعیت ربات**\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ ربات آنلاینه دوست من\n"
                f"⏱️ زمان روشن بودن: {uptime}\n"
                f"🕐 زمان فعلی: {now}\n"
                f"📡 دستورات فعال: `!tagall`, `!delall`, `!startvch`, `!delvch`, `!deloff`\n"
                f"🤖 ربات مجاز دستور: @{ALLOWED_BOT_USERNAME}\n"
                "━━━━━━━━━━━━━━━━━━━━"
            )
            await client.send_message(
                STATUS_REPORT_RECEIVER_ID,
                message,
                parse_mode="md",
            )
            logger.info("📤 گزارش وضعیت به %s ارسال شد", STATUS_REPORT_RECEIVER_ID)
        except FloodWaitError as exc:
            logger.warning("⏳ FloodWait در گزارش وضعیت: %d ثانیه", exc.seconds)
            await asyncio.sleep(exc.seconds + 1)
        except Exception as exc:
            logger.exception("خطا در ارسال گزارش وضعیت: %s", exc)

        # صبر تا گزارش بعدی
        await asyncio.sleep(STATUS_REPORT_INTERVAL_MINUTES * 60)


# ==================== پاسخ به کد 3357 ====================
@client.on(events.NewMessage(pattern=ONLINE_CHECK_CODE))
async def online_check(event):
    """وقتی کسی کد 3357 رو فرستاد، پاسخ می‌ده که ربات آنلاینه."""
    try:
        sender = await event.get_sender()
        sender_name = getattr(sender, "first_name", None) or "دوست"
        await event.reply(
            f"✅ ربات آنلاینه {sender_name} عزیز!\n"
            f"⏱️ زمان روشن بودن: {format_uptime()}\n"
            f"🕐 زمان: {datetime.now():%H:%M:%S}"
        )
        logger.info("📩 کد %s از %s دریافت شد، پاسخ آنلاین بودن ارسال شد",
                    ONLINE_CHECK_CODE, event.sender_id)
    except Exception as exc:
        logger.exception("خطا در پاسخ به کد آنلاین: %s", exc)


# ==================== ۱. تگ اعضا ====================
@client.on(events.NewMessage(pattern=r"^!tagall$"))
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


# ==================== ۲. پاکسازی همه پیام‌ها ====================
@client.on(events.NewMessage(pattern=r"^!delall$"))
async def delete_all(event):
    if not await check_command(event):
        return
    status = await event.reply("⏳ در حال جمع‌آوری پیام‌های گروه...")
    try:
        ids = [m.id async for m in client.iter_messages(event.chat_id)]
        count = await delete_in_batches(event.chat_id, ids, status)
        await finish_status(status, f"✅ تعداد پیام‌های حذف‌شده: {count}")
    except Exception as exc:
        logger.exception("خطا در delall")
        await status.edit(f"❌ پاکسازی کامل نشد: {html.escape(str(exc))[:700]}")


# ==================== ۳. شروع ویس چت ====================
@client.on(events.NewMessage(pattern=r"^!startvch$"))
async def start_voice_chat(event):
    """شروع ویس چت گروه و پین کردن اعلان آبی تولیدشده توسط تلگرام."""
    if not await check_command(event):
        return
    status = await event.reply("⏳ در حال شروع ویس چت...")

    try:
        chat = await event.get_input_chat()

        # --- بررسی اینکه قبلاً ویس چت فعالی هست یا نه ---
        try:
            full = await client(GetFullChannelRequest(chat))
            call = getattr(full.full_chat, "call", None)
            if call is not None:
                await status.edit("⚠️ ویس چت از قبل فعاله. برای حذف `!delvch` رو بفرست.")
                logger.info("🎤 ویس چت از قبل فعال بود (chat=%s)", event.chat_id)
                return
        except Exception as exc:
            logger.warning("بررسی وضعیت ویس چت ناموفق بود: %s", exc)

        # --- ساخت ویس چت ---
        # random_id باید یک عدد int باشه (طبق مستندات TL)
        rand_id = random.randint(0, 0x7FFFFFFF)
        try:
            await client(CreateGroupCallRequest(
                peer=chat,
                random_id=rand_id,
            ))
        except FloodWaitError as exc:
            await status.edit(f"⏳ محدودیت تلگرام؛ {exc.seconds} ثانیه صبر...")
            await asyncio.sleep(exc.seconds + 1)
            await client(CreateGroupCallRequest(
                peer=chat,
                random_id=random.randint(0, 0x7FFFFFFF),
            ))

        await status.edit("✅ ویس چت ساخته شد؛ در حال عضویت ربات...")
        logger.info("🎤 ویس چت ساخته شد (chat=%s)", event.chat_id)

        # --- ربات خودش join ویس چت می‌شه تا اعلان آبی واقعاً ساخته بشه ---
        # تلگرام فقط وقتی کسی join بشه اعلان آبی رو نمایش می‌ده
        try:
            full = await client(GetFullChannelRequest(chat))
            call = getattr(full.full_chat, "call", None)
        except Exception as exc:
            logger.warning("گرفتن اطلاعات call بعد از ساخت ناموفق بود: %s", exc)
            call = None

        if call is not None:
            try:
                # پارامتر params اختیاریه؛ با muted=True ربات می‌شه عضو صامت
                await client(JoinGroupCallRequest(
                    call=call,
                    join_as=InputPeerSelf(),
                    muted=True,
                    video_stopped=True,
                ))
                logger.info("🎧 ربات به ویس چت join شد (muted)")
                await asyncio.sleep(2)
            except FloodWaitError as exc:
                logger.warning("⏳ FloodWait در join ویس چت: %d ثانیه", exc.seconds)
                await asyncio.sleep(exc.seconds + 1)
            except Exception as exc:
                logger.warning("join ویس چت ناموفق بود: %s", exc)
        else:
            logger.warning("call بعد از ساخت پیدا نشد؛ اعلان آبی ممکنه ساخته نشه")

        # --- پیدا کردن اعلان آبی (service message) و پین کردنش ---
        pinned = False
        # پیام‌های اخیر رو از جدید به قدیم می‌گردیم
        async for msg in client.iter_messages(event.chat_id, limit=10):
            if not msg:
                continue
            # اعلان آبی پیام service است (action داره) و معمولاً در زمان ساخت call ساخته می‌شه
            action = getattr(msg, "action", None)
            if action is None:
                continue
            action_type = type(action).__name__
            if action_type in ("MessageActionGroupCall", "MessageActionInviteToGroupCall", "MessageActionGroupCallScheduled"):
                try:
                    await client(UpdatePinnedMessageRequest(
                        peer=chat,
                        id=msg.id,
                        silent=True,
                    ))
                    pinned = True
                    logger.info("📌 اعلان ویس چت پین شد (msg_id=%s, type=%s)",
                                msg.id, action_type)
                    break
                except FloodWaitError as exc:
                    await status.edit(f"⏳ محدودیت پین؛ {exc.seconds} ثانیه صبر...")
                    await asyncio.sleep(exc.seconds + 1)
                    await client(UpdatePinnedMessageRequest(
                        peer=chat,
                        id=msg.id,
                        silent=True,
                    ))
                    pinned = True
                    logger.info("📌 اعلان ویس چت بعد از FloodWait پین شد (msg_id=%s)", msg.id)
                    break
                except Exception as exc:
                    logger.exception("پین اعلان ناموفق بود: %s", exc)
                    break

        if pinned:
            await finish_status(status, "✅ ویس چت شروع شد و اعلان آبی پین شد. 🎤", 5)
        else:
            await finish_status(status, "✅ ویس چت شروع شد (اعلان آبی پیدا نشد تا پین شه).", 5)

    except Exception as exc:
        logger.exception("خطا در startvch")
        await status.edit(f"❌ شروع ویس چت ناموفق بود: {html.escape(str(exc))[:700]}")


# ==================== ۴. حذف ویس چت ====================
@client.on(events.NewMessage(pattern=r"^!delvch$"))
async def delete_voice_chat(event):
    """پایان/حذف ویس چت فعال گروه."""
    if not await check_command(event):
        return
    status = await event.reply("⏳ در حال بررسی ویس چت فعال...")

    try:
        chat = await event.get_input_chat()

        # --- گرفتن آیدی ویس چت فعال از اطلاعات کانال ---
        try:
            full = await client(GetFullChannelRequest(chat))
            call = getattr(full.full_chat, "call", None)
        except Exception as exc:
            logger.exception("گرفتن اطلاعات کانال ناموفق بود: %s", exc)
            await status.edit(f"❌ گرفتن اطلاعات گروه ناموفق بود: {html.escape(str(exc))[:500]}")
            return

        if call is None:
            await status.edit("ℹ️ هیچ ویس چت فعالی وجود نداره.")
            logger.info("🎤 ویس چت فعالی وجود نداشت (chat=%s)", event.chat_id)
            return

        # --- حذف ویس چت ---
        try:
            await client(DiscardGroupCallRequest(call=call))
        except FloodWaitError as exc:
            await status.edit(f"⏳ محدودیت تلگرام؛ {exc.seconds} ثانیه صبر...")
            await asyncio.sleep(exc.seconds + 1)
            await client(DiscardGroupCallRequest(call=call))

        logger.info("🎤 ویس چت حذف شد (chat=%s)", event.chat_id)
        await finish_status(status, "✅ ویس چت پایان یافت. 🎤", 5)

    except Exception as exc:
        logger.exception("خطا در delvch")
        await status.edit(f"❌ حذف ویس چت ناموفق بود: {html.escape(str(exc))[:700]}")


# ==================== ۵. اخراج اکانت‌های دلیت‌اکانت شده ====================
@client.on(events.NewMessage(pattern=r"^!deloff$"))
async def kick_deleted_accounts(event):
    """پیدا و اخراج همه اکانت‌های دلیت‌اکانت شده (Deleted Account) از گروه."""
    if not await check_command(event):
        return
    status = await event.reply("⏳ در حال بررسی اعضای گروه برای پیدا کردن اکانت‌های حذف‌شده...")

    try:
        chat = await event.get_input_chat()

        # --- پیدا کردن اکانت‌های دلیت‌اکانت شده ---
        deleted_users = []
        total = 0
        async for member in client.iter_participants(event.chat_id):
            total += 1
            # اکانت‌های دلیت‌اکانت شده معمولاً first_name خالی، last_name خالی،
            # username خالی و deleted=True دارن
            first = getattr(member, "first_name", None)
            last = getattr(member, "last_name", None)
            username = getattr(member, "username", None)
            is_deleted = getattr(member, "deleted", False)

            if is_deleted or (not first and not last and not username):
                deleted_users.append(member)

        if not deleted_users:
            await finish_status(status, "✅ هیچ اکانت دلیت‌اکانت‌شده‌ای پیدا نشد.", 5)
            logger.info("🧹 هیچ اکانت حذف‌شده‌ای پیدا نشد (chat=%s, total=%d)",
                        event.chat_id, total)
            return

        await status.edit(f"🔍 {len(deleted_users)} اکانت حذف‌شده پیدا شد؛ در حال اخراج...")

        # --- اخراج اکانت‌ها ---
        # از متد سطح بالای client.kick_participant() استفاده می‌کنیم
        # این متد خودش نوع گروه (عادی یا سوپرگروه) رو تشخیص می‌ده و روش مناسب رو
        # به‌کار می‌بره: برای گروه عادی از DeleteChatUserRequest و برای سوپرگروه
        # از EditBannedRequest استفاده می‌کنه. در همه نسخه‌های Telethon پایداره.

        kicked = 0
        failed = 0
        first_error = None  # اولین خطا رو نگه می‌داریم تا به کاربر نشون بدیم
        # آیدی خود ربات رو یک بار می‌گیریم
        try:
            me = await client.get_me()
            my_id = me.id
        except Exception:
            my_id = None

        for user in deleted_users:
            # ادمین‌ها رو اخراج نکن
            if getattr(user, "admin_rights", None) is not None:
                continue
            # خود ربات رو اخراج نکن
            if my_id is not None and user.id == my_id:
                continue

            while True:
                try:
                    # kick_participant خودش conversion و نوع گروه رو هندل می‌کنه
                    await client.kick_participant(chat, user.id)
                    kicked += 1
                    logger.info("🚪 کاربر %s اخراج شد", user.id)
                    break
                except FloodWaitError as exc:
                    await status.edit(f"⏳ محدودیت تلگرام؛ {exc.seconds} ثانیه صبر... (اخراج‌شده: {kicked})")
                    await asyncio.sleep(exc.seconds + 1)
                except Exception as exc:
                    err_str = str(exc)
                    err_type = type(exc).__name__
                    # اولین خطا رو ذخیره کن
                    if first_error is None:
                        first_error = f"{err_type}: {err_str}"
                    # اگه کاربر از قبل اخراج شده یا نیست، خطا رو رد کن
                    if "USER_NOT_PARTICIPANT" in err_str or "CHAT_ADMIN_REQUIRED" in err_str:
                        logger.warning("کاربر %s قبلاً اخراج شده یا دسترسی کافی نیست: %s",
                                       user.id, exc)
                        failed += 1
                    else:
                        logger.warning("اخراج کاربر %s ناموفق بود: %s", user.id, exc)
                        failed += 1
                    break

            # نوتیفیکیشن وضعیت هر ۱۰ اخراج
            if kicked % 10 == 0 and kicked > 0:
                await status.edit(f"⏳ در حال اخراج... ({kicked}/{len(deleted_users)})")
            await asyncio.sleep(0.5)

        msg = (
            f"✅ عملیات اخراج اکانت‌های حذف‌شده پایان یافت.\n"
            f"👥 کل اعضای بررسی‌شده: {total}\n"
            f"🚪 اخراج‌شده: {kicked}\n"
        )
        if failed:
            msg += f"⚠️ ناموفق: {failed}\n"
            if first_error:
                # خطای دقیق اولین مورد ناموفق رو هم نشون بده
                msg += f"🔍 علت اولین خطا: {html.escape(first_error)[:300]}\n"
        await finish_status(status, msg, 10)
        logger.info("🧹 اخراج اکانت‌های حذف‌شده: total=%d, kicked=%d, failed=%d (chat=%s)",
                    total, kicked, failed, event.chat_id)

    except Exception as exc:
        logger.exception("خطا در deloff")
        await status.edit(f"❌ اخراج اکانت‌های حذف‌شده ناموفق بود: {html.escape(str(exc))[:700]}")


# ==================== اجرای برنامه ====================
async def main():
    start_keep_alive()
    await client.start()
    me = await client.get_me()
    logger.info("✅ Tele4U Lite اجرا شد: %s (ID: %s)", me.first_name, me.id)
    logger.info("🤖 فقط دستورات از @%s اجرا می‌شه", ALLOWED_BOT_USERNAME)
    logger.info("📡 دستورات فعال: !tagall, !delall, !startvch, !delvch, !deloff")
    logger.info("📨 گزارش وضعیت هر %d دقیقه به آیدی %s",
                STATUS_REPORT_INTERVAL_MINUTES, STATUS_REPORT_RECEIVER_ID)
    logger.info("🔑 کد آنلاین: %s", ONLINE_CHECK_CODE)

    # شروع تسک گزارش خودکار در پس‌زمینه
    asyncio.create_task(status_reporter())

    await client.run_until_disconnected()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nربات متوقف شد.")
