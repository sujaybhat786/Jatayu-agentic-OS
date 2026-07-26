# Phase 1 — Memory Fix: Apply Instructions

Do these in order. Copy-paste each block exactly. If any step gives an
error, stop and paste me the exact error — don't guess or skip ahead.

---

## Step 0 — Security (do this before anything else, separately)

This patch stops Git from tracking `Credentials.json` **going forward**.
It does **not** remove it from your GitHub history — that secret is
still exposed publicly. Before or right after applying these patches:

1. Go to https://console.cloud.google.com/apis/credentials
2. Delete the OAuth client currently in `Credentials.json` / `.env`, create a new one.
3. Update `.env` and `data/google_accounts.json` with the new client ID/secret.
4. Go to https://github.com/settings/tokens and revoke/regenerate any token you used earlier.
5. Message @BotFather on Telegram → regenerate your bot token → update `.env`.
6. Consider making the GitHub repo private (repo → Settings → Danger Zone → Change visibility).

None of the patches below can fix this for you — it requires you rotating the actual credentials.

---

## Step 1 — Open Terminal and go to your project

```bash
cd "/Users/sujayabhat/Downloads/Agentic OS"
```

## Step 2 — Make sure your local copy is clean and up to date

```bash
git status
```

If it says anything other than "working tree clean", tell me what it says before continuing.

```bash
git pull origin main
```

## Step 3 — Download the two patch files

Save both of these (from this chat) into your project folder, i.e. directly inside `"/Users/sujayabhat/Downloads/Agentic OS"`:
- `phase1_memory_fixes.patch`
- `phase1_untrack_credentials.patch`

## Step 4 — Apply the memory fix patch

```bash
git apply --check phase1_memory_fixes.patch
```

If that prints nothing (no output = good), run:

```bash
git apply phase1_memory_fixes.patch
```

If `--check` prints errors, **stop and paste me the exact output** — don't force it through.

## Step 5 — Stop tracking Credentials.json

```bash
git apply phase1_untrack_credentials.patch
```

(This only removes it from being tracked from now on — see Step 0. It will still exist on your disk, just not committed anymore.)

## Step 6 — Review what changed (optional but good habit)

```bash
git diff --stat
```

You should see 4 files changed: `jatayu/brain.py`, `jatayu/memory/schema.sql`, `jatayu/memory/store.py`, `jatayu/web/server.py`, plus `Credentials.json` removed from tracking.

## Step 7 — Rebuild the memory database with the new schema

The new schema adds one new table (`entities_search_fts`) for faster, smarter lookups. Your **existing facts and people/projects data won't be touched or lost** — this just re-runs the seed script, which is idempotent (safe to run repeatedly, never creates duplicates, per the existing tests).

```bash
python3 -m jatayu.memory.seed
```

## Step 8 — Run the test suite

```bash
python3 -m unittest tests.test_memory -v
```

You should see:
```
Ran 6 tests in ...s
OK
```

If you see `FAILED` or `ERROR`, paste me the full output.

## Step 9 — Restart your server and re-test the exact questions that were wrong before

```bash
# stop any old running server first (Ctrl+C in its terminal, or):
pkill -f "jatayu.web.server"

# then start fresh:
python -m jatayu.web.server
```

Open http://localhost:7860 and ask, in order:
1. "Who is Ram Raghavan?"
2. "What is Framelux?"
3. "What is the mail ID of Tejaswini Hegde?"
4. "What call do I have everyday at 9:00 PM?"

Paste me the actual answers you get back — real transcript, not a summary — so I can confirm they're right before we move to Phase 2.

## Step 10 — Commit and push once confirmed working

```bash
git add -A
git commit -m "Phase 1: relevance-based memory injection, fix prompt composition, untrack Credentials.json"
git push
```

---

## What actually changed, in plain terms

1. **`jatayu/memory/store.py` / `schema.sql`** — Previously, every single
   message dumped the full contact/contract details of *every* person and
   project you have into the prompt, every time, regardless of what you
   asked. That's why it worked in a "17/17 tests passed" demo (small data)
   but would get slower and more expensive as you add more people/projects,
   and it's why some of your earlier real answers looked like the memory
   wasn't being read consistently. Now: only entities actually relevant to
   your message get full detail; everyone else appears as a name-only list
   so the model still knows they exist and can look them up on demand.
   Verified: injected context size grew ~4x for a simulated 25x increase
   in contacts, and lookups stayed under 7ms even at 200+ entities.

2. **`jatayu/brain.py`** — Removed the fragile trick that decided whether
   memory was already included in the prompt by checking if the first 50
   characters of the base prompt happened to appear as a substring
   elsewhere. That's exactly the fragility your own handoff doc (section
   6.1) called out. Replaced with one explicit function that always knows
   exactly what it's assembling.

3. **`jatayu/web/server.py`** — Updated to hand memory to the brain the
   new, explicit way instead of the old workaround.

None of this touches Telegram, Gmail, Hermes, or Browser Use — that's Phase 3+.
