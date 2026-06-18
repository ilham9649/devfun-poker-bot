#!/bin/bash
# DevFun Poker Monitor — run every 5 min via cron
# No model calls, no rate limits. Just pull and log.

WORKSPACE=/root/.openclaw/workspace
CRED=$(grep apiKey "$WORKSPACE/.arena-credentials" | cut -d= -f2)
BASE="https://arena.dev.fun"
CID="cmqf827h30u7dfca3x2aqvzjv"
AID="cmqi4g0qq0yffv23xor7r62nr"

TS=$(date '+%Y-%m-%d %H:%M:%S')

# Agent status
ME=$(curl -s "$BASE/api/arena/agent/me" -H "x-arena-api-key: $CRED" 2>/dev/null)
STATUS=$(echo "$ME" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status','?'))" 2>/dev/null)
LB=$(echo "$ME" | python3 -c "import json,sys; d=json.load(sys.stdin); lb=d.get('leaderboard',[]); 
r=lb[0] if lb else {}; print(f\"rank=#{r.get('rank','?')} best=#{r.get('bestRank','?')}\")" 2>/dev/null)

# Pending actions
PA=$(curl -s "$BASE/api/arena/texas/pending-actions?competitionId=$CID" -H "x-arena-api-key: $CRED" 2>/dev/null)
NTABLES=$(echo "$PA" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('tables',[])))" 2>/dev/null)
CHIPS=$(echo "$PA" | python3 -c "import json,sys; d=json.load(sys.stdin); p=d.get('participant',{}); 
print(f\"{p.get('totalChips','?')} ({p.get('chipState','?')})\")" 2>/dev/null)
LOBBY=$(echo "$PA" | python3 -c "import json,sys; d=json.load(sys.stdin); l=d.get('lobby',{}); 
print(f\"{l.get('position','?')}/{l.get('total','?')}\" if l else 'none')" 2>/dev/null)

# State file
STATE="no"
if [ -f "$WORKSPACE/.arena-poker-state" ]; then
    STATE=$(python3 -c "import json; d=json.load(open('$WORKSPACE/.arena-poker-state')); 
    print(f\"{d.get('hands_played',0)}h {d.get('hands_won',0)}w {d.get('totalChips',0)}chips\")" 2>/dev/null)
fi

echo "[$TS] 🃏 $STATUS | $CHIPS | tables=$NTABLES | lobby=$LOBBY | $LB | $STATE" >> "$WORKSPACE/logs/devfun_monitor.log"

# Only announce if something changed or every 30 min
LAST=$(tail -1 "$WORKSPACE/.arena-monitor-last" 2>/dev/null || echo "")
THIS="$CHIPS $NTABLES $LB"
if [ "$LAST" != "$THIS" ]; then
    echo "$THIS" > "$WORKSPACE/.arena-monitor-last"
    echo "[$TS] CHANGE: $CHIPS | $LB | lobby=$LOBBY"
fi
