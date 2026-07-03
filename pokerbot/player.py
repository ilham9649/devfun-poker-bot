"""
Poker Player — Gemini-powered decision engine for DevFun poker bot.

Uses Gemini 3.1 Flash Lite for poker decisions, incorporating
real-time opponent profiling data. Falls back to quant_decision()
on API errors or timeouts.

Architecture: Player Agent ← consults ← Profiler Agent
"""

import json
import os
import sys
import time
import requests
from typing import Optional

# Import profiler
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pokerbot.profiler import Profiler

# Import quant engine as fallback
from pokerbot.quant import quant_decision, preflop_equity, monte_carlo_equity

# Profiles default to one level above the repo (alongside .arena-credentials)
# so generated data stays out of the repo, but follow ARENA_WORKSPACE if set
# (so multi-instance/eval runs get isolated profile sets). ARENA_PROFILES_FILE
# overrides the location outright.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_PROFILES_DIR = os.path.dirname(_REPO_ROOT)
_PROFILES_DIR = os.environ.get("ARENA_WORKSPACE", _DEFAULT_PROFILES_DIR)
PROFILES_FILE = os.environ.get("ARENA_PROFILES_FILE", os.path.join(_PROFILES_DIR, "opponent_profiles.json"))

GEMINI_API_KEY = os.environ.get("GEMINI_DEEP_RESEARCH_API_KEY", "")
GEMINI_MODEL = "gemini-3.1-flash-lite"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

POSITION_NAMES = {0: "UTG", 1: "HJ", 2: "CO", 3: "BTN", 4: "SB", 5: "BB", 6: "EP"}

# Maximum time we'll wait for Gemini (playground has ~3s deadlines)
GEMINI_TIMEOUT = 4.0

# Statistics tracking
stats = {"gemini_calls": 0, "gemini_success": 0, "gemini_timeout": 0,
         "gemini_error": 0, "fallback_calls": 0}

# ── Gemini API Call ─────────────────────────────────────

def _call_gemini(prompt: str, max_tokens: int = 200) -> Optional[dict]:
    """Call Gemini 3.1 Flash Lite. Returns parsed JSON or None."""
    if not GEMINI_API_KEY:
        return None

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": 0.2,
            "top_p": 0.9
        }
    }
    
    stats["gemini_calls"] += 1
    
    try:
        resp = requests.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=GEMINI_TIMEOUT
        )
        
        if resp.status_code != 200:
            stats["gemini_error"] += 1
            return None
        
        data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            stats["gemini_error"] += 1
            return None
        
        text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        if not text:
            stats["gemini_error"] += 1
            return None
        
        # Extract JSON from response (handle markdown fences)
        text = text.strip()
        if text.startswith("```"):
            # Remove markdown code fences
            lines = text.split("\n")
            text = "\n".join(l for l in lines if not l.startswith("```"))
        
        parsed = json.loads(text)
        stats["gemini_success"] += 1
        return parsed
        
    except requests.Timeout:
        stats["gemini_timeout"] += 1
        return None
    except Exception:
        stats["gemini_error"] += 1
        return None


# ── Prompt Builder ──────────────────────────────────────

def _street_name(street: str) -> str:
    mapping = {
        "PreDeal": "Pre-flop",
        "Preflop": "Pre-flop",
        "Flop": "Flop",
        "Turn": "Turn",
        "River": "River"
    }
    return mapping.get(street, street)


def _position_name(pos: int) -> str:
    return POSITION_NAMES.get(pos, f"Position {pos}")


def _format_hand_history(table_state: dict) -> str:
    """Format recent hand history from table state if available."""
    # DevFun API doesn't provide hand history, but we can note
    # what we know about this table
    parts = []
    street = table_state.get("street", "PreDeal")
    board = table_state.get("boardCards", [])
    
    if street != "PreDeal":
        parts.append(f"Street: {_street_name(street)}")
    
    if board:
        parts.append(f"Board: {' '.join(board)}")
    
    return "\n".join(parts)


