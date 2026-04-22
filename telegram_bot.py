#!/usr/bin/env python3
"""
telegram_bot.py — Σοφία μέσω Telegram (pure urllib, χωρίς εξωτερικές βιβλιοθήκες)
Χρήση: python3 telegram_bot.py
"""

import sys
import json
import time
import threading
import os
import urllib.request
import urllib.error
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

from config import get_config, load_config, save_config
from secretary import run_turn
from contacts import list_contacts, add_contact, remove_contact, load_contacts
from context_manager import list_call_logs, save_call_log
from retell_tools import get_call_details

BASE = "https://api.telegram.org/bot{token}/{method}"

_histories: dict = {}

def _watch_call(token: str, chat_id: int, call_id: str, contact: str, retell_key: str, claude_cfg: dict):
    """Background thread: περιμένει να τελειώσει η κλήση και στέλνει αναφορά."""
    send(token, chat_id, f"📞 Κλήση σε εξέλιξη... Θα σου στείλω αναφορά μόλις τελειώσει.")
    max_wait = 600  # max 10 λεπτά
    waited = 0
    call_ended = False
    while waited < max_wait:
        time.sleep(15)
        waited += 15
        try:
            details = get_call_details(retell_key, call_id)
            status = details.get("status", "")
            if status in ("ended", "error"):
                call_ended = True
                break
        except Exception:
            pass

    # Αν η κλήση δεν τελείωσε μόνη της, κλείσ' την
    if not call_ended:
        try:
            from retell_tools import end_call as _end_call
            _end_call(retell_key, call_id)
        except Exception:
            pass

    # Φέρνουμε transcript και ζητάμε σύνοψη από Claude
    try:
        details = get_call_details(retell_key, call_id)
        transcript = details.get("transcript_preview", "")
        duration = details.get("duration", "—")
        phone = details.get("to_number", "—")

        if transcript and transcript != "—":
            # Σύνοψη μέσω Claude
            import urllib.request as _ur
            import json as _j
            payload = {
                "model": claude_cfg.get("model", "claude-haiku-4-5-20251001"),
                "max_tokens": 300,
                "messages": [{
                    "role": "user",
                    "content": (
                        f"Transcript κλήσης με {contact}:\n{transcript}\n\n"
                        "Γράψε σύντομη αναφορά στα ελληνικά (3-5 γραμμές): "
                        "τι συζητήθηκε, τι αποφασίστηκε, τι εκκρεμεί."
                    )
                }]
            }
            req = _ur.Request(
                "https://api.anthropic.com/v1/messages",
                data=_j.dumps(payload).encode(),
                headers={
                    "x-api-key": claude_cfg["anthropic_api_key"],
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                }
            )
            with _ur.urlopen(req, timeout=30) as r:
                resp = _j.loads(r.read().decode())
            summary = resp["content"][0]["text"]
        else:
            summary = "Δεν βρέθηκε transcript."

        report = (
            f"📋 <b>Αναφορά Κλήσης</b>\n"
            f"👤 <b>Επαφή:</b> {contact}\n"
            f"⏱ <b>Διάρκεια:</b> {duration}\n\n"
            f"{summary}"
        )
        save_call_log(contact=contact, phone=phone, summary=summary, call_id=call_id)
        send(token, chat_id, report)

    except Exception as e:
        send(token, chat_id, f"📋 Κλήση με {contact} τελείωσε. (Δεν ήταν δυνατή η αναφορά: {e})")

# ── Telegram API ──────────────────────────────────────────────────────────────

