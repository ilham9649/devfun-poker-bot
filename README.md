# 🃏 DevFun Poker Bot

An AI-powered Texas Hold'em poker bot for the [dev.fun Arena](https://arena.dev.fun). Built with quantitative poker theory, Monte Carlo equity simulation, and multi-street strategy.

## Features

- **Quantitative Engine** — Pre-computed preflop equity tables + Monte Carlo postflop simulation
- **Push/Fold Charts** — Nash-equilibrium based short-stack strategy (≤20 BB)
- **Tournament-Aware** — ICM pressure, bubble detection, blind escalation adjustments
- **Position-Based Ranges** — Tight from early position, wider from late
- **3-bet/4-bet Strategy** — Value and bluff 3-bets, proper 4-bet/5-bet response
- **Multi-Street Postflop** — C-bet, double barrel, float, and river value/thin value
- **Opponent Exploitation** — Adjusts play vs Nit/Station/LAG/TAG/Weak-Tight opponents
- **Auto-Rebuy** — Automatically re-enters (up to 5 rebuys) after busting; the cron monitor script logs status

## Architecture

```
pokerbot/                      # Importable package
├── bot.py                     # Main bot — API polling, decision routing, chat
├── quant.py                   # Quantitative engine — equity, strategy, ICM (fallback)
├── profiler.py                # Opponent profiler — tracks hands, builds profiles
└── player.py                  # AI player — Gemini 3.1 Flash Lite + profiler integration
scripts/
├── devfun_monitor.sh          # Status logger (cron)
└── devfun_coach_collect.sh    # Coach data collector (cron)
tests/
├── test_quant.py              # Test suite
└── fixtures/                  # Captured API payloads for table-fixture tests
pyproject.toml                 # Package metadata + `pokerbot` entry point
requirements.txt               # Runtime deps (requests)
```

## AI Player (Optional)

The bot can use **Gemini 3.1 Flash Lite** for smarter decisions, incorporating real-time opponent profiling.

### Two-Agent Architecture
1. **Profiler Agent** (`pokerbot/profiler.py`) — Tracks opponent actions across hands, builds statistical profiles with VPIP, PFR, AF, 3-bet%, fold-to-cbet%, and generates natural-language summaries
2. **Player Agent** (`pokerbot/player.py`) — Passes profiler output + table state to Gemini, parses AI response into action. Falls back to `quant_decision()` on API errors/timeouts

### Setup
Set the Gemini API key as an environment variable:
```bash
export GEMINI_DEEP_RESEARCH_API_KEY=your_key_here
```
The bot will automatically start using Gemini for decisions. No code changes needed.

### Profile Data
Opponent profiles are stored in `opponent_profiles.json` **one level above the repo** (alongside `.arena-credentials`) — distinct from the `.arena-*` state files, which live under `ARENA_WORKSPACE` (see [Configuration](#configuration)). This is our own data — not from the platform API. Reliability scales with hands observed (low < 10, medium < 20, high 20+).

## Setup

1. Clone the repo
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Create `.arena-credentials` **one level above the repo** (the workspace root) with your arena credentials. The bot reads this file directly — there is **no `.env` loader**, so skip the `.env` dance:
   ```
   apiKey=arena_sk_xxx
   agentId=cmqxxx
   ```
4. (Optional) Configure via environment variables — see [Configuration](#configuration). **No source edits needed.**
5. Run:
   ```bash
   python3 -m pokerbot.bot
   # or, after `pip install .`:
   pokerbot
   ```

## Configuration

All runtime settings are environment variables — **no source edits required**.

| Variable | Default | Purpose |
|---|---|---|
| `ARENA_COMPETITION_ID` | `cmqf827h30u7dfca3x2aqvzjv` (Playground S3) | Target competition. Set to `seed_poker_eval_s1` for eval mode (below). |
| `ARENA_WORKSPACE` | the repo root | Directory for runtime state files (`.arena-poker-state`, `.arena-opponents.json`, `.arena-bot.pid`, `.arena-stop`, `.arena-coach-advice`) and `opponent_profiles.json` (unless overridden). |
| `ARENA_CREDENTIALS` | _(unset)_ | Explicit path to `.arena-credentials`. If unset, credentials are searched in order: `ARENA_CREDENTIALS` → one level above the repo → `$ARENA_WORKSPACE`. |
| `ARENA_PROFILES_FILE` | _(unset)_ | Explicit path to `opponent_profiles.json`. If unset, defaults to `$ARENA_WORKSPACE/opponent_profiles.json` (or one level above the repo when `ARENA_WORKSPACE` is unset). |
| `GEMINI_DEEP_RESEARCH_API_KEY` | _(unset)_ | Enables the Gemini AI player. Unset ⇒ quantitative engine only. |

Credentials (`.arena-credentials`) are read at import time, so a credentials file must exist before the bot starts. The default location is one level above the repo (the workspace root in the standard deployment); set `ARENA_CREDENTIALS` to point elsewhere — e.g. a per-instance file for multi-instance/eval runs. Opponent profiles follow `ARENA_WORKSPACE` (overridable via `ARENA_PROFILES_FILE`).

### Eval mode
Set `ARENA_COMPETITION_ID=seed_poker_eval_s1` to run in benchmark/eval mode, which attaches a `reasoning` field (truncated to 150 chars) to each submitted action.

## Strategy Overview

### Preflop
- **UTG**: ~15% range (QQ+, AK, AQs)
- **HJ**: ~20% (+ AJ, KQ)
- **CO**: ~25% (+ AT, KQ, KJs, QJs)
- **BTN**: ~30% (+ suited aces, connectors)
- **SB/BB**: Tight defending, re-steal from late position

### Postflop
- **C-bet**: Value hands + semibluffs on flop, give up turn without improvement
- **Double Barrel**: Scare cards + equity continuation
- **River**: Value bet strong hands, thin value vs stations, check/fold weak
- **Float**: IP with draws, give up if miss turn

### Short Stack (≤20 BB)
- Nash push/fold equilibrium
- Position-aware shoving ranges
- Widen as blinds escalate

### Tournament
- ICM tightening for medium stacks near bubble
- Aggression increase as effective BB drops
- Phase detection (early/middle/late/bubble/final table)

## Testing

```bash
python3 tests/test_quant.py
```

## License

MIT
