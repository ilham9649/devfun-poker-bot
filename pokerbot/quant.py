"""
Poker Quant - equity calculator for DevFun bot.
Pre-flop: pre-computed hot/cold equity vs 1-5 random hands.
Post-flop: Monte Carlo simulation.
Tournament: ICM awareness, bubble pressure, blind escalation, phase detection.
Strategy: 3-bet/4-bet, multi-street postflop, opponent exploitation.
"""

import random
import itertools
from collections import Counter

# ── Card utilities ──
RANKS = '23456789TJQKA'
SUITS = 'hdcs'
RANK_VAL = {r: i for i, r in enumerate(RANKS, start=2)}

def make_deck():
    return [r + s for r in RANKS for s in SUITS]

def card_rank(c):
    return RANK_VAL.get(c[0], 0)

def card_suit(c):
    return c[1] if len(c) > 1 else '?'

# ── Hand evaluation (simplified) ──
def evaluate_hand(hole, board):
    """Returns a numeric hand strength (0-8) and detail.
    8=StraightFlush, 7=Quads, 6=FullHouse, 5=Flush, 4=Straight,
    3=Trips, 2=TwoPair, 1=OnePair, 0=HighCard"""
    all_cards = hole + board
    if len(all_cards) < 5:
        return (0, 'incomplete', [])

    ranks = [card_rank(c) for c in all_cards]
    suits = [card_suit(c) for c in all_cards]

    # Count ranks
    rank_counts = Counter(ranks)
    suit_counts = Counter(suits)

    # Flush check
    flush_suit = None
    for s, cnt in suit_counts.items():
        if cnt >= 5:
            flush_suit = s
            break

    flush_cards = sorted([r for c, r in zip(all_cards, ranks)
                          if card_suit(c) == flush_suit and flush_suit], reverse=True) if flush_suit else []

    # Straight check
    unique_ranks = sorted(set(ranks))
    straight_high = None
    # Check normal straights
    for i in range(len(unique_ranks) - 4):
        if unique_ranks[i+4] - unique_ranks[i] == 4:
            straight_high = unique_ranks[i+4]
    # Check wheel (A-2-3-4-5)
    if set([14, 2, 3, 4, 5]).issubset(set(ranks)):
        straight_high = 5

    # Hand classification
    counts = sorted(rank_counts.values(), reverse=True)

    if flush_suit and straight_high and straight_high in flush_cards[:5]:
        return (8, 'straight_flush', [straight_high])
    if counts[0] == 4:
        quads = [r for r, c in rank_counts.items() if c == 4][0]
        return (7, 'quads', [quads])
    if counts[0] == 3 and counts[1] >= 2:
        trips = [r for r, c in rank_counts.items() if c == 3][0]
        pair = [r for r, c in rank_counts.items() if c >= 2 and r != trips][0]
        return (6, 'full_house', [trips, pair])
    if flush_suit:
        return (5, 'flush', flush_cards[:5])
    if straight_high:
        return (4, 'straight', [straight_high])
    if counts[0] == 3:
        trips = [r for r, c in rank_counts.items() if c == 3][0]
        return (3, 'trips', [trips])
    if counts[0] == 2 and counts[1] == 2:
        pairs = sorted([r for r, c in rank_counts.items() if c == 2], reverse=True)
        return (2, 'two_pair', pairs)
    if counts[0] == 2:
        pair = [r for r, c in rank_counts.items() if c == 2][0]
        kickers = sorted([r for r, c in rank_counts.items() if c == 1], reverse=True)[:3]
        return (1, 'one_pair', [pair] + kickers)

    high_cards = sorted(ranks, reverse=True)[:5]
    return (0, 'high_card', high_cards)

# ── Pre-flop Equity (hot/cold vs N random opponents) ──
# Pre-computed equity vs 1 random hand
PREFLOP_EQ_VS_1 = {
    'AA': 0.852, 'KK': 0.824, 'QQ': 0.799, 'JJ': 0.774, 'TT': 0.750,
    '99': 0.720, '88': 0.691, '77': 0.661, '66': 0.633, '55': 0.603,
    '44': 0.570, '33': 0.536, '22': 0.503,
    'AKs': 0.670, 'AQs': 0.662, 'AJs': 0.653, 'ATs': 0.646, 'A9s': 0.629,
    'A8s': 0.619, 'A7s': 0.609, 'A6s': 0.599, 'A5s': 0.599, 'A4s': 0.590,
    'A3s': 0.581, 'A2s': 0.574,
    'AKo': 0.653, 'AQo': 0.644, 'AJo': 0.636, 'ATo': 0.627, 'A9o': 0.608,
    'A8o': 0.597, 'A7o': 0.586, 'A6o': 0.576, 'A5o': 0.576, 'A4o': 0.567,
    'A3o': 0.558, 'A2o': 0.549,
    'KQs': 0.634, 'KJs': 0.626, 'KTs': 0.618, 'K9s': 0.600, 'K8s': 0.588,
    'K7s': 0.577, 'K6s': 0.568, 'K5s': 0.560, 'K4s': 0.552, 'K3s': 0.546,
    'K2s': 0.540,
    'KQo': 0.614, 'KJo': 0.606, 'KTo': 0.597, 'K9o': 0.577, 'K8o': 0.563,
    'K7o': 0.551, 'K6o': 0.542, 'K5o': 0.533, 'K4o': 0.525, 'K3o': 0.518,
    'K2o': 0.512,
    'QJs': 0.603, 'QTs': 0.595, 'Q9s': 0.577, 'Q8s': 0.564, 'Q7s': 0.554,
    'Q6s': 0.546, 'Q5s': 0.539, 'Q4s': 0.532, 'Q3s': 0.526, 'Q2s': 0.520,
    'QJo': 0.581, 'QTo': 0.572, 'Q9o': 0.552, 'Q8o': 0.538, 'Q7o': 0.526,
    'Q6o': 0.517, 'Q5o': 0.509, 'Q4o': 0.501, 'Q3o': 0.495, 'Q2o': 0.488,
    'JTs': 0.575, 'J9s': 0.558, 'J8s': 0.545, 'J7s': 0.536, 'J6s': 0.528,
    'J5s': 0.522, 'J4s': 0.516, 'J3s': 0.510, 'J2s': 0.504,
    'JTo': 0.550, 'J9o': 0.531, 'J8o': 0.517, 'J7o': 0.506, 'J6o': 0.497,
    'J5o': 0.490, 'J4o': 0.483, 'J3o': 0.476, 'J2o': 0.469,
    'T9s': 0.541, 'T8s': 0.528, 'T7s': 0.519, 'T6s': 0.512, 'T5s': 0.506,
    'T4s': 0.500, 'T3s': 0.494, 'T2s': 0.488,
    'T9o': 0.514, 'T8o': 0.499, 'T7o': 0.489, 'T6o': 0.481, 'T5o': 0.474,
    'T4o': 0.467, 'T3o': 0.460, 'T2o': 0.453,
    '98s': 0.508, '97s': 0.497, '96s': 0.490, '95s': 0.484, '94s': 0.478,
    '93s': 0.472, '92s': 0.466,
    '98o': 0.478, '97o': 0.465, '96o': 0.457, '95o': 0.450, '94o': 0.443,
    '93o': 0.436, '92o': 0.429,
    '87s': 0.480, '86s': 0.472, '85s': 0.466, '84s': 0.460, '83s': 0.454,
    '82s': 0.448,
    '87o': 0.448, '86o': 0.439, '85o': 0.432, '84o': 0.425, '83o': 0.418,
    '82o': 0.411,
    '76s': 0.463, '75s': 0.456, '74s': 0.450, '73s': 0.444, '72s': 0.438,
    '76o': 0.429, '75o': 0.421, '74o': 0.414, '73o': 0.407, '72o': 0.401,
    '65s': 0.448, '64s': 0.441, '63s': 0.435, '62s': 0.429,
    '65o': 0.412, '64o': 0.404, '63o': 0.397, '62o': 0.390,
    '54s': 0.434, '53s': 0.428, '52s': 0.422,
    '54o': 0.397, '53o': 0.389, '52o': 0.382,
    '43s': 0.421, '42s': 0.415,
    '43o': 0.382, '42o': 0.375,
    '32s': 0.409,
    '32o': 0.371,
}

