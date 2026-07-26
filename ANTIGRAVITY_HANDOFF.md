# JATAYU OS — Handoff to Antigravity (2026-07-26 night session)

You are picking up an active repair session on JATAYU OS
(github.com/sujaybhat786/Jatayu-agentic-OS). A lot has already been fixed
and verified tonight. This document tells you (1) what's already done and
confirmed working, (2) exactly what's left to apply for tomorrow morning's
launch, and (3) what NOT to touch. Follow it in order. Report raw terminal
output at each checkpoint -- not a summary -- before moving to the next step.

---

## 0. Verify current state before doing anything

Run this first:
```
cd "/Users/sujayabhat/Downloads/Agentic OS"
git log --oneline -10
python3 -m unittest tests.test_memory -v
```

You should see recent commits mentioning "Phase 1", "Phase 2", "field clobbering",
and "web search", and the test suite should show 7 tests, OK. If it doesn't
match this, stop and report the actual output before continuing -- don't assume
and don't patch on top of an unknown state.

---

## 1. What's already done and confirmed working (do not redo)

- Memory system (SQLite + FTS5): fast, relevance-based retrieval. Fixed a
  bug where every message dumped full contact/contract details of every
  person/project regardless of relevance (now token-bounded).
- Prompt composition in brain.py: replaced a fragile string-matching
  hack with an explicit _compose_prompt() method.
- Entity source of truth: SQLite database is now the only place
  structured people/project facts get saved -- Obsidian is no longer used
  for that (freeform notes only).
- Critical data-loss bug fixed: remember_entity's tool wrapper used to
  default unspecified fields to "" instead of None, so any partial
  update (e.g. adding a note about someone) silently wiped their email/phone/
  etc. Fixed, with a permanent regression test
  (test_partial_update_does_not_clobber_existing_fields).
- Diagnostic logging: empty Gemini responses now log the real
  finish_reason/safety_ratings instead of nothing.
- Gmail/Google Workspace: re-authenticated with a fresh OAuth client
  (the old one was deleted after being exposed in git history). Confirmed
  working live -- reading and sending real email.
- Telegram: confirmed working live, both directions.
- Web search: replaced the dead Hermes web-research path with real
  Gemini Google Search grounding (jatayu/tools/web_search.py). Confirmed
  live with genuinely current, verified news.

None of the above needs any further action. If any of it looks missing when
you check the repo, say so -- don't silently re-apply guesses.

---

## 2. Tonight's remaining work -- apply this now

Two files to save into the project first:
- tonight_updates.patch -> save into the project root
  (/Users/sujayabhat/Downloads/Agentic OS/)
- test_scheduler.py -> save into tests/test_scheduler.py

### Step 1 -- try the patch
```
git apply --check tonight_updates.patch
```
If nothing prints, apply it:
```
git apply tonight_updates.patch
```

### Step 2 -- if the patch fails, apply these exact changes manually instead

**config.yaml** -- find:
```
data_dir: data
```
Replace with:
```
  ## Tone & Cultural Voice
  Sujay values Hindu culture and tradition genuinely, not decoratively. Where it fits naturally
  (morning greetings, closing out a good week, encouraging him through a hard task) -- not in every
  message -- you may include ONE small, well-known, accurately-quoted line, drawn only from this
  list, never invented or paraphrased into something that sounds Sanskrit but isn't:
    - "Om Shanti, Shanti, Shanti" (peace invocation, Upanishads)
    - "Satyameva Jayate" -- truth alone triumphs (Mundaka Upanishad)
    - "Tamso Ma Jyotirgamaya" -- lead me from darkness to light (Brihadaranyaka Upanishad)
    - "Karmanye Vadhikaraste, Ma Phaleshu Kadachana" -- you have a right to your work, never to its
      fruits (Bhagavad Gita 2.47) -- fits well when he's grinding on something without guaranteed payoff
    - "Vasudhaiva Kutumbakam" -- the world is one family (Maha Upanishad)
  Never fabricate a verse, never attribute a quote to the wrong source, and never force one in if it
  doesn't genuinely fit the moment -- restraint here matters more than frequency.

data_dir: data
```
(Keep the 2-space indent on the new block exactly as shown, matching the rest of system_prompt: |.)

