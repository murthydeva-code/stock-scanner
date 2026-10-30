#!/usr/bin/env python3
"""
Telegram alert module — sends scan results to user's Telegram via Bot API.
"""

import os
import sys
import json
import urllib.request
import urllib.parse
import urllib.error

# Ensure UTF-8 console output on Windows platforms
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)


def _load_env():
    """Load TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from .env or home config."""
    candidate_files = [
        os.path.join(os.getcwd(), ".env"),
        os.path.join(REPO_ROOT, ".env"),
        os.path.expanduser("~/.trading_bot.env"),
        os.path.expanduser("~/.env"),
    ]
    for env_file in candidate_files:
        try:
            if os.path.isfile(env_file):
                with open(env_file, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("#") or "=" not in line:
                            continue
                        key, _, val = line.partition("=")
                        key = key.strip()
                        val = val.strip().strip('"').strip("'")
                        if key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
                            if not os.environ.get(key) and val:
                                os.environ[key] = val
        except Exception:
            continue


_load_env()
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def get_credentials():
    """Returns (bot_token, chat_id), reloading environment if missing."""
    global BOT_TOKEN, CHAT_ID
    if not BOT_TOKEN or not CHAT_ID:
        _load_env()
        BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
        CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
    return BOT_TOKEN, CHAT_ID


def bot_request(method, params=None):
    token, _ = get_credentials()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set.")
    url = f"https://api.telegram.org/bot{token}/{method}"
    if params:
        data = urllib.parse.urlencode(params).encode('utf-8')
    else:
        data = None
    req = urllib.request.Request(url, data=data, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode('utf-8', errors='ignore')
        raise RuntimeError(f"Telegram API error {e.code}: {err_body}")
    except Exception as e:
        raise RuntimeError(f"Telegram API request failed: {e}")


def send_alert(message, parse_mode="Markdown"):
    token, chat_id = get_credentials()
    if not chat_id:
        raise RuntimeError("TELEGRAM_CHAT_ID not set.")

    params = {
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": "true",
    }
    if parse_mode:
        params["parse_mode"] = parse_mode

    try:
        result = bot_request("sendMessage", params)
        return bool(result.get("ok"))
    except RuntimeError as e:
        # If Markdown entity parsing failed, retry as plain text (no parse_mode)
        if parse_mode:
            try:
                fallback_params = {
                    "chat_id": chat_id,
                    "text": message,
                    "disable_web_page_preview": "true",
                }
                result = bot_request("sendMessage", fallback_params)
                return bool(result.get("ok"))
            except Exception as e2:
                print(f"  ! Telegram fallback send failed: {e2}", file=sys.stderr)
        print(f"  ! Telegram send failed: {e}", file=sys.stderr)
        return False


def send_document(file_path, caption=""):
    token, chat_id = get_credentials()
    if not chat_id or not token:
        raise RuntimeError("Telegram credentials not set.")
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    boundary = "----TradingBotBoundary" + str(hash(file_path))
    with open(file_path, 'rb') as f:
        file_data = f.read()
    filename = os.path.basename(file_path)

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="chat_id"\r\n\r\n'
        f"{chat_id}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="caption"\r\n\r\n'
        f"{caption}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'
        f"Content-Type: application/pdf\r\n\r\n"
    ).encode('utf-8') + file_data + f"\r\n--{boundary}--\r\n".encode('utf-8')

    url = f"https://api.telegram.org/bot{token}/sendDocument"
    req = urllib.request.Request(url, data=body, method='POST')
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode('utf-8')).get("ok", False)
    except Exception as e:
        print(f"  ! Telegram file send failed: {e}", file=sys.stderr)
        return False


