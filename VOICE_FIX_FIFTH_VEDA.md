# JATAYU OS — Fix Default Voice to Fifth Veda Narrator (Antigravity Prompt)

Billing is resolved on Sujay's end. This just fixes the config that was
still pointing at the wrong voice name.

---

## Step 1 — confirm current state

```bash
cd "/Users/sujayabhat/Downloads/Agentic OS"
grep -n "elevenlabs_voice" config.yaml
```
Should show line 91: `elevenlabs_voice: Rachel`

## Step 2 — fix it

Find:
```yaml
elevenlabs_voice: Rachel
```
Replace with:
```yaml
elevenlabs_voice: 5th veda narrator
```

## Step 3 — verify, commit, push

```bash
grep -n "elevenlabs_voice" config.yaml
```
Should now show: `elevenlabs_voice: 5th veda narrator`

```bash
git add -A
git commit -m "Fix config: use Fifth Veda Narrator voice, not Rachel"
git push
```
Paste the commit + push output.

## Step 4 — restart and live-test for real

```bash
pkill -f "jatayu.web.server"
python3 -m jatayu.web.server
```

In the browser, trigger any voice reply (ask a question with voice on),
and check the actual terminal log for this line:
```bash
grep -n "ElevenLabs TTS HTTP" 
```
(or just watch the live terminal output as the reply plays)

- If there's **no** "ElevenLabs TTS HTTP" error line at all → the call
  succeeded, billing is confirmed working, and it should be Fifth Veda
  Narrator's actual voice you hear.
- If you still see an HTTP error line → paste the exact status code and
  message, billing may not have fully propagated yet on ElevenLabs' side.

## Step 5 — report back

Tell me plainly: did you personally hear Fifth Veda Narrator's actual
voice (not the generic fallback voice), yes or no? That's the only proof
that actually matters here — not the absence of an error in the log.
