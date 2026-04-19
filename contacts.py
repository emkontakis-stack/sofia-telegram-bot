"""
contacts.py — Βιβλίο επαφών
"""
import json
from pathlib import Path

CONTACTS_PATH = Path(__file__).parent / "contacts.json"

def load_contacts() -> dict:
    if CONTACTS_PATH.exists():
        with open(CONTACTS_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_contacts(contacts: dict):
    with open(CONTACTS_PATH, "w", encoding="utf-8") as f:
        json.dump(contacts, f, indent=2, ensure_ascii=False)

def resolve_number(name_or_number: str) -> str:
    s = name_or_number.strip()
    if s.startswith("+") or s.isdigit():
        return s
    contacts = load_contacts()
    key = s.lower()
    for name, number in contacts.items():
        if name.lower() == key:
            return number
    for name, number in contacts.items():
        if key in name.lower():
            return number
    return s

def add_contact(name: str, number: str) -> str:
    contacts = load_contacts()
    contacts[name] = number
    save_contacts(contacts)
    return f"Επαφή '{name}' → {number} αποθηκεύτηκε."

def remove_contact(name: str) -> str:
    contacts = load_contacts()
    if name in contacts:
        del contacts[name]
        save_contacts(contacts)
        return f"Επαφή '{name}' διαγράφηκε."
    return f"Δεν βρέθηκε επαφή με όνομα '{name}'."

def list_contacts() -> str:
    contacts = load_contacts()
    if not contacts:
        return "Δεν υπάρχουν αποθηκευμένες επαφές."
    lines = ["Βιβλίο Επαφών:", "─" * 30]
    for name, number in sorted(contacts.items()):
        lines.append(f"  {name:<25} {number}")
    return "\n".join(lines)