def _build_prompt(hole_cards, board, pot, stack, call_amount, current_bet,
                  allowed_actions, street, num_opponents, position,
                  opponent_profiles_text, bb_size, table_state,
                  min_bet=None, min_raise_to=None, game_mode="tournament") -> str:
    """Build the complete prompt for Gemini."""
    
    hole_display = " ".join(hole_cards) if hole_cards else "?"
    board_display = " ".join(board) if board else "Pre-flop (no board yet)"
    street_display = _street_name(street)
    pos_display = _position_name(position)
    bb_stack = round(stack / bb_size, 1)
    
    allowed_str = ", ".join(allowed_actions)
    
    # Pot odds info
    pot_odds_str = ""
    if call_amount > 0 and pot > 0:
        odds_pct = round(call_amount / (pot + call_amount) * 100, 1)
        pot_odds_str = f"Pot odds: {odds_pct}% (need to call {call_amount} to win {pot + call_amount})"

    # Raise history — tell Gemini if we already raised this street
    raise_history = ""
    try:
        from pokerbot.bot import get_street_raise_count
        src = get_street_raise_count(street)
    except ImportError:
        src = 0
    if src > 0:
        raise_history = f"\n⚠️ IMPORTANT: You have already RAISED {src} time(s) this street. If facing a re-raise with a non-premium hand (below top pair/overpair), consider FOLDING or CALLING instead of raising again. Do NOT escalate with marginal hands."
    
    # Legal sizing constraints from API
    sizing_rules = ""
    if "bet" in allowed_actions and min_bet:
        sizing_rules += f"\n- If betting: minimum legal bet is {min_bet} chips"
    if "raise" in allowed_actions and min_raise_to:
        sizing_rules += f"\n- If raising: minimum legal raise to is {min_raise_to} chips"
    
    # Stack depth zone for tournament-aware strategy
    if bb_stack <= 10:
        zone = "CRITICAL (<10 BB): push-or-fold. Shove ANY ace, any pair, KQ/KJ/QT, any suited connector T9s+. Fold only trash (72o, 62o, 53o)."
    elif bb_stack <= 15:
        zone = "SHORT (10-15 BB): shove-or-fold. Shove AT+, KJ+, QT+, any pair 55+, any suited ace, suited connectors JTs+. Open-shove from late position with anything 20%+ equity. Never limp."
    elif bb_stack <= 25:
        zone = "MEDIUM (15-25 BB): tight-aggressive. Open-raise AT+, KJ+, QJ+, any pair, A2s+, KTs+, QTs+. Shove JJ+/AK/AQs vs 3-bets. Do NOT limp. Play suited connectors and broadways."
    elif bb_stack <= 50:
        zone = "COMFORTABLE (25-50 BB): solid TAG. Open wide from late position (any ace, K9+, Q9+, connectors). Do NOT fold KQs, A8s, T8s to small raises."
    else:
        zone = "DEEP (>50 BB): balanced poker. Open wide late position, value bet strong hands. One raise max with marginal hands (K8s, Q9s) facing resistance."

    # Tournament-specific rule block
    tournament_rules = """TOURNAMENT RULES (always apply):
- This is a TOURNAMENT, not a cash game. Chips lost cannot be rebought easily. Survival matters.
- NEVER 3-bet or 4-bet with weak/medium hands (A2s, A3s, KJo, QJo, etc). Only 3-bet with premiums (JJ+, AQ+, AK).
- Do NOT stack off with one-pair hands (top pair, etc) unless very short-stacked (<15 BB) or facing extreme pressure.
- When facing a 3-bet, fold everything except JJ+, AQs, AK. Do not 4-bet light.
- On wet/draw-heavy boards with one-pair or two-pair, prefer check-call over bet-bet-bet. Do not bloat the pot unnecessarily.
- KJo, QJo, K8s, A4s, A7s are MARGINAL hands — NOT strong. Do not raise-war with these. One raise is the absolute maximum; if re-raised, fold.
- If you have already raised once and face a re-raise with anything less than QQ/AK, FOLD. Do not keep raising."""

    # Eval/PVE rule block: stacks reset every hand, opponents are fixed house
    # bots measured (~1M hands) at VPIP 22 / PFR 17 / AF 2.0 / WTSD 93%.
    # They fold a lot preflop but almost NEVER fold once they see a flop.
    eval_rules = """PVE BENCHMARK RULES (this is NOT a tournament):
- Stacks RESET every hand. Busting a hand costs nothing beyond the chips in it. There is NO survival concern, NO ICM. Your ONLY goal: maximize average chips won per hand.
- The opponents are house bots with a known, fixed profile: they fold ~78% of hands preflop, but once they see a flop they go to showdown ~93% of the time. They are calling stations postflop.
- Therefore: DO NOT BLUFF postflop. Bluffs are pure fire vs. stations. No bluff c-bets, no barreling with air, no river bluffs.
- VALUE BET RELENTLESSLY: any top pair or better, bet 60-100% pot on flop, turn AND river. They will call with worse. Thin value is king: second pair good kicker is often a value bet too.
- Preflop: attack their folds. Open-raise wide (any pair, any ace, any two broadway, suited connectors), 3-bet premiums big for value (they call 3-bets too wide).
- With draws: take free cards or call small bets; do not semi-bluff big (they don't fold).
- Fold weak made hands to their big aggression — when a station raises, they have it."""

    # Cash/playground rule block: deep stacks, rebuys allowed → NOT survival.
    # Score is chips won, so play standard aggressive deep-stack poker.
    cash_rules = """CASH-GAME / PLAYGROUND RULES (this is NOT a survival tournament):
- Stacks are deep and rebuys are allowed. There is NO ICM, NO survival premium. Your goal is to WIN CHIPS, so play standard winning cash-game poker, not nitty fold-everything poker.
- OPEN WIDE, especially in position: from the button/cutoff open any pair, any ace, any two broadway, any suited king, suited connectors down to 54s, and K9s/Q9s/J9s type hands. Folding the button with K9s or T8s is a LEAK.
- Do not over-fold. A single raise in front is not a reason to fold a suited/connected/broadway hand in position — call or 3-bet.
- 3-bet premiums for value AND mix in occasional light 3-bets in position vs late-position opens.
- Value bet made hands across streets. C-bet most flops as the preflop raiser in position. Bet your draws for fold equity.
- Still respect real strength: fold to heavy multi-street aggression without a strong hand; don't stack off 100BB+ with one pair on scary boards."""

    if game_mode == "eval":
        rules_block = eval_rules
        game_label = "a PVE POKER BENCHMARK against fixed house bots (reset-stack hands, scored in bb/100)"
        zone_line = f"STACK DEPTH: {bb_stack} BB — stacks reset every hand; play pure chip-EV maximization, no survival adjustments."
    elif game_mode == "cash":
        rules_block = cash_rules
        game_label = "a deep-stacked CASH-GAME style arena (rebuys allowed, ranked by chips won)"
        zone_line = f"STACK DEPTH: {bb_stack} BB — deep-stacked cash game; play wide, aggressive, positional poker (no survival/ICM)."
    else:
        rules_block = tournament_rules
        game_label = "an online POKER TOURNAMENT"
        zone_line = f"STACK DEPTH: {bb_stack} BB — {zone}"

    heads_up_note = ""
    if num_opponents == 1:
        heads_up_note = "\nHEADS-UP POT: ranges are MUCH wider — any pair, any ace, king-high are strong. Do not play fit-or-fold."

    prompt = f"""You are an expert poker AI playing No-Limit Texas Hold'em in {game_label}. Make decisions based on pot odds, implied odds, opponent tendencies, and maximum-EV strategy for this format.

{zone_line}{heads_up_note}

CURRENT SITUATION:
- Your hand: {hole_display}
- Board: {board_display}
- Pot: {pot} chips
- Your stack: {stack} chips ({bb_stack} BB)
- Current bet to call: {call_amount}
- Your position: {pos_display}
- Players in hand (including you): {num_opponents + 1}
- {pot_odds_str}{raise_history}

AVAILABLE ACTIONS: {allowed_str}

OPPONENT PROFILES (from real-time observation):
{opponent_profiles_text}

{rules_block}

Based on all the above, make the maximum-EV decision for this format.

Return ONLY valid JSON (no markdown, no extra text):
{{"action": "fold|check|call|bet|raise", "amount": <number>, "confidence": <0.0-1.0>, "reasoning": "<one sentence>"}}

Rules for bet/raise amounts:
- If betting: size between 0.33x and 1.0x the pot{sizing_rules}
- If raising: size between 2.0x and 4.0x the current bet{sizing_rules}
- If all-in: use "all-in" as action, set amount to your stack. ONLY go all-in with strong made hands or when short-stacked (<15 BB) with a decent hand.
- For fold/check/call: amount = call_amount or 0"""

    return prompt


