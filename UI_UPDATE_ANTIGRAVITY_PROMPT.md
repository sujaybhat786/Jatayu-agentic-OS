# JATAYU OS — UI-Only Update (Antigravity Prompt)

IMPORTANT GROUND RULES — read before doing anything:
- This is a UI-ONLY pass. Do not touch any Python backend file, the voice
  pipeline, session/conversation logic, or anything under jatayu/brain.py,
  jatayu/web/server.py, jatayu/voice/, or jatayu/conversation/.
- Only these three files should change: jatayu/web/static/index.html,
  jatayu/web/static/app.js, jatayu/web/static/style.css.
- If applying any single change below turns out to require touching
  something backend, or risks breaking an existing working flow, STOP and
  skip that one specific change — report back what you skipped and why.
  Do not improvise a workaround that touches backend to make a UI change
  "work" — existing workflow stability outranks any UI improvement here.
- One explicitly excluded item, do NOT attempt it in this pass: making
  voice/Battleground conversations persist correctly as a single chat
  session. That needs live testing to properly diagnose and was
  deliberately left out of this UI-only batch — leave it alone.

---

## Change 1 — Remove the "Google Gemini" model branding

File: `jatayu/web/static/index.html`

Find:
```html
          <div class="hud-card model-card active-primary">
            <div class="model-card-header">
              <h3>Google Gemini</h3>
              <span class="badge ok">ACTIVE PRIMARY</span>
            </div>
            <p class="model-desc">Gemini 3.5 Flash & Gemini 3.1 Pro Preview (Default Core LLM)</p>
            <div class="service-pills">
              <span class="pill">Reasoning</span>
              <span class="pill">Multimodal</span>
              <span class="pill">Code</span>
            </div>
          </div>
```

Replace with:
```html
          <div class="hud-card model-card active-primary">
            <div class="model-card-header">
              <h3>Core Reasoning Engine</h3>
              <span class="badge ok">ACTIVE PRIMARY</span>
            </div>
            <p class="model-desc">Multimodal reasoning, code, and agentic tool use (Default Core LLM)</p>
            <div class="service-pills">
              <span class="pill">Reasoning</span>
              <span class="pill">Multimodal</span>
              <span class="pill">Code</span>
            </div>
          </div>
```

---

## Change 2 — Rename the voice button to "AKRAMAN" and remove the space-bar hint text

File: `jatayu/web/static/index.html`

Find:
```html
        <button id="micBtn" class="btn primary" aria-label="Engage Voice Link">Engage Voice Link</button>
```
Replace with:
```html
        <button id="micBtn" class="btn primary" aria-label="Engage Voice Link">AKRAMAN</button>
```
(aria-label stays descriptive on purpose, for screen-reader accessibility — only the visible label changes.)

Find:
```html
        <div id="hint" class="bg-voice-status">Tap orb or hold [ Space ] to speak</div>
```
Replace with:
```html
        <div id="hint" class="bg-voice-status"></div>
```

---

## Change 3 — Move the voice transcript into a small collapsible round toggle (top-right corner)

File: `jatayu/web/static/index.html`

Find:
```html
      <!-- Stage Bottom & Voice Link Button -->
      <div class="bg-stage-bottom">
        <div id="stateLabel">◈ Standing By ◈</div>
        <p id="bg-user-line" class="bg-user-transcript"></p>
        <p id="bg-assistant-text" class="bg-assistant-transcript"></p>
        <canvas id="waveform"></canvas>
        <button id="micBtn" class="btn primary" aria-label="Engage Voice Link">AKRAMAN</button>
        <div id="hint" class="bg-voice-status"></div>
        <footer class="bg-footer mono">
          <span id="bg-model-footer">—</span>
        </footer>
      </div>
```
Replace with:
```html
      <!-- Transcript toggle: small round dot (top-right) that expands into a caption panel -->
      <button id="transcript-toggle" aria-label="Show voice transcript" title="Show voice transcript"></button>
      <div id="transcript-panel">
        <p id="bg-user-line" class="bg-user-transcript"></p>
        <p id="bg-assistant-text" class="bg-assistant-transcript"></p>
      </div>

      <!-- Stage Bottom & Voice Link Button -->
      <div class="bg-stage-bottom">
        <div id="stateLabel">◈ Standing By ◈</div>
        <canvas id="waveform"></canvas>
        <button id="micBtn" class="btn primary" aria-label="Engage Voice Link">AKRAMAN</button>
        <div id="hint" class="bg-voice-status"></div>
        <footer class="bg-footer mono">
          <span id="bg-model-footer">—</span>
        </footer>
      </div>
```
Note: this only relocates the two existing `<p>` elements (same IDs, so the
JS that fills them in with live transcript text keeps working exactly as
before) and adds one new button — it does not change any voice/transcription
logic.

