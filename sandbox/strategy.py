"""dev.fun Arena sandbox strategy — PvE exploit vs the reference panel.

Entry point: act(table) -> {"action", "amount", "reasoning_text"}.
SELF-CONTAINED: a single bare strategy.py (stdlib only) — the sandbox has no
arena_sdk and submitting one file is the reliable path (a multi-file zip failed
to start). The poker engine below is inlined verbatim from pokerbot/quant.py.

The eval reference panel measures (~1M hands): VPIP 22 / PFR 17 / AF 2.0 /
WTSD 93 / WSD 53 / bluff 18%. They fold ~78% preflop but almost never fold
postflop. Exploit: open ATC from late/SB (steal the 78%), value-bet BIG and
thin (they're price-inelastic), barrel three streets, never bluff, and don't
over-fold to their bets (they bluff ~18%). Baseline: fold-bot = -23.9 bb/100;
v1 of this strategy = +35.8 bb/100.

amount semantics: TOTAL chips committed this street (to-amount), per
allowedActions.amountSemantics == "to-amount". Clamp into bet/raiseRange.
"""

import random
from collections import Counter

# ── Inlined poker engine (self-contained; the sandbox has no arena_sdk and we
#    ship a single bare strategy.py). Ported verbatim from pokerbot/quant.py. ──
RANKS = "23456789TJQKA"
RANK_VAL = {r: i for i, r in enumerate(RANKS, start=2)}
_IDX_TO_RANK = {v: k for k, v in RANK_VAL.items()}


def make_deck():
    return [r + s for r in RANKS for s in "hdcs"]


def card_rank(c):
    return RANK_VAL.get(c[0], 0)


def card_suit(c):
    return c[1] if len(c) > 1 else "?"


def evaluate_hand(hole, board):
    """Numeric hand strength 0-8 + detail (higher is better)."""
    all_cards = hole + board
    if len(all_cards) < 5:
        return (0, "incomplete", [])
    ranks = [card_rank(c) for c in all_cards]
    rank_counts = Counter(ranks)
    suit_counts = Counter(card_suit(c) for c in all_cards)
    flush_suit = None
    for s, cnt in suit_counts.items():
        if cnt >= 5:
            flush_suit = s
            break
    flush_cards = sorted([r for c, r in zip(all_cards, ranks)
                          if card_suit(c) == flush_suit and flush_suit],
                         reverse=True) if flush_suit else []
    unique_ranks = sorted(set(ranks))
    straight_high = None
    for i in range(len(unique_ranks) - 4):
        if unique_ranks[i + 4] - unique_ranks[i] == 4:
            straight_high = unique_ranks[i + 4]
    if {14, 2, 3, 4, 5}.issubset(set(ranks)):
        straight_high = 5
    counts = sorted(rank_counts.values(), reverse=True)
    if flush_suit and straight_high and straight_high in flush_cards[:5]:
        return (8, "straight_flush", [straight_high])
    if counts[0] == 4:
        quads = [r for r, c in rank_counts.items() if c == 4][0]
        return (7, "quads", [quads])
    if counts[0] == 3 and counts[1] >= 2:
        trips = [r for r, c in rank_counts.items() if c == 3][0]
        pair = [r for r, c in rank_counts.items() if c >= 2 and r != trips][0]
        return (6, "full_house", [trips, pair])
    if flush_suit:
        return (5, "flush", flush_cards[:5])
    if straight_high:
        return (4, "straight", [straight_high])
    if counts[0] == 3:
        trips = [r for r, c in rank_counts.items() if c == 3][0]
        return (3, "trips", [trips])
    if counts[0] == 2 and counts[1] == 2:
        pairs = sorted([r for r, c in rank_counts.items() if c == 2], reverse=True)
        return (2, "two_pair", pairs)
    if counts[0] == 2:
        pair = [r for r, c in rank_counts.items() if c == 2][0]
        kickers = sorted([r for r, c in rank_counts.items() if c == 1], reverse=True)[:3]
        return (1, "one_pair", [pair] + kickers)
    return (0, "high_card", sorted(ranks, reverse=True)[:5])


def preflop_hand_key(hole):
    r1, r2 = sorted([card_rank(hole[0]), card_rank(hole[1])], reverse=True)
    rc1, rc2 = _IDX_TO_RANK.get(r1, "?"), _IDX_TO_RANK.get(r2, "?")
    if rc1 == rc2:
        return rc1 + rc2
    suited = card_suit(hole[0]) == card_suit(hole[1])
    return rc1 + rc2 + ("s" if suited else "o")


