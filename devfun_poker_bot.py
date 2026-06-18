#!/usr/bin/env python3
"""DevFun Arena Texas Hold'em Poker Bot — Playground S3.
Polls pending-actions, makes rule-based decisions, submits actions.
Uses configured model for tough spots only."""

import requests
import json
import time
import os
import sys
import random
from datetime import datetime, timezone

# ── Config ──────────────────────────────────────────────
BASE = "https://arena.dev.fun"
COMPETITION_ID = "cmqf827h30u7dfca3x2aqvzjv"

# Read credentials from file (never hardcode)
CRED_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".arena-credentials")
API_KEY = ""
AGENT_ID = ""
for line in open(CRED_FILE):
    line = line.strip()
    if line.startswith("apiKey="):
        API_KEY = ***"=", 1)[1]
    elif line.startswith("agentId="):
        AGENT_ID = line.split("=", 1)[1]

HEADERS = {"x-arena-api-key": API_KEY, "Content-Type": "application/json"}

WORKSPACE = "/root/.openclaw/workspace"
STATE_FILE = f"{WORKSPACE}/.arena-poker-state"
OPPONENTS_FILE = f"{WORKSPACE}/.arena-opponents.json"
STOP_FILE = f"{WORKSPACE}/.arena-stop"
PID_FILE = f"{WORKSPACE}/.arena-bot.pid"
COACH_FILE = f"{WORKSPACE}/.arena-coach-advice"

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
        return mapping.get(style, style if style != "unknown" else "unknown")
    except Exception:
        return "unknown"

# ── Strategy Engine ─────────────────────────────────────
# Import quantitative poker engine
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from poker_quant import quant_decision, preflop_equity, monte_carlo_equity

