#!/usr/bin/env python3
"""
secretary.py — AI Γραμματεία με Retell API
Χρήση:
  python3 secretary.py           # Κανονική λειτουργία
  python3 secretary.py --setup   # Αρχική ρύθμιση keys
  python3 secretary.py --contacts # Διαχείριση επαφών
"""

import sys
import json
import urllib.request
import urllib.error
from datetime import datetime

from config import get_config, setup_wizard
from retell_tools import (
    make_call, end_call, list_active_calls,
    list_recent_calls, get_call_details, list_agents, update_agent,
    TOOL_DEFINITIONS,
)
from contacts import resolve_number, add_contact, remove_contact, list_contacts, load_contacts
from context_manager import build_context, save_call_log, save_contact_note, list_call_logs
from google_tools import (
    get_calendar_events, send_email, setup_google,
    GOOGLE_TOOL_DEFINITIONS,
)

ANTHROPIC_API = "https://api.anthropic.com/v1/messages"

SYSTEM_PROMPT_BASE = """Είσαι η Σοφία, η προσωπική AI γραμματεία του Μάνου Κοντάκη. Λειτουργείς μέσω Retell AI για τηλεφωνικές κλήσεις.

ΙΚΑΝΟΤΗΤΕΣ:
- Εκτέλεση outbound κλήσεων (make_call)
- Τερματισμός ενεργών κλήσεων (end_call)
- Εμφάνιση ενεργών κλήσεων (list_active_calls)
- Ιστορικό κλήσεων (list_recent_calls)
- Λεπτομέρειες & transcript κλήσης (get_call_details)
- Λίστα διαθέσιμων agents (list_agents)
- Καταγραφή κλήσης στη μνήμη (log_call)
- Σημείωση για επαφή (note_contact)
- Έλεγχος ημερολογίου (get_calendar_events)
- Αποστολή email follow-up (send_email)

ΚΑΝΟΝΕΣ:
1. Εκτελείς κλήσεις ΑΜΕΣΑ χωρίς επιπλέον ερωτήσεις αν έχεις αριθμό και agent.
2. Αν λείπει ο αριθμός, ζήτα μόνο αυτόν.
3. Χρησιμοποιείς ΠΑΝΤΑ το default_agent_id αν δεν ορίσει ο χρήστης άλλον.
4. Απαντάς στα Ελληνικά, σύντομα και ουσιαστικά.
5. Μετά από κάθε tool call, αναφέρεις αποτέλεσμα ξεκάθαρα.
6. Αν αναφερθεί όνομα αντί αριθμού, ο αριθμός έχει ήδη αναζητηθεί στο βιβλίο επαφών.
7. Μετά από κλήση, αν ο χρήστης πει "κατέγραψε" ή "σημείωσε", χρησιμοποίησε log_call.
8. Αν σε ρωτήσουν "τι έχω σήμερα" ή "είμαι ελεύθερος", χρησιμοποίησε get_calendar_events.
9. Μετά κλήση, αν ταιριάζει, ΠΡΟΤΕΙΝΕ (μόνο) να στείλεις follow-up email — εκτέλεσε μόνο αν συμφωνήσει.
10. Χρησιμοποιείς το context παρακάτω για να θυμάσαι προηγούμενες κλήσεις και επαφές.
"""

def build_system_prompt() -> str:
    context = build_context()
    if context:
        return SYSTEM_PROMPT_BASE + "\n\n" + context
    return SYSTEM_PROMPT_BASE

