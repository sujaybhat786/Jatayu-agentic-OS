"""Configuration loader — single source for all settings and secrets.

Reads .env for API keys and config.yaml for everything else.
Caches the result so files are only read once per process.
"""

import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv


_config: dict | None = None

# Project root is one level up from this file's parent directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def get_config() -> dict:
    """Load and return the merged configuration.

    First call reads .env and config.yaml; subsequent calls return the
    cached result. Exits with a clear message if the API key is missing.
    """
    global _config
    if _config is not None:
        return _config

    # ── Load secrets from .env ──
    load_dotenv(PROJECT_ROOT / ".env")

    # ── Load settings from config.yaml ──
    config_path = PROJECT_ROOT / "config.yaml"
    if config_path.exists():
        with open(config_path) as f:
            file_config = yaml.safe_load(f) or {}
    else:
        file_config = {}

    # ── Validate API key ──
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("\n⚠️  GEMINI_API_KEY is not set.")
        print("   1. Get a key at: https://aistudio.google.com/apikey")
        print("   2. Add it to .env:  GEMINI_API_KEY=your-key-here\n")
        sys.exit(1)

    # ── Ensure data directory exists ──
    data_dir = PROJECT_ROOT / file_config.get("data_dir", "data")
    data_dir.mkdir(parents=True, exist_ok=True)

    _config = {
        "gemini_api_key": api_key,
        "model": file_config.get("model", "gemini-3.5-flash"),
        "assistant_name": file_config.get("assistant_name", "Jatayu"),
        "system_prompt": file_config.get(
            "system_prompt",
            "You are Jatayu, a personal assistant. Be warm, casual, and brief.",
        ),
        "data_dir": str(data_dir),
        "project_root": str(PROJECT_ROOT),
        # Tier 3 — Voice
        "elevenlabs_voice": file_config.get("elevenlabs_voice", "Rachel"),
        "ptt_key": file_config.get("ptt_key", "space"),
        # Tier 6 — Safety
        "kill_switch": file_config.get("kill_switch", False),
        "location": file_config.get("location", {}),
    }
    _config.update({k: v for k, v in file_config.items() if k not in _config})
    return _config


def reset_config() -> None:
    """Clear the cached config (useful for tests)."""
    global _config
    _config = None
