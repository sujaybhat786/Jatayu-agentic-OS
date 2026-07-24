"""Provider Registry — central index of all communication adapters.

The Brain and Request Dispatcher never reference providers directly.
The registry resolves the correct adapter by source name. Adding a
new provider means registering a new adapter — nothing else changes.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jatayu.comms.adapter import CommunicationAdapter

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """Central registry of all communication providers.

    Usage:
        registry = ProviderRegistry()
        registry.register(whatsapp_adapter)
        registry.register(telegram_adapter)

        adapter = registry.get("whatsapp")
        all_names = registry.list_providers()
    """

    def __init__(self) -> None:
        self._adapters: dict[str, CommunicationAdapter] = {}

    def register(self, adapter: CommunicationAdapter) -> None:
        """Register a communication adapter.

        Raises ValueError if a provider with the same name already exists.
        """
        name = adapter.provider_name
        if name in self._adapters:
            raise ValueError(
                f"Communication provider '{name}' is already registered."
            )
        self._adapters[name] = adapter
        logger.info("Communication provider registered: %s", name)

    def get(self, provider_name: str) -> CommunicationAdapter | None:
        """Look up an adapter by provider name.

        Returns None if not found (caller decides how to handle).
        """
        return self._adapters.get(provider_name)

    def list_providers(self) -> list[str]:
        """Return names of all registered providers."""
        return list(self._adapters.keys())

    @property
    def providers(self) -> dict[str, CommunicationAdapter]:
        """Return a copy of the full provider map."""
        return dict(self._adapters)

    def __len__(self) -> int:
        return len(self._adapters)

    def __contains__(self, name: str) -> bool:
        return name in self._adapters