def compare_hands(strength_a, detail_a, strength_b, detail_b):
    if strength_a != strength_b:
        return 1 if strength_a > strength_b else -1
    for da, db in zip(detail_a, detail_b):
        if da != db:
            return 1 if da > db else -1
    return 0


def monte_carlo_equity(hole, board, num_opponents=1, num_sims=500):
    deck = make_deck()
    known = set(hole + board)
    remaining = [c for c in deck if c not in known]
    wins = 0
    for _ in range(num_sims):
        sim_deck = remaining[:]
        random.shuffle(sim_deck)
        needed = 5 - len(board)
        sim_board = board + sim_deck[:needed]
        idx = needed
        our = evaluate_hand(hole, sim_board)
        win = True
        for _ in range(num_opponents):
            opp = [sim_deck[idx], sim_deck[idx + 1]]
            idx += 2
            oe = evaluate_hand(opp, sim_board)
            if compare_hands(our[0], our[2], oe[0], oe[2]) < 0:
                win = False
                break
        if win:
            wins += 1
    return wins / num_sims if num_sims else 0.0


def estimate_draw_equity(hole, board, num_opponents=1):
    if not board:
        return 0
    our_suit = card_suit(hole[0]) if hole else "?"
    board_suits = [card_suit(c) for c in board]
    flush_draw = board_suits.count(our_suit) == 3 and card_suit(hole[0]) == card_suit(hole[1])
    our_ranks = sorted([card_rank(c) for c in hole], reverse=True)
    board_ranks = sorted(set(card_rank(c) for c in board))
    overcards = sum(1 for r in our_ranks if r > max(board_ranks, default=0))
    all_r = sorted(set(our_ranks + board_ranks))
    has_oesd = any(all_r[i + 3] - all_r[i] == 4 for i in range(len(all_r) - 3))
    has_gutshot = any(all_r[i + 2] - all_r[i] == 5 for i in range(len(all_r) - 2))
    cards_to_come = 5 - len(board)
    draw_eq = 0.0
    if flush_draw:
        draw_eq += 0.20 * min(cards_to_come, 2) / 2
    if has_oesd:
        draw_eq += 0.17 * min(cards_to_come, 2) / 2
    if has_gutshot:
        draw_eq += 0.08 * min(cards_to_come, 2) / 2
    draw_eq += overcards * 0.03 * cards_to_come
    return min(draw_eq, 0.35)

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
    # The panel folds ~78% preflop, so open-steals print money. Open ATC from
    # late/SB, and a very wide range everywhere else. Only genuine trash opens
    # are trimmed from early position.
    hi, lo, suited, pair = _parse_key(hole)
    gap = hi - lo
    if pair:
        return True                               # open every pair
    if pos in ("late", "sb"):
        return True                               # any two — max steal pressure
    if pos == "middle":
        if hi >= 12:
            return True                           # any ace/king/queen
        if hi == 11:
            return suited or lo >= 7              # J7o+, any Jxs
        if suited:
            return lo >= 5 or gap <= 2            # suited connectors/gappers
        return hi >= 10 and lo >= 8               # T8o+, decent offsuit
    # early
    if hi >= 13:
        return True                               # any ace or king
    if hi == 12:
        return suited or lo >= 9                  # Qxs, Q9o+
    if hi == 11:
        return suited or lo >= 10                 # Jxs, JTo
    return suited and gap <= 1 and lo >= 7        # T9s, 98s, 87s


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

def _hu_playable(hole, defending=False):
    """Heads-up ranges are wide: open most buttons, defend the BB liberally."""
    hi, lo, suited, pair = _parse_key(hole)
    if pair or hi >= 13 or suited:
        return True
    if defending:
        return hi >= 10 and lo >= 7 or hi >= 12 and lo >= 5
    return hi >= 11 or (hi >= 9 and hi - lo <= 2)


