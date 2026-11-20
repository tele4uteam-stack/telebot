# -*- coding: utf-8 -*-
"""
اسکریپت تولید SESSION_STRING برای Render (با پشتیبانی از پروکسی)

اگه داخل ایران هستی و خطای TimeoutError می‌گیری، باید از پروکسی استفاده کنی.
این اسکریپت از SOCKS5 و HTTP proxy پشتیبانی می‌کنه.

نحوه استفاده:
    pip install telethon python-socks PySocks
    python generate_session.py
"""

import asyncio
import sys


def get_input(prompt, required=True, default=None):
    while True:
        suffix = f" [{default}]" if default else ""
        value = input(f"{prompt}{suffix}: ").strip()
        if value:
            return value
        if default is not None:
            return default
        if not required:
            return ""
        print("❌ این فیلد اجباری است.")


def ask_proxy():
    """پرسش درباره استفاده از پروکسی."""
    print()
    print("=" * 60)
    print("🔌 تنظیمات پروکسی (برای کاربران داخل ایران)")
    print("=" * 60)
    print()
    print("اگه داخل ایران هستی و خطای TimeoutError می‌گیری،")
    print("باید از پروکسی استفاده کنی.")
    print()
    print("نوع پروکسی رو انتخاب کن:")
    print("  1) SOCKS5 (پیشنهادی - Clash, v2ray)")
    print("  2) HTTP/HTTPS proxy")
    print("  3) بدون پروکسی (اگه خارج از ایران هستی یا VPN کل سیستم روشنه)")
    print()
    choice = get_input("انتخاب (1/2/3)", default="1")

    if choice == "1":
        host = get_input("آدرس پروکسی SOCKS5 (مثلاً 127.0.0.1)", default="127.0.0.1")
        port = get_input("پورت پروکسی SOCKS5 (Clash: 7891, v2ray: 1080)", default="7891")
        username = get_input("یوزرنیم پروکسی (اگه نداری Enter بزن)", required=False)
        password = get_input("رمز پروکسی (اگه نداری Enter بزن)", required=False)
        return ("socks5", host, int(port), username or None, password or None)

    elif choice == "2":
        host = get_input("آدرس پروکسی HTTP (مثلاً 127.0.0.1)", default="127.0.0.1")
        port = get_input("پورت پروکسی HTTP (Clash: 7890, v2ray: 1087)", default="7890")
        return ("http", host, int(port), None, None)

    else:
        return None


async def main():
    try:
        from telethon.sessions import StringSession
        from telethon import TelegramClient
    except ImportError:
        print("❌ telethon نصب نیست. اول اجرا کن: pip install telethon")
        sys.exit(1)

    print("=" * 60)
    print("🔑 تولید SESSION_STRING برای Render")
    print("=" * 60)
    print()

    api_id = get_input("📝 API_ID")
    api_hash = get_input("📝 API_HASH")

    if not api_id.isdigit():
        print("❌ API_ID باید عدد صحیح باشه!")
        return

    api_id = int(api_id)

    print()
    print("📞 شماره موبایل رو با کد کشور وارد کن (مثل: +989121234567)")
    phone = get_input("📝 شماره موبایل")

    # پرسش درباره پروکسی
    proxy_config = ask_proxy()

    # ساخت کلاینت
    if proxy_config:
        ptype, host, port, user, pwd = proxy_config
        print()
        print(f"🔌 استفاده از پروکسی {ptype}://{host}:{port}")
        print("⏳ در حال اتصال به تلگرام از طریق پروکسی...")

        if ptype == "socks5":
            try:
                import python_socks  # noqa: F401
            except ImportError:
                try:
                    import socks  # noqa: F401  PySocks
                except ImportError:
                    print("❌ پکیج پروکسی نصب نیست. اجرا کن:")
                    print("   pip install python-socks PySocks")
                    return

            client = TelegramClient(
                StringSession(),
                api_id,
                api_hash,
                proxy=("socks5", host, port, True, user, pwd),
            )
        else:  # http
            client = TelegramClient(
                StringSession(),
                api_id,
                api_hash,
                proxy=("http", host, port, True, user, pwd),
            )
    else:
        print()
        print("⏳ در حال اتصال به تلگرام (بدون پروکسی)...")
        client = TelegramClient(StringSession(), api_id, api_hash)

    # اتصال با retry
    max_retries = 5
    connected = False
    for attempt in range(1, max_retries + 1):
        try:
            await asyncio.wait_for(client.connect(), timeout=30)
            if await client.is_user_authorized():
                connected = True
                break
            else:
                connected = True
                break
        except asyncio.TimeoutError:
            print(f"⏳ تلاش {attempt}/{max_retries} - timeout، دوباره...")
        except Exception as exc:
            print(f"❌ تلاش {attempt}/{max_retries} - خطا: {exc}")
        if attempt < max_retries:
            await asyncio.sleep(3)

    if not connected:
        print()
        print("❌ اتصال به تلگرام ناموفق بود.")
        print()
        print("🔍 راه‌حل‌ها:")
        print("   ۱. مطمئن شو پروکسی/VPN روشنه")
        print("   ۲. اگه از Clash استفاده می‌کنی، پورت SOCKS5 معمولاً 7891 هست")
        print("   ۳. اگه از v2ray استفاده می‌کنی، پورت SOCKS5 معمولاً 1080 هست")
        print("   ۴. مطمئن شو پروکسی تو حالت 'Global' یا 'Rule' هست")
        print("   ۵. می‌تونی VPN کل سیستم رو روشن کنی و گزینه ۳ (بدون پروکسی) رو انتخاب کنی")
        return

    print("✅ اتصال برقرار شد!")
    print()

    try:
        await client.send_code_request(phone)
        print("📨 کد تأیید به تلگرامت ارسال شد.")
        code = get_input("📝 کد تأیید رو وارد کن")

        try:
            await client.sign_in(phone, code)
        except Exception as exc:
            err_name = exc.__class__.__name__
            if "SessionPasswordNeeded" in err_name or "Two-steps" in str(exc):
                password = get_input("🔒 رمز دوم (2FA) رو وارد کن")
                await client.sign_in(password=password)
            else:
                raise

        session_string = client.session.save()
        print()
        print("=" * 60)
        print("✅ SESSION_STRING با موفقیت ساخته شد!")
        print("=" * 60)
        print()
        print("📋 این رشته رو کپی کن و در Render به‌عنوان SESSION_STRING ذخیره کن:")
        print()
        print(session_string)
        print()
        print("=" * 60)
        print()
        print("⚠️ هشدارهای امنیتی:")
        print("   • این رشته رو با هیچ‌کس به اشتراک نذار")
        print("   • این رشته دسترسی کامل به اکانت تلگرامت رو میده")
        print("   • در امن‌ترین مکان ذخیره کن")
        print()

        with open("session_string.txt", "w", encoding="utf-8") as f:
            f.write(session_string)
        print("💾 SESSION_STRING در فایل session_string.txt هم ذخیره شد.")
        print("   ⚠️ بعد از کپی، این فایل رو پاک کن!")
        print()

    except Exception as exc:
        print(f"❌ خطا: {exc}")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nمتوقف شد.")
    except Exception as exc:
        print(f"\n❌ خطای غیرمنتظره: {exc}")
