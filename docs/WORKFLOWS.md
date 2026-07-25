# JATAYU Core v1.0 — Verified User Workflows

This document outlines the primary end-to-end user workflows supported and regression-tested in JATAYU Core v1.0.

---

## 1. Google Workspace Workflows

### Gmail Send & Read
- **Read**: User asks *"Check my latest emails"* → Intent Classifier routes to `email` → `google_gmail_read` fetches top messages → Brain formats plain-text summary.
- **Draft & Send**: User asks *"Send an email to John about the meeting"* → Model calls `google_gmail_draft` → Brain transitions to `WAITING_FOR_CONFIRMATION` and prompts user via UI → Upon clicking **Yes**, tool executes `google_gmail_send` and returns `✅ Email sent`.

### Drive & Docs
- **Title Resolution**: User asks *"Read my Marketing Strategy doc"* → Tool resolves document title automatically via Drive search (no raw file IDs exposed to user) → `google_docs_read` extracts content.

---

## 2. Messaging & Social Workflows

### Telegram Send
- **Workflow**: User asks *"Send a Telegram message to @alex saying I'm running 5 minutes late"* → Intent Classifier selects Telegram tools → Model calls `telegram_send` → User confirms action → Message delivered with HTTP status code error mapping if recipient is invalid.

---

## 3. Knowledge & Memory Workflows

### Obsidian Note Writing
- **Workflow**: User asks *"Save a note in Obsidian called Sprint Plan with today's action items"* → Tool checks local REST API connection (cached for 10s via `_is_running()`) → `obsidian_write_note` creates or appends to markdown file in vault.

### Long-Term Memory
- **Workflow**: User states *"Remember that I prefer dark mode and concise responses"* → Model calls `remember(fact="Prefers dark mode and concise responses", category="preference")` → Fact stored in `data/memory.json` and immediately available on next turn via `ContextRetriever` protected floor.

---

## 4. Verification

All workflows above are permanently verified against regressions via:
```bash
# Run automated regression test suite
./run_tests.sh
```
