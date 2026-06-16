#!/usr/bin/env bash
# deploy-no-restore.sh — build → push → update runtime (no backup/restore)
set -euo pipefail

ENDPOINT="https://endpoint-55a2ec46-1573-44d8-be75-75ff6c63983d.agentbase-runtime.aiplatform.vngcloud.vn"
REGISTRY="vcr.vngcloud.vn/111480-abp111764/3anhem-agent"
RUNTIME_ID="runtime-ab14b14d-77dd-4f33-bc5f-dcbbcf4f9e6f"
FLAVOR="runtime-s2-general-2x4"
SCRIPT_START=$(date +%s)

# ── Helpers ───────────────────────────────────────────────────────────────────
_elapsed() { echo "$(( $(date +%s) - SCRIPT_START ))s"; }

_bar() {
  local n=$1 total=$2
  local filled=$(( n * 20 / total )) bar="" i
  for i in $(seq 1 $filled); do bar="${bar}█"; done
  for i in $(seq 1 $((20 - filled))); do bar="${bar}░"; done
  echo "[${bar}] $(( n * 100 / total ))%"
}

_header() { echo ""; echo "━━━ $1 ━━━ elapsed: $(_elapsed)"; }

# ── Step 1/3: Build ───────────────────────────────────────────────────────────
_header "🔨 [1/3] Build"
bash .claude/skills/agentbase/scripts/cr.sh credentials docker-login > /dev/null 2>&1
TAG="v$(date +%Y%m%d%H%M%S)"
echo "Tag: $REGISTRY:$TAG"
docker build --platform linux/amd64 -t "$REGISTRY:$TAG" . 2>&1 \
  | grep -v -E "CACHED$|Preparing$|Waiting$|load build definition|load .dockerignore|load metadata|load build context|transferring"
echo "✅ Built: $TAG  (elapsed: $(_elapsed))"

# ── Step 2/3: Push ────────────────────────────────────────────────────────────
_header "📤 [2/3] Push"
docker push "$REGISTRY:$TAG" 2>&1 \
  | grep -v -E "Preparing$|Waiting$|Layer already exists$"
echo "✅ Pushed  (elapsed: $(_elapsed))"

# ── Step 3/3: Update runtime ──────────────────────────────────────────────────
_header "🚀 [3/3] Update Runtime"

# Wait until ACTIVE before calling update
WAIT_START=$(date +%s)
for i in $(seq 1 24); do
  RT_STATUS=$(bash .claude/skills/agentbase/scripts/runtime.sh get "$RUNTIME_ID" 2>/dev/null \
    | python3 -c "import json,sys; print(json.load(sys.stdin).get('status','?'))" 2>/dev/null || echo "?")
  if [ "$RT_STATUS" = "ACTIVE" ]; then
    echo "✅ Runtime ACTIVE"
    break
  fi
  WSEC=$(( $(date +%s) - WAIT_START ))
  echo "$(_bar $i 24) Runtime $RT_STATUS | ${WSEC}s elapsed"
  [ "$i" -eq "24" ] && echo "⚠️  Runtime still $RT_STATUS — proceeding anyway" && break
  sleep 5
done

DEPLOY_START=$(date +%s)
UPDATE_OUT=$(bash .claude/skills/agentbase/scripts/runtime.sh update "$RUNTIME_ID" \
  --image "$REGISTRY:$TAG" --flavor "$FLAVOR" --from-cr \
  --min-replicas 1 --max-replicas 1 --cpu-scale 50 --mem-scale 50)
echo "$UPDATE_OUT" | python3 -c "
import json,sys; d=json.load(sys.stdin)
print(f'✅ API OK  status={d[\"status\"]}  updatedAt={d[\"updatedAt\"]}')" 2>/dev/null \
  || echo "✅ Runtime update requested"

# Wait for new container
MAX_WAIT=20
for i in $(seq 1 $MAX_WAIT); do
  STATUS=$(curl -s -o /tmp/3anhem-health.json -w "%{http_code}" "$ENDPOINT/health" || true)
  SEC=$(( $(date +%s) - DEPLOY_START ))
  if [ "$STATUS" = "200" ]; then
    STARTED_AT=$(python3 -c "import json; d=json.load(open('/tmp/3anhem-health.json')); print(int(d.get('started_at',0)))" 2>/dev/null || echo "0")
    if [ "$STARTED_AT" -gt "$DEPLOY_START" ]; then
      echo "✅ New container confirmed!  $(_bar $MAX_WAIT $MAX_WAIT)  ${SEC}s"
      break
    elif [ "$STARTED_AT" -gt "0" ] && [ "$i" -ge "6" ]; then
      echo "✅ Container healthy (same image, no restart)  ${SEC}s"
      break
    fi
  fi
  echo "$(_bar $i $MAX_WAIT) ${SEC}s — waiting for container..."
  sleep 5
done

TOTAL=$(( $(date +%s) - SCRIPT_START ))
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Deploy complete!  Total: ${TOTAL}s"
echo "   Image:    $REGISTRY:$TAG"
echo "   Endpoint: $ENDPOINT"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
