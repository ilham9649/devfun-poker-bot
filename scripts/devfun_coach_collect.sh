#!/bin/bash
# DevFun Coach Monitor — analyzes recent hands, writes strategy advice for player bot
# Called by cron every 5-10 min

WORKSPACE="${ARENA_WORKSPACE:-/root/.openclaw/workspace}"
CRED_FILE="${ARENA_CREDENTIALS:-$WORKSPACE/.arena-credentials}"
CRED=$(grep apiKey "$CRED_FILE" | cut -d= -f2)
BASE="https://arena.dev.fun"
CID="${ARENA_COMPETITION_ID:-cmqf827h30u7dfca3x2aqvzjv}"
AID="cmqi4g0qq0yffv23xor7r62nr"

# Pull recent hands (last 20)
curl -s "$BASE/api/arena/agent/submissions?agentId=$AID&competitionId=$CID&limit=20" \
  -H "x-arena-api-key: $CRED" 2>/dev/null | python3 -c "
import json, sys, datetime
d = json.load(sys.stdin)
subs = d.get('data', [])
if not subs:
    print('NO_DATA')
    sys.exit(0)

# Aggregate last 20 hands
wins = sum(1 for s in subs if s.get('score',0) > 0 or s.get('data',{}).get('payoutChips',0) > 0)
total = len(subs)
avg_win = sum(s.get('score',0) or s.get('data',{}).get('payoutChips',0) or 0 for s in subs if s.get('score',0) > 0 or s.get('data',{}).get('payoutChips',0) > 0) / max(wins, 1)
losses = total - wins

# Latest hands with hole cards
print(f'RECENT_20: {total} hands, {wins} wins ({wins/total*100:.0f}%), {losses} losses, avg win {avg_win:.0f} chips')
print()
for s in subs[:10]:
    data = s.get('data', {})
    challenge = s.get('challenge', {})
    result = challenge.get('result', {})
    cfg = challenge.get('data', {})
    hole = data.get('holeCards', ['?','?'])
    winners = result.get('winners', [])
    board = result.get('boardCards', [])
    won = any(w.get('agentId') == '$AID' for w in winners)
    wn = next((w.get('handName','?') for w in winners if w.get('agentId') == '$AID'), 
              next((w.get('handName','?') for w in winners), '?'))
    payout = data.get('payoutChips', 0) or 0
    marker = 'WIN' if won else 'LOSS'
    print(f'{marker}: {hole[0]} {hole[1]} | board={board} | {wn} | +{payout}' if won else f'{marker}: {hole[0]} {hole[1]} | board={board} | to {wn} | {payout}')
" 2>/dev/null > "$WORKSPACE/.arena-recent-hands.txt"

# Pull agent stats
curl -s "$BASE/api/arena/agent/me" -H "x-arena-api-key: $CRED" 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
lb = d.get('leaderboard', [])
if lb:
    l = lb[0]
    print(f'AGENT_STATS: chips={l.get(\"totalScore\",\"?\")} | rank={l.get(\"rank\",\"?\")} | best={l.get(\"bestRank\",\"?\")} | subs={l.get(\"totalSubmissions\",0)} | correct={l.get(\"correctCount\",0)} | streak={l.get(\"streak\",0)}')
" 2>/dev/null >> "$WORKSPACE/.arena-recent-hands.txt"

cat "$WORKSPACE/.arena-recent-hands.txt"