# Ranges kept as fallback / opponent-quality filter
# (TIGHTENED from original)
PREFLOP_OPEN = {
    0: {"pairs": 10, "high": ["AK", "AQ"], "suited": ["AK", "AQ", "AJ"]},
    1: {"pairs": 8, "high": ["AK", "AQ", "AJ", "KQ"], "suited": ["AK", "AQ", "AJ", "AT", "KQ"]},
    2: {"pairs": 6, "high": ["AK", "AQ", "AJ", "AT", "KQ", "KJ"], "suited": ["AK", "AQ", "AJ", "AT", "A9", "KQ", "KJ", "QJ", "JT"]},
    3: {"pairs": 2, "high": ["AK", "AQ", "AJ", "AT", "A9", "KQ", "KJ", "KT", "QJ"], "suited": ["AK", "AQ", "AJ", "AT", "A9", "A8", "A7", "A6", "A5", "A4", "A3", "A2", "KQ", "KJ", "KT", "K9", "QJ", "QT", "Q9", "JT", "J9", "T9", "98", "87"]},
    4: {"pairs": 10, "high": ["AK", "AQ"], "suited": ["AK", "AQ", "KQ", "KJ"]},
    5: {"pairs": 4, "high": ["AK", "AQ", "AJ", "AT", "A9", "KQ", "KJ", "KT"], "suited": ["AK", "AQ", "AJ", "AT", "A9", "A8", "A7", "A6", "A5", "A4", "A3", "A2", "KQ", "KJ", "KT", "K9", "QJ", "QT", "Q9", "JT", "J9", "T9", "T8", "98"]},
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
    """Check if hole cards are in our pre-flop open range for position."""
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
    
    if suited and hand_str in rng.get("suited", []):
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
    if not board:
        return "preflop"
    
    ranks = [card_rank_value(c[0].upper()) for c in board]
    paired = len(ranks) != len(set(ranks))
    ace_high = 14 in ranks
    has_fd = board_has_flush_draw(board)
    has_sd = board_straight_draw(board)
    all_low = all(r <= 7 for r in ranks)
    
    if paired:
        return "paired"
    if has_fd and has_sd:
        return "wet"
    if has_fd or has_sd:
        return "wet"
    if ace_high and not has_fd and not has_sd:
        return "ace_high"
    if all_low and len(board) >= 3:
        return "connected_low"
    return "dry"

def choose_preflop_action(state):
    """Decide pre-flop action: fold, call, bet, raise, all-in."""
    hole_cards = state.get("hole_cards", [])
    pos = state.get("position", 3)  # default BTN if unknown
    allowed = state.get("allowed_actions", [])
    call_amount = state.get("call_amount", 0)
    current_bet = state.get("current_bet", 0)
    stack = state.get("stack", 0)
    pot = state.get("pot", 0)
    
    in_range = hand_in_range(hole_cards, pos) if hole_cards else False
    pr = pair_rank(hole_cards)
    suited = is_suited(hole_cards)
    hi, lo = high_card_ranks(hole_cards) if hole_cards else (0, 0)
    
    message = "let's see what develops"
    
    # Facing a raise (need to call or 3-bet)
    # PREMIUM: never fold JJ+ or AK to a single raise in 6-max
    is_premium = pr >= 11 or (hi == 14 and lo >= 13)  # JJ+ or AK
    if call_amount > 0 and "call" in allowed:
        if is_premium:
            # 3-bet premiums, 4-bet KK+ if possible
            if pr >= 13:  # KK+
                if "raise" in allowed:
                    raise_to = min(current_bet * 4, stack)
                    return ("raise", raise_to, "putting in the 4-bet with a monster")
                return ("call", call_amount, "trapping")
            if "raise" in allowed:
                raise_to = min(current_bet * 3, stack)
                return ("raise", raise_to, "3-betting for value")
            if "all-in" in allowed and stack < current_bet * 5:
                return ("all-in", stack, "short stack, getting it in good")
            return ("call", call_amount, "flatting premium")
        
        if not in_range:
            if "fold" in allowed:
                return ("fold", 0, "not the spot I'm looking for")
            return ("call", call_amount, "defending light")
        
        # Speculative: call if cheap
        if call_amount <= pot * 0.15 and (suited or pr >= 7):
            return ("call", call_amount, "priced in with implied odds")
        
        if "fold" in allowed:
            return ("fold", 0, "too much to see a flop here")
        return ("call", call_amount, "price is right")
    
    # No raise facing us — we can open or check
    if "bet" in allowed and in_range:
        # Value sizing: 75-100% pot with strong hands
        if pr >= 10 or (hi == 14 and lo >= 12):
            bet_size = int(pot * 0.9)  # was 0.75 — extract more
        elif pr >= 7 or hi >= 13:
            bet_size = int(pot * 0.75)
        else:
            bet_size = int(pot * 0.55)  # speculative opens
        return ("bet", bet_size, "opening with a standard sizing")
    
    if "bet" in allowed and not in_range:
        # Steal from late position occasionally
        if pos >= 3 and random.random() < 0.25:
            return ("bet", int(pot * 0.5), "late position steal attempt")
        if "check" in allowed:
            return ("check", 0, "taking a free look")
        return ("fold", 0, "nothing to get excited about")
    
    if "check" in allowed:
        return ("check", 0, "checking behind")
    
    return ("fold", 0, "not investing here")

def choose_postflop_action(state):
    """Decide post-flop action based on board texture and hand strength."""
    hole_cards = state.get("hole_cards", [])
    board = state.get("board", [])
    allowed = state.get("allowed_actions", [])
    call_amount = state.get("call_amount", 0)
    pot = state.get("pot", 0)
    stack = state.get("stack", 0)
    street = state.get("street", "flop")
    
    pr = pair_rank(hole_cards)
    hi, lo = high_card_ranks(hole_cards) if hole_cards else (0, 0)
    texture = classify_board(board)
    
    # Estimate hand strength (simplified)
    # 0=nothing, 1=draw, 2=pair, 3=overpair/two_pair, 4=trips+, 5=straight/flush+
    strength = 0
    if pr > 0:
        # Check if we hit a set
        board_ranks = [c[0].upper() for c in board]
        rank_char = {14:'A',13:'K',12:'Q',11:'J',10:'T',9:'9',8:'8',7:'7',6:'6',5:'5',4:'4',3:'3',2:'2'}
        our_rank = rank_char.get(pr, '')
        if our_rank in board_ranks:
            strength = 4  # trips
        elif pr > max(card_rank_value(r) for r in board_ranks) if board_ranks else 14:
            strength = 3  # overpair
        else:
            strength = 2  # pair
    elif hi >= 10:
        # Check if we hit top pair
        board_ranks = [c[0].upper() for c in board]
        rank_char = {14:'A',13:'K',12:'Q',11:'J',10:'T'}
        for rk, rc in rank_char.items():
            if hi == rk and rc in board_ranks:
                strength = 2  # hit top pair
                break
        else:
            strength = 1 if (texture in ("wet", "connected_low") and is_suited(hole_cards)) else 0
    else:
        strength = 1 if texture in ("wet", "connected_low") else 0
    
    # Facing a bet
    if call_amount > 0 and "call" in allowed:
        # RIVER: tight calling — avoid losing big pots with marginal hands
        if street in ("River",):
            if strength >= 3:
                # Strong — call or raise
                if call_amount <= pot * 0.66 and "raise" in allowed:
                    raise_to = min(call_amount * 2, stack)
                    return ("raise", raise_to, "my hand is too strong to just call")
                return ("call", call_amount, "calling with a strong holding")
            if strength == 2 and call_amount <= pot * 0.33:
                # Thin call with one pair vs small bet
                return ("call", call_amount, "getting a good price with showdown value")
            # Fold everything else on river
            if "fold" in allowed:
                return ("fold", 0, f"not calling this river without the goods")
            return ("call", call_amount, "pot odds force a call")
        
        # TURN and earlier: normal calling
        if strength >= 3:
            if "raise" in allowed:
                raise_to = min(call_amount * 3, stack)
                return ("raise", raise_to, "this board favors my holding")
            return ("call", call_amount, "value extracting")
        
        if strength == 2 and call_amount <= pot * 0.5:
            return ("call", call_amount, "one pair, one more street")
        
        if strength == 1 and call_amount <= pot * 0.2 and texture == "dry":
            return ("call", call_amount, "floating the dry board")
        
        if "fold" in allowed:
            return ("fold", 0, f"can't continue on this {texture} board")
        return ("call", call_amount, "pot odds demand a call")
    
    # Initiative — we can bet or check
    if "bet" in allowed:
        if strength >= 4:  # trips+
            bet_size = int(pot)  # full pot, extract max
            return ("bet", bet_size, "building the pot with a monster")
        if strength >= 3:  # overpair/two-pair
            bet_size = int(pot * 0.85)
            return ("bet", bet_size, "strong hand, standard value sizing")
        if strength == 2:  # top pair
            bet_size = int(pot * 0.7)
            return ("bet", bet_size, "standard c-bet continuation")
        # bluffs/semi-bluffs
        if texture == "dry" and street in ("flop",):
            bet_size = int(pot * 0.45)
            return ("bet", bet_size, "board is dry, this should fold out weak pairs")
        if texture == "ace_high" and street == "flop":
            bet_size = int(pot * 0.33)
            return ("bet", bet_size, "ace-high board favors my range")
        if "check" in allowed:
            return ("check", 0, "taking the free card")
    
    if "check" in allowed:
        if strength >= 2 and texture == "wet":
            return ("check", 0, "keeping the pot controlled on a wet board")
        return ("check", 0, "checking behind")
    
    return ("fold", 0, "nothing here")

def decide_action(table):
    """Quantitative decision engine."""
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
            # Try to get opponent style
            aid = seat.get("agentId", "")
            if aid:
                style = get_opponent_style(aid)
                if style != "unknown":
                    opponent_style = style  # use worst-case opponent style
    
    num_opp = max(num_opp, 1)
    
    # Compute call amount
    call_amount = allowed_actions.get("callAmount", 0) or allowed_actions.get("callChips", 0) or 0
    
    # Estimate position from seat number and dealer position
    dealer_seat = table.get("dealerSeatNumber", 0) or 0
    pos = 3  # default BTN
    if self_seat and dealer_seat:
        seats_count = len(table.get("seats", []))
        offset_from_dealer = (self_seat - dealer_seat) % seats_count
        pos_map = {1: 3, 2: 4, 3: 5, 4: 0, 5: 1, 6: 2}  # relative positions
        pos = pos_map.get(offset_from_dealer, 3)
    
    # Use quantitative engine
    action, amount, msg, confidence = quant_decision(
        hole_cards, board, available, pot, stack,
        call_amount, current_bet, num_opp, street, opponent_style,
        bb_size=2, position=pos
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
    log(f"Competition: Playground S3 | Bankroll: 1000 chips | Max rebuys: 5")
    
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
                
                # Use quant engine for all decisions, even under time pressure
                action, amt, msg = decide_action(table)
                
                chat = f"{msg}. {get_chat(action)}"
                # Truncate to 500
                if len(chat) > 500:
                    chat = chat[:497] + "..."
                
                log(f"   → {action.upper()}" + (f" {amt}" if amt else "") + f" | {chat}")
                
                result = post("/api/arena/texas/action", {
                    "tableId": table_id,
                    "action": action,
                    "amount": amt,
                    "message": chat
                })
                
                if result.get("_error"):
                    log(f"   Action rejected: {result.get('_body','?')}")
                
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
            log(f"STATUS: {h} hands | {state.get('hands_won',0)} won | Biggest pot: {state.get('biggest_pot',0)} | Chips: {total_chips}")
        
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main_loop()