**jatayu/tools/scheduler.py** -- find:
```
def _load() -> dict:
    """Load the schedule. Auto-resets if the date has changed."""
    path = _schedule_path()
    if path.exists():
        with open(path) as f:
            data = json.load(f)
        # If the stored date is today, use it. Otherwise start fresh.
        if data.get("date") == str(date.today()):
            return data
    return {"date": str(date.today()), "tasks": []}
```
Replace with:
```
def _load() -> dict:
    """Load the schedule. Tasks persist across days until explicitly completed --
    previously this reset to empty on every date change, silently deleting
    anything not finished by midnight. That's fixed: only a brand-new file
    starts with today's date; existing tasks are never auto-wiped."""
    path = _schedule_path()
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {"date": str(date.today()), "tasks": []}
```

**jatayu/voice/speech_formatter.py** -- find:
```
    # Step 6: Handle long responses
    result = _handle_long_response(result)

    return result.strip()
```
Replace with:
```
    # Step 6: Handle long responses
    result = _handle_long_response(result)

    # Step 7: Respell known Sanskrit/Hindi phrases phonetically so ElevenLabs
    # pronounces them correctly (English-tuned TTS engines often flatten
    # Sanskrit vowel length otherwise). Written chat text is untouched --
    # this only affects what's sent to the voice engine.
    result = _apply_sanskrit_pronunciation(result)

    return result.strip()


# Phonetic respellings for known Sanskrit/Hindi phrases -- elongated vowels
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
```

**jatayu/web/static/app.js** -- four separate small edits:

(a) Find:
```
  App.streamBuf = "";
  setOrbState("THINKING");
```
Replace with:
```
  App.streamBuf = "";
  setOrbState("THINKING");

  if (App.conversation_mode !== "voice") {
    showTypingIndicator();
  }
```

(b) Find:
```
function appendChatBubble(role, text) {
  const empty = $("#chat-empty");
  if (empty) empty.remove();
  const div = document.createElement("div");
  div.className = "msg " + role;
  div.innerHTML =
    role === "assistant"
      ? '<span class="avatar" aria-hidden="true"></span><div class="bubble"></div>'
      : '<div class="bubble"></div>';
  div.querySelector(".bubble").textContent = text;
  const thread = $("#chat-thread");
  if (thread) thread.appendChild(div);
  return div;
}
```
Replace with:
```
function appendChatBubble(role, text) {
  const empty = $("#chat-empty");
  if (empty) empty.remove();
  const div = document.createElement("div");
  div.className = "msg " + role;
  div.innerHTML =
    role === "assistant"
      ? '<span class="avatar" aria-hidden="true"></span><div class="bubble"></div>'
      : '<div class="bubble"></div>';
  div.querySelector(".bubble").textContent = text;
  const thread = $("#chat-thread");
  if (thread) thread.appendChild(div);
  return div;
}

function showTypingIndicator() {
  removeTypingIndicator();
  const empty = $("#chat-empty");
  if (empty) empty.remove();
  const div = document.createElement("div");
  div.className = "msg assistant typing-indicator";
  div.id = "typing-indicator";
  div.innerHTML =
    '<span class="avatar" aria-hidden="true"></span>' +
    '<div class="bubble"><span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span></div>';
  const thread = $("#chat-thread");
  if (thread) {
    thread.appendChild(div);
    thread.scrollTop = thread.scrollHeight;
  }
  return div;
}

function removeTypingIndicator() {
  const el = document.getElementById("typing-indicator");
  if (el) el.remove();
}
```

(c) Find (inside handleChunk):
```
  } else {
    if (!App.chatStreamEl) App.chatStreamEl = appendChatBubble("assistant", "");
    if (App.chatStreamEl) {
      App.chatStreamEl.querySelector(".bubble").textContent = App.streamBuf;
      scrollThread();
    }
  }
}
```
Replace with:
```
  } else {
    if (!App.chatStreamEl) {
      removeTypingIndicator();
      App.chatStreamEl = appendChatBubble("assistant", "");
    }
    if (App.chatStreamEl) {
      App.chatStreamEl.querySelector(".bubble").textContent = App.streamBuf;
      scrollThread();
    }
  }
}
```