def preflop_hand_key(hole):
    """Convert ['Ah','Kh'] -> 'AKs' or 'AA'"""
    r1, r2 = sorted([card_rank(hole[0]), card_rank(hole[1])], reverse=True)
    idx_to_rank = {v: k for k, v in RANK_VAL.items()}
    rc1, rc2 = idx_to_rank.get(r1, '?'), idx_to_rank.get(r2, '?')
    if rc1 == rc2:
        return rc1 + rc2  # pairs: 'AA', 'TT', etc.
    suited = card_suit(hole[0]) == card_suit(hole[1])
    return rc1 + rc2 + ('s' if suited else 'o')

def preflop_equity(hole, num_opponents=1):
    """Get approximate pre-flop equity vs N random opponents."""
    key = preflop_hand_key(hole)
    eq_vs_1 = PREFLOP_EQ_VS_1.get(key, 0.45)
    if num_opponents <= 1:
        return eq_vs_1
    multi_eq = eq_vs_1 * (0.88 ** (num_opponents - 1))
    fair_share = 1.0 / (num_opponents + 1)
    return max(multi_eq, fair_share)

# ── Monte Carlo Post-flop Equity ──
def compare_hands(strength_a, detail_a, strength_b, detail_b):
    """Compare two evaluated hands. Returns 1 if A wins, -1 if B wins, 0 if tie."""
    if strength_a != strength_b:
        return 1 if strength_a > strength_b else -1
    for da, db in zip(detail_a, detail_b):
        if da != db:
            return 1 if da > db else -1
    return 0

def monte_carlo_equity(hole, board, num_opponents=1, num_sims=500):
    """Estimate equity on current street via Monte Carlo simulation.
    Runs quickly enough for 3-5s decision windows."""
    deck = make_deck()
    known = hole + board
    remaining = [c for c in deck if c not in known]

    wins = 0
    for _ in range(num_sims):
        sim_deck = remaining[:]
        random.shuffle(sim_deck)

        # Deal remaining board cards
        needed = 5 - len(board)
        sim_board = board + sim_deck[:needed]
        sim_idx = needed

        # Deal opponent hands
        opp_holes = []
        for _ in range(num_opponents):
            opp_holes.append([sim_deck[sim_idx], sim_deck[sim_idx + 1]])
            sim_idx += 2

        # Evaluate
        our_strength, our_type, our_detail = evaluate_hand(hole, sim_board)

        win = True
        for opp in opp_holes:
            opp_strength, opp_type, opp_detail = evaluate_hand(opp, sim_board)
            result = compare_hands(our_strength, our_detail, opp_strength, opp_detail)
            if result < 0:
                win = False
                break

        if win:
            wins += 1

    return wins / num_sims

# ── Pot Odds & EV ──
def pot_odds(call_amount, pot_size):
    """Calculate pot odds as a fraction."""
    return call_amount / (pot_size + call_amount) if (pot_size + call_amount) > 0 else 0

def should_call(equity, call_amount, pot_size):
    """Should we call based on equity vs pot odds?"""
    odds = pot_odds(call_amount, pot_size)
    return equity > odds, equity, odds

def ev_of_action(action, amount, equity, pot, stack, call_amount=0, fold_equity=0.4):
    """Compute approximate EV of an action."""
    if action == 'fold':
        return 0
    elif action == 'check':
        return equity * pot
    elif action == 'call':
        return equity * (pot + call_amount) - (1 - equity) * call_amount
    elif action in ('bet', 'raise'):
        return fold_equity * pot + (1 - fold_equity) * (equity * (pot + amount) - (1 - equity) * amount)
    elif action == 'all-in':
        return equity * (pot + amount) - (1 - equity) * amount
    return 0

# ── Tournament Module ──