def claude_stream(messages: list, cfg: dict) -> tuple:
    """Streaming request: prints text tokens in real-time, returns (content_list, stop_reason)."""
    payload = {
        "model": cfg.get("model", "claude-haiku-4-5-20251001"),
        "max_tokens": cfg.get("max_tokens", 1024),
        "system": build_system_prompt(),
        "tools": TOOL_DEFINITIONS + GOOGLE_TOOL_DEFINITIONS,
        "messages": messages,
        "stream": True,
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        ANTHROPIC_API,
        data=data,
        method="POST",
        headers={
            "x-api-key": cfg["anthropic_api_key"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    try:
        blocks = {}
        stop_reason = None
        with urllib.request.urlopen(req, timeout=60) as resp:
            for raw_line in resp:
                line = raw_line.decode().rstrip("\r\n")
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                event = json.loads(data_str)
                etype = event.get("type", "")
                if etype == "content_block_start":
                    idx = event["index"]
                    blocks[idx] = dict(event["content_block"])
                elif etype == "content_block_delta":
                    idx = event["index"]
                    delta = event["delta"]
                    if delta["type"] == "text_delta":
                        chunk = delta["text"]
                        blocks[idx]["text"] = blocks[idx].get("text", "") + chunk
                        print(chunk, end="", flush=True)
                    elif delta["type"] == "input_json_delta":
                        blocks[idx]["_raw"] = blocks[idx].get("_raw", "") + delta["partial_json"]
                elif etype == "content_block_stop":
                    idx = event["index"]
                    if blocks.get(idx, {}).get("type") == "tool_use" and "_raw" in blocks[idx]:
                        try:
                            blocks[idx]["input"] = json.loads(blocks[idx]["_raw"])
                        except json.JSONDecodeError:
                            blocks[idx]["input"] = {}
                        del blocks[idx]["_raw"]
                elif etype == "message_delta":
                    stop_reason = event.get("delta", {}).get("stop_reason")
        content = [blocks[i] for i in sorted(blocks)]
        return content, stop_reason
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            err = json.loads(body)
            raise RuntimeError(err.get("error", {}).get("message") or body)
        except json.JSONDecodeError:
            raise RuntimeError(f"HTTP {e.code}: {body}")

def dispatch_tool(tool_name: str, tool_input: dict, cfg: dict) -> str:
    rk = cfg["retell_api_key"]
    default_agent = cfg.get("default_agent_id", "")
    default_from = cfg.get("default_from_number", "")
    try:
        if tool_name == "make_call":
            to_num = resolve_number(tool_input.get("to_number", ""))
            agent = tool_input.get("agent_id") or default_agent
            if not agent:
                return json.dumps({"success": False, "error": "Δεν έχει οριστεί agent. Χρησιμοποίησε --setup ή δώσε agent_id."})
            from_num = tool_input.get("from_number") or default_from
            result = make_call(rk, agent, to_num, from_num, tool_input.get("metadata"))
        elif tool_name == "end_call":
            result = end_call(rk, tool_input["call_id"])
        elif tool_name == "list_active_calls":
            result = list_active_calls(rk)
        elif tool_name == "list_recent_calls":
            result = list_recent_calls(rk, tool_input.get("limit", 20))
        elif tool_name == "get_call_details":
            result = get_call_details(rk, tool_input["call_id"])
        elif tool_name == "list_agents":
            result = list_agents(rk)
        elif tool_name == "update_agent":
            agent_id = tool_input.get("agent_id") or default_agent
            sensitivity = tool_input.get("interruption_sensitivity", 0.3)
            result = update_agent(rk, agent_id, sensitivity)
        elif tool_name == "log_call":
            msg = save_call_log(
                contact=tool_input.get("contact", "Άγνωστος"),
                phone=tool_input.get("phone", "—"),
                summary=tool_input.get("summary", ""),
                call_id=tool_input.get("call_id", ""),
            )
            result = {"success": True, "message": msg}
        elif tool_name == "note_contact":
            msg = save_contact_note(
                name=tool_input.get("name", ""),
                note=tool_input.get("note", ""),
            )
            result = {"success": True, "message": msg}
        elif tool_name == "get_calendar_events":
            result = get_calendar_events(tool_input.get("days", 1))
        elif tool_name == "send_email":
            result = send_email(
                to=tool_input.get("to", ""),
                subject=tool_input.get("subject", ""),
                body=tool_input.get("body", ""),
            )
        else:
            result = {"success": False, "error": f"Άγνωστο tool: {tool_name}"}
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)

def run_turn(user_message: str, history: list, cfg: dict) -> tuple:
    messages = history + [{"role": "user", "content": user_message}]
    first_response = True
    while True:
        if first_response:
            first_response = False
        else:
            print("\nΓραμματεία: ", end="", flush=True)
        content, stop_reason = claude_stream(messages, cfg)
        messages.append({"role": "assistant", "content": content})
        if stop_reason == "tool_use":
            print()
            tool_results = []
            for block in content:
                if block.get("type") == "tool_use":
                    tool_name = block["name"]
                    tool_input = block.get("input", {})
                    tool_id = block["id"]
                    print(f"  🔧 {tool_name}({json.dumps(tool_input, ensure_ascii=False)})")
                    result_str = dispatch_tool(tool_name, tool_input, cfg)
                    result_data = json.loads(result_str)
                    if result_data.get("success"):
                        print(f"  ✓ {result_data.get('message') or 'OK'}")
                    else:
                        print(f"  ✗ {result_data.get('error', 'Σφάλμα')}")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": result_str,
                    })
            messages.append({"role": "user", "content": tool_results})
        elif stop_reason in ("end_turn", "stop_sequence", None):
            updated_history = messages[-40:]
            return "", updated_history
        else:
            print(f"\n[Απροσδόκητο stop_reason: {stop_reason}]")
            return "", messages

