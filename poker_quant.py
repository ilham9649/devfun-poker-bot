"""
Poker Quant — equity calculator for DevFun bot.
Pre-flop: pre-computed hot/cold equity vs 1-5 random hands.
Post-flop: Monte Carlo simulation.
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
        # fold_eq portion: we win pot immediately
        # called portion: we realize our equity
        return fold_equity * pot + (1 - fold_equity) * (equity * (pot + amount) - (1 - equity) * amount)
    elif action == 'all-in':
        return equity * (pot + amount) - (1 - equity) * amount
    return 0

# ── Decision Engine ──
# ── Push/Fold Charts (≤20 BB) ──
# Hands to shove all-in pre-flop based on position and effective stacks
# Based on simplified Nash push/fold equilibrium
PUSH_FOLD_HANDS = {
    # BB threshold -> set of hand keys (pairs, suited, offsuit by high card)
    # Positions: 0=UTG, 1=HJ, 2=CO, 3=BTN, 4=SB, 5=BB
    # BB=20+: normal play
    15: {  # ≤15 BB: shove wide
        0: {'pairs': 5, 'high': ['AK','AQ','AJ','AT','KQ'], 'suited': ['AK','AQ','AJ','AT','A9','KQ','KJ','QJ','JT','T9','98','87']},
        1: {'pairs': 4, 'high': ['AK','AQ','AJ','AT','KQ','KJ'], 'suited': ['AK','AQ','AJ','AT','A9','A8','KQ','KJ','QJ','JT','T9','98','87','76']},
        2: {'pairs': 3, 'high': ['AK','AQ','AJ','AT','KQ','KJ','KT','QJ'], 'suited': ['AK','AQ','AJ','AT','A9','A8','A7','KQ','KJ','KT','QJ','QT','JT','T9','98','87','76','65']},
        3: {'pairs': 2, 'high': ['AK','AQ','AJ','AT','A9','KQ','KJ','KT','QJ','QT'], 'suited': ['AK','AQ','AJ','AT','A9','A8','A7','A6','A5','KQ','KJ','KT','K9','QJ','QT','Q9','JT','J9','T9','98','87','76','65','54']},
        4: {'pairs': 2, 'high': ['AK','AQ','AJ','AT','A9','KQ','KJ','KT','QJ'], 'suited': ['AK','AQ','AJ','AT','A9','A8','A7','KQ','KJ','KT','QJ','JT','T9','98','87']},
        5: {'pairs': 2, 'high': ['AK','AQ','AJ','AT','KQ'], 'suited': ['AK','AQ','AJ','AT','KQ','KJ','QJ']},
    },
    10: {  # ≤10 BB: shove very wide
        0: {'pairs': 4, 'high': ['AK','AQ','AJ','AT','KQ','KJ'], 'suited': ['AK','AQ','AJ','AT','A9','A8','KQ','KJ','QJ','JT','T9','98']},
        1: {'pairs': 3, 'high': ['AK','AQ','AJ','AT','KQ','KJ','KT'], 'suited': ['AK','AQ','AJ','AT','A9','A8','A7','KQ','KJ','KT','QJ','JT','T9','98','87']},
        2: {'pairs': 2, 'high': ['AK','AQ','AJ','AT','A9','KQ','KJ','KT','QJ','QT'], 'suited': ['AK','AQ','AJ','AT','A9','A8','A7','A6','KQ','KJ','KT','K9','QJ','QT','JT','J9','T9','98','87','76']},
        3: {'pairs': 2, 'high': ['AK','AQ','AJ','AT','A9','A8','KQ','KJ','KT','QJ','QT','Q9'], 'suited': ['AK','AQ','AJ','AT','A9','A8','A7','A6','A5','A4','KQ','KJ','KT','K9','QJ','QT','Q9','JT','J9','T9','T8','98','87','76','65','54']},
        4: {'pairs': 2, 'high': ['AK','AQ','AJ','AT','A9','KQ','KJ','KT'], 'suited': ['AK','AQ','AJ','AT','A9','A8','A7','KQ','KJ','KT','QJ','JT','T9','98','87']},
        5: {'pairs': 2, 'high': ['AK','AQ','AJ','AT','KQ','KJ'], 'suited': ['AK','AQ','AJ','AT','A9','KQ','KJ','QJ']},
    },
    5: {  # ≤5 BB: shove any reasonable hand
        0: {'pairs': 2, 'high': ['AK','AQ','AJ','AT','KQ','KJ','KT','QJ','JT'], 'suited': ['AK','AQ','AJ','AT','A9','A8','A7','KQ','KJ','KT','QJ','JT','T9','98']},
        1: {'pairs': 2, 'high': ['AK','AQ','AJ','AT','A9','KQ','KJ','KT','QJ','JT'], 'suited': ['AK','AQ','AJ','AT','A9','A8','A7','A6','KQ','KJ','KT','QJ','QT','JT','T9','98','87']},
        2: {'pairs': 2, 'high': ['AK','AQ','AJ','AT','A9','A8','KQ','KJ','KT','QJ','QT','JT'], 'suited': ['AK','AQ','AJ','AT','A9','A8','A7','A6','A5','KQ','KJ','KT','K9','QJ','QT','JT','J9','T9','98','87','76']},
        3: {'pairs': 2, 'high': ['AK','AQ','AJ','AT','A9','A8','A7','KQ','KJ','KT','QJ','QT','Q9','JT','J9'], 'suited': ['AK','AQ','AJ','AT','A9','A8','A7','A6','A5','A4','A3','KQ','KJ','KT','K9','QJ','QT','Q9','JT','J9','T9','T8','98','87','76','65','54','43']},
        4: {'pairs': 2, 'high': ['AK','AQ','AJ','AT','A9','KQ','KJ','KT'], 'suited': ['AK','AQ','AJ','AT','A9','A8','A7','KQ','KJ','KT','QJ','JT','T9','98']},
        5: {'pairs': 2, 'high': ['AK','AQ','AJ','AT','KQ','KJ'], 'suited': ['AK','AQ','AJ','AT','A9','KQ','KJ','QJ']},
    },
}

def get_push_fold_bb_threshold(stack, bb=2):
    """Get the effective BB threshold bracket."""
    bb_stack = stack / bb
    if bb_stack <= 5: return 5
    if bb_stack <= 10: return 10
    if bb_stack <= 15: return 15
    return 20  # normal play

def is_push_fold_hand(hole, position, bb_threshold):
    """Check if hand is in push/fold range."""
    if bb_threshold >= 20:
        return False
    chart = PUSH_FOLD_HANDS.get(bb_threshold)
    if not chart:
        return False
    pos_chart = chart.get(position, chart.get(0))  # fallback to UTG
    if not pos_chart:
        return False
    
    key = preflop_hand_key(hole)
    r1, r2 = key[0], key[1] if len(key) > 1 else ''
    is_suited = key.endswith('s')
    is_pair = r1 == r2
    
    # Check pairs
    min_pair = pos_chart.get('pairs', 10)
    if is_pair:
        # min_pair is the minimum pair rank number (2=deuces, 10=tens)
        pair_val = RANK_VAL.get(r1, 0)
        # pairs: 2 means any pair (22+), 5 means 55+, 10 means TT+
        if min_pair <= 2:
            return True  # any pair
        return pair_val >= min_pair
    
    # Check high cards (offsuit)
    high_list = pos_chart.get('high', [])
    if not is_suited and len(key) >= 2:
        for h in high_list:
            if key[:2] == h:
                return True
    
    # Check suited
    suited_list = pos_chart.get('suited', [])
    if is_suited and len(key) >= 2:
        for s in suited_list:
            if key[:2] == s:
                return True
    
    return False

def quant_decision(hole, board, allowed_actions, pot, stack, call_amount=0,
                   current_bet=0, num_opponents=2, street='preflop', opponent_style='unknown',
                   bb_size=2, position=3):
    """
    Quantitative poker decision.
    Returns (action, amount, message, confidence).
    """
    # ── PUSH/FOLD MODE (≤20 BB effective stack) ──
    bb_stack = stack / bb_size
    if bb_stack <= 20 and street in ('PreDeal', 'Preflop') and hole:
        bb_thresh = get_push_fold_bb_threshold(stack, bb_size)
        pos = min(position, 5)
        
        if bb_stack <= 5:
            # ≤5 BB: shove any hand with ≥35% equity
            eq = preflop_equity(hole, num_opponents)
            if eq >= 0.35:
                return ('raise', stack, f"PUSH/FOLD ≤5BB — {preflop_hand_key(hole)} {eq*100:.0f}% eq, shoving", eq)
            if 'check' in allowed_actions:
                return ('check', 0, f"PUSH/FOLD ≤5BB — checking {preflop_hand_key(hole)}", 0.2)
            return ('fold', 0, f"PUSH/FOLD ≤5BB — folding {preflop_hand_key(hole)}", 0.2)
        
        if is_push_fold_hand(hole, pos, bb_thresh):
            eq = preflop_equity(hole, num_opponents)
            return ('raise', stack, f"PUSH/FOLD {bb_stack:.0f}BB — {preflop_hand_key(hole)} {eq*100:.0f}% eq, shoving from pos {pos}", eq)
        
        # Not in shove range
        if call_amount == 0 and 'check' in allowed_actions:
            return ('check', 0, f"PUSH/FOLD {bb_stack:.0f}BB — {preflop_hand_key(hole)} not in range, checking", 0.3)
        return ('fold', 0, f"PUSH/FOLD {bb_stack:.0f}BB — {preflop_hand_key(hole)} not in shove range, folding", 0.3)
    
    # ── POST-FLOP PUSH/FOLD (≤10 BB) ──
    if bb_stack <= 10 and board and hole:
        eq = monte_carlo_equity(hole, board, num_opponents, num_sims=200)
        if eq >= 0.40 and ('bet' in allowed_actions or 'raise' in allowed_actions):
            return ('raise', stack, f"PUSH/FOLD {bb_stack:.0f}BB post — {eq*100:.0f}% eq, jamming", eq)
        if call_amount > 0 and eq >= 0.35:
            return ('call', call_amount, f"PUSH/FOLD {bb_stack:.0f}BB post — priced in {eq*100:.0f}%", eq)
        if 'check' in allowed_actions:
            return ('check', 0, f"PUSH/FOLD {bb_stack:.0f}BB post — checking {eq*100:.0f}%", eq)
        return ('fold', 0, f"PUSH/FOLD {bb_stack:.0f}BB post — folding {eq*100:.0f}%", eq)
    
    # ── NORMAL PLAY ──
    equity = 0
    if street in ('PreDeal', 'Preflop') and hole:
        equity = preflop_equity(hole, num_opponents)
    elif board:
        equity = monte_carlo_equity(hole, board, num_opponents, num_sims=300)
    else:
        equity = preflop_equity(hole, num_opponents)
    
    # Adjust equity and fold equity based on opponent style
    style_mult = {
        'Nit': 0.85, 'Station': 1.0, 'LAG': 0.95, 'Weak-Tight': 1.05, 'TAG': 1.0, 'unknown': 1.0,
    }
    fold_eq_map = {
        'Nit': 0.65, 'Station': 0.15, 'LAG': 0.30, 'Weak-Tight': 0.60, 'TAG': 0.40, 'unknown': 0.40,
    }
    equity *= style_mult.get(opponent_style, 1.0)
    equity = min(equity, 1.0)
    fold_equity = fold_eq_map.get(opponent_style, 0.40)
    
    evs = {}
    
    # Facing a bet/raise (need to call or raise)
    if call_amount > 0 and 'call' in allowed_actions:
        should, our_eq, odds = should_call(equity, call_amount, pot)
        
        # Minimum hand quality filter: fold trash regardless of pot odds
        # Pre-flop: only call with equity > 35% (better than 1 random) or pot odds < 15%
        if street in ('PreDeal', 'Preflop') and equity < 0.35 and odds > 0.15:
            if 'fold' in allowed_actions:
                return ('fold', 0, f"trash hand {equity*100:.0f}% eq — not defending", equity)
        
        if equity > 0.45:  # Strong
            if 'raise' in allowed_actions and equity > 0.55:
                raise_amt = min(int(pot * (0.8 + equity)), stack)
                evs['raise'] = ev_of_action('raise', raise_amt, equity, pot, stack)
                return ('raise', raise_amt, f"eq {equity*100:.0f}% > odds {odds*100:.0f}% — raising for value", equity)
            evs['call'] = ev_of_action('call', call_amount, equity, pot, stack)
            return ('call', call_amount, f"equity {equity*100:.0f}% covers {odds*100:.0f}% pot odds", equity)
        elif should:
            evs['call'] = ev_of_action('call', call_amount, equity, pot, stack)
            return ('call', call_amount, f"priced in — {equity*100:.0f}% eq at {odds*100:.0f}% odds", equity)
        else:
            if 'fold' in allowed_actions:
                return ('fold', 0, f"not getting the price — {equity*100:.0f}% eq vs {odds*100:.0f}% needed", equity)
            return ('call', call_amount, f"pot odds: {odds*100:.0f}%", equity)
    
    # Initiative — we can bet
    if 'bet' in allowed_actions:
        if equity > 0.50:
            bet_pct = 0.55 + (equity - 0.5) * 1.2  # 55-110% pot
            bet_size = max(int(pot * bet_pct), int(pot * 0.5))
            return ('bet', bet_size, f"value bet {equity*100:.0f}% equity", equity)
        elif equity > 0.35 and street in ('PreDeal', 'Preflop', 'Flop'):
            # C-bet with moderate equity
            bet_size = int(pot * 0.5)
            return ('bet', bet_size, f"continuation — {equity*100:.0f}% equity", equity)
        elif 'check' in allowed_actions:
            return ('check', 0, f"checking behind — {equity*100:.0f}% equity", equity)
    
    if 'check' in allowed_actions:
        return ('check', 0, f"taking equity realization — {equity*100:.0f}%", equity)
    
    return ('fold', 0, f"no profitable action at {equity*100:.0f}% equity", equity)
