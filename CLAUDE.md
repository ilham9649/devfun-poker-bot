# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An autonomous Texas Hold'em poker bot that plays in [dev.fun Arena](https://arena.dev.fun) tournaments. It runs as a long-running process that polls the arena HTTP API for tables where it owes a decision, chooses an action, and submits it. The code is an importable `pokerbot` Python package; there is no build step and no web/UI layer.

## Commands

```bash
pip install -r requirements.txt   # only third-party dep is `requests` (Gemini is called via raw REST, no SDK)
python3 -m pokerbot.bot            # run the bot (or `pokerbot` after `pip install .`); needs .arena-credentials + network
python3 tests/test_quant.py        # run the test suite (plain script; exits 0 on pass, 1 on fail)
```

- No linter, formatter, or build step is configured. Target Python ≥ 3.8. `pyproject.toml` declares the package and a `pokerbot` console-script entry point (`pokerbot.bot:main_loop`).
- The test files are **self-contained scripts** (each its own `test()`/`test_approx()` runner), **not** pytest. Run the whole file; there is no per-test isolation and pytest won't collect them cleanly.
- Coverage: `tests/test_quant.py` (the engine, ~145 assertions; note: its Monte-Carlo equity assertions are **flaky** and fail ~50% of runs near decision thresholds — unrelated to other modules), `tests/test_player.py` (Gemini decision + amount validation), `tests/test_profiler.py` (profiler data model + LLM throttle), `tests/test_opponent_reader.py` (`player.llm_opponent_summary`, mocked Gemini), `tests/test_capture.py` (`bot` action-capture + LLM refresh helper). `quant.py`/`player.py`/`profiler.py` are import-safe; `bot.py` has import-time side effects (credential read + `fcntl` PID lock) and is imported in `test_capture.py` by staging a throwaway `.arena-credentials` at its read-path with `ARENA_WORKSPACE` isolating state files.

## Layout

```
pokerbot/   # importable package
            #   bot.py      — orchestrator (polling loop, lifecycle, decision routing, opponent-action capture)
            #   quant.py    — fallback engine (equity, ICM, push/fold, postflop)
            #   player.py   — Gemini 3.1 Flash Lite decision agent + LLM opponent reader
            #   profiler.py — opponent profiling (stats + LLM-read tendencies)
scripts/    # devfun_monitor.sh, devfun_coach_collect.sh — standalone cron helpers
tests/      # test_quant.py, test_player.py, test_profiler.py, test_opponent_reader.py, test_capture.py (+ fixtures/)
```

## Architecture

A **two-agent design with a quantitative fallback**, all inside the `pokerbot` package:

1. **Orchestrator — `pokerbot/bot.py`**. Owns all I/O and state: the `main_loop()` polling loop, lifecycle (queue join, auto-rebuy up to 5×, single-instance `fcntl` PID lock, `.arena-stop` kill-switch file), chat-message pools, the per-hand `_hand_state` machine, and `decide_action()` — the single decision router. It instantiates one global `Profiler`, **captures opponent actions** by snapshot-diffing table state once per our turn (`_capture_opponent_actions`), and after each completed hand records showdowns and runs the throttled LLM opponent-reader (`refresh_opponent_llm_profile`, capped at 2 refreshes/hand).

2. **Player Agent — `pokerbot/player.py`**. The primary decision engine: `decide_with_profiling()` builds a prompt from table state + opponent profile summaries, calls **Gemini 3.1 Flash Lite** (`_call_gemini`, 2 s timeout), and parses a JSON response `{action, amount, confidence, reasoning}`. On any failure (no API key, timeout, non-200, unparseable/invalid response) it **falls back to `quant_decision()`**. Also hosts `llm_opponent_summary(profile)` — the LLM opponent-reader that turns an opponent's stats + action transcript + showdown history into a qualitative tendencies summary. Gated entirely by the `GEMINI_DEEP_RESEARCH_API_KEY` env var — unset ⇒ always falls back to quant (and the LLM reader is skipped).

