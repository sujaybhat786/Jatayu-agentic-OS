"""Text-to-Speech abstraction layer.

Defines the VoiceSynthesizer interface. The actual ElevenLabs HTTP calls are
made inline in server.py (web) and mouth.py (CLI). This module provides the
interface contract so future providers can be swapped without changing callers.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod


class VoiceSynthesizer(ABC):
    """Abstract TTS interface — swap implementations to change providers."""

    @abstractmethod
    def synthesize(self, text: str) -> bytes:
        """Convert text to audio bytes (MP3/MPEG).

        Args:
            text: The text to speak.

        Returns:
            Raw MP3 audio bytes, or empty bytes on failure.
        """
        ...


class ElevenLabsSynthesizer(VoiceSynthesizer):
    """ElevenLabs TTS provider.

    The web server implements this inline in server.py for browser delivery.
    This class provides the same implementation for CLI/SDK callers who need
    audio bytes directly (e.g. the push-to-talk CLI mode).
    """

    # Common voice name → ElevenLabs voice ID mapping
    VOICE_MAP: dict[str, str] = {
        "rachel": "21m00Tcm4TlvDq8ikWAM",
        "adam":   "pNInz6obpgDQGcFmaJgB",
        "josh":   "TxGEqnHWrfWFTfGW9XjX",
        "sam":    "yoZ06aMxZJJ28mfd3POQ",
    }
    DEFAULT_VOICE = "rachel"

    def __init__(
        self,
        api_key: str | None = None,
        voice_name: str | None = None,
    ) -> None:
        import httpx  # lazy import — only needed when TTS is actually used
        self._httpx = httpx

        self.api_key = api_key or os.getenv("ELEVENLABS_API_KEY", "").strip()
        resolved_name = (voice_name or self.DEFAULT_VOICE).lower().strip()
        self.voice_id = self.VOICE_MAP.get(resolved_name, self.VOICE_MAP[self.DEFAULT_VOICE])

    def synthesize(self, text: str) -> bytes:
        if not self.api_key or not text.strip():
            return b""

        try:
            with self._httpx.Client(timeout=30.0) as client:
                resp = client.post(
                    f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}",
                    headers={
                        "xi-api-key": self.api_key,
                        "Content-Type": "application/json",
                        "Accept": "audio/mpeg",
                    },
                    json={
                        "text": text,
                        "model_id": "eleven_turbo_v2_5",
                        "voice_settings": {
                            "stability": 0.5,
                            "similarity_boost": 0.75,
                        },
                    },
                )
                resp.raise_for_status()
                return resp.content

        except Exception as e:
            print(f"\n⚠️  ElevenLabs TTS error: {e}")
            return b""
