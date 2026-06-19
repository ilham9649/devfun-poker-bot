#!/usr/bin/env python3
"""Tests for credential / profile path resolution precedence.

Validates that pokerbot.bot resolves .arena-credentials by precedence
(ARENA_CREDENTIALS -> parent-of-repo -> ARENA_WORKSPACE) and that opponent
profiles follow ARENA_WORKSPACE. Run: `python3 tests/test_paths.py`.
"""
import os
import sys
import tempfile

# Repo root on sys.path so `import pokerbot...` resolves.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# --- Arrange: a workspace + a credentials file so pokerbot.bot imports cleanly ---
_TMP = tempfile.mkdtemp(prefix="arena-test-")
_CRED = os.path.join(_TMP, ".arena-credentials")
with open(_CRED, "w") as f:
    f.write("apiKey=testkey_VALUE\nagentId=testagent_VALUE\n")
os.environ["ARENA_WORKSPACE"] = _TMP
os.environ["ARENA_CREDENTIALS"] = _CRED  # precedence #1 — must win

import pokerbot.bot as b          # noqa: E402  (env must be set before import)
import pokerbot.player as p       # noqa: E402
import pokerbot.profiler as pr    # noqa: E402

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


print("\n📋 Credential & profile path resolution")
print("=" * 55)

# 1. ARENA_CREDENTIALS (precedence #1) wins and the file is actually parsed.
test("ARENA_CREDENTIALS wins as CRED_FILE", b.CRED_FILE == _CRED, f"got {b.CRED_FILE}")
test("API_KEY parsed from chosen cred file", b.API_KEY == "testkey_VALUE", f"got {b.API_KEY!r}")
test("AGENT_ID parsed from chosen cred file", b.AGENT_ID == "testagent_VALUE", f"got {b.AGENT_ID!r}")

# 2. _first_existing helper: first existing wins; missing skipped; "" / None ignored; None if none.
d = tempfile.mkdtemp()
_existing = os.path.join(d, "exists")
_missing = os.path.join(d, "missing")
open(_existing, "w").close()
test("_first_existing picks first that exists", b._first_existing([_missing, _existing]) == _existing)
test("_first_existing skips empty/None entries", b._first_existing(["", None, _existing]) == _existing)
test("_first_existing returns None if none exist", b._first_existing([_missing, os.path.join(d, "nope")]) is None)

# 3. Profiles follow ARENA_WORKSPACE (so multi-instance/eval runs isolate profile sets).
_expected_profiles = os.path.join(_TMP, "opponent_profiles.json")
test("player profiles follow ARENA_WORKSPACE", p.PROFILES_FILE == _expected_profiles, f"got {p.PROFILES_FILE}")
test("profiler profiles match player", pr.PROFILES_FILE == p.PROFILES_FILE, f"got {pr.PROFILES_FILE}")

print("\n" + "=" * 55)
print(f"📊 TEST SUMMARY: {passed} passed, {failed} failed, {passed + failed} total")
print("=" * 55)
if errors:
    print("\n❌ FAILURES:")
    for name, detail in errors:
        print(f"  • {name}" + (f" — {detail}" if detail else ""))

sys.exit(0 if failed == 0 else 1)