def handle_local_command(cmd: str) -> tuple:
    parts = cmd.strip().split(None, 2)
    verb = parts[0].lower() if parts else ""
    if verb in ("/contacts", "/επαφές"):
        return True, list_contacts()
    if verb in ("/add", "/προσθήκη") and len(parts) >= 3:
        return True, add_contact(parts[1], parts[2])
    if verb in ("/remove", "/διαγραφή") and len(parts) >= 2:
        return True, remove_contact(parts[1])
    if verb in ("/logs", "/ιστορικό"):
        return True, list_call_logs()
    if verb in ("/help", "/βοήθεια"):
        return True, HELP_TEXT
    if verb in ("/clear", "/καθαρισμός"):
        return True, "__CLEAR__"
    return False, ""

HELP_TEXT = """
╔══════════════════════════════════════════════════╗
║              ΣΟΦΙΑ — Εντολές                     ║
╠══════════════════════════════════════════════════╣
║  Φυσική γλώσσα:                                  ║
║    "κάλεσε τον Γιώργη"                           ║
║    "κάλεσε το 6912345678"                        ║
║    "τερμάτισε την κλήση"                         ║
║    "ποιες κλήσεις είναι ενεργές;"                ║
║    "δείξε μου το ιστορικό κλήσεων"               ║
║    "κατέγραψε — θέμα: ενοίκιο, είπε να..."      ║
║    "σημείωσε για τον Γιώργη ότι..."              ║
║                                                  ║
║  Εντολές συστήματος:                             ║
║    /contacts        — βιβλίο επαφών              ║
║    /add Όνομα +30…  — νέα επαφή                  ║
║    /remove Όνομα    — διαγραφή επαφής            ║
║    /logs            — ιστορικό κλήσεων (μνήμη)  ║
║    /clear           — καθαρισμός ιστορικού       ║
║    /help            — αυτό το μήνυμα             ║
║    exit / quit      — έξοδος                     ║
║                                                  ║
║  Google (πρώτη φορά):                            ║
║    python3 secretary.py --setup-google           ║
╚══════════════════════════════════════════════════╝
"""

def main():
    if "--setup" in sys.argv:
        setup_wizard()
        return
    if "--setup-google" in sys.argv:
        setup_google()
        return
    if "--contacts" in sys.argv:
        print(list_contacts())
        return

    cfg = get_config()
    if not cfg["anthropic_api_key"]:
        print("✗ Δεν υπάρχει Anthropic API key. Τρέξε: python3 secretary.py --setup")
        sys.exit(1)
    if not cfg["retell_api_key"]:
        print("✗ Δεν υπάρχει Retell API key. Τρέξε: python3 secretary.py --setup")
        sys.exit(1)

    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    agent_info = f"Agent: {cfg['default_agent_id']}" if cfg["default_agent_id"] else "⚠  Δεν έχει οριστεί default agent"
    from context_manager import CONTEXT_ROOT
    call_count = len(list((CONTEXT_ROOT / "calls").glob("*.md"))) if (CONTEXT_ROOT / "calls").exists() else 0
    memory_info = f"Μνήμη: {call_count} κλήσεις καταγεγραμμένες"
    print(f"""
╔══════════════════════════════════════╗
║         ΣΟΦΙΑ — AI Γραμματεία v2.0   ║
║  {now:<36}║
╠══════════════════════════════════════╣
║  {agent_info:<36}║
║  {memory_info:<36}║
║  Πληκτρολόγησε /help για βοήθεια    ║
╚══════════════════════════════════════╝
""")

    history = []
    while True:
        try:
            user_input = input("Εσύ: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nΑντίο!")
            break
        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "έξοδος", "τελος", "τέλος"):
            print("Αντίο!")
            break
        handled, local_response = handle_local_command(user_input)
        if handled:
            if local_response == "__CLEAR__":
                history = []
                print("✓ Ιστορικό συνομιλίας καθαρίστηκε.")
            else:
                print(local_response)
            continue
        contacts = load_contacts()
        enriched = user_input
        for name, number in contacts.items():
            if name.lower() in user_input.lower():
                enriched = f"{user_input} [Σημείωση: '{name}' = {number}]"
                break
        print("Γραμματεία: ", end="", flush=True)
        try:
            _, history = run_turn(enriched, history, cfg)
        except RuntimeError as e:
            print(f"\n✗ Σφάλμα: {e}")
        except Exception as e:
            print(f"\n✗ Απρόσμενο σφάλμα: {e}")
        print()

if __name__ == "__main__":
    main()
