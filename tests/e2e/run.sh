#!/bin/bash
# Run the browser tests against stand-ins for the Anthropic API and for car sites. Nothing real is called
# and no key is needed.
#
#   tests/e2e/run.sh                 every test
#   tests/e2e/run.sh zip versions    only the ones named
#
# Needs: Python with the app's requirements, Node, and Playwright with Chromium
# (in /tmp/e2e: npm init -y && npm i playwright && npx playwright install chromium).
# The tests use /tmp/e2e as their working folder and ports 8766 and 8895 to 8899.
set -u
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
work=/tmp/e2e
mkdir -p "$work"
cp "$here"/*.py "$here"/*.js "$here"/og.jpg "$work"/
cd "$work" || exit 1

start_app() {                      # $1 = "store": with the stand-in garage store; $2 = seconds to wait before drawing a car just loaded
  pkill -f "streamlit ru[n]" 2>/dev/null; sleep 2
  local store_url="" store_key=""
  if [ "${1:-}" = store ]; then store_url=http://127.0.0.1:8895; store_key=test-publishable-key; curl -s http://127.0.0.1:8895/reset >/dev/null; fi
  (cd "$repo" && DEALSHEET_DB_URL="$store_url" DEALSHEET_DB_KEY="$store_key" DEALSHEET_SYNC_RETRY=3 DEALSHEET_DRAW_WAIT="${2:-}" ANTHROPIC_BASE_URL=http://127.0.0.1:8899 DEALSHEET_RETRY_WAIT=1 DEALSHEET_ALLOW_LOCAL_PREVIEWS=1 \
     DEALSHEET_VIN_API=http://127.0.0.1:8896/ nohup streamlit run app.py --server.headless true --server.port 8766 \
     --browser.gatherUsageStats false > "$work/streamlit.log" 2>&1 &)
  sleep 6
}

pkill -f "fake_ap[i].py" 2>/dev/null; pkill -f "fake_d[b].py" 2>/dev/null; sleep 1
for f in fake_api.py site.py fake_vin.py fake_skfb.py fake_db.py; do
  pgrep -f "$f" >/dev/null || (nohup python3 "$f" > "${f%.py}.out" 2>&1 &)
done
sleep 2

echo "== unit: what a listing page says about the car"
(cd "$repo" && python3 "$work/judge_test.py" | tail -1 && python3 "$work/judge_real.py" | tail -1 && python3 "$work/kind_test.py" | tail -4 && python3 "$work/rows_test.py" | tail -1)

tests=("$@")
[ ${#tests[@]} -eq 0 ] && tests=(build2 gear check verify ended refresh2 miles blank remove switch listsites details versions zip pasted shared cutshort cutshort_shared kind market)
failed=0
for t in "${tests[@]}"; do
  case "$t" in shared*) start_app store;; cutshort) start_app "" 2;; cutshort_shared) start_app store 2;; *) start_app;; esac
  echo "== $t"
  timeout 600 node "$t.js" > "$t.out" 2>&1
  grep -E "^errors|TEST ERROR" "$t.out" | cut -c1-300
  grep -q '"exc":0,"errs":\[\]' "$t.out" || { failed=$((failed + 1)); echo "   FAILED: see $work/$t.out"; }
done
pkill -f "streamlit ru[n]" 2>/dev/null
echo "$failed test(s) failed"
exit $failed
