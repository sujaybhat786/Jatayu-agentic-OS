# JATAYU OS — 503 Reliability Fix + UI Re-check (Antigravity Prompt)

Two separate things in this document. Do PART A first, fully, with proof.
Then PART B. Report raw output for every checkpoint — no summaries, no
"all requirements complete" statements unless the actual grep/git output
you paste directly under it proves it.

---

## PART A — Diagnose whether the last UI update actually happened

Run these and paste the raw output before doing anything else:

```bash
cd "/Users/sujayabhat/Downloads/Agentic OS"
git log --oneline -5
grep -n "AKRAMAN" jatayu/web/static/index.html
grep -n "transcript-toggle" jatayu/web/static/index.html
grep -n "Core Reasoning Engine" jatayu/web/static/index.html
```

- If `git log` shows a commit starting with "UI:" AND all three greps find
  matches → the UI update already happened, skip re-applying it, go to Part B.
- If NOT → the UI update from `UI_UPDATE_ANTIGRAVITY_PROMPT.md` never
  actually ran. Open that file (it should still be in this project folder)
  and execute it now, fully, following its own instructions exactly. Do not
  report success until the same four greps above actually find matches —
  paste that proof.

---

## PART B — Fix repeated 503 "model overloaded" errors

### The problem
Google's Gemini API occasionally returns a 503 (temporary overload).
Currently JATAYU only retries once, waits a fixed 0.5 seconds, and if that
single retry also fails, shows the user the raw exception text directly —
which is what happened during a live demo.

### The fix — apply these two exact changes to `jatayu/brain.py`

**Change 1 — find:**
```python
        """Single-stream agent loop — no double-call, no re-issue.

        Retry policy: 503/429 errors get up to 2 retries per iteration
        with 1s/2s exponential backoff.
        """
        max_iterations = 10
        tool_config = self._build_tool_config(tools_to_expose)

        gen_config = types.GenerateContentConfig(
            system_instruction=system_prompt,
        )
        if tool_config:
            gen_config.tools = tool_config

        demo_mode = get_config().get("demo_mode", False)
        max_attempts = 1 if demo_mode else 2  # Demo mode: 0 retries (10s max); Normal mode: 1 retry (20.5s max)
```
**Replace with:**
```python
        """Single-stream agent loop — no double-call, no re-issue.

        Retry policy: transient errors (503/429/timeout) get retried with
        real exponential backoff (1s, 2s, 4s...) instead of a single fixed
        0.5s wait — Google's 503 "model overloaded" errors are often
        transient but can take a few seconds to clear, so a single quick
        retry wasn't enough in practice.
        """
        max_iterations = 10
        tool_config = self._build_tool_config(tools_to_expose)

        gen_config = types.GenerateContentConfig(
            system_instruction=system_prompt,
        )
        if tool_config:
            gen_config.tools = tool_config

        demo_mode = get_config().get("demo_mode", False)
        # Demo mode intentionally stays fast/tight-latency (unchanged). Normal
        # mode now gets 3 retries (4 attempts total) with real backoff, since
        # one 0.5s retry was not enough to ride out real overload periods.
        max_attempts = 1 if demo_mode else 4
```

**Change 2 — find:**
```python
                    if is_transient and stream_attempts < max_attempts:
                        wait = 0.5
                        logger.warning(
                            "Brain: transient error iteration=%d attempt=%d/%d "
                            "(retrying in %.1fs): %s", iteration, stream_attempts, max_attempts, wait, e
                        )
                        if on_status:
                            on_status(f"Model busy/timing out, retrying in {wait:.1f}s...")
                        import time as _time
                        _time.sleep(wait)
                        # Clear partials before retry
                        function_calls, text_parts, raw_parts = [], [], []
                        continue
```
**Replace with:**
```python
                    if is_transient and stream_attempts < max_attempts:
                        wait = min(1.0 * (2 ** (stream_attempts - 1)), 8.0)  # 1s, 2s, 4s, capped at 8s
                        logger.warning(
                            "Brain: transient error iteration=%d attempt=%d/%d "
                            "(retrying in %.1fs): %s", iteration, stream_attempts, max_attempts, wait, e
                        )
                        if on_status:
                            on_status(f"Model busy/timing out, retrying in {wait:.1f}s...")
                        import time as _time
                        _time.sleep(wait)
                        # Clear partials before retry
                        function_calls, text_parts, raw_parts = [], [], []
                        continue
```

**Change 3 — find:**
```python
            except Exception as e:
                logger.info("Request Cancelled: session=%s (Exception: %s)", session_id, e)
                session.set_state(RequestState.CANCELLED, f"Exception: {e}")
                session.history = session.history[:initial_history_len]
                error_msg = f"⚠️ Couldn't reach the model: {e}"
                log_error("send", str(e))
                if on_chunk:
                    on_chunk(error_msg)
                return error_msg
```
**Replace with:**
```python
            except Exception as e:
                logger.info("Request Cancelled: session=%s (Exception: %s)", session_id, e)
                session.set_state(RequestState.CANCELLED, f"Exception: {e}")
                session.history = session.history[:initial_history_len]
                err_str = str(e).lower()
                is_transient = any(kw in err_str for kw in (
                    "503", "unavailable", "429", "resource_exhausted",
                    "timed out", "timeout", "time out", "readtimeout"
                ))
                if is_transient:
                    error_msg = ("⚠️ Google's model servers are temporarily overloaded — this isn't "
                                 "a JATAYU bug. It usually clears within a few seconds; please try again.")
                else:
                    error_msg = f"⚠️ Couldn't reach the model: {e}"
                log_error("send", str(e))
                if on_chunk:
                    on_chunk(error_msg)
                return error_msg
```

### New test file — save as `tests/test_brain_retry.py`

(Attached as a separate file: `test_brain_retry.py` — save it into the
`tests/` folder as-is, no edits needed.)

### Verify, commit, push

```bash
python3 -m unittest tests.test_memory tests.test_scheduler tests.test_brain_retry -v
```
Expect **10 tests, OK**. Then:
```bash
git add -A
git commit -m "Fix: real exponential backoff + clean message for Gemini 503/transient errors"
git push
```

### Proof required in your report (not optional)
```bash
grep -n "temporarily overloaded" jatayu/brain.py
git log --oneline -3
```
Paste the actual output of both — a claim of "done" without this pasted
underneath it will not be accepted as complete.

---

## Reminder — same rule as always

Every checkpoint above needs the literal terminal output pasted, not a
description of what it should show. If anything fails or doesn't match,
say so exactly as it appears — do not smooth it over.