def tg(token: str, method: str, payload: dict = None) -> dict:
    url = BASE.format(token=token, method=method)
    data = json.dumps(payload or {}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": e.read().decode()}

def send(token: str, chat_id: int, text: str):
    if not text:
        text = "✓ Έγινε."
    for i in range(0, len(text), 4096):
        tg(token, "sendMessage", {
            "chat_id": chat_id,
            "text": text[i:i+4096],
            "parse_mode": "HTML",
        })

def send_typing(token: str, chat_id: int):
    tg(token, "sendChatAction", {"chat_id": chat_id, "action": "typing"})

# ── Message handling ──────────────────────────────────────────────────────────

def handle(token: str, allowed_id: str, chat_id: int, text: str, cfg: dict):
    if allowed_id and str(chat_id) != str(allowed_id):
        send(token, chat_id, "Δεν έχεις πρόσβαση.")
        return

    text = text.strip()

    # Local commands
    if text in ("/start", "/start@" + cfg.get("bot_username", "")):
        _histories[chat_id] = []
        send(token, chat_id,
            "Γεια σου Μάνο! Είμαι η <b>Σοφία</b>, η AI γραμματεία σου.\n\n"
            "• «κάλεσε τον Γιώργη»\n"
            "• «τι έχω σήμερα;»\n"
            "• «κατέγραψε — είπε να στείλει συμβόλαιο»\n\n"
            "/help για όλες τις εντολές."
        )
        return

    if text.startswith("/chatid"):
        send(token, chat_id, f"Chat ID: <code>{chat_id}</code>")
        return

    if text.startswith("/contacts"):
        send(token, chat_id, list_contacts())
        return

    if text.startswith("/logs"):
        send(token, chat_id, list_call_logs())
        return

    if text.startswith("/clear"):
        _histories[chat_id] = []
        send(token, chat_id, "✓ Ιστορικό καθαρίστηκε.")
        return

    if text.startswith("/help"):
        send(token, chat_id,
            "<b>ΕΝΤΟΛΕΣ:</b>\n"
            "/contacts — βιβλίο επαφών\n"
            "/logs — ιστορικό κλήσεων\n"
            "/clear — καθαρισμός ιστορικού\n"
            "/chatid — το chat ID σου\n\n"
            "<b>ΦΥΣΙΚΗ ΓΛΩΣΣΑ:</b>\n"
            "«κάλεσε τον Γιώργη»\n"
            "«τι έχω σήμερα;»\n"
            "«στείλε email στον X ότι...»\n"
            "«κατέγραψε — είπε ότι...»"
        )
        return

    # Enrichment με επαφές
    contacts = load_contacts()
    enriched = text
    for name, number in contacts.items():
        if name.lower() in text.lower():
            enriched = f"{text} [Σημείωση: '{name}' = {number}]"
            break

    send_typing(token, chat_id)

    if chat_id not in _histories:
        _histories[chat_id] = []

    # Συλλογή output (run_turn γράφει στο stdout)
    collected = []
    class Collector:
        def write(self, s): collected.append(s)
        def flush(self): pass

    import sys
    old_stdout = sys.stdout
    sys.stdout = Collector()
    try:
        _, _histories[chat_id] = run_turn(enriched, _histories[chat_id], cfg)
    finally:
        sys.stdout = old_stdout

    # Αν έγινε make_call, ξεκίνα background watcher
    for msg in reversed(_histories[chat_id]):
        if isinstance(msg.get("content"), list):
            for block in msg["content"]:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    try:
                        result = json.loads(block.get("content", "{}"))
                        call_id = result.get("call_id", "")
                        if call_id:
                            contact = result.get("to_number", "Άγνωστος")
                            # Βρες όνομα επαφής
                            for name, num in load_contacts().items():
                                if num == contact:
                                    contact = name
                                    break
                            threading.Thread(
                                target=_watch_call,
                                args=(token, chat_id, call_id, contact, cfg["retell_api_key"], cfg),
                                daemon=True
                            ).start()
                    except Exception:
                        pass
            break

    raw = "".join(collected).strip()

    # Κρατάμε μόνο γραμμές που δεν είναι tool output
    lines = [l for l in raw.splitlines()
             if not l.strip().startswith(("🔧", "✓ ", "✗ ", "Γραμματεία: ", "Σοφία: "))]
    reply = "\n".join(lines).strip()

    # Αν δεν υπάρχει κείμενο (μόνο tool calls εκτελέστηκαν), δες τελευταία γραμμή
    if not reply:
        all_lines = raw.splitlines()
        for l in reversed(all_lines):
            clean = l.strip().lstrip("✓ ✗ ")
            if clean:
                reply = clean
                break

    send(token, chat_id, reply or "✓ Έγινε.")

# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    if "--setup" in sys.argv:
        setup_telegram()
        return

    cfg = get_config()
    token = cfg.get("telegram_token")
    if not token:
        print("✗ Δεν υπάρχει token. Τρέξε: python3 telegram_bot.py --setup")
        return

    allowed = str(cfg.get("telegram_allowed_chat_id", ""))
    full_cfg = get_config()

    print(f"""
╔══════════════════════════════════════╗
║      ΣΟΦΙΑ — Telegram Bot            ║
╠══════════════════════════════════════╣
║  Κατάσταση: ΕΝΕΡΓΗ                   ║
║  Ασφάλεια: {("ID " + allowed) if allowed else "Ανοιχτή ⚠"}{"" + " " * (25 - len(("ID " + allowed) if allowed else "Ανοιχτή ⚠"))}║
║  Ctrl+C για τερματισμό               ║
╚══════════════════════════════════════╝
Αναμονή μηνυμάτων...
""")

    # Health check server για Render
    port = int(os.environ.get("PORT", 8080))
    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Sofia is running")
        def log_message(self, *args): pass
    health_server = HTTPServer(("0.0.0.0", port), HealthHandler)
    threading.Thread(target=health_server.serve_forever, daemon=True).start()
    print(f"Health check server on port {port}")

    offset = 0
    while True:
        try:
            result = tg(token, "getUpdates", {
                "offset": offset,
                "timeout": 30,
                "allowed_updates": ["message"],
            })
            if not result.get("ok"):
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Σφάλμα: {result}")
                time.sleep(5)
                continue

            for update in result.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                chat_id = msg.get("chat", {}).get("id")
                text = msg.get("text", "")
                if chat_id and text:
                    ts = datetime.now().strftime("%H:%M:%S")
                    print(f"[{ts}] {chat_id}: {text[:60]}")
                    try:
                        handle(token, allowed, chat_id, text, full_cfg)
                    except Exception as e:
                        print(f"  ✗ {e}")
                        send(token, chat_id, f"Σφάλμα: {e}")

        except KeyboardInterrupt:
            print("\nΑντίο!")
            break
        except Exception as e:
            print(f"Loop error: {e}")
            time.sleep(3)

def setup_telegram():
    cfg = load_config()
    print("\n╔══════════════════════════════════════════════════════╗")
    print("║         ΣΟΦΙΑ — Telegram Bot Setup                   ║")
    print("╚══════════════════════════════════════════════════════╝\n")
    print("1. Telegram → @BotFather → /newbot → αντέγραψε token\n")

    token = input("Telegram Bot Token: ").strip()
    if token:
        cfg["telegram_token"] = token

    chat_id = input("Chat ID (Enter για παράλειψη): ").strip()
    if chat_id:
        cfg["telegram_allowed_chat_id"] = chat_id

    save_config(cfg)
    print("\n✓ Έτοιμο! Τρέξε: python3 telegram_bot.py\n")

if __name__ == "__main__":
    main()
