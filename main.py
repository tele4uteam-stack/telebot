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