# ── Gemini Decision ─────────────────────────────────────

def gemini_decision(hole_cards, board, pot, stack, call_amount, current_bet,
                    allowed_actions, street, num_opponents, position,
                    opponent_profiles_text, bb_size=2, table_state=None,
                    game_mode="tournament") -> tuple:
    """
    Make a poker decision using Gemini 3.1 Flash Lite.
    
    Returns: (action: str, amount: int, reasoning: str, confidence: float)
    On failure: returns (None, None, "fallback to quant", 0.0)
    """
    
    # Get legal bet/raise limits from table state
    min_bet = None
    min_raise_to = None
    max_commit = stack
    if table_state:
        aa = table_state.get("allowedActions", {}) or {}
        min_bet = aa.get("minBet")
        min_raise_to = aa.get("minRaiseTo")
        max_commit = aa.get("maxCommit", stack)
        bet_range = aa.get("betRange")
        raise_range = aa.get("raiseRange")
    
    prompt = _build_prompt(hole_cards, board, pot, stack, call_amount,
                          current_bet, allowed_actions, street, num_opponents,
                          position, opponent_profiles_text, bb_size, table_state,
                          min_bet, min_raise_to, game_mode=game_mode)
    
    result = _call_gemini(prompt)
    
    if result is None:
        return (None, None, "Gemini unavailable, falling back to quant", 0.0)
    
    action = result.get("action", "").lower()
    amount = result.get("amount", 0)
    
    # Validate action
    if action not in allowed_actions and action not in ("fold", "check", "call"):
        return (None, None, f"Gemini suggested invalid action '{action}'", 0.0)
    
    # Validate amount against legal limits
    if action == "bet":
        if min_bet and amount < min_bet:
            amount = min_bet
        if amount > max_commit:
            amount = max_commit
    elif action == "raise":
        if min_raise_to and amount < min_raise_to:
            amount = min_raise_to
        if amount > max_commit:
            amount = max_commit
    elif action in ("fold", "check"):
        amount = 0
    elif action == "all-in":
        amount = stack
    elif action == "call":
        amount = call_amount
    
    reasoning = result.get("reasoning", "No reasoning given")
    confidence = result.get("confidence", 0.5)
    
    return (action, amount, reasoning, confidence)


