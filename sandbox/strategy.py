"""dev.fun Arena sandbox strategy — PvE exploit vs the reference panel.

Entry point: act(table) -> {"action", "amount", "reasoning_text"}.
Bundled with quant.py (pure-Python engine from the pokerbot package).

The eval reference panel measures (~1M hands): VPIP 22 / PFR 17 / AF 2.0 /
WTSD 93 / WSD 53. They fold ~78% preflop but almost never fold postflop.
Exploit: steal wide preflop, value-bet relentlessly, never bluff postflop.

amount semantics: TOTAL chips committed this street (to-amount), per
allowedActions.amountSemantics == "to-amount". Clamp into bet/raiseRange.
"""

from quant import (
    evaluate_hand,
    monte_carlo_equity,
    preflop_hand_key,
    card_rank,
    estimate_draw_equity,
)

# Postflop Monte Carlo budget. The sandbox allows ~10s/decision; 400 sims of
# pure-Python evaluation stays well under 2s even 5-handed.
MC_SIMS = 400


# ── table reading ────────────────────────────────────────

def _hero_seat(table):
    self_no = table.get("selfSeatNumber")
    for s in table.get("seats") or []:
        if s.get("seatNumber") == self_no:
            return s
    return {}


def _active_opponents(table):
    self_no = table.get("selfSeatNumber")
    n = 0
    for s in table.get("seats") or []:
        if s.get("seatNumber") != self_no and s.get("status") in ("Active", "AllIn"):
            n += 1
    return max(n, 1)


def _blind_seats(table):
    """(sb_seat, bb_seat) numbers from recentEvents; None if not found."""
    sb_amt = table.get("smallBlindChips")
    bb_amt = table.get("bigBlindChips")
    sb = bb = None
    for ev in table.get("recentEvents") or []:
        if ev.get("type") != "BlindPosted":
            continue
        s = ev.get("summary") or {}
        if sb is None and s.get("amount") == sb_amt:
            sb = s.get("seatNumber")
        elif bb is None and s.get("amount") == bb_amt:
            bb = s.get("seatNumber")
    return sb, bb


def _position(table):
    """'sb' | 'bb' | 'early' | 'middle' | 'late' from blind seats + seat order.

    Seats act preflop starting left of the BB; the last non-blind seat is the
    button. With no blind info default to 'middle' (plays a sane range).
    """
    sb, bb = _blind_seats(table)
    self_no = table.get("selfSeatNumber")
    if self_no == sb:
        return "sb"
    if self_no == bb:
        return "bb"
    if bb is None:
        return "middle"
    seats = sorted(s.get("seatNumber") for s in table.get("seats") or []
                   if s.get("seatNumber") is not None
                   and s.get("status") in ("Active", "AllIn")
                   and s.get("seatNumber") not in (sb, bb))
    if not seats or self_no not in seats:
        return "middle"
    # cyclic order starting from the first seat after the BB
    ordered = sorted(seats, key=lambda n: ((n - (bb or 0)) % 1000))
    idx = ordered.index(self_no)
    remaining = len(ordered) - idx  # 1 == button (acts last of the non-blinds)
    if remaining <= 2:
        return "late"
    if idx == 0 and len(ordered) >= 3:
        return "early"
    return "middle"


def _street_raises(table, street):
    """How many raises recentEvents shows on this street (incl. ours)."""
    n = 0
    for ev in table.get("recentEvents") or []:
        if ev.get("type") == "ActionTaken" and ev.get("street") == street:
            if (ev.get("summary") or {}).get("action") in ("raise", "bet"):
                n += 1
    return n


# ── preflop ranges (steal-heavy vs a 78%-fold panel) ─────

def _parse_key(hole):
    key = preflop_hand_key(hole)  # 'AKs' / 'T9o' / '77'
    hi, lo = card_rank(hole[0]), card_rank(hole[1])
    if lo > hi:
        hi, lo = lo, hi
    return hi, lo, key.endswith("s"), hi == lo


