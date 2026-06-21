#!/usr/bin/env python3
"""Tests for pokerbot.player.llm_opponent_summary — the LLM opponent reader.

Mocks _call_gemini so no network is used. Covers: no-key short-circuit, happy
path rendering, JSON schema validation (empty tendencies → None), parse failure,
and prompt contents. Run: `python3 tests/test_opponent_reader.py`.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["ARENA_WORKSPACE"] = tempfile.mkdtemp(prefix="arena-reader-")

import pokerbot.player as player          # noqa: E402
from pokerbot.profiler import OpponentProfile  # noqa: E402

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


def make_profile():
    p = OpponentProfile("agent-villain", "Villain")
    for _ in range(5):
        p.record_hand_observed()
    p.record_action("raise", "Preflop", 30, 10, 1000, True, sizing_bb=3.0, pot_before=20)
    p.record_action("bet", "Flop", 60, 0, 990, False, sizing_bb=4.0, pot_before=60)
    p.record_showdown("Two Pair", won=False, pot=120)
    return p


print("\n📋 Player: LLM opponent reader (llm_opponent_summary)")
print("=" * 55)

# ── no-key short-circuit ──
player.GEMINI_API_KEY = ""
test("no API key → None", player.llm_opponent_summary(make_profile()) is None)

# ── happy path ──
player.GEMINI_API_KEY = "fake-key"
captured = {}

def fake_call(prompt, max_tokens=200):
    captured["max_tokens"] = max_tokens
    captured["prompt"] = prompt
    return {
        "style": "loose-aggressive",
        "tendencies": ["opens wide from the BTN", "folds to 3-bets ~60%"],
        "exploitation": ["3-bet bluff the BTN", "value-bet thinner"],
        "reliability": "medium",
    }
player._call_gemini = fake_call
out = player.llm_opponent_summary(make_profile())
test("happy path returns rendered string", isinstance(out, str) and "Villain" in out, out)
test("rendered includes style", out and "loose-aggressive" in out, out)
test("rendered includes tendencies", out and "opens wide from the BTN" in out, out)
test("rendered includes exploit hints", out and "3-bet bluff the BTN" in out, out)
test("uses larger max_tokens for summary", captured["max_tokens"] == 300, captured.get("max_tokens"))
test("prompt includes VPIP stat", "VPIP" in captured["prompt"])
test("prompt includes action transcript", "raise 3.0bb" in captured["prompt"], "transcript missing")
test("prompt includes showdown history", "Two Pair" in captured["prompt"], "showdown missing")

# ── schema validation: empty tendencies → None ──
player._call_gemini = lambda prompt, max_tokens=200: {"style": "TAG", "tendencies": []}
test("empty tendencies → None", player.llm_opponent_summary(make_profile()) is None)

# ── schema validation: missing style → None ──
player._call_gemini = lambda prompt, max_tokens=200: {"tendencies": ["x"]}
test("missing style → None", player.llm_opponent_summary(make_profile()) is None)

# ── non-dict / parse failure → None ──
player._call_gemini = lambda prompt, max_tokens=200: None
test("None response → None", player.llm_opponent_summary(make_profile()) is None)

# ── missing exploitation is fine ──
player._call_gemini = lambda prompt, max_tokens=200: {"style": "nit", "tendencies": ["folds 80% preflop"]}
out2 = player.llm_opponent_summary(make_profile())
test("missing exploitation still renders", isinstance(out2, str) and "nit" in out2, out2)
test("missing exploitation omits Exploit clause", out2 and "Exploit:" not in out2, out2)

print("\n" + "=" * 55)
print(f"📊 TEST SUMMARY: {passed} passed, {failed} failed, {passed + failed} total")
print("=" * 55)
if errors:
    print("\n❌ FAILURES:")
    for name, detail in errors:
        print(f"  • {name}" + (f" — {detail}" if detail else ""))

sys.exit(0 if failed == 0 else 1)
