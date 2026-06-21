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
GEMINI_TIMEOUT = 2.0

# Statistics tracking
stats = {"gemini_calls": 0, "gemini_success": 0, "gemini_timeout": 0,
         "gemini_error": 0, "fallback_calls": 0}

# ── Gemini API Call ─────────────────────────────────────

def _call_gemini(prompt: str) -> Optional[dict]:
    """Call Gemini 3.1 Flash Lite. Returns parsed JSON or None."""
    if not GEMINI_API_KEY:
        return None
    
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": 200,
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
                  min_bet=None, min_raise_to=None) -> str:
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
    
    # Legal sizing constraints from API
    sizing_rules = ""
    if "bet" in allowed_actions and min_bet:
        sizing_rules += f"\n- If betting: minimum legal bet is {min_bet} chips"
    if "raise" in allowed_actions and min_raise_to:
        sizing_rules += f"\n- If raising: minimum legal raise to is {min_raise_to} chips"
    
    prompt = f"""You are an expert poker AI playing 6-max No-Limit Texas Hold'em in an online tournament playground. Make decisions based on pot odds, implied odds, opponent tendencies, and proper poker strategy.

CURRENT SITUATION:
- Your hand: {hole_display}
- Board: {board_display}
- Pot: {pot} chips
- Your stack: {stack} chips ({bb_stack} BB)
- Current bet to call: {call_amount}
- Your position: {pos_display}
- Players in hand (including you): {num_opponents + 1}
- {pot_odds_str}

AVAILABLE ACTIONS: {allowed_str}

OPPONENT PROFILES (from real-time observation):
{opponent_profiles_text}

Based on all the above, make the optimal decision.

Return ONLY valid JSON (no markdown, no extra text):
{{"action": "fold|check|call|bet|raise", "amount": <number>, "confidence": <0.0-1.0>, "reasoning": "<one sentence>"}}

Rules for bet/raise amounts:
- If betting: size between 0.33x and 1.0x the pot{sizing_rules}
- If raising: size between 2.0x and 4.0x the current bet{sizing_rules}
- If all-in: use "all-in" as action, set amount to your stack
- For fold/check/call: amount = call_amount or 0"""

    return prompt


# ── Gemini Decision ─────────────────────────────────────

def gemini_decision(hole_cards, board, pot, stack, call_amount, current_bet,
                    allowed_actions, street, num_opponents, position,
                    opponent_profiles_text, bb_size=2, table_state=None) -> tuple:
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
                          min_bet, min_raise_to)
    
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

def decide_with_profiling(hole_cards, board, allowed_actions, pot, stack,
                          call_amount, current_bet, num_opponents, street,
                          position, table_state, profiler: Profiler,
                          bb_size=2) -> tuple:
    """
    Main decision function. Uses Gemini + profiler, falls back to quant_decision.
    
    Returns: (action, amount, message, equity/confidence)
    """
    
    # Get opponent profiles
    seats = table_state.get("seats", []) if table_state else []
    our_agent_id = table_state.get("selfSeatNumber", "")
    
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
            opponent_text, bb_size, table_state
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
