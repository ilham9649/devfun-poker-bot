#!/usr/bin/env python3
"""Test suite for pokerbot.quant — tournament readiness validation.
Tests: preflop classification, push/fold, equity, postflop, opponents, ICM, 3-bet/4-bet."""

import sys
import os
import traceback

# Add the repo root (parent of tests/) to sys.path so `from pokerbot.quant`
# resolves whether run via `python3 tests/test_quant.py` or a test runner.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pokerbot.quant import (
    # Card utils
    preflop_hand_key, card_rank, card_suit, make_deck,
    # Equity
    preflop_equity, monte_carlo_equity, PREFLOP_EQ_VS_1,
    # Hand eval
    evaluate_hand, compare_hands,
    # Push/fold
    get_push_fold_bb_threshold, is_push_fold_hand,
    # Decision engine
    quant_decision,
    # Tournament
    tournament_phase, is_near_bubble, icm_tighten_factor,
    effective_bb_over_time, aggression_from_blinds,
    # Hand tiers
    hand_tier, is_premium_hand, is_value_3bet_hand,
    is_bluff_3bet_hand, is_4bet_stack_off_hand, should_fold_to_5bet,
    # 3-bet sizing
    three_bet_size, four_bet_size,
    # Opponent exploitation
    classify_from_stats, exploitation_adjustment, get_fold_equity,
    # Postflop
    classify_board_texture, estimate_draw_equity,
    is_scare_card, postflop_decision,
    # Pot odds
    pot_odds, should_call, ev_of_action,
)

# ── Test Framework ──
passed = 0
failed = 0
errors = []

