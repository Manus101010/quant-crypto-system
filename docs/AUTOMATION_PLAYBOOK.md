# Automation Playbook — running a Python app 24/7 for $0

How the QuantCore crypto scanner runs unattended, laptop off, at zero cost. Written
so another Claude Code project can copy the pattern. Everything below is in
production in this repo and was verified end-to-end.

## The constraint
Free or nothing — no VPS, no card. (Oracle Free Tier signup failed; Netlify/Vercel are
the wrong shape: serverless, no long-running process, no persistent disk.)

## The stack (all free, no card)

| Job | Service | Why |
|---|---|---|
| Shared state / database | **Supabase** (Postgres free tier) | Cloud jobs and the UI need ONE source of truth; local SQLite can't be shared |
| Always-on worker (polling, scheduled jobs) | **GitHub Actions**, self-chaining relay | Public repo = unlimited free minutes |
| Web UI / phone access | **Streamlit Community Cloud** | Free hosting from a GitHub repo; phone "Add to Home Screen" |
| Notifications | **Telegram Bot API** | Free push to phone, plain `requests.post` |
| Secrets | `.env` locally · GitHub repo secrets · Streamlit secrets | Same keys, three stores |

```
Streamlit UI ─┐                        ┌─ Telegram (alerts, summaries, brief)
              ├──► Supabase ◄──────────┤
Laptop app ───┘   (single source)      └─ GitHub Actions relay worker
                                           (polls every 15 min + scheduled jobs)
```

## Pattern 1 — Backend switch (local SQLite ⇄ Supabase, zero app changes)
`triggers/db.py` keeps its SQLite functions, then at the bottom rebinds every public
function to a Supabase twin (`triggers/supastore.py`) when `SUPABASE_URL`+`SUPABASE_KEY`
are set. The rest of the app just imports `db` and never knows which backend it has.
- Use the **service_role** key server-side; enable **RLS with no policies** so the
  public anon key can read nothing.
- Store timestamps as **ISO text** to keep SQLite string comparisons identical.
- Schema changes: run SQL in the Supabase SQL editor (the REST client can't do DDL).

## Pattern 2 — One secrets helper for three environments
```python
def _secret(key, default=""):
    v = os.getenv(key, "")              # .env locally / GitHub Actions secrets
    if v: return v
    if "streamlit" not in sys.modules:  # CLI/cron: don't import streamlit
        return default
    try:
        import streamlit as st          # Streamlit Cloud: st.secrets, NOT os.environ
        return str(st.secrets.get(key, default))
    except Exception:
        return default
```
Gotcha: values are read at import → after editing Streamlit secrets you must **Reboot app**.

## Pattern 3 — The self-chaining relay worker (the key trick)
GitHub's free `schedule:` cron is **throttled and late** (we asked for every 15 min and
got ~every 3–6 h, starts up to 3 h late). So don't rely on cron for cadence:
1. Each run loops internally (`--interval 900`) for ~5h40m (`--max-minutes 340`; job cap 360).
2. The last step **dispatches the next run itself** — `GITHUB_TOKEN` *is* allowed to trigger
   `workflow_dispatch`. A `concurrency` group queues it until this run ends → no gap.
3. Hourly cron stays only as a backup restarter. Cancelling a run stops the chain.

```yaml
on:
  schedule: [{cron: "7 * * * *"}]          # backup only
  workflow_dispatch:
    inputs: {minutes: {default: "340"}}    # short test runs: minutes=2
concurrency: {group: monitor, cancel-in-progress: false}
permissions: {contents: read, actions: write}
jobs:
  poll:
    runs-on: ubuntu-latest
    timeout-minutes: 355
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.11", cache: pip}
      - run: pip install -r requirements.txt
      - run: python monitor.py --interval 900 --max-minutes ${{ github.event.inputs.minutes || '340' }} --quiet-start
        env: {SUPABASE_URL: ${{ secrets.SUPABASE_URL }}, SUPABASE_KEY: ${{ secrets.SUPABASE_KEY }}}
      - name: Hand over to the next run
        if: ${{ !cancelled() }}
        env: {GH_TOKEN: ${{ github.token }}}
        run: gh workflow run monitor.yml --ref main -R ${{ github.repository }}
```
Verify with a `minutes=2` run and confirm a new run appears when it ends.

