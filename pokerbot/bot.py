#!/usr/bin/env python3
"""DevFun Arena Texas Hold'em Poker Bot.
Polls pending-actions, makes rule-based decisions, submits actions.
Uses configured model for tough spots only."""

import requests
import json
import time
import os
import sys
import random
from datetime import datetime, timezone

# Gemini AI player: set GEMINI_DEEP_RESEARCH_API_KEY env var for AI-powered decisions
# Falls back to quant_decision() automatically if unset or unavailable

# ── Config ──────────────────────────────────────────────
BASE = "https://arena.dev.fun"
# Competition ID — override via ARENA_COMPETITION_ID env var
# Current: cmqf827h30u7dfca3x2aqvzjv = Playground S3
# Eval:    seed_poker_eval_s1 = Eval S1
COMPETITION_ID = os.environ.get("ARENA_COMPETITION_ID", "cmqf827h30u7dfca3x2aqvzjv")

# Workspace: where state/pid/coach files live. Defaults to repo root.
# Override via ARENA_WORKSPACE for multi-instance (e.g. eval).
WORKSPACE = os.environ.get("ARENA_WORKSPACE", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATE_FILE = f"{WORKSPACE}/.arena-poker-state"
OPPONENTS_FILE = f"{WORKSPACE}/.arena-opponents.json"
STOP_FILE = f"{WORKSPACE}/.arena-stop"
PID_FILE = f"{WORKSPACE}/.arena-bot.pid"
COACH_FILE = f"{WORKSPACE}/.arena-coach-advice"


def _first_existing(paths):
    """Return the first path in `paths` that exists on disk, else None."""
    return next((p for p in paths if p and os.path.isfile(p)), None)


# Credentials resolution (first match wins):
#   1. ARENA_CREDENTIALS env var            — explicit per-instance override
#   2. <parent-of-repo>/.arena-credentials  — legacy / shared-credential default
#   3. <ARENA_WORKSPACE>/.arena-credentials  — honor the workspace override last
# Keeping #2 as the default preserves existing deployments unchanged.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CRED_FILE = _first_existing([
    os.environ.get("ARENA_CREDENTIALS", ""),
    os.path.join(_REPO_ROOT, ".arena-credentials"),
    os.path.join(WORKSPACE, ".arena-credentials"),
])
if CRED_FILE is None:
    raise FileNotFoundError(
        ".arena-credentials not found. Set ARENA_CREDENTIALS, or place it at "
        f"{os.path.join(_REPO_ROOT, '.arena-credentials')!r} or under "
        f"ARENA_WORKSPACE={WORKSPACE!r}."
    )
API_KEY = ""
AGENT_ID = ""
for line in open(CRED_FILE):
    line = line.strip()
    if line.startswith("apiKey="):
        API_KEY = line.split("=", 1)[1]
    elif line.startswith("agentId="):
        AGENT_ID = line.split("=", 1)[1]

HEADERS = {"x-arena-api-key": API_KEY, "Content-Type": "application/json"}

# Coach advice (reloaded periodically)
coach_advice = ""
last_coach_check = 0

