# JATAYU OS — Verbatim Save/Recall (Antigravity Prompt)

Adds a small, dedicated way to save text and get it back EXACTLY as given —
no Chief of Staff, no automation, no analysis. This is the simple version
Sujay actually asked for.

---

## Step 1 — `jatayu/memory/schema.sql`

Find:
```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_dedup ON entities(type, name_lower);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);
```
Replace with:
```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_dedup ON entities(type, name_lower);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);

-- ─────────────────────────────────────────────────────────────
-- NOTES: verbatim save/recall — separate from `facts` on purpose.
-- `facts` get surfaced to the LLM as context for it to reason/write about;
-- `notes` are for when the exact original text must come back unchanged
-- (e.g. "repeat exactly what I told you"). One row per label — saving to
-- the same label again replaces the previous content (last one wins).
-- ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS notes (
    label      TEXT PRIMARY KEY,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

---

## Step 2 — `jatayu/memory/store.py`

**(a)** Find:
```python
    def close(self):
        self._con.close()
```
Replace with:
```python
    def close(self):
        self._con.close()

    # ─────────────────────────── NOTES (verbatim) ───────────────────────────

    def save_note(self, label: str, content: str) -> str:
        """Save exact text under a label. Saving to the same label again
        REPLACES the previous content (last one wins) — this is intentional
        for things like a weekly update that gets refreshed each week."""
        now = _now()
        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO notes (label, content, created_at, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(label) DO UPDATE SET content=excluded.content, updated_at=excluded.updated_at""",
                (label, content, now, now),
            )
        return label

    def recall_note(self, label: str) -> Optional[str]:
        """Return the exact saved content for a label, or None if nothing's saved yet."""
        with self._cursor() as cur:
            cur.execute("SELECT content FROM notes WHERE label = ?", (label,))
            row = cur.fetchone()
        return row["content"] if row else None

    def list_notes(self) -> list[dict]:
        with self._cursor() as cur:
            cur.execute("SELECT label, content, updated_at FROM notes ORDER BY updated_at DESC")
            return [dict(r) for r in cur.fetchall()]
```

**(b)** Find:
```python
def _tool_get_person(name: str) -> str:
```
Replace with (this adds two new functions right before it — keep `_tool_get_person` itself unchanged, it's repeated here only to anchor the insertion point):
```python
def _tool_save_note(label: str, content: str) -> str:
    get_store().save_note(label, content)
    return f"✅ Saved verbatim under label '{label}'. Will be recalled exactly as written when asked."


def _tool_recall_note(label: str) -> str:
    content = get_store().recall_note(label)
    if content is None:
        return f"No note saved under label '{label}' yet."
    return content


def _tool_get_person(name: str) -> str:
```

**(c)** Find:
```python
    registry.register(Tool(
        name="get_person",
        description="Look up a stored person by name, nickname, alias, or relation.",
        handler=_tool_get_person,
        params=[
```
Replace with:
```python
    registry.register(Tool(
        name="save_note",
        description=(
            "Save text EXACTLY as given, under a label, for guaranteed word-for-word recall later "
            "(e.g. a weekly update the user dictates). Saving to the same label again REPLACES the "
            "previous content. Use this instead of `remember` when the user wants their exact wording "
            "preserved, not a fact you might paraphrase later."
        ),
        handler=_tool_save_note,
        params=[
            ToolParam(name="label", type="string", description="A short identifier, e.g. 'weekly_update'"),
            ToolParam(name="content", type="string", description="The exact text to save, verbatim"),
        ],
    ))

    registry.register(Tool(
        name="recall_note",
        description=(
            "Retrieve text previously saved with save_note, by label. IMPORTANT: when you get a result "
            "back from this tool, output it to the user EXACTLY as returned — verbatim, no paraphrasing, "
            "no summarizing, no reformatting, no added commentary mixed into it. A brief one-line intro "
            "before it (e.g. 'Here's what you told me:') is fine, but the saved content itself must be "
            "word-for-word identical to what's stored."
        ),
        handler=_tool_recall_note,
        params=[
            ToolParam(name="label", type="string", description="The label it was saved under"),
        ],
    ))

    registry.register(Tool(
        name="get_person",
        description="Look up a stored person by name, nickname, alias, or relation.",
        handler=_tool_get_person,
        params=[
```

---

## Step 3 — `jatayu/pipeline/intent_classifier.py`

**(a)** Find:
```python
_add(r"\bmy\s+memories?\b",                           "memory", "retrieve", 0.80)
```
Replace with:
```python
_add(r"\bmy\s+memories?\b",                           "memory", "retrieve", 0.80)
_add(r"\bweekly\s+update\b",                          "memory", "retrieve", 0.88)
_add(r"\brepeat\s+(exactly\s+)?what\s+i\s+told\b",     "memory", "retrieve", 0.92)
_add(r"\bread\s+(that|it)\s+back\b",                  "memory", "retrieve", 0.88)
```

**(b)** Find:
```python
    "memory":         ["remember", "forget", "update_memory", "list_memories", "remember_entity", "get_person", "get_project", "obsidian_read_note", "obsidian_search", "obsidian_write_note"],
```
Replace with:
```python
    "memory":         ["remember", "forget", "update_memory", "list_memories", "remember_entity", "get_person", "get_project", "save_note", "recall_note", "obsidian_read_note", "obsidian_search", "obsidian_write_note"],
```

---

## Step 4 — `jatayu/brain.py`

Find:
```python
ROUTING CARD (follow strictly):
- URL in message + "analyze / what do they do / summarize" → call web_search with the URL.
- Current events, facts you're unsure of, or anything needing up-to-date info → call web_search.
- Coding/debugging/dev task explicitly for the Hermes agent → hermes_ask (requires the local Hermes CLI to be installed; if it's not, tell the user plainly rather than pretending it worked).
```
Replace with:
```python
ROUTING CARD (follow strictly):
- URL in message + "analyze / what do they do / summarize" → call web_search with the URL.
- Current events, facts you're unsure of, or anything needing up-to-date info → call web_search.
- User dictates something they want repeated back EXACTLY later (a weekly update, a briefing, a script)
  → call save_note(label, content) with their exact words, not your summary of them.
- User asks to hear back a saved note/weekly update/briefing → call recall_note(label), then output its
  result verbatim — no paraphrasing, no summarizing, no editing. A short intro line before it is fine.
- Coding/debugging/dev task explicitly for the Hermes agent → hermes_ask (requires the local Hermes CLI to be installed; if it's not, tell the user plainly rather than pretending it worked).
```

---

## Step 5 — new test file

Save the attached `test_notes.py` into `tests/test_notes.py`.

---

## Verify, commit, push

```bash
python3 -m unittest tests.test_memory tests.test_scheduler tests.test_brain_retry tests.test_notes -v
```
Expect **14 tests, OK**.

```bash
python3 -c "from jatayu.brain import Brain; b = Brain(); n=[t.name for t in b.registry.list_tools()]; print('save_note' in n, 'recall_note' in n)"
```
Must print `True True`.

```bash
git add -A
git commit -m "Add verbatim save_note/recall_note — separate from facts, guaranteed exact recall"
git push
```

---

## Live test — the real proof, word for word

In the chat, send this exact message:
```
Save my weekly update, word for word: This week I closed 2 new clients and brought in $4,000 in revenue, published 3 websites with 2 more building. We hit 300K followers with 2.5M views and gained 3,000+ new followers.
```

Then, separately, ask:
```
Read back my weekly update.
```

Paste the second reply **character for character**. It must match the
sentence above exactly — same numbers, same punctuation, same wording. If
even one word is changed or summarized, this isn't done yet — say exactly
what differed, don't round it up to "close enough."
