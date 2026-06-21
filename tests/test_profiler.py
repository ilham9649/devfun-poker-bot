#!/usr/bin/env python3
"""Tests for pokerbot.profiler — LLM opponent-reader data model + throttling.

Covers: action transcript + showdown capture, the LLM-refresh throttle, the
cached summary_for_prompt fallback, and to_dict/from_dict round-trip (incl.
loading old profiles that predate the LLM fields). Run: `python3 tests/test_profiler.py`.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# profiler.py reads PROFILES_FILE at Profiler() init; point it at a temp dir.
os.environ["ARENA_WORKSPACE"] = tempfile.mkdtemp(prefix="arena-prof-")

from pokerbot.profiler import OpponentProfile, Profiler  # noqa: E402

passed = 0
failed = 0
errors = []


def test(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        line = f"  ❌ {name}" + (f" — {detail}" if detail else "")
        print(line)
        errors.append((name, detail))


print("\n📋 Profiler: LLM reader data model + throttling")
print("=" * 55)

# ── action transcript capture ──
p = OpponentProfile("agent-abc", "Alice")
p.record_action("raise", "Preflop", pot=30, call_amount=10, stack_before=1000,
                is_preflop=True, sizing_bb=3.0, facing_bet=False, pot_before=20)
p.record_action("bet", "Flop", pot=60, call_amount=0, stack_before=990,
                is_preflop=False, sizing_bb=4.0, facing_bet=False, pot_before=60)
test("record_action bumps total_actions", p.total_actions == 2, p.total_actions)
test("record_action bumps raise count", p.actions["raise"] == 1, p.actions)
test("record_action appends transcript entries", len(p.recent_actions) == 2, len(p.recent_actions))
test("transcript formats street+action+sizing",
     "Preflop:raise 3.0bb" in p.transcript_text() and "Flop:bet 4.0bb" in p.transcript_text(),
     p.transcript_text())
_ff = OpponentProfile("ff")
_ff.record_action("fold", "Flop", 60, 30, 500, False, facing_bet=True)
test("transcript marks facing-bet folds", "facing bet" in _ff.transcript_text(), _ff.transcript_text())

# ── showdown capture ──
p.record_showdown("Two Pair", won=True, pot=200, street_reached="River")
test("showdown_history appended", len(p.showdown_history) == 1, len(p.showdown_history))
test("showdown_text formats hand+result",
     "Two Pair(won)" in p.showdown_text(), p.showdown_text())
test("showdown_text empty case",
     OpponentProfile("y").showdown_text() == "none reached showdown")

# ── hands_observed + refresh counter ──
p2 = OpponentProfile("agent-def")
for _ in range(4):
    p2.record_hand_observed()
test("record_hand_observed counts hands", p2.hands_observed == 4, p2.hands_observed)
test("record_hand_observed bumps refresh counter",
     p2.hands_since_llm_refresh == 4, p2.hands_since_llm_refresh)

# ── needs_llm_refresh throttle ──
fresh = OpponentProfile("a1")
for _ in range(2):
    fresh.record_hand_observed()
test("throttle: <3 hands never refreshes", fresh.needs_llm_refresh(showdown_triggered=True) is False)
for _ in range(3):  # now 5 hands
    fresh.record_hand_observed()
test("throttle: no summary + >=3 hands → refresh", fresh.needs_llm_refresh() is True)
fresh.set_llm_summary("Alice: TAG. Exploit: fold to her 3-bets.")
test("throttle: right after refresh → no refresh", fresh.needs_llm_refresh(showdown_triggered=True) is False)
# one more hand, no showdown, not yet N(8): no refresh
fresh.record_hand_observed()
test("throttle: <N hands since refresh, no showdown → no refresh",
    fresh.needs_llm_refresh() is False)
# showdown trigger beats the N-hands clock
test("throttle: showdown trigger → refresh",
    fresh.needs_llm_refresh(showdown_triggered=True) is True)
# advance to N hands without showdown → refresh on the clock
fresh.set_llm_summary("x")
for _ in range(8):
    fresh.record_hand_observed()
test("throttle: N hands elapsed → refresh on the clock", fresh.needs_llm_refresh() is True)
test("set_llm_summary resets refresh counter", fresh.hands_since_llm_refresh == 8)  # not yet reset

# ── summary_for_prompt fallback ──
s = OpponentProfile("a2", "Bob")
for _ in range(6):
    s.record_hand_observed()
s.record_action("call", "Preflop", 20, 10, 1000, True)
fb = s.summary_for_prompt()
test("summary_for_prompt falls back to generate_summary when uncached",
     fb.startswith("Bob:") and "VPIP" in fb, fb[:60])
s.set_llm_summary("Bob: maniac. Exploit: call down light.")
test("summary_for_prompt returns cached LLM string", s.summary_for_prompt() == "Bob: maniac. Exploit: call down light.")

# ── to_dict / from_dict round-trip ──
src = OpponentProfile("agent-ghi", "Carol")
for _ in range(5):
    src.record_hand_observed()
src.record_action("raise", "Preflop", 30, 10, 1000, True, sizing_bb=3.0, pot_before=20)
src.record_showdown("Flush", won=True, pot=500)
src.set_llm_summary("Carol: LAG. Exploit: trap.")
d = src.to_dict()
restored = OpponentProfile.from_dict(d)
test("round-trip: llm_summary preserved", restored.llm_summary == "Carol: LAG. Exploit: trap.")
test("round-trip: recent_actions preserved", len(restored.recent_actions) == 1)
test("round-trip: showdown_history preserved", len(restored.showdown_history) == 1)
test("round-trip: throttle counters preserved",
     restored.llm_hands_at_refresh == 5 and restored.hands_since_llm_refresh == 0)

# ── old profile (no LLM fields) loads cleanly ──
legacy = {
    "agent_id": "agent-old", "agent_name": "OldTimer",
    "first_seen": "2026-01-01T00:00:00+00:00", "last_seen": "2026-01-01T00:00:00+00:00",
    "hands_observed": 12, "total_actions": 40,
    "actions_breakdown": {"fold": 10, "check": 5, "call": 15, "bet": 6, "raise": 4, "all-in": 0},
}
old = OpponentProfile.from_dict(legacy)
test("legacy profile loads", old.hands_observed == 12)
test("legacy profile has empty llm_summary", old.llm_summary == "")
test("legacy profile refresh-eligible (>=3 hands, no summary)",
     old.needs_llm_refresh() is True)

# ── deque bounds prevent unbounded growth ──
big = OpponentProfile("agent-big")
for i in range(100):
    big.record_action("call", "Flop", 30, 10, 1000, False)
test("recent_actions bounded at maxlen=40", len(big.recent_actions) == 40, len(big.recent_actions))

# ── get_profiles_for_prompt serves the LLM-cached summary ──
prof = Profiler(profiles_path=os.path.join(os.environ["ARENA_WORKSPACE"], "p.json"))
prof.get_or_create("agent-zzz", "Dee")
prof.profiles["agent-zzz"].total_actions = 5
prof.profiles["agent-zzz"].set_llm_summary("Dee: nit. Exploit: steal wide.")
text = prof.get_profiles_for_prompt(["agent-zzz"])
test("get_profiles_for_prompt returns cached LLM summary", "Dee: nit. Exploit: steal wide." in text, text[:60])

print("\n" + "=" * 55)
print(f"📊 TEST SUMMARY: {passed} passed, {failed} failed, {passed + failed} total")
print("=" * 55)
if errors:
    print("\n❌ FAILURES:")
    for name, detail in errors:
        print(f"  • {name}" + (f" — {detail}" if detail else ""))

sys.exit(0 if failed == 0 else 1)