# ── Main Decision Entry Point ───────────────────────────

# ── LLM Opponent Reader ─────────────────────────────────
# Runs OFF the decision path (post-hand, throttled by the Profiler). Reads an
# opponent's accumulated stats + action transcript + showdown history and
# synthesizes a qualitative tendencies summary. The result is cached on the
# profile (Profiler.summary_for_prompt) and injected into the decision prompt
# with ZERO added decision latency. Returns the rendered summary string, or
# None on any failure so the caller keeps the deterministic fallback.

def llm_opponent_summary(profile) -> Optional[str]:
    """Synthesize a qualitative opponent tendencies summary via Gemini.

    Returns a prompt-ready summary string on success, None on any failure
    (no API key, timeout, non-200, unparseable/invalid JSON)."""
    if not GEMINI_API_KEY:
        return None

    stats = profile.compute_stats()
    name = profile.agent_name or f"Opponent {profile.agent_id[:8]}"
    reliability = ("high" if profile.total_actions >= 20 else
                   "medium" if profile.total_actions >= 10 else "low")

    prompt = f"""You are a poker opponent-reader. Given a target opponent's observed stats, recent action transcript, and showdown history, write a CONCISE tendencies profile an exploiting player can act on in one read.

OPPONENT: {name} — current read: {profile.classify_style()} (reliability: {reliability})
HANDS OBSERVED: {profile.hands_observed}, ACTIONS: {profile.total_actions}

STATS:
  VPIP {stats['vpip']*100:.0f}% | PFR {stats['pfr']*100:.0f}% | AF {stats['aggression_factor']:.1f} | 3bet {stats['three_bet_pct']*100:.0f}% | c-bet {stats['cbet_pct']*100:.0f}% | fold-to-cbet {stats['fold_to_cbet_pct']*100:.0f}%

RECENT ACTION TRANSCRIPT (most recent last):
{profile.transcript_text(limit=20)}

SHOWDOWN HANDS REVEALED:
{profile.showdown_text(limit=10)}

Return ONLY valid JSON (no markdown, no extra text):
{{"style": "<one phrase: e.g. tight-aggressive / loose-passive calling station / maniac / nit>", "tendencies": ["<short concrete tendency>", "<up to 4 more>"], "exploitation": ["<one short exploit hint>", "<optional second>"], "reliability": "<low|medium|high>"}}"""

    result = _call_gemini(prompt, max_tokens=300)
    if not isinstance(result, dict):
        return None

    style = result.get("style", "").strip()
    tendencies = result.get("tendencies", [])
    exploitation = result.get("exploitation", [])
    reliability = result.get("reliability", "").strip() or reliability

    # Schema validation: need at least a style and one concrete tendency.
    if not style or not isinstance(tendencies, list) or not tendencies:
        return None
    tendencies = [t for t in tendencies if isinstance(t, str) and t.strip()]
    exploitation = [t for t in exploitation if isinstance(t, str) and t.strip()]
    if not tendencies:
        return None

    rendered = f"{name}: {style} (reliability: {reliability})."
    rendered += " Tendencies: " + "; ".join(tendencies) + "."
    if exploitation:
        rendered += " Exploit: " + "; ".join(exploitation) + "."
    return rendered