(d) Find (inside handleDone):
```
  } else {
    if (!App.chatStreamEl) App.chatStreamEl = appendChatBubble("assistant", "");
    if (App.chatStreamEl) {
      App.chatStreamEl.querySelector(".bubble").textContent = msg.text;
      App.chatStreamEl = null;
      scrollThread();
    }
    setOrbState("IDLE");
```
Replace with:
```
  } else {
    if (!App.chatStreamEl) {
      removeTypingIndicator();
      App.chatStreamEl = appendChatBubble("assistant", "");
    }
    if (App.chatStreamEl) {
      App.chatStreamEl.querySelector(".bubble").textContent = msg.text;
      App.chatStreamEl = null;
      scrollThread();
    }
    setOrbState("IDLE");
```

(e) Find (inside handleTurnError):
```
  } else {
    if (App.chatStreamEl) {
      App.chatStreamEl.querySelector(".bubble").textContent = text;
      App.chatStreamEl = null;
    } else {
      appendChatBubble("assistant", text);
    }
  }
```
Replace with:
```
  } else {
    removeTypingIndicator();
    if (App.chatStreamEl) {
      App.chatStreamEl.querySelector(".bubble").textContent = text;
      App.chatStreamEl = null;
    } else {
      appendChatBubble("assistant", text);
    }
  }
```

**jatayu/web/static/style.css** -- find:
```
.msg.assistant .bubble {
  border-left: 2px solid var(--color-primary);
  box-shadow: inset 8px 0 18px -12px var(--color-primary-dim);
  background: var(--panel-bg);
  color: var(--color-primary-hi);
}
```
Replace with:
```
.msg.assistant .bubble {
  border-left: 2px solid var(--color-primary);
  box-shadow: inset 8px 0 18px -12px var(--color-primary-dim);
  background: var(--panel-bg);
  color: var(--color-primary-hi);
}

.typing-indicator .bubble {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 14px 18px;
}
.typing-dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  background: var(--color-primary);
  opacity: 0.4;
  animation: typing-bounce 1.2s ease-in-out infinite;
}
.typing-dot:nth-child(2) { animation-delay: 0.15s; }
.typing-dot:nth-child(3) { animation-delay: 0.3s; }
@keyframes typing-bounce {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
  30% { transform: translateY(-5px); opacity: 1; }
}
```

---

## 3. Verify, commit, push

```
python3 -m unittest tests.test_memory tests.test_scheduler -v
```
Expect 8 tests, OK. Then:
```
git add -A
git commit -m "Tonight: task persistence fix, Sanskrit tone, TTS pronunciation, typing indicator"
git push
```

---

## 4. Live test checklist -- paste back the REAL output of each, not a summary

1. Restart the server:
```
pkill -f "jatayu.web.server"
python3 -m jatayu.web.server
```
2. In the browser (localhost:7860), send: Jai Shri Ram Jatayu
   -> expect a reply containing Jai Shri Ram Captain.
3. Send: Add a task: draft launch video script, priority high
   then send: what are my tasks?
   -> confirm the task actually appears.
4. Send any normal message and just watch the chat while waiting for the
   reply -- confirm three bouncing dots appear immediately, before any text
   streams in.

Report the literal text of what appeared for all four -- copy-paste, don't
paraphrase.

---

## 5. Do NOT build any of these tonight -- explicitly out of scope

- Instagram integration (dropped entirely, not needed)
- The "instant filler reply while thinking in background" mechanism
- Triple-click-on-orb to stop voice playback
- Any Battleground UI redesign/"wow" pass
- An automated, self-updating weekly business report -- tonight's briefing
  is manually fed by Sujay (real numbers, told to JATAYU directly), not
  pulled automatically from any live data source. Building the automated
  version properly is future work, not tonight's work.

If asked to do any of these anyway, don't -- flag it back to Sujay instead
of quietly doing it.

---

## 6. Still outstanding, not urgent tonight

- Telegram bot token has still not been rotated (was exposed earlier in
  chat history). Should happen this week, not blocking launch.
- GitHub repo is still public. Should be made private this week.

---

## 7. Reporting back

For every step above, paste the actual terminal/browser output. If
something fails, paste the actual error -- do not describe what you expect
it would say, do not summarize a success that you didn't literally see
happen. This project has been burned before by confident-sounding reports
that didn't match reality -- raw output only, every time.
