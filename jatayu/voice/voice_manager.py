"""VoiceManager — coordinates the STT pipeline for voice interactions.

This is the central voice orchestrator for the web server. It:
- Uses the SpeechRecognizer interface (swap provider without touching this file)
- Exposes start_listening() / stop_listening() as future-proof hooks
- Does NOT manage recording or playback (those are browser/platform concerns)

Usage in server.py:
    from jatayu.voice.voice_manager import VoiceManager
    _voice_manager = VoiceManager()
    transcript = _voice_manager.transcribe(audio_bytes, content_type)
"""

from __future__ import annotations

from jatayu.voice.speech_to_text import SpeechRecognizer, get_default_recognizer


class VoiceManager:
    """Coordinates speech-to-text transcription for the voice pipeline.

    Designed to be instantiated once at server startup and reused across
    all requests. Thread-safe — recognizer implementations must be stateless.

    Future extensions (VAD, wake word, continuous listening) will be added
    here without changing the public interface callers depend on.
    """

    def __init__(self, recognizer: SpeechRecognizer | None = None) -> None:
        self.recognizer = recognizer or get_default_recognizer()

    # ── Core ──

    def transcribe(self, audio_bytes: bytes, content_type: str = "audio/webm") -> str:
        """Convert audio bytes to text using the configured STT provider.

        Args:
            audio_bytes: Raw audio data (e.g. webm/opus from MediaRecorder).
            content_type: MIME type of the audio.

        Returns:
            Transcribed text string, or empty string on failure.
        """
        return self.recognizer.transcribe(audio_bytes, content_type)

    # ── Future interface hooks ──
    # These exist as a design contract. Callers (e.g. BattleGround) can call
    # them today (they are no-ops) and behaviour will be added when VAD /
    # wake-word / continuous-listening is implemented.

    def start_listening(self) -> None:
        """Signal the voice manager to begin audio capture mode.

        V1: No-op — click-to-talk is managed by the browser UI directly.
        Future: Start VAD, wake word detection, or hardware trigger.
        """
        pass

    def stop_listening(self) -> None:
        """Signal the voice manager to stop audio capture mode.

        V1: No-op — click-to-talk is managed by the browser UI directly.
        Future: Stop VAD or wake word detection.
        """
        pass
