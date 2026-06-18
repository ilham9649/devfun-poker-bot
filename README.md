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
- **Auto-Restart** — Monitor script handles crashes and auto-rebuys

## Architecture

```
scripts/
├── devfun_poker_bot.py      # Main bot — API polling, decision routing, chat
├── poker_quant.py           # Quantitative engine — equity, strategy, ICM (fallback)
├── poker_profiler.py        # Opponent profiler — tracks hands, builds profiles
├── poker_player.py          # AI player — Gemini 3.1 Flash Lite + profiler integration
├── test_poker_quant.py      # Test suite (145 tests)
├── devfun_monitor.sh        # Auto-restart monitor
└── devfun_coach_collect.sh  # Coach data collector
```

## AI Player (Optional)

The bot can use **Gemini 3.1 Flash Lite** for smarter decisions, incorporating real-time opponent profiling.

### Two-Agent Architecture
1. **Profiler Agent** (`poker_profiler.py`) — Tracks opponent actions across hands, builds statistical profiles with VPIP, PFR, AF, 3-bet%, fold-to-cbet%, and generates natural-language summaries
2. **Player Agent** (`poker_player.py`) — Passes profiler output + table state to Gemini, parses AI response into action. Falls back to `quant_decision()` on API errors/timeouts

### Setup
Set the Gemini API key as an environment variable:
```bash
export GEMINI_DEEP_RESEARCH_API_KEY=your_key_here
```
The bot will automatically start using Gemini for decisions. No code changes needed.

### Profile Data
Opponent profiles are stored in `opponent_profiles.json` in the project root. This is our own data — not from the platform API. Reliability scales with hands observed (low < 10, medium < 20, high 20+).

## Setup

1. Clone the repo
2. Copy `.env.example` to `.env` and fill in your arena credentials
3. Rename `.env` to `.arena-credentials` in your workspace root:
   ```
   apiKey=arena_sk_xxx
   agentId=cmqxxx
   ```
4. Update `COMPETITION_ID` in `devfun_poker_bot.py` to your target competition
5. Run:
   ```bash
   python3 scripts/devfun_poker_bot.py
   ```

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
python3 scripts/test_poker_quant.py
```

## License

MIT
