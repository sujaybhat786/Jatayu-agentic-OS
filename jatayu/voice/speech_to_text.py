"""Speech-to-Text abstraction layer.

Defines the SpeechRecognizer interface and built-in provider implementations.
To swap STT providers, subclass SpeechRecognizer and implement transcribe().
The rest of the system calls get_default_recognizer() and never touches
provider-specific code directly.

Phase A improvements (July 2026):
  - language="en"   forces English-letter output (no Devanagari/Kannada/etc.)
  - temperature=0   deterministic output, best for proper nouns
Phase B improvements (July 2026):
  - stt_vocabulary.yaml loaded at startup; domain prompt sent with every call
Phase C prep:
  - STT_MODEL env var lets you switch models without touching code
"""

from __future__ import annotations

import os
import pathlib
from abc import ABC, abstractmethod

import httpx


# ── Vocabulary loading (Phase B) ──────────────────────────────────────────────

_VOCAB_PATH = pathlib.Path(__file__).parent / "stt_vocabulary.yaml"


def _parse_simple_yaml(path: pathlib.Path) -> dict:
    """Minimal YAML parser for the vocabulary file (no PyYAML dependency).

    Only handles the specific structure used by stt_vocabulary.yaml:
        category_name:
          - term one
          - term two
    """
    result: dict[str, list[str]] = {}
    current_key: str | None = None

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.endswith(":") and not stripped.startswith("-"):
            current_key = stripped[:-1]
            result[current_key] = []
        elif stripped.startswith("- ") and current_key is not None:
            result[current_key].append(stripped[2:].strip())

    return result


def _load_vocabulary_prompt() -> str:
    """Load stt_vocabulary.yaml and build a compact context prompt string.

    The prompt primes the STT model so proper nouns (Sanskrit, Indian names,
    project names) are spelled correctly in English letters.

    Returns an empty string if the file is missing or unreadable.
    Hard cap: 900 chars (~200 tokens) to respect the OpenAI 224-token limit.
    """
    if not _VOCAB_PATH.exists():
        return ""

    try:
        try:
            import yaml  # type: ignore[import]
            with _VOCAB_PATH.open(encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except ImportError:
            data = _parse_simple_yaml(_VOCAB_PATH)
    except Exception as e:
        print(f"STT: Could not load stt_vocabulary.yaml: {e}")
        return ""

    # Flatten all categories into one deduplicated list
    all_terms: list[str] = []
    for category_terms in data.values():
        if isinstance(category_terms, list):
            for term in category_terms:
                if isinstance(term, str) and term not in all_terms:
                    all_terms.append(term)

    if not all_terms:
        return ""

    # Contextual sentence format (more effective than a raw comma list)
    terms_str = ", ".join(all_terms)
    prompt = (
        f"This is a voice conversation with JATAYU. "
        f"The speaker may reference: {terms_str}."
    )

    # Hard cap to stay within the API token limit
    if len(prompt) > 900:
        prompt = prompt[:897] + "..."

    return prompt


# Built once at module load time — reused for every API call
_VOCABULARY_PROMPT: str = _load_vocabulary_prompt()


# ── Abstract interface ─────────────────────────────────────────────────────────

class SpeechRecognizer(ABC):
    """Abstract STT interface — swap implementations to change providers."""

    @abstractmethod
    def transcribe(self, audio_bytes: bytes, content_type: str = "audio/webm") -> str:
        """Convert audio bytes to text.

        Args:
            audio_bytes: Raw audio data from the browser or microphone.
            content_type: MIME type of the audio (e.g. 'audio/webm', 'audio/mp4').

        Returns:
            Transcribed text in English letters, or empty string on failure.
        """
        ...


# ── OpenAI implementation ──────────────────────────────────────────────────────

class OpenAIWhisperRecognizer(SpeechRecognizer):
    """OpenAI Whisper / GPT-4o-Transcribe STT provider.

    Calls the REST API directly via httpx — no openai SDK dependency.

    Active parameters:
      language="en"   — forces English-letter output for ALL spoken content.
                        Prevents Devanagari, Kannada, Tamil, etc. from appearing.
      temperature=0   — deterministic output (best spelling consistency).
      prompt          — domain vocabulary from stt_vocabulary.yaml.

    Model override: set STT_MODEL env var (default: whisper-1).
    Examples:
      STT_MODEL=whisper-1               (current default)
      STT_MODEL=gpt-4o-mini-transcribe  (Phase C upgrade candidate)
      STT_MODEL=gpt-4o-transcribe       (highest accuracy)
    """

    DEFAULT_MODEL = "whisper-1"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "").strip()
        self.model = os.getenv("STT_MODEL", self.DEFAULT_MODEL).strip()

        # Log active configuration at startup
        term_count = len([t for t in _VOCABULARY_PROMPT.split(",") if t.strip()]) if _VOCABULARY_PROMPT else 0
        print(f"STT ready: model={self.model}, language=en, vocabulary_terms={term_count}")
        if not _VOCABULARY_PROMPT:
            print("STT: stt_vocabulary.yaml not found — no domain priming active")

    def _ext_from_content_type(self, content_type: str) -> str:
        """Map MIME type to a file extension the OpenAI API accepts."""
        mapping = {
            "mp4": "mp4",
            "ogg": "ogg",
            "wav": "wav",
            "flac": "flac",
            "m4a": "m4a",
            "mpeg": "mp3",
        }
        for key, ext in mapping.items():
            if key in content_type:
                return ext
        return "webm"

    def transcribe(self, audio_bytes: bytes, content_type: str = "audio/webm") -> str:
        if not self.api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. "
                "Add it to .env to use OpenAI Whisper STT."
            )

        ext = self._ext_from_content_type(content_type)

        # Build multipart form fields
        fields: dict = {
            "file": (f"audio.{ext}", audio_bytes, content_type),
            "model": (None, self.model),
            # PHASE A: Force English-letter output regardless of spoken language.
            # This prevents Devanagari, Kannada, Tamil, etc. from ever appearing.
            "language": (None, "en"),
            # PHASE A: Deterministic transcription — best for proper nouns.
            "temperature": (None, "0"),
        }

        # PHASE B: Attach vocabulary prompt if available
        if _VOCABULARY_PROMPT:
            fields["prompt"] = (None, _VOCABULARY_PROMPT)

        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    files=fields,
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("text", "")

        except httpx.HTTPStatusError as e:
            print(
                f"\nSTT error: HTTP {e.response.status_code}"
                f" — {e.response.text[:200]}"
            )
            return ""
        except Exception as e:
            print(f"\nSTT error: {e}")
            return ""


# ── Provider registry ──────────────────────────────────────────────────────────

_PROVIDER_MAP: dict[str, type[SpeechRecognizer]] = {
    "openai": OpenAIWhisperRecognizer,
    # Future providers — add implementations here, register below
    # "deepgram": DeepgramRecognizer,
    # "google": GoogleChirpRecognizer,
    # "local": LocalWhisperRecognizer,
}


def get_default_recognizer() -> SpeechRecognizer:
    """Return the active STT recognizer.

    Provider selected via STT_PROVIDER env var (default: openai).
    Model within the provider selected via STT_MODEL env var.
    """
    provider_name = os.getenv("STT_PROVIDER", "openai").lower().strip()
    provider_class = _PROVIDER_MAP.get(provider_name, OpenAIWhisperRecognizer)
    return provider_class()
