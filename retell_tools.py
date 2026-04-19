"""
retell_tools.py — Όλες οι λειτουργίες Retell API
"""
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from typing import Optional

RETELL_BASE = "https://api.retellai.com"

def _athens_time_closing() -> str:
    h = datetime.now(timezone(timedelta(hours=3))).hour
    if 6 <= h < 13:
        return "Καλή συνέχεια"
    elif 13 <= h < 21:
        return "Καλό απόγευμα"
    else:
        return "Καληνύχτα"

def _request(method: str, path: str, api_key: str, body: Optional[dict] = None) -> dict:
    url = f"{RETELL_BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()
        try:
            err = json.loads(body_text)
            raise RuntimeError(err.get("message") or err.get("error") or body_text)
        except json.JSONDecodeError:
            raise RuntimeError(f"HTTP {e.code}: {body_text}")

def make_call(api_key: str, agent_id: str, to_number: str,
              from_number: str = "", metadata: dict = None) -> dict:
    payload = {"agent_id": agent_id, "to_number": to_number}
    if from_number:
        payload["from_number"] = from_number

    instructions = (metadata or {}).get("instructions") or ""
    farewell_rule = (
        " Πριν κλείσεις την κλήση, ΠΑΝΤΑ περίμενε ο συνομιλητής να πει αποχαιρετισμό "
        "(π.χ. 'αντίο', 'γεια σας', 'καληνύχτα', 'τα λέμε'). "
        "Αν δε μιλήσει για 5 δευτερόλεπτα τότε μπορείς να κλείσεις."
    )
    payload["retell_llm_dynamic_variables"] = {
        "instructions": instructions + farewell_rule,
        "time_closing": _athens_time_closing(),
    }

    result = _request("POST", "/v2/create-phone-call", api_key, payload)
    return {
        "success": True,
        "call_id": result.get("call_id"),
        "status": result.get("call_status"),
        "to_number": to_number,
        "message": f"Κλήση ξεκίνησε προς {to_number} (ID: {result.get('call_id')})"
    }

def end_call(api_key: str, call_id: str) -> dict:
    _request("POST", f"/v2/end-call/{call_id}", api_key)
    return {"success": True, "call_id": call_id, "message": f"Κλήση {call_id} τερματίστηκε."}

def list_active_calls(api_key: str) -> dict:
    result = _request("POST", "/v2/list-calls", api_key, {
        "filter_criteria": {"call_status": ["ongoing", "registered"]}, "limit": 20
    })
    calls = result if isinstance(result, list) else []
    return {"success": True, "count": len(calls), "calls": [
        {"call_id": c.get("call_id"), "to_number": c.get("to_number"),
         "status": c.get("call_status"), "started": _fmt_ts(c.get("start_timestamp"))}
        for c in calls]}

def list_recent_calls(api_key: str, limit: int = 20) -> dict:
    result = _request("POST", "/v2/list-calls", api_key, {"limit": limit, "sort_order": "descending"})
    calls = result if isinstance(result, list) else []
    return {"success": True, "count": len(calls), "calls": [
        {"call_id": c.get("call_id"), "to_number": c.get("to_number"),
         "status": c.get("call_status"), "started": _fmt_ts(c.get("start_timestamp")),
         "duration": _fmt_dur(c.get("duration_ms"))}
        for c in calls]}

def get_call_details(api_key: str, call_id: str) -> dict:
    c = _request("GET", f"/v2/get-call/{call_id}", api_key)
    transcript = c.get("transcript", "")
    return {"success": True, "call_id": call_id, "to_number": c.get("to_number"),
            "status": c.get("call_status"), "started": _fmt_ts(c.get("start_timestamp")),
            "duration": _fmt_dur(c.get("duration_ms")),
            "transcript_preview": transcript[:500] + ("…" if len(transcript) > 500 else "") if transcript else "—"}

def list_agents(api_key: str) -> dict:
    result = _request("GET", "/v2/list-agents", api_key)
    agents = result if isinstance(result, list) else []
    return {"success": True, "count": len(agents), "agents": [
        {"agent_id": a.get("agent_id"), "name": a.get("agent_name") or a.get("agent_id")}
        for a in agents]}