File: `jatayu/web/static/style.css`

Find:
```css
.bg-assistant-transcript {
  font-family: var(--font-body);
  font-size: 14px;
  color: var(--color-primary-hi);
  text-align: center;
  max-width: 520px;
  margin: 0 auto 4px;
  opacity: 0.95;
  line-height: 1.45;
}
```
Replace with:
```css
.bg-assistant-transcript {
  font-family: var(--font-body);
  font-size: 14px;
  color: var(--color-primary-hi);
  text-align: center;
  max-width: 520px;
  margin: 0 auto 4px;
  opacity: 0.95;
  line-height: 1.45;
}

/* Transcript toggle: collapses to a small dot, expands into a caption panel */
#transcript-toggle {
  position: fixed;
  top: 20px;
  right: 20px;
  z-index: 5;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 1px solid var(--color-primary-dim);
  background: var(--color-primary);
  opacity: 0.55;
  cursor: pointer;
  padding: 0;
  transition: opacity 0.2s ease, transform 0.2s ease;
}
#transcript-toggle:hover { opacity: 1; transform: scale(1.15); }
#transcript-panel.open ~ #transcript-toggle,
#transcript-toggle.active { opacity: 1; }

#transcript-panel {
  position: fixed;
  top: 44px;
  right: 20px;
  z-index: 5;
  width: 300px;
  max-height: 220px;
  overflow-y: auto;
  padding: 14px 16px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--panel-bg);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  display: none;
}
#transcript-panel.open { display: block; }
#transcript-panel .bg-user-transcript,
#transcript-panel .bg-assistant-transcript {
  text-align: left;
  max-width: none;
  margin: 0 0 8px;
}
```

File: `jatayu/web/static/app.js`

Find:
```javascript
  if (micBtnEngage) micBtnEngage.addEventListener("click", toggleMic);
```
Replace with:
```javascript
  if (micBtnEngage) micBtnEngage.addEventListener("click", toggleMic);

  const transcriptToggle = $("#transcript-toggle");
  const transcriptPanel = $("#transcript-panel");
  if (transcriptToggle && transcriptPanel) {
    transcriptToggle.addEventListener("click", () => {
      transcriptPanel.classList.toggle("open");
      transcriptToggle.classList.toggle("active");
    });
  }
```

---

## Change 4 — Make the "speaking" state visibly red (currently near-identical to idle/thinking gold)

File: `jatayu/web/static/style.css`

Find:
```css
body[data-orb-state="SPEAKING"], body[data-state="speaking"] {
  --orb: #ffe9b0;
  --orb-pulse: 0.9s;
  --color-primary: #ffe9b0;
  --color-primary-hi: #ffffff;
  --color-primary-dim: #8f887a;
}
```
Replace with:
```css
body[data-orb-state="SPEAKING"], body[data-state="speaking"] {
  --orb: #ff4757;
  --orb-pulse: 0.9s;
  --color-primary: #ff4757;
  --color-primary-hi: #ffb3ba;
  --color-primary-dim: #8a2e37;
}
```
Listening (blue, `#7fd7ff`) and idle/neutral (gold, the default skin) are
untouched — only the speaking-state color changes, and it's picked to be
visually distinct from the existing red "ALERT" state color (`#ff6a4d`) so
speaking and kill-switch/alert don't look identical.

---

## Verify, commit, push

```bash
node --check jatayu/web/static/app.js
python3 -m unittest tests.test_memory tests.test_scheduler -v
```
Expect the JS check to print nothing (syntax OK) and **8 tests, OK** —
this confirms nothing backend broke, since none of these changes should
affect those tests at all.

```bash
git add -A
git commit -m "UI: remove Gemini branding, rename voice button to AKRAMAN, add collapsible transcript panel, red speaking state"
git push
```

---

## Live test checklist — report the REAL result of each, not a description of what should happen

1. Restart the server, open localhost:7860, go to Battleground.
2. Confirm the button now says **AKRAMAN** instead of "Engage Voice Link".
3. Confirm there's no more "Tap orb or hold [ Space ] to speak" text visible.
4. Look for a small dot in the top-right corner. Click it — confirm a panel
   opens showing transcript text. Click again — confirm it collapses back
   to a dot.
5. Go to the Integrations view — confirm the model card now says "Core
   Reasoning Engine", not "Google Gemini" / no Gemini version text visible.
6. Trigger a voice reply (ask it something via voice) and watch the orb
   while it's speaking — confirm it's now red, not gold/cream.

Paste back exactly what you see for each of the six, plus the raw output
of the test command and the git push. If anything looks different from
what's described above, say so plainly — don't round up to "it worked."