## Pattern 4 — Exact-time jobs inside the worker (not cron)
Cron is UTC-only, ignores DST, and runs late. Instead the worker loop calls
`autoscan.run_due()` each pass (`triggers/autoscan.py`):
- Schedule as `(name, IANA tz, "HH:MM")` → `zoneinfo` handles DST automatically.
- Persist "last run per slot" in a tiny key/value table (`app_state`) so relay
  hand-overs never repeat or skip a job; skip slots missed by >90 min (don't run stale).
- **Mark the slot done before running** so a crash can't retry a heavy job every poll.
- Sleep `min(interval, seconds_to_next_slot)` so jobs fire on time, not up to 15 min late.
Our jobs: scans at 06:50 / 00:05 UTC / 15:00 Sydney, brief at 07:00 Sydney.

## Pattern 5 — Telegram that never loses a message
- `parse_mode=HTML`; escape `<`/`>` in dynamic text (`&lt;`) — a stray `<80` 400'd a live alert.
- On a 400, retry once as plain text with tags stripped.
- Only mark an event "sent" if delivery succeeded (else retry next poll).

## Pattern 6 — Deploying the UI on Streamlit Community Cloud
- Repo must be visible to Streamlit: OAuth app lacks private-repo scope by default →
  we made the repo **public** after verifying no secrets were ever committed
  (`git log --all -- .env` empty; grep for key patterns).
- Main file `app.py`; paste secrets as TOML (`KEY = "value"`), then reboot.
- Cloud installs the **newest** packages: pin majors (`pandas<3`), and replace deprecated
  APIs early (`Styler.applymap`→`map`, `use_container_width`→`width="stretch"`).
- Free apps sleep after inactivity (wake button) — fine for UI; the worker is separate.
- Local-disk files are wiped on restart → anything persistent goes to Supabase.
- Data files the cloud needs (e.g. `data/crypto_validation.json`) must not be gitignored —
  and code should **fail closed** if they're missing.

## Pattern 7 — Retire the laptop jobs
Once cloud jobs run, disable local duplicates (`launchctl bootout` + `disable`) or every
alert/brief arrives twice.

## Verification habit (what kept this honest)
- After every deploy: trigger the workflow manually, read the step logs, confirm the
  side effect (row in Supabase, Telegram message).
- Health check = recent runs (in_progress + no gaps), last run per scheduled slot from
  `app_state`, recent events, UI loads. Each check here found a real bug (late cron,
  coverage gaps, stale data file, starved scans).
- Dry-run anything that writes by stubbing the DB writes.

## Gotchas we hit (save yourself the time)
| Symptom | Cause | Fix |
|---|---|---|
| launchd job exits 78 | log path under TCC-protected ~/Desktop | log to ~/Library/Logs, `bash -c 'cd … && exec …'` |
| DNS NXDOMAIN for Supabase | URL hand-copied from a screenshot (l vs i) | copy via the dashboard's Copy button |
| Cron every 15 min ran every 3–6 h | GitHub free-tier throttling | self-chaining relay (Pattern 3) |
| Daily job arrived 3 h late | cron delay | run it inside the worker (Pattern 4) |
| `${!k}` bad substitution | zsh, not bash | run the snippet with `bash -c` |
| API key "invalid format" | wrong key pasted long ago | validate key shape on load; test with a live call |

## Cost: $0/month
Supabase free · GitHub Actions free (public repo) · Streamlit Community Cloud free ·
Telegram free · market data via free public APIs.
