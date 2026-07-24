"""The ears — Speech-to-Text seam.

Transcribes audio bytes to text using the Deepgram REST API.
This is the only module that talks to Deepgram. To swap STT providers,
replace only this file.
"""

from __future__ import annotations

import os
import httpx

from jatayu.config import get_config


def _get_api_key() -> str:
    """Get the Deepgram API key from environment."""
    key = os.getenv("DEEPGRAM_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "DEEPGRAM_API_KEY is not set. Add it to .env."
        )
    return key


def transcribe(audio_bytes: bytes, sample_rate: int = 16000) -> str:
    """Transcribe audio bytes to text.

    This is the STT seam — the only function the rest of the harness
    calls. Swap the implementation to change providers.

    Args:
        audio_bytes: Raw audio data (16-bit PCM, mono).
        sample_rate: Sample rate in Hz (default 16000).

    Returns:
        The transcribed text, or empty string on failure.
    """
    api_key = _get_api_key()

    url = "https://api.deepgram.com/v1/listen"
    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": "audio/raw",
    }
    params = {
        "encoding": "linear16",
        "sample_rate": str(sample_rate),
        "channels": "1",
        "model": "nova-3",
        "smart_format": "true",
        "punctuate": "true",
    }

    try:
        response = httpx.post(
            url,
            headers=headers,
            params=params,
            content=audio_bytes,
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()

        # Extract transcript from Deepgram response
        channels = data.get("results", {}).get("channels", [])
        if channels:
            alternatives = channels[0].get("alternatives", [])
            if alternatives:
                return alternatives[0].get("transcript", "")

        return ""

    except httpx.HTTPStatusError as e:
        print(f"\n⚠️  Deepgram error: {e.response.status_code} — {e.response.text[:200]}")
        return ""
    except Exception as e:
        print(f"\n⚠️  Transcription failed: {e}")
        return ""
