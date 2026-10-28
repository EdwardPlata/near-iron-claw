#!/usr/bin/env bash
# End-to-end smoke test for the near-iron-claw middleware chain.
# Asserts each layer: Vercel static + functions, and the Supabase edge function.
#
# Usage:
#   scripts/smoke.sh                      # test the live production URLs
#   BASE=http://localhost:3000 scripts/smoke.sh
#
# Exit code 0 = all assertions passed. Chat is expected to return 502 until a
# valid NEAR AI key is set in app_config (the whole chain is still exercised).
set -u

BASE="${BASE:-https://near-iron-claw.vercel.app}"
SUPABASE_FN="${SUPABASE_FN:-https://duesorupitzmjubbylxg.supabase.co/functions/v1/chat}"
pass=0 fail=0

check() { # name expected actual
  if [ "$2" = "$3" ]; then printf '  ✅ %-46s %s\n' "$1" "$3"; pass=$((pass+1));
  else printf '  ❌ %-46s expected %s, got %s\n' "$1" "$2" "$3"; fail=$((fail+1)); fi
}
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

echo "Testing $BASE"
check "GET /  (static frontend)"            200 "$(code "$BASE/")"
check "GET /api/health"                     200 "$(code "$BASE/api/health")"
check "POST /api/chat (empty body -> 400)"  400 "$(code -X POST "$BASE/api/chat" -H 'content-type: application/json' -d '{}')"
check "GET /api/chat (method guard -> 405)" 405 "$(code "$BASE/api/chat")"
# Full chain always returns 200 now: a real reply with a valid key, or a graceful
# degraded echo when every provider fails (the whole pipeline still runs + logs).
check "POST /api/chat (graceful -> 200)"    200 "$(code -X POST "$BASE/api/chat" -H 'content-type: application/json' -d '{"prompt":"ping","max_tokens":8}')"
check "GET /api/logs (observability)"       200 "$(code "$BASE/api/logs?limit=5")"
check "POST /api/logs (method guard -> 405)" 405 "$(code -X POST "$BASE/api/logs")"
check "Supabase edge fn (no JWT -> 401)"    401 "$(code -X POST "$SUPABASE_FN" -H 'content-type: application/json' -d '{"prompt":"hi"}')"

echo ""
echo "  $pass passed, $fail failed"
[ "$fail" -eq 0 ]