3. **Profiler Agent — `pokerbot/profiler.py`**. The `Profiler` class manages `OpponentProfile` objects persisted to `opponent_profiles.json`. It accumulates raw opponent action counts, derives VPIP / PFR / AF / 3-bet% / fold-to-cbet% / c-bet%, classifies style (LAG / TAG / Station / Nit / Weak-Tight), and retains a bounded recent-action transcript + showdown history. `summary_for_prompt()` is what the decision path injects: it returns the cached LLM-written tendencies summary when present, else falls back to the deterministic `generate_summary()`. The LLM summary is refreshed post-hand, throttled (at showdown or every ~8 hands observed; `needs_llm_refresh`).

**Fallback engine — `pokerbot/quant.py`** (~1180 lines). A pure, import-safe library (no I/O) that the Player falls back to and that all tests exercise: 5-card hand evaluation (`evaluate_hand`/`compare_hands`), preflop equity from a lookup table (`preflop_equity`), postflop equity via Monte Carlo (`monte_carlo_equity`), tournament overlays (`icm_tighten_factor`, `is_near_bubble`, `tournament_phase`, blind escalation), short-stack Nash push/fold (`is_push_fold_hand`), multi-street postflop (`_flop_decision`/`_turn_decision`/`_river_decision`), and opponent exploitation (`exploitation_adjustment`, `get_fold_equity`). The top-level router is `quant_decision()`.

**Decision flow:** `main_loop` → `decide_action(table)` → `decide_with_profiling(...)` (Gemini + profiler) → on failure → `quant_decision(...)`. Both paths return a 4-tuple `(action, amount, message, confidence/equity)`; `decide_action` returns the first three. `bb_size` is currently hardcoded to `2` at the call site, so blind-escalation math does not track the real big blind.

`scripts/devfun_monitor.sh` and `scripts/devfun_coach_collect.sh` are standalone cron helpers (curl + inline `python3 -c`) that log status and build a recent-hands digest; they do not import the package.

## Runtime environment & configuration

- **Arena credentials** (`apiKey=...`, `agentId=...`) are read from `.arena-credentials` at the **workspace root**, at **import time** of `pokerbot/bot.py`. `WORKSPACE` defaults to `/root/.openclaw/workspace` and is overridable via the `ARENA_WORKSPACE` env var; `CRED_FILE` resolves to `$WORKSPACE/.arena-credentials`.
- `WORKSPACE` holds runtime state files: `.arena-poker-state`, `.arena-opponents.json`, `.arena-bot.pid`, `.arena-coach-advice`, and the `.arena-stop` kill switch (create it to stop the bot cleanly).
- **`GEMINI_DEEP_RESEARCH_API_KEY`** env var enables the Gemini player; without it the bot runs purely on the quant engine.
- **`opponent_profiles.json`** is the Profiler's own data, stored at the workspace root (one level above the repo), accumulated across runs — not from the arena API.
- **`COMPETITION_ID`** is hardcoded near the top of `pokerbot/bot.py`.
- Polling cadence: `POLL_INTERVAL` 1.5 s idle, `API_COOLDOWN` 0.8 s minimum between API calls (rate-limited in `get`/`post`).

## Working in this code

- **`pokerbot/bot.py` has import-time side effects** (credential file read + `fcntl` PID lock). It cannot be imported without a `.arena-credentials` present, and a second process will exit immediately. To unit-test the bot layer, set `ARENA_WORKSPACE` to a temp dir containing a fake `.arena-credentials`.
- **`pokerbot/quant.py`, `player.py`, and `profiler.py` are import-safe** (no I/O at import) — prefer them (especially `quant`) for isolated testing and reasoning.
- **Two independent state machines** coexist: the per-hand `_hand_state` (raised-preflop / prior-street action / equity, threaded into `quant_decision`) and the cross-hand `Profiler` + opponent-stats caches. Changes to one rarely affect the other.
- **Gemini is best-effort by design** — never assume a decision came from Gemini; always preserve a working `quant_decision` fallback path when editing `player.py`.
- API responses are accessed with `.get()` chains with minimal shape validation; malformed payloads can crash `decide_action` mid-hand (no surrounding `try/except`).
