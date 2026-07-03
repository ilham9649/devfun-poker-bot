#!/usr/bin/env bash
# strategy.py is self-contained (stdlib only) — submit it directly as a bare
# file. This script just validates it imports + runs act() in isolation, exactly
# as the sandbox does. Usage: sandbox/build.sh
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
python3 -I - "$here/strategy.py" <<'PY'
import sys, importlib.util, json
spec = importlib.util.spec_from_file_location("strategy", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
fn = getattr(m, "choose_action", None) or getattr(m, "act", None)
assert fn, "no act()/choose_action() entrypoint"
t = {"potChips":30,"street":"Preflop","boardCards":[],"currentBet":20,
     "smallBlindChips":10,"bigBlindChips":20,"selfSeatNumber":1,
     "seats":[{"seatNumber":1,"status":"Active","stackChips":990,"holeCards":["Ah","Kd"]},
              {"seatNumber":2,"status":"Active","stackChips":980,"holeCards":[]}],
     "allowedActions":{"availableActions":["fold","call","raise"],"callChips":10,
                       "betRange":{"min":0,"max":0},"raiseRange":{"min":40,"max":990},
                       "amountSemantics":"to-amount"},
     "recentEvents":[{"type":"BlindPosted","summary":{"amount":10,"seatNumber":1}},
                     {"type":"BlindPosted","summary":{"amount":20,"seatNumber":2}}]}
r = fn(t)
assert isinstance(r, (dict, str, tuple)), f"bad return type {type(r)}"
print("isolation OK:", json.dumps(r, default=str))
PY