def _open_ok(hole, pos):
    hi, lo, suited, pair = _parse_key(hole)
    gap = hi - lo
    if pair:
        return lo >= 5 if pos == "early" else True
    if pos in ("late", "sb"):
        if hi == 14:
            return True                       # any ace
        if hi == 13:
            return suited or lo >= 9          # K5s+? -> any Ks, K9o+
        if hi == 12:
            return (suited and lo >= 7) or lo >= 10
        if suited and gap <= 2 and lo >= 5:
            return True                       # 75s+, T8s+ style
        return suited and lo >= 8 or (not suited and hi >= 11 and lo >= 10)
    if pos == "middle":
        if hi == 14:
            return suited or lo >= 9
        if hi == 13:
            return (suited and lo >= 9) or lo >= 10
        if hi == 12:
            return (suited and lo >= 9) or lo == 11
        return (suited and gap <= 1 and lo >= 8)  # JTs, T9s, 98s
    # early
    if hi == 14:
        return (suited and lo >= 9) or lo >= 10
    if hi == 13 and (suited and lo >= 10 or lo >= 11):
        return True
    return hi == 12 and suited and lo >= 10       # QTs+


def _call_raise_ok(hole, call_chips, stack):
    """Continue vs a single raise: value 3-bet handled separately; this is the
    flat-call range. Set-mining is highly profitable vs a 93%-WTSD panel."""
    hi, lo, suited, pair = _parse_key(hole)
    if pair:
        return call_chips <= max(stack * 0.12, 1)  # set mine
    if hi == 14 and (lo >= 11 or (suited and lo >= 10)):
        return True                                # AQ+, AJs+/ATs
    if hi == 13 and lo >= 11 and suited:
        return True                                # KQs/KJs
    if suited and hi - lo <= 1 and lo >= 9:
        return True                                # JTs/T9s/QJs
    return False


def _is_value_3bet(hole):
    key = preflop_hand_key(hole)
    return key in ("AA", "KK", "QQ", "AKs", "AKo")


def _is_3bet_defend(hole):
    key = preflop_hand_key(hole)
    return key in ("AA", "KK", "QQ", "JJ", "TT", "AKs", "AKo", "AQs")


# ── action builders (to-amount semantics, clamped legal) ─

def _clamped(action, rng, amount):
    lo, hi = int(rng.get("min") or 0), int(rng.get("max") or 0)
    if hi <= 0 or lo <= 0:
        return None
    return {"action": action, "amount": max(lo, min(int(amount), hi))}


def _raise_to(table, amount, why):
    aa = table.get("allowedActions") or {}
    avail = aa.get("availableActions") or []
    for verb, rng_key in (("raise", "raiseRange"), ("bet", "betRange")):
        if verb in avail:
            act_ = _clamped(verb, aa.get(rng_key) or {}, amount)
            if act_:
                act_["reasoning_text"] = why
                return act_
    return None


def _call_or_check(table, why):
    aa = table.get("allowedActions") or {}
    avail = aa.get("availableActions") or []
    if int(aa.get("callChips") or 0) == 0 and "check" in avail:
        return {"action": "check", "reasoning_text": why}
    if "call" in avail:
        return {"action": "call", "reasoning_text": why}
    if "check" in avail:
        return {"action": "check", "reasoning_text": why}
    return {"action": "fold", "reasoning_text": why}


def _check_or_fold(table, why):
    aa = table.get("allowedActions") or {}
    if "check" in (aa.get("availableActions") or []):
        return {"action": "check", "reasoning_text": why}
    return {"action": "fold", "reasoning_text": why}


# ── streets ──────────────────────────────────────────────

