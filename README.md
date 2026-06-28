# OptionRadar

A calls-only, curated-universe options **signal** system. It scans a small,
static watchlist once a day, runs a **gate → score → fire** pipeline, and emits
at most one of three Telegram messages:

- 😴 **No Trade Today** (the default — firing often means something is broken)
- ✅ **Standard Signal** (a modest, mechanical +25–30% play, high win rate)
- 🚀 **Moonshot** (a rare, separately-flagged alignment worth a ride-the-runner play)

It is **read-only**: it never places, modifies, or cancels orders. Entry is
manual. Schwab is the single data source. The "database" is just a SQLite file
committed to this repo.

> Design intent (from the spec): ~$4–5k fun-money account, single long calls (no
> spreads), high risk tolerance, **1–2 trades/month is fine**. Puts are
> deliberately excluded. The modest target *is* the edge.

## How it works (the daily pipeline)

```
GitHub Action (weekdays, ~30 min before close)
        ↓
Schwab pricehistory (universe + sector ETFs + SPY)  →  EMA 20/50/200, RSI, ATR, rel-strength
        ↓
Schwab chains (45–60 DTE)  →  strikes, greeks, IV;  append today's ATM IV to the store
        ↓
Stage 1: gates G1–G5            →  survivors          (binary, ALL must pass)
        ↓
Stage 2: score F1–F7            →  composite + rank    (0–100 each; weighted)
        ↓
Stage 3: test #1 vs Standard fire logic
            ├─ fails  →  No Trade Today
            └─ fires  →  Moonshot upgrade?  yes → 🚀 card   /   no → ✅ card
        ↓
Commit updated IV-history store  ·  Send Telegram (always sends something)
```

The composite is used for **ranking only**. The *fire* decision uses the
**floor across factors** and the **gap to #2**, not the composite (see
`fire.py`).

## Layout

| Path | What it is |
|------|-----------|
| `optionradar/config.py` | **Universe** (§1) + **the single parameter table** (§10). All magic numbers live here. |
| `optionradar/indicators.py` | EMA, Wilder RSI/ATR, returns, realized vol — pure Python. |
| `optionradar/schwab_client.py` | Schwab OAuth + `pricehistory` / `chains` (read-only). |
| `optionradar/data.py` | Builds `NameSnapshot`s from candles + chains. |
| `optionradar/iv_store.py` | The IV-history store ("the database is just the repo", §11.2). |
| `optionradar/gates.py` | Stage 1 — gates G1–G5 (§3). |
| `optionradar/factors.py` | Stage 2 — scored factors F1–F7 (§4). |
| `optionradar/fire.py` | Stage 3 — fire logic + Moonshot upgrade + regime bumps (§5). |
| `optionradar/strike.py` | Strike/delta/DTE selection (§6) + exit plans (§7). |
| `optionradar/telegram.py` | The three message formats (§8) + delivery. |
| `optionradar/pipeline.py` | Daily orchestration (§9). |
| `optionradar/providers.py` | `SchwabProvider` (live) and `MockProvider` (offline/tests). |
| `scripts/run_daily.py` | Daily entry point. |
| `scripts/backfill.py` | One-time IV backfill (§11.3). |
| `.github/workflows/daily.yml` | The scheduled GitHub Action. |
| `data/iv_history.sqlite` | The committed IV store (created by backfill). |

## Quick start (offline, no credentials)

The `MockProvider` generates deterministic synthetic data so you can exercise
the whole pipeline without Schwab access.

```bash
# 1. seed ~252 days of IV history (realized-vol stand-in)
python -m scripts.backfill --mode rvol --db data/iv_history.sqlite

# 2. run a scan, print the card, don't send to Telegram
python -m scripts.run_daily --mock --no-send

# 3. run the tests
python -m pytest -q
```

(On Windows, prefix with `PYTHONIOENCODING=utf-8` so the emoji in the cards
print to the console.)

## Going live

1. **Secrets** — set these as GitHub Action secrets (and locally in a `.env`,
   see `.env.example`):
   - `SCHWAB_CLIENT_ID`, `SCHWAB_CLIENT_SECRET`, `SCHWAB_REFRESH_TOKEN`
     (reuse the OAuth app from the TQQQ system)
   - `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
2. **Backfill the IV store once** so F2 (IV percentile) is at full strength on
   day one — you do **not** wait a year:
   ```bash
   python -m scripts.backfill --mode schwab        # best
   # fallback ladder if historical chains are thin:
   python -m scripts.backfill --mode rvol          # realized-vol seed
   python -m scripts.backfill --mode none          # start empty, warm up forward
   ```
   Commit `data/iv_history.sqlite`.
3. **Enable the workflow** (`.github/workflows/daily.yml`). It runs weekdays,
   commits the updated store back to the repo (`contents: write`), and sends the
   card to Telegram.

### Warm-up ladder (if you skip the backfill)

| IV history depth | Behaviour |
|---|---|
| `< 90 days` | Standard signals allowed (caveated); **Moonshots suppressed** |
| `≥ 90 days` | Standard signals trustworthy |
| `≥ 252 days` | Full strength, Moonshots enabled |

## Tuning

All thresholds live in `optionradar/config.py` (`PARAMS`). **Paper-trade 4–6
weeks before real money.** Don't backtest-tune — eyeball whether Standard fires
feel real and Moonshots stay rare, then adjust the table by hand. Every run
stores its survivors + scores in the `run_audit` table so the No-Trade card can
explain itself and you can audit whether a threshold did its job.

## Earnings calendar

G5 (no earnings before the planned exit) reads `data/earnings.json`
(`{ "NVDA": "2026-08-27", ... }`). A missing entry is treated as "clear" — the
buffer guards against a *known* event, it doesn't silently drop names. Refresh
that file from whatever calendar feed you prefer.
