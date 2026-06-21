#!/usr/bin/env python3
"""Tests for pokerbot.bot opponent-action capture + LLM refresh helper.

Imports pokerbot.bot under a staged workspace (it has import-time side effects:
credential read + fcntl PID lock). Validates the snapshot-diff action classifier,
the new-hand guard, blind handling, and refresh_opponent_llm_profile throttling.
Run: `python3 tests/test_capture.py`.
"""
import os
import sys
import atexit
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# --- stage a throwaway .arena-credentials so pokerbot.bot imports cleanly ---
# bot.py reads credentials from its _REPO_ROOT (3 dirnames up from pokerbot/bot.py
# = parent of the repo) at import time, and there is no env override on master.
# tests/test_capture.py is also 3 dirnames below that point, so we compute the
# same path, write a fake file only if none exists, and remove only what we made.
_TMP = tempfile.mkdtemp(prefix="arena-capture-")
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CRED = os.path.join(_REPO_ROOT, ".arena-credentials")
_CREATED_CRED = not os.path.exists(_CRED)
if _CREATED_CRED:
    with open(_CRED, "w") as f:
        f.write("apiKey=testkey_VALUE\nagentId=ME\n")
    atexit.register(lambda: os.path.exists(_CRED) and os.remove(_CRED))
os.environ["ARENA_WORKSPACE"] = _TMP          # isolate state/pid files off the repo
os.environ["ARENA_CREDENTIALS"] = _CRED       # honored once the env-override lands (PR #7/#8)

import pokerbot.bot as b                 # noqa: E402
from pokerbot.profiler import Profiler   # noqa: E402

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


def snap(table_id, street, pot, cur_bet, seats):
    return {"tableId": table_id, "street": street, "potChips": pot, "currentBet": cur_bet,
            "boardCards": [], "selfSeatNumber": 1, "seats": seats}


def seat(sn, aid, name="", stack=1000, status="Active"):
    s = {"seatNumber": sn, "agentId": aid, "stackChips": stack, "status": status}
    if name:
        s["agentName"] = name
    return s


print("\n📋 Bot: opponent-action capture + LLM refresh")
print("=" * 55)

# ── first snapshot of a hand has no predecessor → nothing captured, stashed ──
prof = Profiler(profiles_path=os.path.join(_TMP, "cap.json"))
b._last_table_snapshot.clear()
t0 = snap("T1", "Preflop", 6, 2, [
    seat(1, "ME", stack=998),
    seat(2, "OPP_A", "Alice", stack=1000),
    seat(3, "OPP_B", "Bob", stack=1000),
])
b._capture_opponent_actions(t0, prof, "ME", bb_size=2)
test("first snapshot captures nothing", prof.profiles.get("OPP_A") is None)
test("first snapshot is stashed", "T1" in b._last_table_snapshot)

# ── raise + fold classification on the next snapshot ──
t1 = snap("T1", "Preflop", 50, 40, [
    seat(1, "ME", stack=998),
    seat(2, "OPP_A", "Alice", stack=960),       # -40 facing the BB → raise
    seat(3, "OPP_B", "Bob", stack=1000, status="Folded"),
])
b._capture_opponent_actions(t1, prof, "ME", bb_size=2)
a = prof.profiles["OPP_A"]; bb = prof.profiles["OPP_B"]
test("Alice classified as raise", a.actions["raise"] == 1, a.actions)
test("Alice transcript has sizing", "Preflop:raise 20.0bb" in a.transcript_text(), a.transcript_text())
test("Bob classified as fold", bb.actions["fold"] == 1, bb.actions)
test("Bob transcript notes facing bet", "facing bet" in bb.transcript_text(), bb.transcript_text())

# ── bet vs call vs all-in (coherent multi-seat flow) ──
prof2 = Profiler(profiles_path=os.path.join(_TMP, "cap2.json"))
b._last_table_snapshot.clear()
# (A) dry flop, no bet yet — stashed as the predecessor
b._capture_opponent_actions(
    snap("T2", "Flop", 30, 0, [seat(1, "ME"),
                               seat(2, "B", "Bettor", stack=1000),
                               seat(3, "C", "Cal", stack=1000)]),
    prof2, "ME")
