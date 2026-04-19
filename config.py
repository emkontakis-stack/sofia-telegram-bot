"""
config.py — Διαχείριση ρυθμίσεων και API keys
Αποθηκεύει τα keys στο ~/.secretary_config.json
"""
import os
import json
from pathlib import Path

CONFIG_PATH = Path.home() / ".secretary_config.json"

DEFAULTS = {
    "anthropic_api_key": "",
    "retell_api_key": "",
    "default_agent_id": "",
    "default_from_number": "",
    "model": "claude-haiku-4-5-20251001",
    "max_tokens": 1024,
}

def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return {**DEFAULTS, **json.load(f)}
    return dict(DEFAULTS)

def save_config(cfg: dict):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    CONFIG_PATH.chmod(0o600)

def get_config() -> dict:
    cfg = load_config()
    env_map = {
        "ANTHROPIC_API_KEY":        "anthropic_api_key",
        "RETELL_API_KEY":           "retell_api_key",
        "DEFAULT_AGENT_ID":         "default_agent_id",
        "DEFAULT_FROM_NUMBER":      "default_from_number",
        "TELEGRAM_TOKEN":           "telegram_token",
        "TELEGRAM_ALLOWED_CHAT_ID": "telegram_allowed_chat_id",
        "MODEL":                    "model",
    }
    for env_key, cfg_key in env_map.items():
        if os.environ.get(env_key):
            cfg[cfg_key] = os.environ[env_key]
    return cfg

def setup_wizard():
    print("\n╔══════════════════════════════════════╗")
    print("║      ΓΡΑΜΜΑΤΕΙΑ — Αρχική Ρύθμιση     ║")
    print("╚══════════════════════════════════════╝\n")
    cfg = load_config()

    print("Anthropic API key (από https://console.anthropic.com):")
    val = input(f"  [{'*' * 8 if cfg['anthropic_api_key'] else 'κενό'}] > ").strip()
    if val: cfg["anthropic_api_key"] = val

    print("\nRetell API key (από https://app.retellai.com → Settings):")
    val = input(f"  [{'*' * 8 if cfg['retell_api_key'] else 'κενό'}] > ").strip()
    if val: cfg["retell_api_key"] = val

    print("\nDefault Agent ID (προαιρετικό):")
    val = input(f"  [{cfg['default_agent_id'] or 'κενό'}] > ").strip()
    if val: cfg["default_agent_id"] = val

    print("\nDefault From Number (π.χ. +15551234567, προαιρετικό):")
    val = input(f"  [{cfg['default_from_number'] or 'κενό'}] > ").strip()
    if val: cfg["default_from_number"] = val

    save_config(cfg)
    print("\n✓ Ρυθμίσεις αποθηκεύτηκαν στο ~/.secretary_config.json\n")
    return cfg