def tournament_phase(total_players, active_players, hands_played=0):
    """Detect tournament phase: early, middle, late, bubble."""
    if total_players <= 0:
        return "middle"

    elim_rate = (total_players - active_players) / total_players

    # Estimate bubble: near money cutoff
    # Typical: top 15-20% get paid. Bubble = 1-2 spots before that.
    money_spots = max(1, total_players * 15 // 100)  # ~15% paid
    bubble_zone = active_players <= money_spots + 3 and active_players > money_spots

    if active_players <= 4:
        return "final_table"
    elif bubble_zone:
        return "bubble"
    elif elim_rate < 0.3:
        return "early"
    elif elim_rate < 0.7:
        return "middle"
    else:
        return "late"

def is_near_bubble(total_players, active_players):
    """Check if we're on the bubble (1-2 spots before the money)."""
    if total_players <= 0 or active_players <= 0:
        return False
    money_spots = max(1, total_players * 15 // 100)
    return money_spots < active_players <= money_spots + 2

def icm_tighten_factor(stack, avg_stack, total_players, active_players):
    """Return a multiplier for how much tighter to play (ICM pressure).
    Higher = tighter. Returns 1.0 for no adjustment."""
    if avg_stack <= 0:
        return 1.0

    stack_ratio = stack / avg_stack

    # Medium stacks (0.8-1.5x avg) feel the most ICM pressure
    if 0.8 <= stack_ratio <= 1.5:
        base_icm = 1.15  # play 15% tighter
    elif stack_ratio > 2.0:
        base_icm = 0.90  # big stack: play 10% wider (can afford risk)
    elif stack_ratio < 0.5:
        base_icm = 0.90  # short stack: need to gamble, play wider
    else:
        base_icm = 1.0

    # Bubble pressure
    if is_near_bubble(total_players, active_players):
        if stack_ratio <= 1.5:
            # Most stacks on bubble: play tighter
            base_icm *= 1.25
        elif stack_ratio > 2.0:
            # Big stack on bubble: abuse others
            base_icm *= 0.80
        elif stack_ratio > 2.0:
            # Big stack on bubble: abuse others
            base_icm *= 0.80

    return base_icm

def effective_bb_over_time(stack, bb_size, hands_played=0):
    """Return effective BB and whether blinds are escalating."""
    return stack / bb_size if bb_size > 0 else 999

def aggression_from_blinds(eff_bb, bb_size):
    """Adjust aggression based on effective BB.
    Low BB = more aggressive (desperate or shove mode).
    High BB = standard."""
    if eff_bb <= 10:
        return 1.3  # 30% more aggressive in shove territory
    elif eff_bb <= 20:
        return 1.15
    elif eff_bb <= 40:
        return 1.0
    else:
        return 0.95  # deep stack: can afford patience

# ── Preflop Range Tiers ──
# Categorize hand strength for 3-bet/4-bet decisions

def hand_tier(hole):
    """Classify hand into strength tier for strategic decisions.
    Returns: 'premium', 'strong', 'playable', 'speculative', 'trash'"""
    key = preflop_hand_key(hole)
    eq = PREFLOP_EQ_VS_1.get(key, 0.45)
    
    if eq >= 0.79:  # AA, KK, QQ
        return 'premium'
    elif eq >= 0.65:  # QQ-JJ, TT+, AKs, AQs, AKo
        return 'strong'
    elif eq >= 0.55:  # 99-88, AQo-ATo, AJs-ATs, KQs/o, KJs, QJs
        return 'playable'
    elif eq >= 0.43:  # smaller pairs, suited connectors, Axs, broadway combos
        return 'speculative'
    else:
        return 'trash'

def is_premium_hand(hole):
    """QQ+, AK — always 3-bet/4-bet. Broader than hand_tier premium."""
    key = preflop_hand_key(hole)
    return key in ('AA', 'KK', 'QQ', 'AKs', 'AKo') or key.startswith('KK') or key.startswith('QQ')

def is_value_3bet_hand(hole):
    """QQ+, AK, JJ, TT - hands strong enough to 3-bet for value."""
    key = preflop_hand_key(hole)
    eq = PREFLOP_EQ_VS_1.get(key, 0.45)
    return eq >= 0.65  # roughly QQ+/AK and TT/JJ

def is_bluff_3bet_hand(hole, position):
    """Axs, suited connectors from late position - bluff 3-bet candidates."""
    key = preflop_hand_key(hole)
    tier = hand_tier(hole)

    if tier not in ('speculative', 'playable'):
        return False

    # Axs (A2s-A5s) are good bluff candidates - blocker to bigger aces
    if len(key) >= 3 and key[0] == 'A' and key[1] in '2345' and key[2] == 's':
        return position >= 2  # CO, BTN, SB

    # Suited connectors 67s+ from late position
    if key.endswith('s') and not key.startswith('A'):
        r1 = RANK_VAL.get(key[0], 0)
        r2 = RANK_VAL.get(key[1], 0)
        if abs(r1 - r2) <= 2 and r1 >= 6:  # connected within 2 gaps, 7+
            return position >= 3  # BTN, SB only

    # KJs, QTs, JTs from BTN/CO
    if position >= 2 and key in ('KJs', 'KQs', 'QTs', 'JTs', 'T9s', '87s', '76s', '65s'):
        return True

    return False

def is_4bet_stack_off_hand(hole):
    """QQ+, AK, JJ - stack off to a 5-bet. Broader range to avoid ICM-suicide."""
    key = preflop_hand_key(hole)
    return key in ('KK', 'AA', 'AKs', 'AKo', 'QQ', 'JJ')

def should_fold_to_5bet(hole):
    """Only TT- and weak suited aces fold to 5-bet. Keep QQ+/AKs/JJ in."""
    key = preflop_hand_key(hole)
    return key in ('TT', '99', '88', 'AQo', 'AJs')

# ── 3-bet/4-bet Sizing ──

def three_bet_size(open_raise, in_position, pot):
    """Calculate 3-bet sizing.
    In position: 3x the raise
    Out of position: 4x the raise"""
    base = open_raise * (3 if in_position else 4)
    return max(base, pot)  # never smaller than pot

def four_bet_size(three_bet_amount, stack):
    """4-bet sizing: roughly 2.5x the 3-bet, or shove if < 40% stack."""
    size = three_bet_amount * 2.5
    if size > stack * 0.4:
        return stack  # shove
    return int(size)

# ── Opponent Exploitation ──

def classify_from_stats(vpip=0, pfr=0, af=0):
    """Classify opponent style from VPIP/PFR/AF if label is unknown.
    VPIP: % of hands voluntarily put money in pot
    PFR: % of hands raised preflop
    AF: aggression factor (bet+raise / call)"""
    if vpip <= 0:
        return "unknown"
    if vpip < 22:  # tight
        if af >= 2:
            return "TAG"
        return "Nit" if pfr < 10 else "Weak-Tight"
    else:  # loose
        if af >= 2:
            return "LAG"
        return "Station"

def exploitation_adjustment(opponent_style, hand_tier_val, in_position, board_texture='dry'):
    """Return (equity_multiplier, fold_equity_multiplier, strategy_notes)
    based on opponent type."""

    adjustments = {
        'Nit': {
            'eq_mult': 1.0,  # they have it when they bet
            'fold_eq_mult': 0.75,  # they fold a LOT to aggression
            'notes': [
                'steal_more_late',
                'fold_to_raises',
                'bluff_dry_boards',
            ],
        },
        'Station': {
            'eq_mult': 1.05,  # value bet wider - they pay off
            'fold_eq_mult': 0.30,  # they NEVER fold
            'notes': [
                'value_bet_thin',
                'never_bluff',
                'dont_raise_bluff',
            ],
        },
        'LAG': {
            'eq_mult': 0.95,  # widen value range against aggression
            'fold_eq_mult': 0.45,  # they fight back
            'notes': [
                'widen_3bet_value',
                'call_down_lighter_tp',
                'trap_more',
            ],
        },
        'Weak-Tight': {
            'eq_mult': 1.02,
            'fold_eq_mult': 0.65,
            'notes': [
                'bluff_dry_boards',
                'raise_cbets',
                'steal_late',
            ],
        },
        'TAG': {
            'eq_mult': 1.0,
            'fold_eq_mult': 0.40,
            'notes': [
                'standard_play',
                'respect_raises',
            ],
        },
        'unknown': {
            'eq_mult': 1.0,
            'fold_eq_mult': 0.40,
            'notes': [
                'standard_play',
            ],
        },
    }

    return adjustments.get(opponent_style, adjustments['unknown'])

def get_fold_equity(opponent_style, board_texture='dry', in_position=True,
                    num_opponents=1):
    """Get fold equity estimate based on opponent and board texture.

    num_opponents: ALL of them must fold for a bluff to work, so fold
    equity compounds (p_fold ** n) in multi-way pots.
    """
    base = {
        'Nit': 0.65, 'Station': 0.15, 'LAG': 0.30,
        'Weak-Tight': 0.60, 'TAG': 0.40, 'unknown': 0.40,
    }.get(opponent_style, 0.40)

    # Wet boards reduce fold equity for everyone
    if board_texture == 'wet':
        base *= 0.7

    # Being IP increases fold equity slightly (position pressure)
    if in_position:
        base *= 1.05

    base = min(base, 0.85)

    # Every opponent must fold — bluffing into 3-way+ pots rarely works
    if num_opponents > 1:
        base = base ** num_opponents

    return base

# ── Multi-street Postflop ──

def classify_board_texture(board):
    """Classify board: dry, wet, paired, ace_high, connected_low."""
    if not board:
        return "preflop"

    ranks = [card_rank(c) for c in board]
    suits = [card_suit(c) for c in board]

    paired = len(ranks) != len(set(ranks))
    ace_high = 14 in ranks
    has_flush_draw = any(v >= 3 for v in Counter(suits).values())

    unique_ranks = sorted(set(ranks))
    has_straight_draw = False
    for i in range(len(unique_ranks) - 2):
        if unique_ranks[i+2] - unique_ranks[i] <= 4:
            has_straight_draw = True
            break

    all_low = all(r <= 7 for r in ranks)

    if paired:
        return "paired"
    if has_flush_draw and has_straight_draw:
        return "wet"
    if has_flush_draw or has_straight_draw:
        return "wet"
    if ace_high and not has_flush_draw and not has_straight_draw:
        return "ace_high"
    if all_low and len(board) >= 3:
        return "connected_low"
    return "dry"

def estimate_draw_equity(hole, board, num_opponents=1):
    """Quick draw equity estimation: flush draws, straight draws, overcards."""
    if not board:
        return 0

    our_suit = card_suit(hole[0]) if hole else '?'
    board_suits = [card_suit(c) for c in board]
    flush_draw = board_suits.count(our_suit) == 3 and card_suit(hole[0]) == card_suit(hole[1])

    our_ranks = sorted([card_rank(c) for c in hole], reverse=True)
    board_ranks = sorted(set(card_rank(c) for c in board))

    # Overcards
    overcards = sum(1 for r in our_ranks if r > max(board_ranks, default=0))

    # Open-ended straight draw or gutshot
    all_r = sorted(set(our_ranks + board_ranks))
    has_oesd = False
    has_gutshot = False
    for i in range(len(all_r) - 3):
        if all_r[i+3] - all_r[i] == 4:
            has_oesd = True
            break
    for i in range(len(all_r) - 2):
        if all_r[i+2] - all_r[i] == 5:
            has_gutshot = True
            break

    draw_eq = 0
    cards_to_come = 5 - len(board)

    if flush_draw:
        draw_eq += 0.20 * min(cards_to_come, 2) / 2  # ~9% per card, 2 streets
    if has_oesd:
        draw_eq += 0.17 * min(cards_to_come, 2) / 2
    if has_gutshot:
        draw_eq += 0.08 * min(cards_to_come, 2) / 2
    draw_eq += overcards * 0.03 * cards_to_come

    return min(draw_eq, 0.35)

def improved_on_turn_or_river(prev_board, new_board, hole):
    """Check if our hand improved from previous street."""
    if not prev_board or not new_board or len(new_board) <= len(prev_board):
        return False

    _, prev_type, _ = evaluate_hand(hole, prev_board) if len(prev_board) >= 3 else (0, 'incomplete', [])
    _, new_type, _ = evaluate_hand(hole, new_board) if len(new_board) >= 3 else (0, 'incomplete', [])

    return new_type != prev_type

def is_scare_card(new_card, board):
    """Check if the latest card is a scare card (completes draws)."""
    if not new_card or not board:
        return False

    suits = [card_suit(c) for c in board]
    nc_suit = card_suit(new_card)

    # Card completes a flush
    if suits.count(nc_suit) >= 3:
        return True

    # Card could complete a straight
    ranks = sorted(set([card_rank(c) for c in board] + [card_rank(new_card)]))
    for i in range(len(ranks) - 4):
        if ranks[i+4] - ranks[i] == 4:
            return True

    # High card (A, K) on board
    if card_rank(new_card) >= 13:
        return True

    # Pairs the board
    board_ranks = [card_rank(c) for c in board]
    if card_rank(new_card) in board_ranks:
        return True

    return False

def postflop_decision(hole, board, allowed_actions, pot, stack, call_amount=0,
                       num_opponents=1, street='Flop', opponent_style='unknown',
                       raised_preflop=False, in_position=True,
                       prev_action_on_prior_street='check', prev_equity=0):
    """
    Multi-street postflop decision engine.

    Args:
        raised_preflop: did we raise preflop? (initiative indicator)
        in_position: are we in position?
        prev_action_on_prior_street: what did we do on previous street?
        prev_equity: equity estimate from previous street

    Returns: (action, amount, message, equity)
    """
    if not board or not hole:
        return ('check', 0, 'no board/hole cards', 0)

    equity = monte_carlo_equity(hole, board, num_opponents, num_sims=300)
    draw_eq = estimate_draw_equity(hole, board, num_opponents)
    combined_eq = equity + draw_eq * 0.5  # blend raw equity with draw potential
    texture = classify_board_texture(board)
    fold_eq = get_fold_equity(opponent_style, texture, in_position,
                              num_opponents=num_opponents)

    strength, hand_type, _ = evaluate_hand(hole, board)

    # Exploitation adjustments
    exploit = exploitation_adjustment(opponent_style, hand_tier(hole), in_position, texture)
    adj_fold_eq = fold_eq * exploit.get('fold_eq_mult', 1.0) / 0.40

    # ── RIVER ──
    if street == 'River':
        return _river_decision(equity, strength, hand_type, allowed_actions, pot, stack,
                               call_amount, opponent_style, texture, fold_eq, in_position)

    # ── TURN ──
    if street == 'Turn':
        return _turn_decision(hole, board, equity, draw_eq, strength, hand_type,
                               allowed_actions, pot, stack, call_amount, num_opponents,
                               opponent_style, texture, fold_eq, raised_preflop,
                               prev_action_on_prior_street, prev_equity, in_position)

    # ── FLOP ──
    return _flop_decision(hole, board, equity, draw_eq, strength, hand_type,
                           allowed_actions, pot, stack, call_amount, num_opponents,
                           opponent_style, texture, fold_eq, raised_preflop, in_position)


def _flop_decision(hole, board, equity, draw_eq, strength, hand_type,
                   allowed_actions, pot, stack, call_amount, num_opponents,
                   opponent_style, texture, fold_eq, raised_preflop, in_position):
    """Flop decision logic with c-bet, float, and raise strategies."""
    exploit = exploitation_adjustment(opponent_style, hand_tier(hole), in_position, texture)
    exploit_notes = exploit.get('notes', [])

    # ── FACING A BET ──
    if call_amount > 0 and 'call' in allowed_actions:
        # Strong hand: raise
        if equity > 0.65:
            if 'raise' in allowed_actions:
                raise_amt = min(call_amount * 3, stack)
                return ('raise', raise_amt, f"flopped strong ({hand_type}) - raising", equity)
            return ('call', call_amount, f"flopped strong ({hand_type}) - calling", equity)

        # Medium hand (TP, overpair): call
        if equity > 0.50:
            odds = pot_odds(call_amount, pot)
            if equity > odds:
                return ('call', call_amount, f"flop call - {equity*100:.0f}% eq vs {odds*100:.0f}% odds", equity)
            # Vs Station, call wider
            if opponent_style == 'Station' and equity > 0.40:
                return ('call', call_amount, f"vs Station - wide call with {equity*100:.0f}% eq", equity)
            if 'fold' in allowed_actions:
                return ('fold', 0, f"not enough equity to call - {equity*100:.0f}%", equity)

        # Draw: float IP
        if draw_eq > 0.15 and in_position:
            odds = pot_odds(call_amount, pot)
            if draw_eq > odds or call_amount <= pot * 0.25:
                return ('call', call_amount, f"float IP - draw equity {draw_eq*100:.0f}%", equity)

        # Bluff-raise vs Weak-Tight or Nit on dry board
        if 'raise_cbets' in exploit_notes and call_amount <= pot * 0.5 and texture == 'dry':
            if 'raise' in allowed_actions:
                return ('raise', call_amount * 3, f"raise flop - vs {opponent_style} on dry board", equity)

        # Fold
        if 'fold' in allowed_actions:
            return ('fold', 0, f"flop fold - {equity*100:.0f}% eq on {texture} board", equity)
        return ('call', call_amount, "forced to call", equity)

    # ── INITIATIVE (WE CAN BET/CHECK) ──
    if 'bet' in allowed_actions:
        # C-bet: bet if we raised preflop
        if raised_preflop:
            if equity > 0.55:
                # Strong c-bet for value
                bet_size = max(int(pot * 0.66), int(pot * 0.5))
                return ('bet', bet_size, f"c-bet value - {equity*100:.0f}% eq, {hand_type}", equity)
            elif equity > 0.40 and draw_eq > 0.10:
                # Semi-bluff c-bet with draw
                bet_size = int(pot * 0.5)
                return ('bet', bet_size, f"semi-bluff c-bet - {equity*100:.0f}% eq + draw", equity)
            elif equity > 0.35 and texture in ('dry', 'ace_high'):
                # Bluff c-bet on favorable texture
                # But NOT vs Station
                if opponent_style != 'Station':
                    bet_size = int(pot * 0.4)
                    return ('bet', bet_size, f"c-bet bluff - {texture} board, IP={in_position}", equity)
            # Check behind with weak hands
            if 'check' in allowed_actions:
                return ('check', 0, f"give up c-bet - {equity*100:.0f}% eq", equity)

        # No initiative - bet strong hands only
        if equity > 0.60:
            bet_size = int(pot * 0.75)
            return ('bet', bet_size, f"donk bet - {equity*100:.0f}% eq, {hand_type}", equity)

        # Bluff opportunities
        if 'bluff_dry_boards' in exploit_notes and texture == 'dry':
            if random.random() < 0.25:  # 25% frequency
                bet_size = int(pot * 0.45)
                return ('bet', bet_size, f"bluff - vs {opponent_style} on dry board", equity)

        if 'check' in allowed_actions:
            return ('check', 0, f"check behind - {equity*100:.0f}% eq", equity)

    if 'check' in allowed_actions:
        return ('check', 0, f"checking - {equity*100:.0f}% eq", equity)

    return ('fold', 0, f"no action - {equity*100:.0f}% eq", equity)


def _turn_decision(hole, board, equity, draw_eq, strength, hand_type,
                   allowed_actions, pot, stack, call_amount, num_opponents,
                   opponent_style, texture, fold_eq, raised_preflop,
                   prev_action, prev_equity, in_position):
    """Turn decision with double-barrel and float-give-up logic."""
    exploit = exploitation_adjustment(opponent_style, hand_tier(hole), in_position, texture)
    exploit_notes = exploit.get('notes', [])

    # ── FACING A BET ──
    if call_amount > 0 and 'call' in allowed_actions:
        if equity > 0.65:
            if 'raise' in allowed_actions:
                return ('raise', min(call_amount * 3, stack), f"turn raise - strong {hand_type}", equity)
            return ('call', call_amount, f"turn call - strong {hand_type}, {equity*100:.0f}% eq", equity)

        if equity > 0.50:
            odds = pot_odds(call_amount, pot)
            if equity > odds:
                return ('call', call_amount, f"turn call - {equity*100:.0f}% eq vs {odds*100:.0f}%", equity)

        # Float continuation: if we floated flop and improved or picked up draw
        if prev_action == 'call' and in_position:
            if equity > prev_equity + 0.05 or draw_eq > 0.15:
                if call_amount <= pot * 0.4:
                    return ('call', call_amount, f"turn float - improved from flop", equity)

        # Vs LAG: call down lighter with TP+
        if 'call_down_lighter_tp' in exploit_notes and strength >= 1:
            if call_amount <= pot * 0.5:
                return ('call', call_amount, f"vs LAG - calling lighter, {equity*100:.0f}% eq", equity)

        # Fold
        if 'fold' in allowed_actions:
            return ('fold', 0, f"turn fold - {equity*100:.0f}% eq", equity)
        return ('call', call_amount, "forced call", equity)

    # ── INITIATIVE ──
    if 'bet' in allowed_actions:
        # Double barrel: strong hand or scare card
        improved = len(board) >= 4 and is_scare_card(board[-1], board[:-1])

        if equity > 0.60:
            bet_size = int(pot * 0.75)
            return ('bet', bet_size, f"turn value - {hand_type}, {equity*100:.0f}% eq", equity)

        # Double barrel with scare card if we c-bet flop
        if raised_preflop and prev_action == 'bet' and improved:
            if opponent_style != 'Station':
                bet_size = int(pot * 0.65)
                return ('bet', bet_size, f"double barrel - scare card, {equity*100:.0f}% eq", equity)

        # Semi-bluff with strong draw on turn
        if draw_eq > 0.20:
            bet_size = int(pot * 0.55)
            return ('bet', bet_size, f"turn semi-bluff - draw eq {draw_eq*100:.0f}%", equity)

        # Give up
        if 'check' in allowed_actions:
            return ('check', 0, f"give up turn - {equity*100:.0f}% eq, no improvement", equity)

    if 'check' in allowed_actions:
        return ('check', 0, f"check turn - {equity*100:.0f}% eq", equity)

    return ('fold', 0, f"turn fold - {equity*100:.0f}% eq", equity)


def _river_decision(equity, strength, hand_type, allowed_actions, pot, stack,
                    call_amount, opponent_style, texture, fold_eq, in_position):
    """River logic: thin value, check medium, fold weak."""
    exploit = exploitation_adjustment(opponent_style, '', in_position, texture)
    exploit_notes = exploit.get('notes', [])

    # ── FACING A BET ──
    if call_amount > 0 and 'call' in allowed_actions:
        odds = pot_odds(call_amount, pot)

        # Strong: raise or call
        if equity > 0.70:
            if 'raise' in allowed_actions and call_amount <= pot * 0.5:
                return ('raise', min(call_amount * 2, stack), f"river raise - {hand_type}", equity)
            return ('call', call_amount, f"river call - {hand_type}, {equity*100:.0f}% eq", equity)

        # Medium: call if odds good
        if equity > 0.50:
            if equity > odds:
                return ('call', call_amount, f"river call - value, {equity*100:.0f}% eq", equity)

        # Thin call vs Station (they bluff less)
        if 'value_bet_thin' in exploit_notes and equity > 0.45 and call_amount <= pot * 0.25:
            return ('call', call_amount, f"vs Station thin call - {equity*100:.0f}% eq", equity)

        # Fold
        if 'fold' in allowed_actions:
            return ('fold', 0, f"river fold - {equity*100:.0f}% eq", equity)
        return ('call', call_amount, "forced", equity)

    # ── INITIATIVE ──
    if 'bet' in allowed_actions:
        # Value bet: strong to medium hands
        if equity > 0.75:
            bet_size = int(pot * 0.75)
            return ('bet', bet_size, f"river value - {hand_type}", equity)

        # Thin value vs Station
        if 'value_bet_thin' in exploit_notes and equity > 0.55:
            bet_size = int(pot * 0.50)
            return ('bet', bet_size, f"thin value vs {opponent_style}", equity)

        # Bluff: only vs Nit/Weak-Tight on missed draws
        if 'bluff_dry_boards' in exploit_notes and equity < 0.35:
            if random.random() < 0.20:  # 20% frequency
                bet_size = int(pot * 0.50)
                return ('bet', bet_size, f"river bluff - vs {opponent_style}", equity)

        # Check behind medium/weak hands
        if 'check' in allowed_actions:
            return ('check', 0, f"check behind river - {equity*100:.0f}% eq", equity)

    if 'check' in allowed_actions:
        return ('check', 0, f"check river - {equity*100:.0f}% eq", equity)

    return ('fold', 0, f"river fold - {equity*100:.0f}% eq", equity)


# ── Push/Fold Charts (≤20 BB) ──
PUSH_FOLD_HANDS = {
    15: {
        0: {'pairs': 5, 'high': ['AK','AQ','AJ','AT','KQ'], 'suited': ['AK','AQ','AJ','AT','A9','KQ','KJ','QJ','JT','T9','98','87']},
        1: {'pairs': 4, 'high': ['AK','AQ','AJ','AT','KQ','KJ'], 'suited': ['AK','AQ','AJ','AT','A9','A8','KQ','KJ','QJ','JT','T9','98','87','76']},
        2: {'pairs': 3, 'high': ['AK','AQ','AJ','AT','KQ','KJ','KT','QJ'], 'suited': ['AK','AQ','AJ','AT','A9','A8','A7','KQ','KJ','KT','QJ','QT','JT','T9','98','87','76','65']},
        3: {'pairs': 2, 'high': ['AK','AQ','AJ','AT','A9','KQ','KJ','KT','QJ','QT'], 'suited': ['AK','AQ','AJ','AT','A9','A8','A7','A6','A5','KQ','KJ','KT','K9','QJ','QT','Q9','JT','J9','T9','98','87','76','65','54']},
        4: {'pairs': 2, 'high': ['AK','AQ','AJ','AT','A9','KQ','KJ','KT','QJ'], 'suited': ['AK','AQ','AJ','AT','A9','A8','A7','KQ','KJ','KT','QJ','JT','T9','98','87']},
        5: {'pairs': 2, 'high': ['AK','AQ','AJ','AT','KQ'], 'suited': ['AK','AQ','AJ','AT','KQ','KJ','QJ']},
    },
    10: {
        0: {'pairs': 4, 'high': ['AK','AQ','AJ','AT','KQ','KJ'], 'suited': ['AK','AQ','AJ','AT','A9','A8','KQ','KJ','QJ','JT','T9','98']},
        1: {'pairs': 3, 'high': ['AK','AQ','AJ','AT','KQ','KJ','KT'], 'suited': ['AK','AQ','AJ','AT','A9','A8','A7','KQ','KJ','KT','QJ','JT','T9','98','87']},
        2: {'pairs': 2, 'high': ['AK','AQ','AJ','AT','A9','KQ','KJ','KT','QJ','QT'], 'suited': ['AK','AQ','AJ','AT','A9','A8','A7','A6','KQ','KJ','KT','K9','QJ','QT','JT','J9','T9','98','87','76']},
        3: {'pairs': 2, 'high': ['AK','AQ','AJ','AT','A9','A8','KQ','KJ','KT','QJ','QT','Q9'], 'suited': ['AK','AQ','AJ','AT','A9','A8','A7','A6','A5','A4','KQ','KJ','KT','K9','QJ','QT','Q9','JT','J9','T9','T8','98','87','76','65','54']},
        4: {'pairs': 2, 'high': ['AK','AQ','AJ','AT','A9','KQ','KJ','KT'], 'suited': ['AK','AQ','AJ','AT','A9','A8','A7','KQ','KJ','KT','QJ','JT','T9','98','87']},
        5: {'pairs': 2, 'high': ['AK','AQ','AJ','AT','KQ','KJ'], 'suited': ['AK','AQ','AJ','AT','A9','KQ','KJ','QJ']},
    },
    5: {
        0: {'pairs': 2, 'high': ['AK','AQ','AJ','AT','KQ','KJ','KT','QJ','JT'], 'suited': ['AK','AQ','AJ','AT','A9','A8','A7','KQ','KJ','KT','QJ','JT','T9','98']},
        1: {'pairs': 2, 'high': ['AK','AQ','AJ','AT','A9','KQ','KJ','KT','QJ','JT'], 'suited': ['AK','AQ','AJ','AT','A9','A8','A7','A6','KQ','KJ','KT','QJ','QT','JT','T9','98','87']},
        2: {'pairs': 2, 'high': ['AK','AQ','AJ','AT','A9','A8','KQ','KJ','KT','QJ','QT','JT'], 'suited': ['AK','AQ','AJ','AT','A9','A8','A7','A6','A5','KQ','KJ','KT','K9','QJ','QT','JT','J9','T9','98','87','76']},
        3: {'pairs': 2, 'high': ['AK','AQ','AJ','AT','A9','A8','A7','KQ','KJ','KT','QJ','QT','Q9','JT','J9'], 'suited': ['AK','AQ','AJ','AT','A9','A8','A7','A6','A5','A4','A3','32','KQ','KJ','KT','K9','QJ','QT','Q9','JT','J9','T9','T8','98','87','76','65','54','43']},
        4: {'pairs': 2, 'high': ['AK','AQ','AJ','AT','A9','KQ','KJ','KT'], 'suited': ['AK','AQ','AJ','AT','A9','A8','A7','KQ','KJ','KT','QJ','JT','T9','98']},
        5: {'pairs': 2, 'high': ['AK','AQ','AJ','AT','KQ','KJ'], 'suited': ['AK','AQ','AJ','AT','A9','KQ','KJ','QJ','JT']},
    },
}

def get_push_fold_bb_threshold(stack, bb=2):
    """Get the effective BB threshold bracket."""
    bb_stack = stack / bb
    if bb_stack <= 5: return 5
    if bb_stack <= 10: return 10
    if bb_stack <= 15: return 15
    return 20

def is_push_fold_hand(hole, position, bb_threshold):
    """Check if hand is in push/fold range."""
    if bb_threshold >= 20:
        return False
    chart = PUSH_FOLD_HANDS.get(bb_threshold)
    if not chart:
        return False
    pos_chart = chart.get(position, chart.get(0))
    if not pos_chart:
        return False

    key = preflop_hand_key(hole)
    r1, r2 = key[0], key[1] if len(key) > 1 else ''
    is_suited = key.endswith('s')
    is_pair = r1 == r2

    min_pair = pos_chart.get('pairs', 10)
    if is_pair:
        if min_pair <= 2:
            return True
        pair_val = RANK_VAL.get(r1, 0)
        return pair_val >= min_pair

    high_list = pos_chart.get('high', [])
    if not is_suited and len(key) >= 2:
        for h in high_list:
            if key[:2] == h:
                return True

    suited_list = pos_chart.get('suited', [])
    if is_suited and len(key) >= 2:
        for s in suited_list:
            if key[:2] == s:
                return True

    return False

# ── Decision Engine ──
def quant_decision(hole, board, allowed_actions, pot, stack, call_amount=0,
                   current_bet=0, num_opponents=2, street='preflop', opponent_style='unknown',
                   bb_size=2, position=3,
                   # New optional params (with defaults for backward compat)
                   raised_preflop=False, in_position=None,
                   total_players=6, active_players=6, hands_played=0,
                   avg_stack=None, prev_action='check', prev_equity=0,
                   opponent_stats=None):
    """
    Quantitative poker decision.
    Returns (action, amount, message, confidence).

    Maintains full backward compatibility - all new params have defaults.
    """
    # Resolve in_position from position if not provided
    if in_position is None:
        in_position = position >= 3  # CO/BTN are IP

    # ── Tournament Context ──
    phase = tournament_phase(total_players, active_players, hands_played)
    on_bubble = is_near_bubble(total_players, active_players)
    eff_stack = effective_bb_over_time(stack, bb_size, hands_played)
    icm_factor = icm_tighten_factor(stack, avg_stack or stack, total_players, active_players)
    agg_factor = aggression_from_blinds(eff_stack, bb_size)

    # ── Preflop: PUSH/FOLD MODE (<20 BB effective stack) ──
    bb_stack = stack / bb_size
    if bb_stack < 20 and street in ('PreDeal', 'Preflop') and hole:
        bb_thresh = get_push_fold_bb_threshold(stack, bb_size)
        pos = min(position, 5)

        # Tournament adjustments for push/fold
        # On bubble with medium stack: tighten shove range
        if on_bubble and 0.8 <= stack / (avg_stack or stack) <= 1.5:
            eq_min = 0.40  # higher threshold
        else:
            eq_min = 0.35

        if bb_stack <= 5:
            eq = preflop_equity(hole, num_opponents)
            if eq >= eq_min:
                return ('raise', stack, f"PUSH/FOLD ≤5BB - {preflop_hand_key(hole)} {eq*100:.0f}% eq, shoving [phase={phase}]", eq)
            if 'check' in allowed_actions:
                return ('check', 0, f"PUSH/FOLD ≤5BB - checking {preflop_hand_key(hole)}", 0.2)
            return ('fold', 0, f"PUSH/FOLD ≤5BB - folding {preflop_hand_key(hole)}", 0.2)

        if is_push_fold_hand(hole, pos, bb_thresh):
            eq = preflop_equity(hole, num_opponents)
            # ICM adjustment: skip marginal shoves on bubble
            if on_bubble and 0.8 <= stack / (avg_stack or stack) <= 1.5 and eq < 0.45:
                pass  # skip this shove
            else:
                return ('raise', stack, f"PUSH/FOLD {bb_stack:.0f}BB - {preflop_hand_key(hole)} {eq*100:.0f}% eq [phase={phase}]", eq)

        if call_amount == 0 and 'check' in allowed_actions:
            return ('check', 0, f"PUSH/FOLD {bb_stack:.0f}BB - {preflop_hand_key(hole)} not in range, checking", 0.3)
        return ('fold', 0, f"PUSH/FOLD {bb_stack:.0f}BB - {preflop_hand_key(hole)} not in shove range, folding", 0.3)

    # ── POST-FLOP PUSH/FOLD (≤10 BB) ──
    if bb_stack <= 10 and board and hole:
        eq = monte_carlo_equity(hole, board, num_opponents, num_sims=200)
        if eq >= 0.40 and ('bet' in allowed_actions or 'raise' in allowed_actions):
            return ('raise', stack, f"PUSH/FOLD {bb_stack:.0f}BB post - {eq*100:.0f}% eq, jamming", eq)
        if call_amount > 0 and eq >= 0.35:
            return ('call', call_amount, f"PUSH/FOLD {bb_stack:.0f}BB post - priced in {eq*100:.0f}%", eq)
        if 'check' in allowed_actions:
            return ('check', 0, f"PUSH/FOLD {bb_stack:.0f}BB post - checking {eq*100:.0f}%", eq)
        return ('fold', 0, f"PUSH/FOLD {bb_stack:.0f}BB post - folding {eq*100:.0f}%", eq)

    # ── NORMAL PREFLOP ──
    if street in ('PreDeal', 'Preflop') and hole:
        return _preflop_decision(hole, allowed_actions, pot, stack, call_amount,
                                   current_bet, num_opponents, opponent_style,
                                   bb_size, position, in_position,
                                   phase, on_bubble, icm_factor, agg_factor,
                                   total_players, active_players,
                                   opponent_stats=opponent_stats)

    # ── NORMAL POSTFLOP ──
    if board and hole:
        return postflop_decision(hole, board, allowed_actions, pot, stack,
                                  call_amount, num_opponents, street,
                                  opponent_style, raised_preflop, in_position,
                                  prev_action, prev_equity)

    # ── Fallback ──
    equity = preflop_equity(hole, num_opponents) if hole else 0.45

    if call_amount > 0 and 'call' in allowed_actions:
        odds = pot_odds(call_amount, pot)
        if equity > odds:
            return ('call', call_amount, f"fallback call - {equity*100:.0f}% eq", equity)
        if 'fold' in allowed_actions:
            return ('fold', 0, f"fallback fold", equity)

    if 'check' in allowed_actions:
        return ('check', 0, "fallback check", equity)

    return ('fold', 0, "no profitable action", equity)


def _preflop_decision(hole, allowed_actions, pot, stack, call_amount,
                      current_bet, num_opponents, opponent_style,
                      bb_size, position, in_position,
                      phase, on_bubble, icm_factor, agg_factor,
                      total_players, active_players,
                      opponent_stats=None):
    """Preflop decision with tournament awareness, 3-bet/4-bet, and opponent exploitation."""
    key = preflop_hand_key(hole)
    tier = hand_tier(hole)
    eq = preflop_equity(hole, num_opponents)

    exploit = exploitation_adjustment(opponent_style, tier, in_position)
    exploit_notes = exploit.get('notes', [])

    # ── FACING A RAISE (call_amount > 0) ──
    if call_amount > 0 and 'call' in allowed_actions:
        # Estimate what kind of raise this is
        is_open_raise = call_amount <= bb_size * 4
        is_3bet = call_amount > bb_size * 4 and call_amount <= bb_size * 12
        is_4bet = call_amount > bb_size * 12

        if is_4bet:
            # Facing 4-bet: stack off QQ+/AKs, call AQ/TT/JJ, fold rest
            if is_4bet_stack_off_hand(hole):
                return ('raise', stack, f"5-bet jam - {key} vs 4-bet", eq)
            # AQs/TT/JJ: call 4-bet, don't nit-fold
            if key in ('AQs', 'AQo', 'TT', 'JJ', '99') and eq >= 0.55:
                return ('call', call_amount, f"call 4-bet - {key}, {eq*100:.0f}% eq", eq)
            if should_fold_to_5bet(hole):
                if 'fold' in allowed_actions:
                    return ('fold', 0, f"fold to 4-bet - {key} can't stand the heat", eq)
            # Mixed: hands with 60%+ eq can call
            if eq >= 0.60:
                return ('call', call_amount, f"call 4-bet - {key}, {eq*100:.0f}% eq", eq)
            if 'fold' in allowed_actions:
                return ('fold', 0, f"fold to 4-bet - {key}", eq)

        if is_3bet:
            # Facing 3-bet: 4-bet premiums, call playable, fold trash
            if is_4bet_stack_off_hand(hole):
                four_amt = four_bet_size(call_amount, stack)
                return ('raise', four_amt, f"4-bet - {key} vs 3-bet", eq)
            # AQs/AKo: call IP, small 3-bet OOP
            if key in ('AQs', 'AQo', 'AKs', 'AKo'):
                if in_position:
                    return ('call', call_amount, f"call 3-bet IP - {key}, {eq*100:.0f}% eq", eq)
                elif call_amount <= stack * 0.15:
                    return ('call', call_amount, f"call 3-bet small - {key}, {eq*100:.0f}% eq", eq)
                # OOP vs large 3-bet: still call with AQ+, don't nit-fold
                return ('call', call_amount, f"call 3-bet - {key}, {eq*100:.0f}% eq", eq)
            if should_fold_to_5bet(hole) and eq >= 0.62:
                # QQ/JJ: always call 3-bet, don't fold
                if in_position:
                    return ('call', call_amount, f"call 3-bet IP - {key}, {eq*100:.0f}% eq", eq)
                else:
                    if call_amount <= stack * 0.20:
                        return ('call', call_amount, f"call 3-bet - {key}, small sizing", eq)
                    return ('call', call_amount, f"call 3-bet OOP - {key}, {eq*100:.0f}% eq", eq)
            if tier in ('playable',) and in_position and call_amount <= pot * 0.3:
                return ('call', call_amount, f"call 3-bet - {key}, IP with decent hand", eq)
            if 'fold' in allowed_actions:
                return ('fold', 0, f"fold to 3-bet - {key}, {eq*100:.0f}% eq", eq)

        # Facing open raise (standard)
        if tier == 'premium':
            # 3-bet all premiums
            three_amt = three_bet_size(call_amount, in_position, pot)
            three_amt = min(three_amt, stack)
            return ('raise', three_amt, f"3-bet - {key}, premium", eq)

        if tier == 'strong':
            if is_value_3bet_hand(hole):
                three_amt = three_bet_size(call_amount, in_position, pot)
                return ('raise', three_amt, f"3-bet value - {key}", eq)
            # JJ/TT vs tight opponent: call to keep dominated hands in
            if opponent_style in ('Nit', 'Weak-Tight'):
                return ('call', call_amount, f"flat vs {opponent_style} - {key}", eq)
            return ('call', call_amount, f"call - {key}, {eq*100:.0f}% eq", eq)

        if tier == 'playable':
            # Vs Nit: fold to their raises (they have it)
            if 'fold_to_raises' in exploit_notes:
                if 'fold' in allowed_actions:
                    return ('fold', 0, f"fold - {key}, vs {opponent_style} (they have it)", eq)
            # Speculative call IP if cheap
            if in_position and call_amount <= pot * 0.15:
                return ('call', call_amount, f"speculative call IP - {key}", eq)
            if 'fold' in allowed_actions:
                return ('fold', 0, f"fold - {key}, {eq*100:.0f}% eq", eq)

        # Speculative: only very cheap calls IP
        if tier == 'speculative' and in_position and call_amount <= bb_size * 2:
            return ('call', call_amount, f"cheap speculative - {key}", eq)

        if 'fold' in allowed_actions:
            return ('fold', 0, f"preflop fold - {key}, {eq*100:.0f}% eq", eq)

    # ── OPENING (no raise facing us) ──
    if 'bet' in allowed_actions:
        # ICM tightness: on bubble with medium stack, only open premiums
        if on_bubble and icm_factor > 1.15:
            if tier not in ('premium', 'strong'):
                if 'check' in allowed_actions:
                    return ('check', 0, f"bubble fold - {key}, too risky", eq)
                return ('fold', 0, f"bubble fold - {key}", eq)

        # Premium/Strong: always open/raise
        if tier in ('premium', 'strong'):
            open_size = max(int(bb_size * (3 if in_position else 4)), int(pot * 0.75))
            open_size = min(open_size, stack)
            return ('bet', open_size, f"open - {key}, {tier}", eq)

        # Playable: open in late position, sometimes middle
        if tier == 'playable':
            if position >= 2:  # CO+
                open_size = int(bb_size * (2.5 if in_position else 3))
                open_size = min(open_size, stack)
                return ('bet', open_size, f"open - {key}, late position", eq)
            # Early/mid position: only open best playable hands
            if eq >= 0.58:
                open_size = int(bb_size * 3)
                return ('bet', min(open_size, stack), f"open EP - {key}, {eq*100:.0f}% eq", eq)
            if 'check' in allowed_actions:
                return ('check', 0, f"check - {key}, not strong enough to open", eq)

        # Bluff 3-bet opportunities
        if is_bluff_3bet_hand(hole, position) and 'never_bluff' not in exploit_notes:
            if position >= 2 and random.random() < 0.15 * agg_factor:  # 15% frequency
                open_size = int(bb_size * 3)
                return ('bet', min(open_size, stack), f"bluff open - {key} from late", eq)

        # Steal from late position vs tight opponents
        if 'steal_more_late' in exploit_notes and position >= 3:
            if random.random() < 0.30 * agg_factor:  # 30% steal vs Nit/Weak-Tight
                steal_size = int(bb_size * 2.5)
                return ('bet', min(steal_size, stack), f"steal - {key} vs {opponent_style}", eq)

        # Speculative: very rarely open from late
        if tier == 'speculative' and position >= 3 and random.random() < 0.05:
            open_size = int(bb_size * 2.5)
            return ('bet', min(open_size, stack), f"speculative open - {key}, BTN", eq)

        if 'check' in allowed_actions:
            return ('check', 0, f"check - {key}, out of range", eq)

    if 'check' in allowed_actions:
        return ('check', 0, f"check - {key}", eq)

    return ('fold', 0, f"preflop fold - {key}", eq)