# (B) Bettor opens 30 (prev currentBet was 0 → bet); Cal hasn't acted
b._capture_opponent_actions(
    snap("T2", "Flop", 60, 30, [seat(1, "ME"),
                               seat(2, "B", "Bettor", stack=970),
                               seat(3, "C", "Cal", stack=1000)]),
    prof2, "ME")
# (C) Cal matches the outstanding 30 (prev currentBet was 30 → call)
b._capture_opponent_actions(
    snap("T2", "Flop", 90, 30, [seat(1, "ME"),
                               seat(2, "B", "Bettor", stack=970),
                               seat(3, "C", "Cal", stack=970)]),
    prof2, "ME")
test("Bettor classified as bet (no prior bet)",
     prof2.profiles["B"].actions["bet"] == 1, prof2.profiles["B"].actions)
test("Cal classified as call (faced outstanding bet)",
     prof2.profiles["C"].actions["call"] == 1, prof2.profiles["C"].actions)

prof3 = Profiler(profiles_path=os.path.join(_TMP, "cap3.json"))
b._last_table_snapshot.clear()
b._capture_opponent_actions(
    snap("T3", "Turn", 200, 0, [seat(1, "ME"), seat(2, "AI", "Allinner", stack=500)]),
    prof3, "ME")
b._capture_opponent_actions(
    snap("T3", "Turn", 700, 500, [seat(1, "ME"), seat(2, "AI", "Allinner", stack=0, status="AllIn")]),
    prof3, "ME")
test("all-in classified on status flip",
     prof3.profiles["AI"].actions["all-in"] == 1, prof3.profiles["AI"].actions)

# ── new-hand guard: pot reset / street regressed → no spurious diff ──
before = a.total_actions
b._capture_opponent_actions(
    snap("T1", "Preflop", 6, 2, [seat(1, "ME", stack=1500), seat(2, "OPP_A", "Alice", stack=1500)]),
    prof, "ME")
test("new-hand guard: no spurious actions on pot reset",
     prof.profiles["OPP_A"].total_actions == before, prof.profiles["OPP_A"].total_actions)

# ── our own seat is never profiled ──
test("our own seat never profiled", "ME" not in prof.profiles)

# ── refresh_opponent_llm_profile throttling ──
from pokerbot.profiler import OpponentProfile

# gemini disabled → never refreshes
prof_target = OpponentProfile("agent-rf", "Refresher")
for _ in range(5):
    prof_target.record_hand_observed()
test("refresh: gemini disabled → False",
     b.refresh_opponent_llm_profile(prof_target, gemini_enabled=False) is False)
# enabled but mocked LLM → refreshes once, then throttled
b.llm_opponent_summary = lambda prof: "Refresher: TAG. Exploit: bluff less."
test("refresh: writes summary when eligible",
     b.refresh_opponent_llm_profile(prof_target, gemini_enabled=True) is True)
test("refresh: summary cached on profile", prof_target.llm_summary == "Refresher: TAG. Exploit: bluff less.")
test("refresh: immediately after → throttled (False)",
     b.refresh_opponent_llm_profile(prof_target, showdown_triggered=True, gemini_enabled=True) is False)
# LLM returns None (failure) → no cache overwrite, returns False
b.llm_opponent_summary = lambda prof: None
fresh2 = OpponentProfile("agent-rf2")
for _ in range(5):
    fresh2.record_hand_observed()
test("refresh: LLM failure → False, no summary set",
     b.refresh_opponent_llm_profile(fresh2, gemini_enabled=True) is False
     and fresh2.llm_summary == "")

print("\n" + "=" * 55)
print(f"📊 TEST SUMMARY: {passed} passed, {failed} failed, {passed + failed} total")
print("=" * 55)
if errors:
    print("\n❌ FAILURES:")
    for name, detail in errors:
        print(f"  • {name}" + (f" — {detail}" if detail else ""))

sys.exit(0 if failed == 0 else 1)