def decide_with_profiling(hole_cards, board, allowed_actions, pot, stack,
                          call_amount, current_bet, num_opponents, street,
                          position, table_state, profiler: Profiler,
                          bb_size=2, game_mode="tournament") -> tuple:
    """
    Main decision function. Uses Gemini + profiler, falls back to quant_decision.
    
    Returns: (action, amount, message, equity/confidence)
    """
    
    # Get opponent profiles
    seats = table_state.get("seats", []) if table_state else []
    our_agent_id = table_state.get("selfAgentId", "")
    
    # Extract opponent IDs from seats
    opponent_ids = []
    for seat in seats:
        aid = seat.get("agentId", "")
        if aid and aid != our_agent_id:
            opponent_ids.append(aid)
    
    opponent_text = profiler.get_table_profiles(seats, our_agent_id)
    
    # Try Gemini
    if len(opponent_ids) > 0 or True:  # Always try Gemini if we can
        action, amount, reasoning, confidence = gemini_decision(
            hole_cards, board, pot, stack, call_amount, current_bet,
            allowed_actions, street, num_opponents, position,
            opponent_text, bb_size, table_state, game_mode=game_mode
        )
        
        if action is not None:
            msg = f"🎯 Gemini: {reasoning}"
            return (action, amount, msg, confidence)
    
    # Fallback to quant_decision (returns 4 values: action, amount, msg, confidence)
    stats["fallback_calls"] += 1
    
    action, amount, msg, _ = quant_decision(
        hole_cards, board, allowed_actions, pot, stack,
        call_amount, current_bet, num_opponents, street, "unknown",
        bb_size, position
    )
    
    # Get equity for confidence
    if street in ("PreDeal", "Preflop") and hole_cards:
        equity = preflop_equity(hole_cards, num_opponents)
    elif board and hole_cards:
        equity = monte_carlo_equity(hole_cards, board, num_opponents, num_sims=200)
    else:
        equity = 0.5 if hole_cards else 0
    
    msg = f"🔧 quant: {msg}"
    return (action, amount, msg, equity)


def get_stats() -> dict:
    """Return Gemini usage statistics."""
    return dict(stats)
