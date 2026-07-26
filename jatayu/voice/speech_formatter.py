"""Speech Formatter — transforms written Brain output into natural spoken text.

This is a PURE TEXT FORMATTER. No AI. No API calls. No dependencies.
It sits between the Brain's written response and ElevenLabs TTS.

The written response displayed in Chat is NEVER modified.
Only the text sent to ElevenLabs is transformed.

Usage:
    from jatayu.voice.speech_formatter import format_for_speech
    spoken_text = format_for_speech(brain_response)
"""

from __future__ import annotations

import random
import re

# ══════════════════════════════════════════════════════════════
#  CONFIGURATION — edit these values to tune speech behaviour.
#  Do NOT bury configurable values deeper in the code.
# ══════════════════════════════════════════════════════════════

# Character count AFTER cleaning. Responses longer than this
# get summarised verbally. ~700 chars ≈ 23 seconds of speech.
LONG_RESPONSE_THRESHOLD = 700

# Natural intro phrases for summarised long responses.
# One is randomly selected each time to avoid repetition.
LONG_RESPONSE_INTROS = [
    "I've put the full details on your screen. Here's the key point.",
    "The complete version is displayed in chat. In short,",
    "I've written out the full response for you. To summarise,",
    "Done. The detailed version is on your screen. The gist is,",
    "I've drafted that for you. Here's a quick summary.",
    "The full version is on your screen. Let me give you the highlights.",
]

# Phrases used when a code block is removed from speech.
CODE_BLOCK_REPLACEMENT = "I've displayed the code on your screen."

# Maximum number of sentences to keep from a long response.
# 4 sentences allows spoken summaries to complete a natural thought.
SUMMARY_SENTENCE_COUNT = 4


# ══════════════════════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════════════════════

def format_for_speech(text: str) -> str:
    """Transform the Brain's written response into natural spoken text.

    Processing order matters — each step assumes the output of the previous.

    Args:
        text: Raw Brain output (may contain markdown, code, URLs, etc.)

    Returns:
        Cleaned, conversational text suitable for TTS.
    """
    if not text or not text.strip():
        return ""

    result = text

    # Step 1: Replace code blocks with a spoken announcement
    result = _strip_code_blocks(result)

    # Step 2: Strip markdown image/link syntax — keep label, drop URL
    result = _strip_links_and_images(result)

    # Step 3: Strip URLs and file paths
    result = _strip_urls(result)
    result = _strip_file_paths(result)

    # Step 4: Strip markdown formatting
    result = _strip_headings(result)
    result = _strip_bold_italic(result)
    result = _strip_bullet_markers(result)
    result = _strip_horizontal_rules(result)
    result = _strip_inline_code(result)

    # Step 5: Clean up whitespace
    result = _collapse_whitespace(result)

    # Step 6: Handle long responses
    result = _handle_long_response(result)

    # Step 7: Respell known Sanskrit/Hindi phrases phonetically so ElevenLabs
    # pronounces them correctly (English-tuned TTS engines often flatten
    # Sanskrit vowel length otherwise). Written chat text is untouched —
    # this only affects what's sent to the voice engine.
    result = _apply_sanskrit_pronunciation(result)

    return result.strip()


# Phonetic respellings for known Sanskrit/Hindi phrases — elongated vowels
# ("ee", "aa") nudge English TTS engines toward correct pronunciation.
# Case-insensitive match, applied whole-phrase so partial words aren't touched.
_SANSKRIT_PRONUNCIATION: dict[str, str] = {
    "jai shri ram": "Jai Shree Raam",
    "jai shree ram": "Jai Shree Raam",
    "har har mahadev": "Har Har Ma-haa-dayv",
    "om shanti": "Aum Shaanti",
    "satyameva jayate": "Satya-mayva Jayatay",
    "vasudhaiva kutumbakam": "Vasudhaiva Kutum-bakam",
}


