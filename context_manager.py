"""
context_manager.py — Δυναμικό context & μνήμη κλήσεων για τη Σοφία
"""
import json
from pathlib import Path
from datetime import datetime

CONTEXT_ROOT = Path.home() / ".secretary" / "context"

def ensure_dirs():
    for d in ["profile", "contacts", "calls", "tools"]:
        (CONTEXT_ROOT / d).mkdir(parents=True, exist_ok=True)

def build_context() -> str:
    ensure_dirs()
    parts = []

    profile_file = CONTEXT_ROOT / "profile" / "manos.md"
    if profile_file.exists():
        parts.append("## ΠΡΟΦΙΛ ΧΡΗΣΤΗ\n" + profile_file.read_text(encoding="utf-8").strip())

    call_files = sorted((CONTEXT_ROOT / "calls").glob("*.md"), reverse=True)[:7]
    if call_files:
        call_lines = ["## ΠΡΟΣΦΑΤΕΣ ΚΛΗΣΕΙΣ"]
        for cf in call_files:
            call_lines.append(cf.read_text(encoding="utf-8").strip())
        parts.append("\n\n".join(call_lines))

    contact_files = sorted((CONTEXT_ROOT / "contacts").glob("*.md"))
    if contact_files:
        c_lines = ["## ΣΗΜΕΙΩΣΕΙΣ ΕΠΑΦΩΝ"]
        for cf in contact_files:
            c_lines.append(f"### {cf.stem.replace('_', ' ')}\n" + cf.read_text(encoding="utf-8").strip())
        parts.append("\n\n".join(c_lines))

    tools_file = CONTEXT_ROOT / "tools" / "tools.md"
    if tools_file.exists():
        parts.append("## ΟΔΗΓΙΕΣ ΧΡΗΣΗΣ TOOLS\n" + tools_file.read_text(encoding="utf-8").strip())

    return "\n\n---\n\n".join(parts)

def save_call_log(contact: str, phone: str, summary: str, call_id: str = "") -> str:
    ensure_dirs()
    ts = datetime.now()
    filename = CONTEXT_ROOT / "calls" / f"{ts.strftime('%Y%m%d_%H%M%S')}_{contact.replace(' ', '_')}.md"
    filename.write_text(
        f"# {contact} — {ts.strftime('%d/%m/%Y %H:%M')}\n"
        f"**Τηλέφωνο:** {phone}  |  **Call ID:** {call_id or '—'}\n\n"
        f"{summary}\n",
        encoding="utf-8",
    )
    return f"✓ Log αποθηκεύτηκε: {filename.name}"

def save_contact_note(name: str, note: str) -> str:
    ensure_dirs()
    filename = CONTEXT_ROOT / "contacts" / f"{name.replace(' ', '_')}.md"
    existing = filename.read_text(encoding="utf-8").strip() if filename.exists() else ""
    date_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    updated = (existing + f"\n\n## {date_str}\n{note}").strip()
    filename.write_text(updated, encoding="utf-8")
    return f"✓ Σημείωση για '{name}' αποθηκεύτηκε."

def list_call_logs(limit: int = 10) -> str:
    ensure_dirs()
    files = sorted((CONTEXT_ROOT / "calls").glob("*.md"), reverse=True)[:limit]
    if not files:
        return "Δεν υπάρχουν αποθηκευμένα logs κλήσεων."
    lines = [f"{'─'*50}", "ΙΣΤΟΡΙΚΟ ΚΛΗΣΕΩΝ (από τη μνήμη)", f"{'─'*50}"]
    for f in files:
        first_line = f.read_text(encoding="utf-8").split("\n")[0].lstrip("# ")
        lines.append(f"  {first_line}")
    return "\n".join(lines)