def format_scan_summary(scan_data, max_winners=3, max_near_miss=5):
    scan_date = scan_data.get("scan_date", "today")
    total_scanned = scan_data.get("total_scanned", 0)
    total_passing = scan_data.get("total_passing", 0)
    total_near_miss = scan_data.get("total_near_miss", 0)
    fetch_fail = scan_data.get("total_fetch_failed", 0)
    qualifying = scan_data.get("qualifying", [])
    near_miss = scan_data.get("near_miss", [])

    lines = [
        f"*📊 DAILY SCAN REPORT*",
        f"*{scan_date}* · Midcap 100 + Smallcap 250",
        f"",
        f"Scanned: *{total_scanned}* stocks",
        f"✅ 7/7 PASS: *{total_passing}*",
        f"⚠ 6/7 near-miss: *{total_near_miss}*",
        f"❌ fetch failed: *{fetch_fail}*",
        f"",
        f"━━━━━━━━━━━━━━━━━━",
    ]

    if qualifying:
        lines.append(f"")
        lines.append(f"*🏆 TODAY'S QUALIFYING STOCKS*")
        lines.append(f"_(all 7 rules pass — Mansfield RS shown)_")
        for r in qualifying[:max_winners]:
            sym = r.get("symbol", "?")
            price = r.get("last_price") or 0.0
            rsi = r.get("rsi_d") or 0.0
            ema30w = r.get("ema30_w") or 0.0
            ema60m = r.get("ema60_m") or 0.0
            mrs = r.get("mansfield_rs") or 0.0
            lines.append(f"")
            lines.append(f"*{sym}* Rs {price:,.2f}")
            lines.append(f"  RSI: {rsi:.1f}")
            lines.append(f"  30EMA(W): Rs {ema30w:,.2f}")
            lines.append(f"  60EMA(M): Rs {ema60m:,.2f}")
            lines.append(f"  Mansfield RS: {mrs:+.2f}")
            lines.append(f"  ✅ all 7 rules pass")
    else:
        lines.append(f"")
        lines.append(f"_No stocks pass all 7 rules today._")
        lines.append(f"_Strategy is selective — wait for cleaner setup._")

    if near_miss:
        lines.append(f"")
        lines.append(f"━━━━━━━━━━━━━━━━━━")
        lines.append(f"")
        lines.append(f"*⚠ NEAR-MISS WATCHLIST* (6/7 rules)")
        for r in near_miss[:max_near_miss]:
            sym = r.get("symbol", "?")
            price = r.get("last_price") or 0.0
            rsi = r.get("rsi_d") or 0.0
            mrs = r.get("mansfield_rs") or 0.0
            rules = r.get("rules") or {}
            failed = [k.replace("rule", "").split("_", 1)[0]
                      for k, v in rules.items() if not v]
            fail_str = ",".join(failed) if failed else "?"
            lines.append(f"• *{sym}* Rs {price:,.2f} · RSI {rsi:.1f} · MRS {mrs:+.2f} · R{fail_str} fail")

    lines.append(f"")
    lines.append(f"━━━━━━━━━━━━━━━━━━")
    lines.append(f"")
    lines.append(f"_Strategy: 7-rule Weinstein momentum (Mansfield RS + Stage 2 EMA)_")
    lines.append(f"_Verify on TradingView before deploying capital_")

    return "\n".join(lines)


def send_scan_summary(scan_data, pdf_path=None):
    msg = format_scan_summary(scan_data)
    if len(msg) > 4090:
        msg = msg[:4090] + "..."

    success = send_alert(msg)
    if not success:
        return False

    if pdf_path and os.path.isfile(pdf_path):
        send_document(pdf_path, caption=f"📊 Full watchlist PDF — {scan_data.get('scan_date', 'today')}")

    return True


def send_error_alert(title, error_details):
    """Send an operational error alert to Telegram if a scan fails."""
    lines = [
        f"⚠️ *STOCK SCANNER ERROR*",
        f"*{title}*",
        f"",
        f"Details:",
        f"```{str(error_details)[:3000]}```",
        f"",
        f"_Please check GitHub Actions or system logs._",
    ]
    return send_alert("\n".join(lines))


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 telegram_alert.py \"your message\"")
        print("Or:    python3 telegram_alert.py --status")
        print("Or:    python3 telegram_alert.py --test")
        sys.exit(1)

    token, chat_id = get_credentials()

    if sys.argv[1] == "--status":
        print(f"TELEGRAM_BOT_TOKEN: {'[OK] set' if token else '[X] missing'}")
        print(f"TELEGRAM_CHAT_ID:    {'[OK] set' if chat_id else '[X] missing'}")
        if token and chat_id:
            try:
                me = bot_request("getMe")
                if me.get("ok"):
                    bot = me["result"]
                    print(f"Bot: @{bot.get('username')} ({bot.get('first_name')})")
                    print(f"-> Ready to send alerts to chat_id {chat_id}")
                else:
                    print(f"[X] Bot token invalid: {me}")
            except Exception as e:
                print(f"[X] Bot token check failed: {e}")
        else:
            print("\nPlease ensure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set in .env or environment.")
        return

    if sys.argv[1] == "--test":
        msg = (
            "*🤖 Trading Bot Test Alert*\n\n"
            "If you're seeing this, your Telegram integration is working!\n\n"
            "Your scanner will send you daily alerts after each market scan.\n\n"
            "_— Multi-Timeframe Momentum Scanner_"
        )
        if send_alert(msg):
            print("[OK] Test alert sent successfully!")
        else:
            print("[X] Test alert failed. Check credentials.")
        return

    msg = " ".join(sys.argv[1:])
    if send_alert(msg):
        print(f"[OK] Alert sent: {msg[:60]}{'...' if len(msg) > 60 else ''}")
    else:
        print("[X] Alert failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