def _apply_sanskrit_pronunciation(text: str) -> str:
    """Replace known phrases with phonetic spellings for TTS only."""
    result = text
    for phrase, phonetic in _SANSKRIT_PRONUNCIATION.items():
        result = re.sub(re.escape(phrase), phonetic, result, flags=re.IGNORECASE)
    return result


# ══════════════════════════════════════════════════════════════
#  FORMATTING RULES — each is a small, testable function
# ══════════════════════════════════════════════════════════════

def _strip_code_blocks(text: str) -> str:
    """Remove fenced code blocks (```...```) and replace with a spoken note."""
    # Track whether we replaced any code blocks
    has_code = bool(re.search(r"```", text))
    # Remove fenced code blocks (with or without language specifier)
    result = re.sub(r"```[\w]*\n.*?```", "", text, flags=re.DOTALL)
    # If we removed code, insert a spoken note (only once)
    if has_code and CODE_BLOCK_REPLACEMENT not in result:
        result = result.strip() + " " + CODE_BLOCK_REPLACEMENT
    return result


def _strip_links_and_images(text: str) -> str:
    """Convert [label](url) → label and ![alt](url) → (nothing)."""
    # Images: remove entirely (can't speak an image)
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
    # Links: keep the label text, drop the URL
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    return text


def _strip_urls(text: str) -> str:
    """Remove standalone URLs (http://, https://, www.)."""
    return re.sub(r"https?://\S+|www\.\S+", "", text)


def _strip_file_paths(text: str) -> str:
    """Remove Unix-style file paths like /path/to/file.py."""
    return re.sub(r"(?<!\w)/[\w./\-]+(?:\.\w+)", "", text)


def _strip_headings(text: str) -> str:
    """Remove markdown heading markers (# ## ### etc.)."""
    return re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)


def _strip_bold_italic(text: str) -> str:
    """Remove bold/italic markers: **, *, __, _."""
    # Bold first (** or __), then italic (* or _)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"\1", text)
    return text


def _strip_bullet_markers(text: str) -> str:
    """Remove bullet/list markers: - , * , 1. , 2. , etc."""
    # Numbered lists: "1. ", "2. ", etc.
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
    # Unordered lists: "- " or "* " at line start
    text = re.sub(r"^\s*[-*]\s+", "", text, flags=re.MULTILINE)
    return text


def _strip_horizontal_rules(text: str) -> str:
    """Remove markdown horizontal rules (---, ***, ___)."""
    return re.sub(r"^[\-\*_]{3,}\s*$", "", text, flags=re.MULTILINE)


def _strip_inline_code(text: str) -> str:
    """Remove backtick wrappers from inline code: `word` → word."""
    return re.sub(r"`([^`]+)`", r"\1", text)


def _collapse_whitespace(text: str) -> str:
    """Collapse multiple blank lines and excessive spaces into clean prose."""
    # Multiple newlines → single newline
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Multiple spaces → single space
    text = re.sub(r"[ \t]{2,}", " ", text)
    # Trim each line
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(lines)


def _handle_long_response(text: str) -> str:
    """If the cleaned text is too long, summarise for speech.

    Short/medium responses (≤ threshold): returned as-is.
    Long responses (> threshold): first N sentences + intro phrase.
    """
    if len(text) <= LONG_RESPONSE_THRESHOLD:
        return text

    # Extract sentences (simple split on . ! ? followed by space or end)
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    sentences = [s.strip() for s in sentences if s.strip()]

    if not sentences:
        return text

    # Take the first few sentences as the summary
    summary_sentences = sentences[:SUMMARY_SENTENCE_COUNT]
    summary = " ".join(summary_sentences)

    # Ensure the summary ends with proper punctuation
    if summary and summary[-1] not in ".!?":
        summary += "."

    # Prepend a natural intro phrase
    intro = random.choice(LONG_RESPONSE_INTROS)

    return f"{intro} {summary}"
