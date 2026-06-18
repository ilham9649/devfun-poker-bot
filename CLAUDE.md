# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An autonomous Texas Hold'em poker bot that plays in [dev.fun Arena](https://arena.dev.fun) tournaments. It runs as a long-running process that polls the arena HTTP API for tables where it owes a decision, chooses an action, and submits it. There is no build step and no web/UI layer — it's a polling daemon plus a strategy library.

## Commands

```bash
pip install requests          # only third-party dependency (Gemini is called via raw REST, no SDK)
python3 devfun_poker_bot.py   # run the bot (needs .arena-credentials + network; see Runtime below)
python3 test_poker_quant.py   # run the test suite (plain script; exits 0 on pass, 1 on fail)
```

- No linter, formatter, or build step is configured. Target Python ≥ 3.8.
- The test file is a **self-contained script** (its own `test()`/`test_approx()` runner with ~145 assertions across 10 groups), **not** pytest. Run the whole file; there is no per-test isolation and pytest will not collect it cleanly.
- The suite covers `poker_quant.py` only. `devfun_poker_bot.py`, `poker_player.py`, and `poker_profiler.py` have **no tests**.

## Architecture

The codebase is a **two-agent design with a quantitative fallback**. Three layers:

1. **Orchestrator — `devfun_poker_bot.py`** (~770 lines). Owns all I/O and state: the `main_loop()` polling loop, lifecycle (queue join, auto-rebuy up to 5×, single-instance `fcntl` PID lock, `.arena-stop` kill-switch file), chat-message pools, the per-hand `_hand_state` machine, and `decide_action()` — the single decision router. It instantiates one global `Profiler` and feeds it hand results after each completed hand.

2. **Player Agent — `poker_player.py`**. The primary decision engine: `decide_with_profiling()` builds a prompt from table state + opponent profile summaries, calls **Gemini 3.1 Flash Lite** (`_call_gemini`, 2 s timeout), and parses a JSON response `{action, amount, confidence, reasoning}`. On any failure (no API key, timeout, non-200, unparseable/invalid response) it **falls back to `quant_decision()`**. Gated entirely by the `GEMINI_DEEP_RESEARCH_API_KEY` env var — unset ⇒ always falls back to quant.

3. **Profiler Agent — `poker_profiler.py`**. The `Profiler` class manages `OpponentProfile` objects persisted to `opponent_profiles.json`. It accumulates raw opponent action counts, derives VPIP / PFR / AF / 3-bet% / fold-to-cbet% / c-bet%, classifies style (LAG / TAG / Station / Nit / Weak-Tight), and `generate_summary()` produces the natural-language tendencies injected into the Gemini prompt.

**Fallback engine — `poker_quant.py`** (~1180 lines). A pure, import-safe library (no I/O) that the Player falls back to and that all tests exercise: 5-card hand evaluation (`evaluate_hand`/`compare_hands`), preflop equity from a lookup table (`preflop_equity`), postflop equity via Monte Carlo (`monte_carlo_equity`), tournament overlays (`icm_tighten_factor`, `is_near_bubble`, `tournament_phase`, blind escalation), short-stack Nash push/fold (`is_push_fold_hand`), multi-street postflop (`_flop_decision`/`_turn_decision`/`_river_decision`), and opponent exploitation (`exploitation_adjustment`, `get_fold_equity`). The top-level router is `quant_decision()`.

**Decision flow:** `main_loop` → `decide_action(table)` → `decide_with_profiling(...)` (Gemini + profiler) → on failure → `quant_decision(...)`. Both the Gemini path and the quant fallback return a 4-tuple `(action, amount, message, confidence/equity)`; `decide_action` returns the first three. `bb_size` is currently hardcoded to `2` at the call site, so blind-escalation math does not track the real big blind.

`scripts/`-referenced files (`devfun_monitor.sh`, `devfun_coach_collect.sh`) actually live at the repo root; they are standalone cron helpers (curl + inline `python3 -c`) that log status and build a recent-hands digest, and do not import the Python modules.

## Runtime environment & configuration

- **Arena credentials** (`apiKey=...`, `agentId=...`) are read from `.arena-credentials` located **one directory above the script** (i.e. the workspace root in the standard `/root/.openclaw/workspace/<repo>` deployment) at **import time**.
- **`WORKSPACE`** is hardcoded to `/root/.openclaw/workspace` and holds runtime state files: `.arena-poker-state`, `.arena-opponents.json`, `.arena-bot.pid`, `.arena-coach-advice`, and the `.arena-stop` kill switch (create it to stop the bot cleanly).
- **`GEMINI_DEEP_RESEARCH_API_KEY`** env var enables the Gemini player; without it the bot runs purely on the quant engine.
- **`opponent_profiles.json`** is the Profiler's own data (one level above the repo, alongside `.arena-credentials`), accumulated across runs — not from the arena API.
- **`COMPETITION_ID`** is hardcoded near the top of `devfun_poker_bot.py`.
- Polling cadence: `POLL_INTERVAL` 1.5 s idle, `API_COOLDOWN` 0.8 s minimum between API calls (rate-limited in `get`/`post`).

## Working in this code

- **`devfun_poker_bot.py` has import-time side effects** (credential file read + `fcntl` PID lock). It cannot be imported without a `.arena-credentials` present, and a second import/process will exit immediately. To unit-test the bot layer, point the process at a temp workspace containing a fake `.arena-credentials`, or refactor the side effects behind a `main()` (currently a known gap).
- **`poker_quant.py` is the only import-safe module** — prefer it for isolated testing and reasoning.
- **Two independent state machines** coexist: the per-hand `_hand_state` (raised-preflop / prior-street action / equity, threaded into `quant_decision`) and the cross-hand `Profiler` + opponent-stats caches. Changes to one rarely affect the other.
- **Gemini is best-effort by design** — never assume a decision came from Gemini; always preserve a working `quant_decision` fallback path when editing `poker_player.py`.
- API responses are accessed with `.get()` chains with minimal shape validation; malformed payloads can crash `decide_action` mid-hand (no surrounding `try/except`).