def update_agent(api_key: str, agent_id: str, interruption_sensitivity: float = 0.3) -> dict:
    """Ενημερώνει agent: χαμηλό interruption, 5δλ σιωπή → κλείσιμο, αναμονή αποχαιρετισμού."""
    payload = {
        "interruption_sensitivity": max(0.0, min(1.0, interruption_sensitivity)),
        "end_call_after_silence_ms": 5000,
        "reminder_trigger_ms": 4000,
        "reminder_max_count": 1,
    }
    _request("PATCH", f"/v2/update-agent/{agent_id}", api_key, payload)
    return {
        "success": True,
        "agent_id": agent_id,
        "interruption_sensitivity": interruption_sensitivity,
        "end_call_after_silence_ms": 5000,
        "message": f"Agent ενημερώθηκε: interruption_sensitivity={interruption_sensitivity}, σιωπή 5δλ → κλείσιμο"
    }

def _fmt_ts(ts):
    if not ts: return "—"
    try:
        dt = datetime.fromtimestamp(ts / 1000 if ts > 1e10 else ts)
        return dt.strftime("%d/%m/%Y %H:%M")
    except: return str(ts)

def _fmt_dur(ms):
    if not ms: return "—"
    s = int(ms / 1000)
    return f"{s // 60}:{s % 60:02d}"

TOOL_DEFINITIONS = [
    {"name": "make_call", "description": "Εκκινεί outbound τηλεφωνική κλήση μέσω Retell AI. Πριν την κλήση ανανεώνει αυτόματα το system prompt με τις instructions.",
     "input_schema": {"type": "object", "properties": {
         "to_number": {"type": "string", "description": "Αριθμός προορισμού E.164 (π.χ. +306912345678)"},
         "agent_id": {"type": "string", "description": "Retell agent ID"},
         "from_number": {"type": "string", "description": "Αριθμός αποστολέα (προαιρετικό)"},
         "metadata": {"type": "object", "description": "Πρέπει να περιέχει 'instructions' με αυτό που θα πει/κάνει ο agent και 'purpose' με τον σκοπό"}},
     "required": ["to_number", "agent_id"]}},
    {"name": "end_call", "description": "Τερματίζει ενεργή κλήση.",
     "input_schema": {"type": "object", "properties": {"call_id": {"type": "string"}}, "required": ["call_id"]}},
    {"name": "list_active_calls", "description": "Επιστρέφει τις ενεργές κλήσεις.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "list_recent_calls", "description": "Επιστρέφει ιστορικό πρόσφατων κλήσεων.",
     "input_schema": {"type": "object", "properties": {"limit": {"type": "integer"}}}},
    {"name": "get_call_details", "description": "Επιστρέφει λεπτομέρειες & transcript κλήσης.",
     "input_schema": {"type": "object", "properties": {"call_id": {"type": "string"}}, "required": ["call_id"]}},
    {"name": "list_agents", "description": "Επιστρέφει τους διαθέσιμους Retell agents.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "update_agent", "description": "Ενημερώνει ρυθμίσεις Retell agent (π.χ. interruption_sensitivity για να μην ξεκινά από την αρχή όταν μιλά ο συνομιλητής).",
     "input_schema": {"type": "object", "properties": {
         "agent_id": {"type": "string", "description": "ID του agent"},
         "interruption_sensitivity": {"type": "number", "description": "0.0-1.0 (χαμηλό=δύσκολα διακόπτεται, default 0.3)"}},
     "required": ["agent_id"]}},
    {"name": "log_call", "description": "Αποθηκεύει σύνοψη κλήσης στη μνήμη. Χρήση μετά κάθε κλήση αν ο χρήστης πει 'κατέγραψε', 'σημείωσε' ή 'θυμήσου'.",
     "input_schema": {"type": "object", "properties": {
         "contact": {"type": "string", "description": "Όνομα επαφής"},
         "phone": {"type": "string", "description": "Τηλέφωνο"},
         "summary": {"type": "string", "description": "Τι συζητήθηκε, τι αποφασίστηκε, τι εκκρεμεί"},
         "call_id": {"type": "string", "description": "Retell call ID (προαιρετικό)"}},
     "required": ["contact", "summary"]}},
    {"name": "note_contact", "description": "Αποθηκεύει σημείωση για μια επαφή (προτιμήσεις, ιστορικό, σχέση). Χρήση όταν ο χρήστης πει 'σημείωσε για τον X ότι...'.",
     "input_schema": {"type": "object", "properties": {
         "name": {"type": "string", "description": "Όνομα επαφής"},
         "note": {"type": "string", "description": "Σημείωση για την επαφή"}},
     "required": ["name", "note"]}},
]