def _preflop(table, hole):
    aa = table.get("allowedActions") or {}
    call_chips = int(aa.get("callChips") or 0)
    bb = int(table.get("bigBlindChips") or 2)
    hero = _hero_seat(table)
    stack = int(hero.get("stackChips") or 0)
    pos = _position(table)
    raises = _street_raises(table, "Preflop")
    facing_raise = call_chips > 0 and int(table.get("currentBet") or 0) > bb

    if _is_value_3bet(hole):
        # Big for value — the panel calls 3-bets too wide.
        target = max(int(table.get("currentBet") or bb) * 3, bb * 4)
        act_ = _raise_to(table, target, "premium, raising for value")
        if act_:
            return act_
        return _call_or_check(table, "premium, no raise available")

    if facing_raise:
        if raises >= 2:  # 3-bet or more back to us
            if _is_3bet_defend(hole):
                return _call_or_check(table, "strong vs 3-bet, calling")
            return {"action": "fold", "reasoning_text": "not continuing vs 3-bet"}
        if _call_raise_ok(hole, call_chips, stack):
            return _call_or_check(table, "profitable call vs raise")
        return {"action": "fold", "reasoning_text": "weak vs raise"}

    if _open_ok(hole, pos):
        # Open/steal: 3bb (+ the current bet if limpers). Panel folds 78%.
        act_ = _raise_to(table, bb * 3, "open-raise, stealing wide")
        if act_:
            return act_
        return _call_or_check(table, "open range, no raise available")

    if call_chips == 0:
        return _call_or_check(table, "free look in the blind")
    # Complete tiny amounts in the blinds with speculative suited stuff.
    hi, lo, suited, pair = _parse_key(hole)
    if call_chips <= bb and (suited or pair or hi >= 12):
        return _call_or_check(table, "cheap blind complete")
    return {"action": "fold", "reasoning_text": "out of range"}


def _made_hand_value(hole, board, strength):
    """True if this is a clear value hand vs a calling station."""
    if strength >= 2:  # two pair+
        return True
    if strength != 1:
        return False
    board_ranks = [card_rank(c) for c in board]
    top_board = max(board_ranks) if board_ranks else 0
    h1, h2 = card_rank(hole[0]), card_rank(hole[1])
    if h1 == h2 and h1 > top_board:
        return True                       # overpair
    # top pair, decent kicker
    if h1 == top_board and h2 >= 10 or h2 == top_board and h1 >= 10:
        return True
    return False


def _postflop(table, hole, board, street):
    aa = table.get("allowedActions") or {}
    call_chips = int(aa.get("callChips") or 0)
    pot = int(table.get("potChips") or 0)
    n_opp = _active_opponents(table)
    strength, hand_type, _detail = evaluate_hand(hole, board)
    value = _made_hand_value(hole, board, strength)
    eq = monte_carlo_equity(hole, board, n_opp, num_sims=MC_SIMS)
    raises = _street_raises(table, street)

    if call_chips == 0:
        if value:
            # Stations pay three streets — bet big.
            return _raise_to(table, int(pot * 0.75) or 1,
                             "value bet vs station") or _check_or_fold(table, "no bet size")
        if strength == 1 and street == "Flop" and eq > 0.45:
            return _raise_to(table, int(pot * 0.5) or 1,
                             "thin flop value") or _check_or_fold(table, "no bet size")
        # No bluffs vs a 93%-WTSD panel; draws take free cards.
        return _check_or_fold(table, "checking, no bluffs vs stations")

    pot_odds = call_chips / float(pot + call_chips) if (pot + call_chips) else 1.0
    if strength >= 2 and street != "River" and raises < 2:
        return _raise_to(table, int(table.get("currentBet") or call_chips) * 3,
                         "raising two pair+ for value") or _call_or_check(table, "value call")
    if value:
        return _call_or_check(table, "value hand, calling")
    draw_eq = estimate_draw_equity(hole, board, n_opp)
    if eq > pot_odds + 0.04 or (street != "River" and draw_eq >= 0.16 and pot_odds <= 0.30):
        return _call_or_check(table, "odds justify the call")
    return {"action": "fold", "reasoning_text": "beat, folding to station aggression"}


# ── entry point ──────────────────────────────────────────

def _decide(table):
    hole = list(_hero_seat(table).get("holeCards") or [])
    board = list(table.get("boardCards") or [])
    street = table.get("street") or "Preflop"
    if len(hole) != 2:
        return _check_or_fold(table, "no hole cards visible")
    if street == "Preflop" or not board:
        return _preflop(table, hole)
    return _postflop(table, hole, board, street)


def act(table: dict) -> dict:
    try:
        return _decide(table)
    except Exception as e:  # never forfeit a spot on a bug
        aa = table.get("allowedActions") or {}
        avail = aa.get("availableActions") or []
        if "check" in avail:
            return {"action": "check", "reasoning_text": f"fallback ({type(e).__name__})"}
        return {"action": "fold", "reasoning_text": f"fallback ({type(e).__name__})"}