def _preflop(table, hole):
    aa = table.get("allowedActions") or {}
    call_chips = int(aa.get("callChips") or 0)
    bb = int(table.get("bigBlindChips") or 2)
    hero = _hero_seat(table)
    stack = int(hero.get("stackChips") or 0)
    pos = _position(table)
    raises = _street_raises(table, "Preflop")
    facing_raise = call_chips > 0 and int(table.get("currentBet") or 0) > bb
    heads_up = _active_opponents(table) == 1

    if heads_up and not _is_value_3bet(hole):
        if facing_raise:
            if _is_3bet_defend(hole) or (
                    call_chips <= bb * 3 and _hu_playable(hole, defending=True)):
                return _call_or_check(table, "HU defend")
            return {"action": "fold", "reasoning_text": "HU fold vs raise"}
        if _hu_playable(hole):
            act_ = _raise_to(table, bb * 3, "HU open")
            if act_:
                return act_
            return _call_or_check(table, "HU limp behind")
        if call_chips == 0:
            return _call_or_check(table, "HU free look")
        if call_chips <= bb and _hu_playable(hole, defending=True):
            return _call_or_check(table, "HU cheap complete")
        return {"action": "fold", "reasoning_text": "HU out of range"}

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
    board_ranks = [card_rank(c) for c in board]
    top_board = max(board_ranks) if board_ranks else 0
    board_paired = len(set(board_ranks)) < len(board_ranks)
    h1, h2 = card_rank(hole[0]), card_rank(hole[1])
    if strength >= 3:  # trips+
        return True
    if strength == 2:
        # A paired board can inflate "two pair" — only genuine two pair
        # (both hole cards working) or an overpair counts as value.
        if not board_paired:
            return True
        if h1 == h2 and h1 > top_board:
            return True                   # overpair + board pair
        return (h1 in board_ranks and h2 >= 10) or (h2 in board_ranks and h1 >= 10)
    if strength != 1:
        return False
    if h1 == h2 and h1 > top_board:
        return True                       # overpair
    # top pair, decent kicker
    if h1 == top_board and h2 >= 10 or h2 == top_board and h1 >= 10:
        return True
    return False


def _raise_worthy(hole, board, strength):
    """Raise-for-value hands vs a station bet: genuine two pair or better."""
    if strength >= 3:
        return True
    if strength != 2:
        return False
    board_ranks = [card_rank(c) for c in board]
    if len(set(board_ranks)) < len(board_ranks):   # board itself is paired
        h1, h2 = card_rank(hole[0]), card_rank(hole[1])
        return h1 == h2 and h1 > max(board_ranks)  # overpair only
    return True


def _any_pair_plus(hole, board, strength):
    """Any made pair or better (thin-value candidate on the flop)."""
    if strength >= 2:
        return True
    if strength == 1:
        return True
    # pocket pair below board is still a pair
    return card_rank(hole[0]) == card_rank(hole[1])


def _postflop(table, hole, board, street):
    aa = table.get("allowedActions") or {}
    call_chips = int(aa.get("callChips") or 0)
    pot = int(table.get("potChips") or 0)
    n_opp = _active_opponents(table)
    strength, hand_type, _detail = evaluate_hand(hole, board)
    value = _made_hand_value(hole, board, strength)
    eq = monte_carlo_equity(hole, board, n_opp, num_sims=MC_SIMS)
    raises = _street_raises(table, street)
    draw_eq = estimate_draw_equity(hole, board, n_opp)

    if call_chips == 0:
        if value:
            # Stations are price-inelastic — size UP. Overbet-ish the flop/turn
            # with strong hands and keep barreling; they pay three streets.
            frac = 1.0 if street in ("Flop", "Turn") else 0.85
            return _raise_to(table, int(pot * frac) or 1,
                             "big value bet vs station") or _check_or_fold(table, "no bet size")
        if street == "Flop" and _any_pair_plus(hole, board, strength) and eq > 0.42:
            # Thin value + protection on the flop with any pair.
            return _raise_to(table, int(pot * 0.6) or 1,
                             "thin flop value") or _check_or_fold(table, "no bet size")
        # No bluffs vs a 93%-WTSD panel; draws take free cards.
        return _check_or_fold(table, "checking, no bluffs vs stations")

    pot_odds = call_chips / float(pot + call_chips) if (pot + call_chips) else 1.0
    if _raise_worthy(hole, board, strength) and street != "River" and raises < 2:
        return _raise_to(table, int(table.get("currentBet") or call_chips) * 3,
                         "raising two pair+ for value") or _call_or_check(table, "value call")
    if value:
        return _call_or_check(table, "value hand, calling")
    # They bluff ~18% of bets, so don't over-fold: call a single small/medium
    # bet with any pair or a live draw. Fold only weak holdings to big pressure.
    small_bet = pot_odds <= 0.42
    if strength == 1 and small_bet:
        return _call_or_check(table, "pair vs a station bet (they bluff often)")
    if eq > pot_odds + 0.03 or (street != "River" and draw_eq >= 0.16 and pot_odds <= 0.33):
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