def test(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        msg = f"  ❌ {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)
        errors.append((name, detail))

def test_approx(name, actual, expected, tolerance=0.05, detail=""):
    """Test that actual is within tolerance of expected."""
    ok = abs(actual - expected) <= tolerance
    test(name, ok, f"expected ~{expected}, got {actual}" if not ok else detail)

def test_in(name, value, collection, detail=""):
    test(name, value in collection, f"{value} not in {collection}" + (f" — {detail}" if detail else ""))

# ────────────────────────────────────────────────────────
# TEST GROUP 1: Preflop Hand Classification
# ────────────────────────────────────────────────────────
print("\n📋 TEST GROUP 1: Preflop Hand Classification")
print("=" * 55)

# Pair detection
test("AA is a pair", preflop_hand_key(['Ah', 'As']) == 'AA')
test("KK is a pair", preflop_hand_key(['Kh', 'Ks']) == 'KK')
test("22 is a pair", preflop_hand_key(['2h', '2s']) == '22')

# Suited detection
test("AKs is suited", preflop_hand_key(['Ah', 'Kh']) == 'AKs')
test("AKo is offsuit", preflop_hand_key(['Ah', 'Kd']) == 'AKo')

# Correct ordering (high card first)
test("KA maps to AK", preflop_hand_key(['Kh', 'Ah']) == 'AKs')
test("QK maps to KQ", preflop_hand_key(['Qh', 'Kh']) == 'KQs')

# Range inclusion
test("AA in preflop table", 'AA' in PREFLOP_EQ_VS_1)
test("72o in preflop table", '72o' in PREFLOP_EQ_VS_1)
test("AKs in preflop table", 'AKs' in PREFLOP_EQ_VS_1)

# Hand tiers
test("AA is premium", hand_tier(['Ah', 'As']) == 'premium')
test("KK is premium", hand_tier(['Kh', 'Ks']) == 'premium')
test("QQ is premium", hand_tier(['Qh', 'Qs']) == 'premium')
test("JJ is strong", hand_tier(['Jh', 'Js']) == 'strong', f"got {hand_tier(['Jh', 'Js'])}")
test("TT is strong", hand_tier(['Th', 'Ts']) == 'strong', f"got {hand_tier(['Th', 'Ts'])}")
test("AKs is strong", hand_tier(['Ah', 'Kh']) == 'strong')
test("AKo is strong", hand_tier(['Ah', 'Kd']) == 'strong')
test("99 is strong (0.72 eq)", hand_tier(['9h', '9s']) == 'strong', f"got {hand_tier(['9h', '9s'])}")
test("AQo is playable", hand_tier(['Ah', 'Qd']) == 'playable', f"got {hand_tier(['Ah', 'Qd'])}")
test("76s is speculative", hand_tier(['7h', '6h']) == 'speculative')
test("72o is trash", hand_tier(['7h', '2d']) == 'trash')
test("32o is trash", hand_tier(['3h', '2d']) == 'trash')

# Premium detection
test("AA is premium hand", is_premium_hand(['Ah', 'As']))
test("KK is premium hand", is_premium_hand(['Kh', 'Ks']))
test("QQ is premium hand", is_premium_hand(['Qh', 'Qs']))
test("AKs is premium hand", is_premium_hand(['Ah', 'Ks']))
test("JJ is NOT premium hand", not is_premium_hand(['Jh', 'Js']))
test("AKo is premium hand (3-bet range)", is_premium_hand(['Ah', 'Kd']))

# ────────────────────────────────────────────────────────
# TEST GROUP 2: Push/Fold Decisions
# ────────────────────────────────────────────────────────
print("\n📋 TEST GROUP 2: Push/Fold Decisions")
print("=" * 55)

# BB thresholds
test("5BB → threshold 5", get_push_fold_bb_threshold(10, 2) == 5)
test("10BB → threshold 10", get_push_fold_bb_threshold(20, 2) == 10)
test("15BB → threshold 15", get_push_fold_bb_threshold(30, 2) == 15)
test("20BB → threshold 20", get_push_fold_bb_threshold(40, 2) == 20)
test("40BB → threshold 20", get_push_fold_bb_threshold(80, 2) == 20)

# Push/fold at 5BB
test("5BB: AA is push", is_push_fold_hand(['Ah', 'As'], 0, 5))
test("5BB: AKs is push", is_push_fold_hand(['Ah', 'Ks'], 0, 5))
test("5BB: 72o is NOT push", not is_push_fold_hand(['7h', '2d'], 0, 5))

# Push/fold at 10BB
test("10BB: AA is push", is_push_fold_hand(['Ah', 'As'], 0, 10))
test("10BB: AKs is push", is_push_fold_hand(['Ah', 'Ks'], 0, 10))
test("10BB: JTo is NOT push UTG", not is_push_fold_hand(['Jh', 'Td'], 0, 10))

# Push/fold at 15BB
test("15BB: AA is push", is_push_fold_hand(['Ah', 'As'], 0, 15))
test("15BB: AKs is push", is_push_fold_hand(['Ah', 'Ks'], 0, 15))
test("15BB: 72o is NOT push", not is_push_fold_hand(['7h', '2d'], 0, 15))

# Push/fold at 20BB: normal play (no push)
test("20BB: AA is NOT push (normal play)", not is_push_fold_hand(['Ah', 'As'], 0, 20))

# BTN is widest
test("5BB BTN: 32s is push", is_push_fold_hand(['3h', '2h'], 3, 5))
test("5BB UTG: 32s is NOT push", not is_push_fold_hand(['3h', '2h'], 0, 5))

# quant_decision push/fold at various stack depths
action5, _, msg5, _ = quant_decision(['Ah', 'As'], [], ['fold', 'raise'], 0, 10, 0, 0, 2, 'Preflop', 'unknown', 2, 3)
test("5BB AA quant → raise", action5 == 'raise', f"got {action5}: {msg5}")

action10, _, msg10, _ = quant_decision(['7h', '2d'], [], ['fold', 'check', 'raise'], 0, 20, 0, 0, 2, 'Preflop', 'unknown', 2, 3)
test("10BB 72o quant → fold/check", action10 in ('fold', 'check'), f"got {action10}: {msg10}")

action15, _, msg15, _ = quant_decision(['Ah', 'Ks'], [], ['fold', 'check', 'raise'], 0, 30, 0, 0, 2, 'Preflop', 'unknown', 2, 3)
test("15BB AKs quant → raise", action15 == 'raise', f"got {action15}: {msg15}")

action20, _, msg20, _ = quant_decision(['Ah', 'Ks'], [], ['fold', 'check', 'bet', 'raise'], 0, 40, 0, 0, 2, 'Preflop', 'unknown', 2, 3)
test("20BB AKs quant → bet or raise (not push)", action20 in ('bet', 'raise'), f"got {action20}: {msg20}")

# ────────────────────────────────────────────────────────
# TEST GROUP 3: Preflop Equity Accuracy
# ────────────────────────────────────────────────────────
print("\n📋 TEST GROUP 3: Preflop Equity Accuracy")
print("=" * 55)

# Known equities vs 1 opponent
test_approx("AA equity ~85%", preflop_equity(['Ah', 'As'], 1), 0.852, 0.02)
test_approx("KK equity ~82%", preflop_equity(['Kh', 'Ks'], 1), 0.824, 0.02)
test_approx("72o equity ~40%", preflop_equity(['7h', '2d'], 1), 0.401, 0.05)
test_approx("AKs equity ~67%", preflop_equity(['Ah', 'Ks'], 1), 0.670, 0.02)

# Multi-opponent scaling
eq1 = preflop_equity(['Ah', 'As'], 1)
eq2 = preflop_equity(['Ah', 'As'], 2)
eq3 = preflop_equity(['Ah', 'As'], 3)
test("AA equity drops with more opponents", eq1 > eq2 > eq3, f"1:{eq1:.3f} 2:{eq2:.3f} 3:{eq3:.3f}")

# Bottom of range
eq_72o = preflop_equity(['7h', '2d'], 1)
test("72o has equity > 0.35", eq_72o > 0.35, f"got {eq_72o:.3f}")
test("72o has equity < 0.45", eq_72o < 0.45, f"got {eq_72o:.3f}")

# 32o is the worst
eq_32o = preflop_equity(['3h', '2d'], 1)
test("32o equity < 72o", eq_32o < eq_72o, f"32o:{eq_32o:.3f} 72o:{eq_72o:.3f}")

# ────────────────────────────────────────────────────────
# TEST GROUP 4: Postflop Decision Logic
# ────────────────────────────────────────────────────────
print("\n📋 TEST GROUP 4: Postflop Decision Logic")
print("=" * 55)

# Strong hand on board → should bet/raise
# AA with A on board = strong
action_pf, _, msg_pf, _ = postflop_decision(
    ['Ah', 'As'], ['Kh', '7d', '2c'], ['fold', 'check', 'bet'],
    pot=100, stack=500, call_amount=0, num_opponents=1,
    street='Flop', opponent_style='unknown', raised_preflop=True, in_position=True,
    prev_action_on_prior_street='check', prev_equity=0
)
test("Strong hand (AA on AK7) → bet", action_pf in ('bet', 'raise'), f"got {action_pf}: {msg_pf}")

# Weak hand on board → should check or fold
action_weak, _, msg_weak, _ = postflop_decision(
    ['7h', '2d'], ['Ah', 'Kd', 'Qc'], ['fold', 'check', 'bet'],
    pot=100, stack=500, call_amount=0, num_opponents=1,
    street='Flop', opponent_style='unknown', raised_preflop=False, in_position=True,
    prev_action_on_prior_street='check', prev_equity=0
)
test("Weak hand (72 on AKQ) → check", action_weak == 'check', f"got {action_weak}: {msg_weak}")

# Draw → should call (not fold) when facing small bet
# Draw test: use a hand that won't randomly hit high
# Flush draw: board has exactly 2 of our suit, low cards (no overcard equity)
action_draw, _, msg_draw, _ = postflop_decision(
    ['6h', '5h'], ['Ah', 'Kd', '7h'], ['fold', 'call', 'raise'],
    pot=100, stack=500, call_amount=20, num_opponents=1,
    street='Flop', opponent_style='unknown', raised_preflop=False, in_position=True,
    prev_action_on_prior_street='check', prev_equity=0
)
test("Flush draw facing small bet → call", action_draw == 'call', f"got {action_draw}: {msg_draw}")

# Facing big bet with nothing → fold
action_fold, _, msg_fold, _ = postflop_decision(
    ['7h', '2d'], ['Ah', 'Kd', 'Qc'], ['fold', 'call'],
    pot=100, stack=500, call_amount=100, num_opponents=1,
    street='Flop', opponent_style='unknown', raised_preflop=False, in_position=True,
    prev_action_on_prior_street='check', prev_equity=0
)
test("Nothing vs pot bet → fold", action_fold == 'fold', f"got {action_fold}: {msg_fold}")

# River value bet → strong hand bets
action_river, _, msg_river, _ = postflop_decision(
    ['Ah', 'As'], ['Kh', '7d', '2c', 'Tc', '3h'], ['fold', 'check', 'bet'],
    pot=200, stack=500, call_amount=0, num_opponents=1,
    street='River', opponent_style='unknown', raised_preflop=True, in_position=True,
    prev_action_on_prior_street='bet', prev_equity=0.8
)
test("River strong hand → bet", action_river == 'bet', f"got {action_river}: {msg_river}")

# River weak hand → check behind
action_river_chk, _, msg_river_chk, _ = postflop_decision(
    ['7h', '2d'], ['Ah', 'Kd', 'Qc', 'Tc', '3h'], ['fold', 'check', 'bet'],
    pot=200, stack=500, call_amount=0, num_opponents=1,
    street='River', opponent_style='unknown', raised_preflop=False, in_position=True,
    prev_action_on_prior_street='check', prev_equity=0.2
)
test("River weak hand → check", action_river_chk == 'check', f"got {action_river_chk}: {msg_river_chk}")

# ────────────────────────────────────────────────────────
# TEST GROUP 5: Opponent Exploitation
# ────────────────────────────────────────────────────────
print("\n📋 TEST GROUP 5: Opponent Exploitation")
print("=" * 55)

# classify_from_stats
test("Low VPIP+low AF → Nit", classify_from_stats(15, 8, 1.5) == 'Nit')
test("Low VPIP+high AF → TAG", classify_from_stats(20, 16, 3.0) == 'TAG')
test("Low VPIP+low PFR → Weak-Tight", classify_from_stats(18, 10, 1.8) == 'Weak-Tight')
test("High VPIP+high AF → LAG", classify_from_stats(35, 28, 3.5) == 'LAG')
test("High VPIP+low AF → Station", classify_from_stats(45, 10, 1.0) == 'Station')
test("Zero VPIP → unknown", classify_from_stats(0, 0, 0) == 'unknown')

# Exploitation adjustments
exp_nit = exploitation_adjustment('Nit', 'playable', True)
test("vs Nit: fold_to_raises in notes", 'fold_to_raises' in exp_nit.get('notes', []))
test("vs Nit: bluff_dry_boards in notes", 'bluff_dry_boards' in exp_nit.get('notes', []))

exp_station = exploitation_adjustment('Station', 'playable', True)
test("vs Station: never_bluff in notes", 'never_bluff' in exp_station.get('notes', []))
test("vs Station: value_bet_thin in notes", 'value_bet_thin' in exp_station.get('notes', []))

exp_lag = exploitation_adjustment('LAG', 'playable', True)
test("vs LAG: widen_3bet_value in notes", 'widen_3bet_value' in exp_lag.get('notes', []))

exp_wt = exploitation_adjustment('Weak-Tight', 'playable', True)
test("vs Weak-Tight: raise_cbets in notes", 'raise_cbets' in exp_wt.get('notes', []))

# Fold equity varies by opponent
fe_nit = get_fold_equity('Nit', 'dry', True)
fe_station = get_fold_equity('Station', 'dry', True)
test("Fold equity: Nit > Station", fe_nit > fe_station, f"Nit:{fe_nit:.2f} Station:{fe_station:.2f}")

fe_dry = get_fold_equity('TAG', 'dry', True)
fe_wet = get_fold_equity('TAG', 'wet', True)
test("Fold equity: dry > wet (same opponent)", fe_dry >= fe_wet, f"dry:{fe_dry:.2f} wet:{fe_wet:.2f}")

# Tighter vs LAG: 3-bet range should be wider
# Premium hands still 3-bet vs anyone
test("3-bet value: QQ vs any", is_value_3bet_hand(['Qh', 'Qs']))
test("3-bet value: AA vs any", is_value_3bet_hand(['Ah', 'As']))
test("3-bet value: AKs vs any", is_value_3bet_hand(['Ah', 'Ks']))

# ────────────────────────────────────────────────────────
# TEST GROUP 6: Tournament ICM Logic
# ────────────────────────────────────────────────────────
print("\n📋 TEST GROUP 6: Tournament ICM Logic")
print("=" * 55)

# Tournament phases
test("Early phase", tournament_phase(100, 95, 0) == 'early')
test("Middle phase", tournament_phase(100, 60, 50) == 'middle')
test("Late phase", tournament_phase(100, 20, 200) == 'late')
test("Final table", tournament_phase(100, 4, 500) == 'final_table')

# Bubble detection
# 100 players, 15 paid → bubble at 16-17 players
test("Near bubble (100 players, 16 left)", is_near_bubble(100, 16))
test("Near bubble (100 players, 17 left)", is_near_bubble(100, 17))
test("NOT bubble (100 players, 20 left)", not is_near_bubble(100, 20))
test("NOT bubble (100 players, 15 left)", not is_near_bubble(100, 15))

# Bubble phase detection
test("Bubble phase detected", tournament_phase(100, 16, 50) == 'bubble')

# ICM tighten factor
# Medium stack (1x avg): should tighten
icm_medium = icm_tighten_factor(1000, 1000, 100, 16)
test("Medium stack ICM: tighten", icm_medium >= 1.1, f"got {icm_medium:.2f}")

# Big stack: play wider
icm_big = icm_tighten_factor(3000, 1000, 100, 16)
test("Big stack ICM: wider", icm_big < 1.0, f"got {icm_big:.2f}")

# Short stack: wider to gamble (test off-bubble to avoid bubble pressure override)
icm_short = icm_tighten_factor(400, 1000, 100, 80)
test("Short stack ICM: wider", icm_short <= 1.0, f"got {icm_short:.2f}")

# Bubble + medium stack: MUCH tighter
icm_bubble_mid = icm_tighten_factor(1000, 1000, 100, 16)
test("Bubble medium stack: very tight", icm_bubble_mid >= 1.2, f"got {icm_bubble_mid:.2f}")

# Bubble + big stack: abuse
icm_bubble_big = icm_tighten_factor(3000, 1000, 100, 16)
test("Bubble big stack: even wider", icm_bubble_big < 0.9, f"got {icm_bubble_big:.2f}")

# Effective BB
test("Effective BB", effective_bb_over_time(100, 2) == 50)
test("Effective BB large stack", effective_bb_over_time(1000, 2) == 500)

# Blind escalation aggression
test("5BB: high aggression", aggression_from_blinds(5, 2) > 1.0)
test("40BB: standard aggression", aggression_from_blinds(40, 2) <= 1.0)

# ────────────────────────────────────────────────────────
# TEST GROUP 7: 3-bet/4-bet Decisions
# ────────────────────────────────────────────────────────
print("\n📋 TEST GROUP 7: 3-bet/4-bet Decisions")
print("=" * 55)

# Premiums should 3-bet
test("AA 3-bet value", is_value_3bet_hand(['Ah', 'As']))
test("KK 3-bet value", is_value_3bet_hand(['Kh', 'Ks']))
test("QQ 3-bet value", is_value_3bet_hand(['Qh', 'Qs']))
test("AKs 3-bet value", is_value_3bet_hand(['Ah', 'Ks']))

# Speculative should NOT 3-bet for value
test("76s NOT 3-bet value", not is_value_3bet_hand(['7h', '6h']))

# Bluff 3-bet candidates
test("A5s bluff from BTN", is_bluff_3bet_hand(['Ah', '5h'], 3))
test("A2s bluff from CO", is_bluff_3bet_hand(['Ah', '2h'], 2))
test("A2s NOT bluff from UTG", not is_bluff_3bet_hand(['Ah', '2h'], 0))
test("76s bluff from BTN", is_bluff_3bet_hand(['7h', '6h'], 3))
test("76s NOT bluff from UTG", not is_bluff_3bet_hand(['7h', '6h'], 0))
test("72o NOT bluff", not is_bluff_3bet_hand(['7h', '2d'], 3))

# 4-bet stack-off hands
test("KK stack off", is_4bet_stack_off_hand(['Kh', 'Ks']))
test("AA stack off", is_4bet_stack_off_hand(['Ah', 'As']))
test("AKs stack off", is_4bet_stack_off_hand(['Ah', 'Ks']))
test("QQ NOT stack off", not is_4bet_stack_off_hand(['Qh', 'Qs']))
test("JJ NOT stack off", not is_4bet_stack_off_hand(['Jh', 'Js']))

# Should fold to 5-bet
test("QQ fold to 5-bet", should_fold_to_5bet(['Qh', 'Qs']))
test("JJ fold to 5-bet", should_fold_to_5bet(['Jh', 'Js']))
test("AKo fold to 5-bet", should_fold_to_5bet(['Ah', 'Kd']))
test("AA NOT fold to 5-bet", not should_fold_to_5bet(['Ah', 'As']))
test("KK NOT fold to 5-bet", not should_fold_to_5bet(['Kh', 'Ks']))

# Sizing
test("3-bet IP: 3x raise", three_bet_size(20, True, 30) == 60)
test("3-bet OOP: 4x raise", three_bet_size(20, False, 30) == 80)
test("3-bet min is pot", three_bet_size(5, True, 30) == 30)  # max(15, 30) = 30

four_bet = four_bet_size(60, 500)
test("4-bet: 2.5x 3-bet", four_bet == 150, f"got {four_bet}")

four_bet_jam = four_bet_size(100, 200)
test("4-bet: shove when >40% stack", four_bet_jam == 200, f"got {four_bet_jam}")

# quant_decision: premium hand facing raise → 3-bet
action_3bet, amt_3bet, msg_3bet, _ = quant_decision(
    ['Ah', 'As'], [], ['fold', 'call', 'raise'], 0, 500,
    call_amount=20, current_bet=20, num_opponents=2,
    street='Preflop', opponent_style='unknown', bb_size=2, position=3
)
test("AA facing raise → raise (3-bet)", action_3bet == 'raise', f"got {action_3bet}: {msg_3bet}")
test("3-bet amount > 0", amt_3bet > 0, f"got {amt_3bet}")

# Trash hand facing raise → fold
action_fold_pf, _, msg_fold_pf, _ = quant_decision(
    ['7h', '2d'], [], ['fold', 'call'], 0, 500,
    call_amount=20, current_bet=20, num_opponents=2,
    street='Preflop', opponent_style='unknown', bb_size=2, position=3
)
test("72o facing raise → fold", action_fold_pf == 'fold', f"got {action_fold_pf}: {msg_fold_pf}")

# ────────────────────────────────────────────────────────
# TEST GROUP 8: Board Texture & Scare Cards
# ────────────────────────────────────────────────────────
print("\n📋 TEST GROUP 8: Board Texture & Scare Cards")
print("=" * 55)

test("Dry board", classify_board_texture(['Kh', '7d', '2c']) == 'dry')
test("Wet board (flush draw)", classify_board_texture(['Ah', 'Kh', '7h']) == 'wet')
test("Paired board", classify_board_texture(['Kh', 'Kd', '7c']) == 'paired')
test("Ace high board", classify_board_texture(['Ah', 'Kd', '7c']) == 'ace_high')
test("Preflop (empty)", classify_board_texture([]) == 'preflop')

# Scare cards
test("Ace is scare card", is_scare_card('Ah', ['Kh', '7d', '2c']))
test("King is scare card", is_scare_card('Kh', ['7d', '2c', '3h']))
test("Flush-completing card is scare", is_scare_card('3h', ['Ah', 'Kh', '7h', '2c']))
test("Low card on low board NOT scare", not is_scare_card('3c', ['7d', '2h']))

# Draw equity estimation
draw_eq_flush = estimate_draw_equity(['Ah', '2h'], ['Kh', '9h', '3d'], 1)
test("Flush draw has draw equity", draw_eq_flush > 0, f"got {draw_eq_flush:.3f}")

# ────────────────────────────────────────────────────────
# TEST GROUP 9: Hand Evaluation
# ────────────────────────────────────────────────────────
print("\n📋 TEST GROUP 9: Hand Evaluation")
print("=" * 55)

# Pair
s, t, d = evaluate_hand(['Ah', 'As'], ['Kh', '7d', '2c', 'Tc', '3h'])
test("AA = one pair (pair on board? no) → actually pair of aces", s == 1 and t == 'one_pair', f"got {t}")

# Two pair
s2, t2, _ = evaluate_hand(['Ah', 'Ks'], ['Kh', '7d', '2c', 'Tc', 'Ad'])
test("AK on AK board = two pair", s2 == 2 and t2 == 'two_pair', f"got {t2}")

# Trips
s3, t3, _ = evaluate_hand(['Ah', 'As'], ['Ah', 'Kd', '7c', 'Tc', '3h'])
test("AA on Axx = trips", s3 == 3 and t3 == 'trips', f"got {t3}")

# Compare hands
result = compare_hands(8, [14], 7, [14])
test("Straight flush > quads", result == 1)

result2 = compare_hands(1, [14, 13, 12], 1, [14, 13, 11])
test("Pair of AK > pair of AKQ lower kicker", result2 == 1)

# ────────────────────────────────────────────────────────
# TEST GROUP 10: Backward Compatibility
# ────────────────────────────────────────────────────────
print("\n📋 TEST GROUP 10: Backward Compatibility")
print("=" * 55)

# quant_decision must work with original signature (no new params)
action_compat, amt_compat, msg_compat, conf_compat = quant_decision(
    ['Ah', 'As'], [], ['fold', 'check', 'bet', 'raise'], 100, 500,
    call_amount=0, current_bet=0, num_opponents=2, street='Preflop',
    opponent_style='unknown', bb_size=2, position=3
)
test("Original signature still works", action_compat in ('bet', 'raise'), f"got {action_compat}: {msg_compat}")
test("Returns 4-tuple", len((action_compat, amt_compat, msg_compat, conf_compat)) == 4)

# Empty hole cards → check/fold gracefully
action_empty, _, _, _ = quant_decision(
    [], [], ['fold', 'check'], 100, 500, 0, 0, 2, 'Flop', 'unknown', 2, 3
)
test("Empty hole cards → check", action_empty in ('check', 'fold'), f"got {action_empty}")

# ────────────────────────────────────────────────────────
# SUMMARY
# ────────────────────────────────────────────────────────
print("\n" + "=" * 55)
print(f"📊 TEST SUMMARY: {passed} passed, {failed} failed, {passed + failed} total")
print("=" * 55)

if errors:
    print("\n❌ FAILURES:")
    for name, detail in errors:
        print(f"  • {name}" + (f" — {detail}" if detail else ""))

sys.exit(0 if failed == 0 else 1)