# Prevent duplicate instances
import fcntl
try:
    pid_fd = open(PID_FILE, "w")
    fcntl.flock(pid_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    pid_fd.write(str(os.getpid()))
    pid_fd.flush()
except (IOError, OSError):
    print("Another instance is already running. Exiting.")
    sys.exit(0)

# Polling
POLL_INTERVAL = 1.5  # seconds between polls when idle
API_COOLDOWN = 0.8  # minimum seconds between API calls
last_api_call = 0

# ── Helpers ──────────────────────────────────────────────

def rate_limit():
    """Enforce minimum gap between API calls."""
    global last_api_call
    elapsed = time.time() - last_api_call
    if elapsed < API_COOLDOWN:
        time.sleep(API_COOLDOWN - elapsed)
    last_api_call = time.time()

def get(endpoint, params=None):
    rate_limit()
    try:
        r = requests.get(f"{BASE}{endpoint}", headers=HEADERS, params=params, timeout=15)
        return r.json() if r.ok else {"_error": r.status_code, "_body": r.text[:200]}
    except Exception as e:
        return {"_error": str(e)}

def post(endpoint, data=None):
    rate_limit()
    try:
        r = requests.post(f"{BASE}{endpoint}", headers=HEADERS, json=data or {}, timeout=15)
        return r.json() if r.ok else {"_error": r.status_code, "_body": r.text[:200]}
    except Exception as e:
        return {"_error": str(e)}

def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except:
        return {"hands_played": 0, "hands_won": 0, "biggest_pot": 0, "totalChips": 1000}

def save_state(s):
    with open(STATE_FILE, "w") as f:
        json.dump(s, f, indent=2)

def load_opponents():
    try:
        with open(OPPONENTS_FILE) as f:
            return json.load(f)
    except:
        return {"opponents": {}}

def save_opponents(o):
    with open(OPPONENTS_FILE, "w") as f:
        json.dump(o, f, indent=2)

def log(msg):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

def reload_coach():
    """Reload coach advice file."""
    global coach_advice, last_coach_check
    now = time.time()
    if now - last_coach_check < 30:  # check every 30s
        return
    last_coach_check = now
    try:
        with open(COACH_FILE) as f:
            advice = f.read().strip()
            if advice and advice != coach_advice:
                coach_advice = advice
                if advice != 'steady':
                    log(f"COACH: {advice[:100]}...")
    except:
        pass

# ── Opponent Fetch ──────────────────────────────────────

def fetch_opponent_stats(agent_id):
    opponents = load_opponents()
    if agent_id in opponents.get("opponents", {}):
        return opponents["opponents"][agent_id]
    
    log(f"Fetching stats for opponent {agent_id[:12]}...")
    data = get(f"/api/arena/texas/agent-stats", {"agentId": agent_id, "competitionId": COMPETITION_ID})
    stats = data if not data.get("_error") else {}
    
    opponents["opponents"][agent_id] = {
        "stats": stats,
        "last_fetched": datetime.now(timezone.utc).isoformat()
    }
    save_opponents(opponents)
    return opponents["opponents"][agent_id]

def get_opponent_style(agent_id):
    """Get opponent style — use VPIP/PFR stats if label is unknown."""
    try:
        opp = fetch_opponent_stats(agent_id)
        stats = opp.get("stats", {}) or {}
        playing_style = stats.get("playingStyle") or {}
        style = playing_style.get("label", "unknown") if isinstance(playing_style, dict) else "unknown"
        mapping = {
            "loose-aggressive": "LAG",
            "tight-aggressive": "TAG",
            "loose-passive": "Station",
            "tight-passive": "Nit",
            "tight-weak": "Weak-Tight",
        }
        mapped = mapping.get(style, style if style != "unknown" else "unknown")
        
        # If style is unknown, try to classify from stats
        if mapped == "unknown":
            from pokerbot.quant import classify_from_stats
            vpip = stats.get("vpip", 0) or 0
            pfr = stats.get("pfr", 0) or 0
            af = stats.get("aggressionFactor", 0) or 0
            mapped = classify_from_stats(vpip, pfr, af)
        
        return mapped
    except Exception:
        return "unknown"

# ── Strategy Engine ─────────────────────────────────────
# Import quantitative poker engine
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pokerbot.quant import (
    quant_decision, preflop_equity, monte_carlo_equity,
    preflop_hand_key, hand_tier, is_premium_hand,
    classify_board_texture, exploitation_adjustment,
    classify_from_stats,
    get_fold_equity, tournament_phase, is_near_bubble,
    icm_tighten_factor, effective_bb_over_time,
    postflop_decision, estimate_draw_equity,
)

# Import AI player + profiler
from pokerbot.player import decide_with_profiling, get_stats as get_ai_stats, llm_opponent_summary
from pokerbot.profiler import Profiler

# Initialize profiler (saves profiles to opponent_profiles.json)
profiler = Profiler()

# ── Tightened Preflop Ranges (VPIP ~25-30%) ──
# UTG: ~15%, HJ: ~20%, CO: ~25%, BTN: ~30%, SB: ~25%, BB: ~10% (defending)
PREFLOP_OPEN = {
    0: {"pairs": 9, "high": ["AK", "AQ"], "suited": ["AK", "AQ", "AJs"]},                        # UTG ~15%
    1: {"pairs": 8, "high": ["AK", "AQ", "AJ"], "suited": ["AK", "AQ", "AJ", "ATs", "KQ"]},       # HJ ~20%
    2: {"pairs": 6, "high": ["AK", "AQ", "AJ", "AT", "KQ"], "suited": ["AK", "AQ", "AJ", "ATs", "A9s", "KQ", "KJs", "QJs"]},  # CO ~25%
    3: {"pairs": 3, "high": ["AK", "AQ", "AJ", "AT", "A9", "KQ", "KJ"], "suited": ["AK", "AQ", "AJs", "ATs", "A9s", "A8s", "A7s", "A6s", "A5s", "KQ", "KJs", "QTs", "JTs", "T9s"]},  # BTN ~30%
    4: {"pairs": 7, "high": ["AK", "AQ", "AJ", "A9", "KQ", "KJ"], "suited": ["AK", "AQ", "AJs", "ATs", "KQ", "KJs"]},   # SB ~25%
    5: {"pairs": 5, "high": ["AK", "AQ"], "suited": ["AK", "AQ", "AJs", "ATs", "KQs"]},           # BB ~10% (defending)
}

def parse_card(card_str):
    """Parse 'Ah' -> (rank='A', suit='h'). Returns (rank_char, suit_char)."""
    if not card_str or len(card_str) < 2:
        return ('?', '?')
    return (card_str[0].upper(), card_str[1].lower())

def card_rank_value(rank_char):
    order = {'2':2,'3':3,'4':4,'5':5,'6':6,'7':7,'8':8,'9':9,'T':10,'J':11,'Q':12,'K':13,'A':14}
    return order.get(rank_char, 0)

def has_pair(hole_cards):
    if not hole_cards or len(hole_cards) < 2:
        return False
    return hole_cards[0][0].upper() == hole_cards[1][0].upper()

def is_suited(hole_cards):
    if not hole_cards or len(hole_cards) < 2:
        return False
    return hole_cards[0][1].lower() == hole_cards[1][1].lower()

def pair_rank(hole_cards):
    """Return numeric pair value (2-14) if paired, else 0."""
    if has_pair(hole_cards):
        return card_rank_value(hole_cards[0][0].upper())
    return 0

def high_card_ranks(hole_cards):
    """Return sorted (hi, lo) rank values for unpaired hand."""
    r1 = card_rank_value(hole_cards[0][0].upper())
    r2 = card_rank_value(hole_cards[1][0].upper())
    return (max(r1, r2), min(r1, r2))

def hand_in_range(hole_cards, pos_idx):
    """Check if hole cards are in our tightened pre-flop open range for position."""
    rng = PREFLOP_OPEN[pos_idx]
    pr = pair_rank(hole_cards)
    
    if pr >= rng["pairs"]:
        return True
    
    hi, lo = high_card_ranks(hole_cards)
    suited = is_suited(hole_cards)
    
    rank_to_char = {14:'A',13:'K',12:'Q',11:'J',10:'T',9:'9',8:'8',7:'7',6:'6',5:'5',4:'4',3:'3',2:'2'}
    hic = rank_to_char.get(hi, '')
    loc = rank_to_char.get(lo, '')
    hand_str = hic + loc
    
    # Note: high list stores "AK", "AQ" etc (offsuit broadway)
    # suited list stores "AKs", "AQs" etc (suited broadway)
    if suited and hand_str + 's' in rng.get("suited", []):
        return True
    if not suited and hand_str in rng.get("high", []):
        return True
    return False

def board_has_flush_draw(board):
    suits = [c[1].lower() for c in board if len(c) >= 2]
    from collections import Counter
    return any(v >= 3 for v in Counter(suits).values())

def board_straight_draw(board):
    ranks = sorted(set(card_rank_value(c[0].upper()) for c in board if len(c) >= 2))
    for i in range(len(ranks) - 2):
        if ranks[i+2] - ranks[i] <= 4:
            return True
    return False

def classify_board(board):
    """Classify board texture: dry, wet, paired, ace_high, connected_low."""
    return classify_board_texture(board)

# ── Hand State Tracker ──
# Track per-hand state: did we raise preflop, previous street actions
_hand_state = {}

def reset_hand_state():
    global _hand_state
    _hand_state = {
        'raised_preflop': False,
        'prev_action': 'check',
        'prev_equity': 0,
        'street': 'preflop',
        'raise_count_per_street': {},  # {'Preflop': 1, 'Flop': 2, ...}
    }

def update_hand_state(action, equity=0, street=None):
    global _hand_state
    if street:
        _hand_state['prev_action'] = _hand_state.get('street_action', 'check')
        _hand_state['prev_equity'] = _hand_state.get('equity', 0)
        _hand_state['street'] = street
        _hand_state['street_action'] = action
        _hand_state['equity'] = equity
    if action in ('bet', 'raise') and _hand_state['street'] in ('PreDeal', 'Preflop'):
        _hand_state['raised_preflop'] = True
    # Track raise count per street
    st = street or _hand_state.get('street', 'preflop')
    if action in ('bet', 'raise'):
        _hand_state['raise_count_per_street'][st] = _hand_state['raise_count_per_street'].get(st, 0) + 1
    _hand_state['last_action'] = action

def get_street_raise_count(street):
    st = street or _hand_state.get('street', 'preflop')
    return _hand_state.get('raise_count_per_street', {}).get(st, 0)

MAX_RAISES_PER_STREET = 2  # Cap raises per street to prevent infinite raise wars

def get_hand_state():
    return _hand_state

# ── Opponent Action Capture (feeds the Profiler + LLM reader) ──
# The Arena API exposes no action log, so we infer each opponent's action by
# diffing per-seat state between consecutive table snapshots we see (once per
# our turn). Blinds never get mis-counted: the snapshot is dropped at hand-end,
# so each hand's first snapshot has no predecessor to diff against.
_last_table_snapshot = {}

_STREET_ORDER = {"PreDeal": 0, "Preflop": 1, "Flop": 2, "Turn": 3, "River": 4}


def _classify_seat_action(prev_seat, curr_seat, prev_snap, bb_size):
    """Infer one opponent action from a seat's stack/status change.

    Returns (action, chips_in, facing_bet) or None when nothing conclusive."""
    prev_stack = prev_seat.get("stackChips", 0) or 0
    curr_stack = curr_seat.get("stackChips", 0) or 0
    delta = prev_stack - curr_stack  # >0 = chips left their stack
    prev_status = prev_seat.get("status")
    curr_status = curr_seat.get("status")
    facing_bet = (prev_snap.get("currentBet", 0) or 0) > 0

    if curr_status == "Folded" and prev_status != "Folded":
        return ("fold", 0, facing_bet)
    if curr_status == "AllIn" and prev_status != "AllIn":
        return ("all-in", delta, facing_bet)
    if delta > bb_size:  # clearly voluntary (more than a single blind)
        if facing_bet:
            call_sz = prev_snap.get("currentBet", 0) or 0
            return ("raise" if delta > call_sz * 1.3 else "call", delta, facing_bet)
        return ("bet", delta, facing_bet)
    if delta > 0:  # small voluntary — limp or min-call
        return ("call" if facing_bet else "bet", delta, facing_bet)
    if prev_status != "Folded" and curr_status != "Folded" and not facing_bet:
        return ("check", 0, facing_bet)
    return None


def _capture_opponent_actions(table, profiler_obj, our_agent_id, bb_size=None):
    """Diff this table snapshot vs the prior one for this tableId and feed each
    inferred opponent action to the profiler. Best-effort: the LLM reader is
    robust to the residual noise; deterministic stats may under/over-count but
    never crash."""
    table_id = table.get("tableId")
    if table_id is None:
        return
    street = table.get("street", "PreDeal")
    seats = table.get("seats", []) or []

    # Build the current per-seat snapshot.
    curr_seats = {}
    for seat in seats:
        sn = seat.get("seatNumber")
        if sn is None:
            continue
        curr_seats[sn] = {
            "agentId": seat.get("agentId", ""),
            "agentName": seat.get("agentName", ""),
            "stackChips": seat.get("stackChips", 0) or 0,
            "status": seat.get("status", ""),
        }
    curr_snap = {
        "seats": curr_seats,
        "street": street,
        "potChips": table.get("potChips", 0) or 0,
        "currentBet": table.get("currentBet", 0) or 0,
    }

    prev_snap = _last_table_snapshot.get(table_id)
    if prev_snap:
        prev_street = prev_snap.get("street", "PreDeal")
        prev_pot = prev_snap.get("potChips", 0) or 0
        # New-hand guard: street regressed or pot reset → don't diff.
        same_hand = (_STREET_ORDER.get(street, 0) >= _STREET_ORDER.get(prev_street, 0)
                     and curr_snap["potChips"] >= prev_pot * 0.5)
        if same_hand:
            pot_before = prev_pot
            is_preflop = street in ("PreDeal", "Preflop")
            board_tex = classify_board(table.get("boardCards", []) or [])
            for sn, curr_seat in curr_seats.items():
                aid = curr_seat.get("agentId", "")
                if not aid or aid == our_agent_id:
                    continue
                prev_seat = prev_snap["seats"].get(sn)
                if not prev_seat or prev_seat.get("agentId") != aid:
                    continue
                inferred = _classify_seat_action(prev_seat, curr_seat, prev_snap, bb_size)
                if not inferred:
                    continue
                action, chips_in, fbet = inferred
                profiler_obj.observe_action(
                    agent_id=aid, agent_name=curr_seat.get("agentName", ""),
                    action=action, street=street, pot=pot_before,
                    call_amount=chips_in, stack_before=prev_seat.get("stackChips", 0),
                    is_preflop=is_preflop, board_texture=board_tex,
                    sizing_bb=round(chips_in / bb_size, 1) if bb_size else 0.0,
                    facing_bet=fbet, pot_before=pot_before,
                )

    _last_table_snapshot[table_id] = curr_snap


def refresh_opponent_llm_profile(profile, showdown_triggered=False, gemini_enabled=False):
    """Throttled LLM re-profile of one opponent. Runs only post-hand (off the
    decision path). Returns True when a fresh summary was written."""
    if not gemini_enabled or profile is None:
        return False
    if not profile.needs_llm_refresh(showdown_triggered=showdown_triggered):
        return False
    try:
        summary = llm_opponent_summary(profile)
    except Exception as e:
        log(f"⚠️ LLM profile error for {profile.agent_id[:8]}: {e}")
        return False
    if summary:
        profile.set_llm_summary(summary)
        return True
    return False

# ── Opponent Stats Tracker ──
_opponent_stats_cache = {}

def get_opponent_stats(agent_id):
    """Fetch and return raw stats dict for an opponent."""
    if agent_id in _opponent_stats_cache:
        return _opponent_stats_cache[agent_id]
    try:
        opp = fetch_opponent_stats(agent_id)
        stats = opp.get("stats", {}) or {}
        _opponent_stats_cache[agent_id] = stats
        return stats
    except:
        return {}

# ── Choose Preflop Action (Tightened) ──
def choose_preflop_action(state):
    """Decide pre-flop action: fold, call, bet, raise, all-in.
    Uses tightened ranges (~25-30% VPIP)."""
    hole_cards = state.get("hole_cards", [])
    pos = state.get("position", 3)  # default BTN if unknown
    allowed = state.get("allowed_actions", [])
    call_amount = state.get("call_amount", 0)
    current_bet = state.get("current_bet", 0)
    stack = state.get("stack", 0)
    pot = state.get("pot", 0)
    opponent_style = state.get("opponent_style", "unknown")
    
    in_range = hand_in_range(hole_cards, pos) if hole_cards else False
    pr = pair_rank(hole_cards)
    suited = is_suited(hole_cards)
    hi, lo = high_card_ranks(hole_cards) if hole_cards else (0, 0)
    
    # Use quant engine's hand tier
    key = preflop_hand_key(hole_cards) if hole_cards else '??'
    tier = hand_tier(hole_cards) if hole_cards else 'trash'
    
    exploit = exploitation_adjustment(opponent_style, tier, pos >= 3)
    exploit_notes = exploit.get('notes', [])
    
    in_position = pos >= 3  # CO/BTN are IP
    message = "let's see what develops"
    
    # ── FACING A RAISE ──
    is_premium = pr >= 11 or (hi == 14 and lo >= 13)  # JJ+ or AK
    
    if call_amount > 0 and "call" in allowed:
        if tier == 'premium':
            # 3-bet premiums (QQ+), 4-bet KK+
            if pr >= 13:  # KK+
                if "raise" in allowed:
                    raise_to = min(current_bet * 4, stack)
                    return ("raise", raise_to, "4-betting with a monster")
                return ("call", call_amount, "trapping premium")
            # QQ, JJ, AK: 3-bet for value
            if "raise" in allowed:
                raise_to = min(current_bet * 3, stack)
                return ("raise", raise_to, "3-betting for value")
            if "all-in" in allowed and stack < current_bet * 5:
                return ("all-in", stack, "short stack, getting it in good")
            return ("call", call_amount, "flatting premium IP")
        
        if tier == 'strong':
            # TT/AQs etc: call IP, fold OOP to tight opponents
            if 'fold_to_raises' in exploit_notes:
                if "fold" in allowed:
                    return ("fold", 0, f"fold — {key} vs {opponent_style}")
            if in_position:
                return ("call", call_amount, f"flat strong — {key} IP")
            if "fold" in allowed:
                return ("fold", 0, f"fold OOP — {key}")
            return ("call", call_amount, f"forced call — {key}")
        
        # Vs Nit: fold to raises (they have it)
        if 'fold_to_raises' in exploit_notes:
            if "fold" in allowed:
                return ("fold", 0, f"respect {opponent_style}'s raise")
        
        if not in_range:
            if "fold" in allowed:
                return ("fold", 0, "not the spot I'm looking for")
            return ("call", call_amount, "defending light")
        
        # Only very cheap speculative calls
        if call_amount <= pot * 0.1 and (suited or pr >= 7):
            return ("call", call_amount, "priced in with implied odds")
        
        if "fold" in allowed:
            return ("fold", 0, "too much to see a flop")
        return ("call", call_amount, "price is right")
    
    # ── NO RAISE FACING US — OPEN ──
    if "bet" in allowed and in_range:
        # Proper sizing: 3x in position, 4x OOP
        if tier in ('premium', 'strong'):
            bet_size = int(pot * 0.9) if tier == 'premium' else int(pot * 0.75)
        elif pr >= 7 or hi >= 13:
            bet_size = int(pot * 0.7)
        else:
            bet_size = int(pot * 0.55)
        update_hand_state('bet')
        return ("bet", bet_size, "opening with standard sizing")
    
    if "bet" in allowed and not in_range:
        # Steal from late position vs tight opponents
        if pos >= 3:
            if 'steal_more_late' in exploit_notes and random.random() < 0.30:
                update_hand_state('bet')
                return ("bet", int(pot * 0.5), f"steal vs {opponent_style}")
            if random.random() < 0.10:  # occasional steal
                update_hand_state('bet')
                return ("bet", int(pot * 0.5), "late position steal attempt")
        if "check" in allowed:
            return ("check", 0, "taking a free look")
        return ("fold", 0, "nothing to get excited about")
    
    if "check" in allowed:
        return ("check", 0, "checking behind")
    
    return ("fold", 0, "not investing here")

def choose_postflop_action(state):
    """Decide post-flop action using multi-street logic with opponent exploitation."""
    hole_cards = state.get("hole_cards", [])
    board = state.get("board", [])
    allowed = state.get("allowed_actions", [])
    call_amount = state.get("call_amount", 0)
    pot = state.get("pot", 0)
    stack = state.get("stack", 0)
    street = state.get("street", "flop")
    opponent_style = state.get("opponent_style", "unknown")
    position = state.get("position", 3)
    
    pr = pair_rank(hole_cards)
    hi, lo = high_card_ranks(hole_cards) if hole_cards else (0, 0)
    texture = classify_board(board)
    in_position = position >= 3
    
    hs = get_hand_state()
    raised_pf = hs.get('raised_preflop', False)
    prev_action = hs.get('prev_action', 'check')
    prev_eq = hs.get('prev_equity', 0)
    
    # Use the quant engine's multi-street postflop
    action, amount, msg, eq = postflop_decision(
        hole_cards, board, allowed, pot, stack,
        call_amount=call_amount,
        num_opponents=1,
        street=street,
        opponent_style=opponent_style,
        raised_preflop=raised_pf,
        in_position=in_position,
        prev_action_on_prior_street=prev_action,
        prev_equity=prev_eq,
    )
    
    update_hand_state(action, eq, street)
    return (action, amount, msg)

def decide_action(table):
    """Decision engine: Gemini 3.1 Flash Lite + profiler, falls back to quant_decision."""
    # Capture opponent actions seen since our last turn (cheap; off the LLM path).
    _capture_opponent_actions(table, profiler, AGENT_ID, bb_size=table.get('bigBlindChips'))
    allowed_actions = table.get("allowedActions", {})
    available = allowed_actions.get("availableActions", [])
    street = table.get("street", "PreDeal")
    board = table.get("boardCards", [])
    current_bet = table.get("currentBet", 0)
    pot = table.get("potChips", 0)
    
    # Get our seat info
    self_seat = table.get("selfSeatNumber")
    hole_cards = []
    stack = 0
    num_opp = 0
    opponent_style = "unknown"
    
    for seat in table.get("seats", []):
        if seat.get("seatNumber") == self_seat:
            hole_cards = seat.get("holeCards") or []
            stack = seat.get("stackChips", 0)
        elif seat.get("status") in ("Active", "AllIn"):
            num_opp += 1
            aid = seat.get("agentId", "")
            if aid:
                style = get_opponent_style(aid)
                if style != "unknown":
                    opponent_style = style
    
    num_opp = max(num_opp, 1)
    
    # Compute call amount
    call_amount = allowed_actions.get("callAmount", 0) or allowed_actions.get("callChips", 0) or 0
    
    # Estimate position
    dealer_seat = table.get("dealerSeatNumber", 0) or 0
    pos = 3
    if self_seat and dealer_seat:
        seats_count = len(table.get("seats", []))
        offset_from_dealer = (self_seat - dealer_seat) % seats_count
        pos_map = {1: 3, 2: 4, 3: 5, 4: 0, 5: 1, 6: 2}
        pos = pos_map.get(offset_from_dealer, 3)
    
    # Dynamic blind size from table (tournament may use 5/10, not 1/2)
    bb_size = table.get('bigBlindChips') or 2

    # ── Raise cap: prevent infinite raise wars ──
    from pokerbot.bot import get_street_raise_count, MAX_RAISES_PER_STREET
    street_raise_count = get_street_raise_count(street)
    if street_raise_count >= MAX_RAISES_PER_STREET:
        # We've already raised twice on this street — force fold or call
        if 'call' in available and call_amount > 0:
            call_msg = f"raise cap hit ({street_raise_count}/{MAX_RAISES_PER_STREET} on {street}), calling instead"
            log(f"   ⚠️ {call_msg}")
            return ('call', call_amount, call_msg)
        elif 'check' in available:
            return ('check', 0, f"raise cap hit ({street_raise_count}/{MAX_RAISES_PER_STREET} on {street}), checking")
        else:
            return ('fold', 0, f"raise cap hit ({street_raise_count}/{MAX_RAISES_PER_STREET} on {street}), folding")

    # Try Gemini + profiler first, fallback to quant_decision
    action, amount, msg, extra = decide_with_profiling(
        hole_cards, board, available, pot, stack,
        call_amount, current_bet, num_opp, street,
        pos, table, profiler, bb_size=bb_size
    )
    
    return (action, amount, msg)

# ── Chat Message Pool (anti-repetition) ─────────────────

CHAT_FOLD = [
    "not the spot I'm looking for",
    "this hand doesn't play well out of position",
    "too much heat for what I'm holding",
    "folding and moving on",
    "picking a better spot",
    "letting this one go",
    "not getting involved here",
]

CHAT_CALL_CHEAP = [
    "price is right, let's see a flop",
    "getting a decent price to continue",
    "priced in with some implied odds",
    "pot odds justify the call",
    "cheap enough to take a look",
    "calling to evaluate the next street",
]

CHAT_CALL_STRONG = [
    "not going anywhere with this holding",
    "keeping the pot controlled",
    "letting you keep the lead",
    "calling to see what develops",
    "this hand has too much equity to fold",
]

CHAT_RAISE = [
    "putting pressure on the opener",
    "this sizing should narrow the field",
    "taking control of the pot",
    "not letting you dictate the action",
    "testing your range right now",
]

CHAT_BET = [
    "standard continuation sizing",
    "board favors my range here",
    "keeping the pressure on",
    "can't let you see free cards",
    "this bet defines the hand",
]

CHAT_CHECK = [
    "taking the free card",
    "checking behind for pot control",
    "seeing what the turn brings",
    "no reason to inflate this pot",
    "keeping the pot controlled until the next street",
]

CHAT_POOLS = {
    "fold": CHAT_FOLD,
    "call": CHAT_CALL_CHEAP,  # will swap if strong
    "bet": CHAT_BET,
    "raise": CHAT_RAISE,
    "check": CHAT_CHECK,
    "all-in": CHAT_RAISE,
}

def get_chat(action, strength=0):
    """Get a varied chat message. Avoids repetition by cycling."""
    pool = CHAT_POOLS.get(action, CHAT_CHECK)
    if action == "call" and strength >= 2:
        pool = CHAT_CALL_STRONG
    return random.choice(pool)

# ── Main Loop ────────────────────────────────────────────

def main_loop():
    log("=== OpenClaw Poker Bot Started ===")
    log(f"Competition: {COMPETITION_ID} | Bankroll: 1000 chips | Max rebuys: 5")
    
    state = load_state()
    joined = False  # track if we've joined this session
    
    while True:
        # Check stop signal
        if os.path.exists(STOP_FILE):
            log("Stop signal received. Leaving queue...")
            post("/api/arena/texas/leave", {"competitionId": COMPETITION_ID})
            log("Bot stopped.")
            break
        
        # Reload coach advice
        reload_coach()
        
        # Poll pending actions
        data = get("/api/arena/texas/pending-actions", {"competitionId": COMPETITION_ID})
        
        if data.get("_error"):
            log(f"API error: {data.get('_error')} — retrying in 5s")
            time.sleep(5)
            continue
        
        tables = data.get("tables", [])
        participant = data.get("participant", {})
        runner = data.get("runner", {})
        
        chip_state = participant.get("chipState", "unknown")
        total_chips = participant.get("totalChips", 0)
        
        if tables:
            # ── ACTION REQUIRED ──────────────────────
            # Sort by earliest deadline
            tables.sort(key=lambda t: t.get("actionDeadlineAt", float("inf")) or float("inf"))
            
            for table in tables:
                table_id = table.get("tableId")
                deadline_at = table.get("actionDeadlineAt")
                street = table.get("street", "?")
                
                if deadline_at:
                    remaining_ms = deadline_at - (time.time() * 1000)
                    remaining_s = remaining_ms / 1000
                else:
                    remaining_s = 999
                
                # Skip tables where deadline has already passed
                if remaining_s <= 0:
                    log(f"TIMEOUT: {street} | Table {table.get('tableNumber','?')} | deadline passed")
                    continue
                
                log(f"🎯 ACTION: {street} | Table {table.get('tableNumber','?')} | {remaining_s:.0f}s left")
                
                # Show hole cards privately
                self_seat = table.get("selfSeatNumber")
                for seat in table.get("seats", []):
                    if seat.get("seatNumber") == self_seat:
                        hole = seat.get("holeCards")
                        if hole:
                            log(f"   Cards: {' '.join(hole)} | Stack: {seat.get('stackChips',0)}")
                        break
                
                board = table.get("boardCards", [])
                if board:
                    log(f"   Board: {' '.join(board)} | Pot: {table.get('potChips',0)}")
                
                # Use decision engine (Gemini + profiler, or quant fallback)
                action, amt, msg = decide_action(table)
                
                # Public chat: only send safe, randomized messages (never Gemini reasoning)
                # Gemini reasoning may contain hole cards or strategy thinking — keep it in logs only
                chat = get_chat(action)
                
                log(f"   → {action.upper()}" + (f" {amt}" if amt else "") + f" | {msg}. {get_chat(action)}")
                
                # Build action payload
                action_payload = {
                    "tableId": table_id,
                    "action": action,
                    "amount": amt,
                    "message": chat
                }
                # Eval/benchmark requires reasoning field (separate from chat message, max 150 chars)
                if COMPETITION_ID == "seed_poker_eval_s1":
                    reasoning = msg.replace("🎯 Gemini: ", "").replace("🔧 quant: ", "")
                    if len(reasoning) > 150:
                        reasoning = reasoning[:147] + "..."
                    action_payload["reasoning"] = reasoning
                
                result = post("/api/arena/texas/action", action_payload)
                
                if result.get("_error"):
                    log(f"   Action rejected: {result.get('_body','?')}")
                    # Fallback: if raise rejected, try all-in or call instead of retrying
                    if action == "raise" and "available" in allowed_actions:
                        available = allowed_actions.get("availableActions", [])
                        if "call" in available:
                            call_amt = allowed_actions.get("callAmount", 0) or allowed_actions.get("callChips", 0) or 0
                            fallback_payload = {"tableId": table_id, "action": "call", "amount": call_amt, "message": "adjusting sizing"}
                            fb_result = post("/api/arena/texas/action", fallback_payload)
                            if not fb_result.get("_error"):
                                log(f"   ✓ Fallback: call {call_amt}")
                            else:
                                # Last resort: check/fold
                                if "check" in available:
                                    check_result = post("/api/arena/texas/action", {"tableId": table_id, "action": "check", "amount": 0, "message": ""})
                                    log(f"   ✓ Fallback: check")
                                elif "fold" in available:
                                    post("/api/arena/texas/action", {"tableId": table_id, "action": "fold", "amount": 0, "message": ""})
                                    log(f"   ✓ Fallback: fold (raise rejected, no call/check)")
                    continue  # move to next table, don't retry same action this cycle
                
                # Update state
                part = result.get("participant", {})
                if part:
                    state["totalChips"] = part.get("totalChips", state.get("totalChips", 0))
                    save_state(state)
                
                # Check if hand ended
                tbl = result.get("table", {})
                if tbl.get("status") in ("Completed", "Cancelled"):
                    winners = tbl.get("winners", [])
                    if winners:
                        for w in winners:
                            if w.get("agentId") == AGENT_ID:
                                state["hands_won"] = state.get("hands_won", 0) + 1
                                state["biggest_pot"] = max(state.get("biggest_pot", 0), w.get("amount", 0))
                                log(f"🏆 WON! {w.get('handName','?')} — {w.get('amount',0)} chips")
                            else:
                                log(f"   Lost to: {w.get('agentName','?')} ({w.get('handName','?')})")
                    state["hands_played"] = state.get("hands_played", 0) + 1
                    save_state(state)
                    
                    # Feed hand result to profiler + run the throttled LLM
                    # opponent-reader (off the decision path — the hand is over).
                    gemini_on = bool(os.environ.get("GEMINI_DEEP_RESEARCH_API_KEY", ""))
                    # Opponents who reached a real showdown (a handName was revealed).
                    showdown_ids = {w.get("agentId") for w in winners if w.get("handName")}
                    llm_refreshes = 0
                    for seat in table.get("seats", []):
                        aid = seat.get("agentId", "")
                        if not aid or aid == AGENT_ID:
                            continue
                        aname = seat.get("agentName", "")
                        prof = profiler.get_or_create(aid, aname)
                        prof.record_hand_observed()
                        # Showdown-revealed hand for this opponent. Only winners'
                        # handNames are exposed by the API; losers' cards stay hidden.
                        if aid in showdown_ids:
                            w = next((x for x in winners if x.get("agentId") == aid), {})
                            prof.record_showdown(
                                hand_name=w.get("handName", ""),
                                won=True,
                                pot=w.get("amount", 0),
                                street_reached=tbl.get("street", "River"),
                            )
                        # Throttled re-profile (showdown OR every N hands); cap cost/hand.
                        if llm_refreshes < 2 and refresh_opponent_llm_profile(
                                prof, showdown_triggered=(aid in showdown_ids),
                                gemini_enabled=gemini_on):
                            llm_refreshes += 1
                            log(f"🧠 LLM profiled {aname or aid[:8]}: {prof.llm_summary[:60]}")
                    profiler.save()
                    # Drop the per-table snapshot so the next hand starts clean
                    # (its first snapshot then has no predecessor → blinds aren't diffed).
                    _last_table_snapshot.pop(table_id, None)
                    
                    # Reset hand state at end of hand
                    reset_hand_state()
                    
                    if state["hands_played"] % 10 == 0:
                        log(f"📊 {state['hands_played']} hands, {state['hands_won']} won | "
                            f"Chips: {part.get('totalChips','?')} | BB: {tbl.get('bigBlindChips','?')}")
        else:
            # ── NO ACTION ──────────────────────────
            # Check if we need to rejoin
            if chip_state == "busted":
                total = participant.get("totalChips", 0)
                buy_in = participant.get("initialChips", 1000)  # fallback
                if total < buy_in:
                    rebuy_count = participant.get("rebuyCount", 0)
                    if rebuy_count < 5:
                        log(f"Busted ({total} chips). Rebuy #{rebuy_count + 1}...")
                        rebuy = post("/api/arena/texas/rebuy", {"competitionId": COMPETITION_ID})
                        if not rebuy.get("_error"):
                            log("Rebuy successful. Rejoining...")
                            joined = False  # force rejoin
                        else:
                            log(f"Rebuy failed: {rebuy}")
                    else:
                        log("Out of rebuys. Stopping.")
                        break
                else:
                    log(f"Busted status but totalChips={total} >= buyIn. Rejoining...")
                    joined = False
            
            if not joined and chip_state == "available":
                # Check lobby first
                lobby = get(f"/api/arena/texas/lobby", {"competitionId": COMPETITION_ID})
                if lobby.get("_error") or lobby.get("lobby") is None:
                    log("Joining queue...")
                    join_resp = post("/api/arena/texas/join", {"competitionId": COMPETITION_ID})
                    if join_resp.get("kind") == "queued":
                        pos = join_resp.get("lobby", {}).get("position", "?")
                        total = join_resp.get("lobby", {}).get("total", "?")
                        log(f"Queued — position {pos}/{total}")
                    joined = True
                else:
                    log(f"In lobby — position {lobby['lobby'].get('position','?')}/{lobby['lobby'].get('total','?')}")
                    joined = True
            
            # If still locked_in_play, just wait
            if chip_state == "locked_in_play":
                pass  # hands are settling, auto-requeue should handle
        
        # Periodic status (only report when count changes and is multiple of 30)
        h = state.get("hands_played", 0)
        last_reported = state.get("_last_status_report", 0)
        if h > 0 and h != last_reported and h % 30 == 0:
            state["_last_status_report"] = h
            save_state(state)
            ai_stats = get_ai_stats()
            if ai_stats.get('gemini_calls', 0) > 0:
                success_rate = ai_stats['gemini_success'] / ai_stats['gemini_calls'] * 100 if ai_stats['gemini_calls'] > 0 else 0
                log(f"STATUS: {h} hands | {state.get('hands_won',0)} won | Chips: {total_chips} | "
                    f"AI: {ai_stats['gemini_success']}/{ai_stats['gemini_calls']} calls ({success_rate:.0f}%) | "
                    f"Fallbacks: {ai_stats['fallback_calls']} | Profiles: {len(profiler.profiles)}")
            else:
                log(f"STATUS: {h} hands | {state.get('hands_won',0)} won | Big pot: {state.get('biggest_pot',0)} | Chips: {total_chips}")
        
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main_loop()
