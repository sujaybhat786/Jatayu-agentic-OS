"""Jatayu entry point — text REPL and voice mode.

Run with:
    python -m jatayu                 # text mode (default)
    python -m jatayu --voice         # push-to-talk voice mode
    python -m jatayu.main            # explicit module (text)
"""

import argparse
import sys

from jatayu.brain import Brain


def _print_chunk(text: str) -> None:
    """Streaming callback — prints each chunk as it arrives."""
    print(text, end="", flush=True)


def run_text_mode(brain: Brain) -> None:
    """Run the text conversation loop (REPL)."""
    name = brain.assistant_name
    print(f"🪶  {name} is ready. Type a message, or 'quit' to exit.\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print(f"\n\n👋  See you later!\n")
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "bye"):
            print(f"\n👋  See you later!\n")
            break

        print(f"\n{name}: ", end="", flush=True)
        brain.send(user_input, on_chunk=_print_chunk)
        print("\n")


def run_voice_mode(brain: Brain) -> None:
    """Run push-to-talk voice mode."""
    from jatayu.voice.push_to_talk import PushToTalk

    name = brain.assistant_name

    def handle_transcript(transcript: str, on_chunk=None) -> str:
        """Feed a voice transcript into the brain."""
        return brain.send(transcript, on_chunk=on_chunk)

    ptt = PushToTalk(
        on_transcript=handle_transcript,
        ptt_key="space",
    )
    ptt.run(assistant_name=name)


def main() -> None:
    """Parse args and run the appropriate mode."""
    parser = argparse.ArgumentParser(
        description="Jatayu — your personal assistant",
    )
    parser.add_argument(
        "--voice",
        action="store_true",
        help="Enable push-to-talk voice mode (hold SPACE to talk)",
    )
    args = parser.parse_args()

    print("\n🪶  Starting up…", flush=True)

    try:
        brain = Brain()
    except SystemExit:
        return
    except Exception as e:
        print(f"\n⚠️  Failed to initialize: {e}\n")
        return

    if args.voice:
        run_voice_mode(brain)
    else:
        run_text_mode(brain)


if __name__ == "__main__":
    main()
