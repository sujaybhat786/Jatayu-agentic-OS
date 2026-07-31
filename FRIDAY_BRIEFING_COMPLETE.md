# JATAYU OS — Friday-Night Briefing (Complete, Final Version)

This is the ONLY file you need for this feature — ignore
FRIDAY_BRIEFING_FEATURE.md and FRIDAY_BRIEFING_FINALIZE.md from earlier,
this one has the final wording built in from the start. Do these steps
in order, in your project folder:
```
cd "/Users/sujayabhat/Downloads/Agentic OS"
```

---

## Step 1 — `jatayu/pipeline/command_center.py` — three edits

**(a)** Find:
```python
_GREETINGS_IN = frozenset([
```
Replace with:
```python
def _is_friday_shutdown_briefing(lower: str) -> bool:
    """Detects Sujay's specific Friday-night shutdown ritual — the greeting
    invocation, plus a request for the weekly update, plus signing off for
    the week. Deliberately checks independent keywords rather than one rigid
    phrase, so natural variation in wording still matches."""
    has_ritual = "jai shri ram jatayu" in lower
    has_friday = "friday" in lower
    has_shutdown = any(kw in lower for kw in
                        ("shut down", "shutdown", "shutting down", "sign off", "signing off"))
    has_weekly_ask = "weekly" in lower and any(kw in lower for kw in ("update", "brief"))
    return has_ritual and has_friday and has_shutdown and has_weekly_ask


_GREETINGS_IN = frozenset([
```

**(b)** Find:
```python
        # ── 4. Time / date ─────────────────────────────────────────────────
        if lower in _TIME_QUERIES or lower.rstrip("?") in _TIME_QUERIES:
            return FastResult(text=self._now_formatted(), source="time")

        # ── 5. Direct tool reads (no reasoning needed) ─────────────────────
```
Replace with:
```python
        # ── 4. Time / date ─────────────────────────────────────────────────
        if lower in _TIME_QUERIES or lower.rstrip("?") in _TIME_QUERIES:
            return FastResult(text=self._now_formatted(), source="time")

        # ── 4.5. Friday-night shutdown ritual (greeting + weekly briefing) ──
        # Fully deterministic — greeting and sign-off are fixed by design so
        # they can never drift; only the middle content varies (whatever was
        # last saved via save_note under label 'weekly_update'). Falls through
        # to the Brain if nothing's been saved yet, or if this isn't really
        # what the user is asking for.
        if _is_friday_shutdown_briefing(lower):
            result = self._direct_friday_briefing()
            if result:
                return FastResult(text=result, source="tool")

        # ── 5. Direct tool reads (no reasoning needed) ─────────────────────
```

**(c)** Find:
```python
    def _direct_list_memories(self) -> str | None:
        """Read memories directly without the Brain."""
        try:
            from jatayu.memory.store import list_memories
            return list_memories()
        except Exception as e:
            logger.debug("CommandCenter: list_memories failed: %s", e)
            return None
```
Replace with:
```python
    def _direct_list_memories(self) -> str | None:
        """Read memories directly without the Brain."""
        try:
            from jatayu.memory.store import list_memories
            return list_memories()
        except Exception as e:
            logger.debug("CommandCenter: list_memories failed: %s", e)
            return None

    def _direct_friday_briefing(self) -> str | None:
        """Deterministic Friday-night shutdown ritual: greeting + verbatim
        weekly update (if one's been saved) + sign-off. Zero LLM involved —
        the greeting and sign-off are fixed by design so they can never
        drift week to week; only the middle content varies, sourced exactly
        as saved via save_note(label='weekly_update')."""
        try:
            from jatayu.memory.store import get_store
            content = get_store().recall_note("weekly_update")
            if not content:
                return None  # nothing saved yet — fall through to the Brain
            return f"Jai Shri Ram Captain! {content} Take rest, and see you at 4:00 AM on Monday, Har Har Mahadev Captain!"
        except Exception as e:
            logger.debug("CommandCenter: friday briefing failed: %s", e)
            return None
```

---

## Step 2 — new test file

Save the attached `test_friday_briefing.py` into `tests/test_friday_briefing.py`
(final wording already built in — nothing to edit).

---

## Step 3 — save this week's actual update (exact text, zero AI involved)

```bash
python3 -c "
from jatayu.memory.store import get_store

content = ('We had an absolutely banger week! We secured over \$2,500 in revenue and achieved over '
    '5 million views, with a total of 300K followers across social media platforms. Four websites and '
    'two apps are live, with five more in the pipeline set to launch next week. We\'ve acquired 3 new '
    'clients and sent proposals to 50 more prospective clients. Overall, it was a great, productive week, '
    'Captain. Multiple new projects are lined up for next week.')

get_store().save_note('weekly_update', content)
print('Saved. Recalled back:')
print(get_store().recall_note('weekly_update'))
"
```
Paste the output — confirm it reads back exactly as written above.

---

## Step 4 — verify, commit, push

```bash
python3 -m unittest tests.test_memory tests.test_scheduler tests.test_brain_retry tests.test_notes tests.test_friday_briefing -v
```
Expect **20 tests, OK**.

```bash
git add -A
git commit -m "Add deterministic Friday-night shutdown briefing (zero-LLM, guaranteed exact wording)"
git push
```

---

## Step 5 — live test, exact match required

Restart the server:
```bash
pkill -f "jatayu.web.server"
python3 -m jatayu.web.server
```

In the chat, send this EXACT message:
```
Jai Shri Ram Jatayu, Its Friday Night, Time to Shut down! Before going, brief me the weekly update!
```

Paste the reply, character for character. It must read exactly:

> Jai Shri Ram Captain! We had an absolutely banger week! We secured over $2,500 in revenue and achieved over 5 million views, with a total of 300K followers across social media platforms. Four websites and two apps are live, with five more in the pipeline set to launch next week. We've acquired 3 new clients and sent proposals to 50 more prospective clients. Overall, it was a great, productive week, Captain. Multiple new projects are lined up for next week. Take rest, and see you at 4:00 AM on Monday, Har Har Mahadev Captain!

If it's even one character off, say exactly what differed — don't round it up.
