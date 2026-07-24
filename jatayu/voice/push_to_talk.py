"""Push-to-talk controller — hold a key to speak, release to send.

Records audio while a key is held, transcribes on release, feeds the
transcript into the brain, and speaks the reply aloud. The text REPL
remains the canonical interface; this is an adapter on top.
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable

import numpy as np
import sounddevice as sd

from jatayu.voice import ears, mouth


# Audio recording settings
SAMPLE_RATE = 16000   # Hz — matches Deepgram's preferred rate
CHANNELS = 1          # mono
DTYPE = "int16"       # 16-bit PCM


class PushToTalk:
    """Push-to-talk voice controller.

    Hold spacebar (or configured key) to record, release to transcribe
    and process. Uses pynput for key detection.

    Args:
        on_transcript: Called with the transcribed text when recording
                       finishes. This should feed into the brain.
        on_reply_chunk: Called with each text chunk from the brain's reply
                        for both printing and TTS routing.
    """

    def __init__(
        self,
        on_transcript: Callable[[str], str],
        ptt_key: str = "space",
    ):
        self.on_transcript = on_transcript
        self.ptt_key = ptt_key
        self._recording = False
        self._audio_frames: list[np.ndarray] = []
        self._stream = None
        self._lock = threading.Lock()

    def run(self, assistant_name: str = "Jatayu") -> None:
        """Start the push-to-talk loop. Blocks until Ctrl+C.

        Args:
            assistant_name: Name to display in prompts.
        """
        from pynput import keyboard

        print(f"\n🎙️  Voice mode active. Hold SPACE to talk, release to send.")
        print(f"   Press Ctrl+C to exit.\n")

        key_to_match = self._resolve_key(self.ptt_key)

        def on_press(key):
            if self._key_matches(key, key_to_match):
                self._start_recording()

        def on_release(key):
            if self._key_matches(key, key_to_match):
                self._stop_and_process(assistant_name)

        try:
            with keyboard.Listener(
                on_press=on_press,
                on_release=on_release,
            ) as listener:
                listener.join()
        except KeyboardInterrupt:
            print(f"\n\n👋  See you later!\n")

    def _start_recording(self) -> None:
        """Begin capturing audio from the microphone."""
        with self._lock:
            if self._recording:
                return
            self._recording = True

        # Interrupt any ongoing playback
        mouth.interrupt()

        self._audio_frames = []
        print("🔴 Recording…", end="", flush=True)

        def audio_callback(indata, frames, time_info, status):
            if status:
                pass  # Ignore minor status warnings
            self._audio_frames.append(indata.copy())

        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            callback=audio_callback,
        )
        self._stream.start()

    def _stop_and_process(self, assistant_name: str) -> None:
        """Stop recording, transcribe, and process through the brain."""
        with self._lock:
            if not self._recording:
                return
            self._recording = False

        # Stop the audio stream
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        print(" done.", flush=True)

        # Combine recorded audio frames
        if not self._audio_frames:
            print("(no audio captured)")
            return

        audio_data = np.concatenate(self._audio_frames)
        audio_bytes = audio_data.tobytes()

        # Transcribe
        print("📝 Transcribing…", end="", flush=True)
        transcript = ears.transcribe(audio_bytes, SAMPLE_RATE)

        if not transcript.strip():
            print(" (couldn't make out what you said)")
            return

        print(f" \"{transcript}\"")

        # Process through brain — on_transcript returns the full reply
        print(f"\n{assistant_name}: ", end="", flush=True)

        # Collect chunks for both printing and TTS
        reply_chunks: list[str] = []

        def collect_and_print(chunk: str) -> None:
            print(chunk, end="", flush=True)
            reply_chunks.append(chunk)

        full_reply = self.on_transcript(transcript, collect_and_print)
        print("\n")

        # Speak the reply
        if full_reply and full_reply.strip():
            mouth.speak(full_reply)

    @staticmethod
    def _resolve_key(key_name: str):
        """Convert a key name string to a pynput key object."""
        from pynput import keyboard
        key_map = {
            "space": keyboard.Key.space,
            "ctrl": keyboard.Key.ctrl,
            "alt": keyboard.Key.alt,
            "shift": keyboard.Key.shift,
            "tab": keyboard.Key.tab,
        }
        return key_map.get(key_name.lower(), keyboard.Key.space)

    @staticmethod
    def _key_matches(pressed_key, target_key) -> bool:
        """Check if a pressed key matches the target."""
        return pressed_key == target_key
