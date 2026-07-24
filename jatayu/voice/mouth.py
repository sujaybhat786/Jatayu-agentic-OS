"""The mouth — Text-to-Speech seam.

Speaks text aloud using the ElevenLabs REST API with streaming playback.
This is the only module that talks to ElevenLabs. To swap TTS providers,
replace only this file.
"""

from __future__ import annotations

import io
import os
import threading
import wave

import numpy as np
import sounddevice as sd

from jatayu.config import get_config


# Playback state — allows interruption
_playback_lock = threading.Lock()
_should_stop = threading.Event()


def _get_api_key() -> str:
    """Get the ElevenLabs API key from environment."""
    key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "ELEVENLABS_API_KEY is not set. Add it to .env."
        )
    return key


def _get_voice_id() -> str:
    """Get the configured ElevenLabs voice ID.

    Uses the voice name from config to look up a voice ID.
    Falls back to 'Rachel' (21m00Tcm4TlvDq8ikWAM) by default.
    """
    # Common voice name → ID mappings
    voice_map = {
        "rachel": "21m00Tcm4TlvDq8ikWAM",
        "adam": "pNInz6obpgDQGcFmaJgB",
        "antoni": "ErXwobaYiN019PkySvjV",
        "domi": "AZnzlk1XvdvUeBnXmlld",
        "elli": "MF3mGyEYCl7XYWbV9V6O",
        "josh": "TxGEqnHWrfWFTfGW9XjX",
        "sam": "yoZ06aMxZJJ28mfd3POQ",
    }

    config = get_config()
    voice_name = config.get("elevenlabs_voice", "rachel").lower().strip()
    return voice_map.get(voice_name, voice_map["rachel"])


def speak(text: str) -> None:
    """Speak the given text aloud.

    This is the TTS seam — the only function the rest of the harness
    calls for speech output. Blocks until playback finishes or is
    interrupted via interrupt().

    Args:
        text: The text to speak.
    """
    if not text or not text.strip():
        return

    _should_stop.clear()

    try:
        import httpx

        api_key = _get_api_key()
        voice_id = _get_voice_id()

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        payload = {
            "text": text,
            "model_id": "eleven_turbo_v2_5",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.0,
                "use_speaker_boost": True,
            },
        }

        response = httpx.post(
            url,
            headers=headers,
            json=payload,
            timeout=30.0,
        )
        response.raise_for_status()

        # Play the audio
        _play_audio_bytes(response.content)

    except Exception as e:
        print(f"\n⚠️  TTS failed: {e}")


def speak_streamed(text_chunks) -> None:
    """Speak text from a stream of chunks.

    Accumulates chunks into sentence-sized pieces and speaks each one
    to minimize latency — starts speaking the first sentence while the
    rest is still being generated.

    Args:
        text_chunks: Iterable of text strings.
    """
    _should_stop.clear()
    buffer = ""
    sentence_enders = {".", "!", "?", "\n"}

    for chunk in text_chunks:
        if _should_stop.is_set():
            break

        buffer += chunk

        # Check if we have a complete sentence to speak
        for i, char in enumerate(buffer):
            if char in sentence_enders and len(buffer[:i + 1].strip()) > 10:
                sentence = buffer[:i + 1].strip()
                buffer = buffer[i + 1:]
                if sentence:
                    speak(sentence)
                    if _should_stop.is_set():
                        return
                break

    # Speak any remaining text
    if buffer.strip() and not _should_stop.is_set():
        speak(buffer.strip())


def interrupt() -> None:
    """Stop any ongoing playback immediately."""
    _should_stop.set()
    sd.stop()


def _play_audio_bytes(audio_bytes: bytes) -> None:
    """Play MP3 audio bytes through the speakers.

    Uses a temporary conversion through pydub or raw playback.
    Falls back to writing a temp file if direct playback isn't possible.
    """
    if _should_stop.is_set():
        return

    try:
        # Try using pydub for MP3 decoding
        from pydub import AudioSegment

        audio = AudioSegment.from_mp3(io.BytesIO(audio_bytes))
        samples = np.array(audio.get_array_of_samples(), dtype=np.float32)
        samples = samples / (2**15)  # normalize 16-bit to float

        if audio.channels == 2:
            samples = samples.reshape(-1, 2)

        with _playback_lock:
            if not _should_stop.is_set():
                sd.play(samples, samplerate=audio.frame_rate)
                sd.wait()

    except ImportError:
        # Fallback: use ffmpeg or mpv via subprocess
        import subprocess
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=True) as f:
            f.write(audio_bytes)
            f.flush()
            try:
                subprocess.run(
                    ["afplay", f.name],  # macOS built-in
                    check=True,
                    capture_output=True,
                )
            except FileNotFoundError:
                print("\n⚠️  No audio player found. Install pydub or ffmpeg for TTS playback.")
