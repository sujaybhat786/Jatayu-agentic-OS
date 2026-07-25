"""Credential Vault — Manages API keys and secrets for plugins securely."""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

class Vault:
    """Centralized credential manager."""
    
    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.vault_file = self.data_dir / "vault.json"
        
        # In a real enterprise system, we would use cryptography.fernet here
        # For Phase 3A, we simulate encryption by storing them in a dedicated JSON file
        # isolated from standard memory and config.
        
        if not self.vault_file.exists():
            with open(self.vault_file, "w") as f:
                json.dump({}, f)
                
    def _load(self) -> dict[str, dict[str, str]]:
        try:
            with open(self.vault_file) as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load vault: {e}")
            return {}
            
    def _save(self, data: dict[str, dict[str, str]]):
        with open(self.vault_file, "w") as f:
            json.dump(data, f, indent=2)

    def get_credential(self, plugin_id: str, key: str) -> str | None:
        """Retrieve a credential for a specific plugin.
        
        Falls back to environment variables if not in vault (for backward compatibility).
        """
        data = self._load()
        plugin_creds = data.get(plugin_id, {})
        
        if key in plugin_creds:
            return plugin_creds[key]
            
        # Fallback to env
        env_val = os.getenv(key)
        if env_val:
            return env_val
            
        return None
        
    def set_credential(self, plugin_id: str, key: str, value: str):
        """Store a credential securely."""
        data = self._load()
        if plugin_id not in data:
            data[plugin_id] = {}
        data[plugin_id][key] = value
        self._save(data)
