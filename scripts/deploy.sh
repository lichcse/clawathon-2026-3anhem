#!/usr/bin/env bash
# deploy.sh — backup → build → push → update runtime → restore
set -euo pipefail

ENDPOINT="https://endpoint-55a2ec46-1573-44d8-be75-75ff6c63983d.agentbase-runtime.aiplatform.vngcloud.vn"
REGISTRY="vcr.vngcloud.vn/111480-abp111764/3anhem-agent"
RUNTIME_ID="runtime-ab14b14d-77dd-4f33-bc5f-dcbbcf4f9e6f"
FLAVOR="runtime-s2-general-2x4"
BACKUP_FILE="/tmp/3anhem-backup-$(date +%Y%m%d%H%M%S).json"
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

# ── Secrets ───────────────────────────────────────────────────────────────────
SECRET_KEY=$(grep '^SECRET_KEY=' .env 2>/dev/null | cut -d= -f2- | tr -d '"' || true)
if [ -z "$SECRET_KEY" ]; then
  echo "❌ SECRET_KEY not found in .env"
  exit 1
fi

# ── Step 1/5: Backup ──────────────────────────────────────────────────────────
_header "📦 [1/5] Backup"
HTTP_STATUS=$(curl -s -o "$BACKUP_FILE" -w "%{http_code}" \
  -H "X-Admin-Secret: $SECRET_KEY" "$ENDPOINT/api/admin/backup")

if [ "$HTTP_STATUS" != "200" ]; then
  echo "⚠️  Backup failed (HTTP $HTTP_STATUS)"
  read -p "Continue WITHOUT backup? [y/N] " confirm
  [ "$confirm" = "y" ] || exit 1
else
  COUNTS=$(python3 -c "
import json; d=json.load(open('$BACKUP_FILE')); c=d['counts']
print(f\"users={c['users']} repos={c['repositories']} messages={c['chat_messages']}\")" 2>/dev/null || echo "")
  echo "✅ Saved: $BACKUP_FILE ($COUNTS)"
  HAS_DATA=$(python3 -c "import json; d=json.load(open('$BACKUP_FILE')); print('yes' if d['counts']['users']>0 else 'no')" 2>/dev/null || echo "no")
  if [ "$HAS_DATA" = "no" ]; then
    echo "⚠️  Backup EMPTY — live container may have no data"
    ls -t /tmp/3anhem-backup-*.json 2>/dev/null | head -3 || true
  fi
fi

# ── Step 2/5: Build ───────────────────────────────────────────────────────────
_header "🔨 [2/5] Build"
bash .claude/skills/agentbase/scripts/cr.sh credentials docker-login > /dev/null 2>&1
TAG="v$(date +%Y%m%d%H%M%S)"
echo "Tag: $REGISTRY:$TAG"
docker build --platform linux/amd64 -t "$REGISTRY:$TAG" . 2>&1 \
  | grep -v -E "CACHED$|Preparing$|Waiting$|load build definition|load .dockerignore|load metadata|load build context|transferring"
echo "✅ Built: $TAG  (elapsed: $(_elapsed))"

# ── Step 3/5: Push ────────────────────────────────────────────────────────────
_header "📤 [3/5] Push"
docker push "$REGISTRY:$TAG" 2>&1 \
  | grep -v -E "Preparing$|Waiting$|Layer already exists$"
echo "✅ Pushed  (elapsed: $(_elapsed))"

# ── Step 4/5: Update runtime ──────────────────────────────────────────────────
_header "🚀 [4/5] Update Runtime"

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
NEW_CONTAINER_CONFIRMED=false
for i in $(seq 1 $MAX_WAIT); do
  STATUS=$(curl -s -o /tmp/3anhem-health.json -w "%{http_code}" "$ENDPOINT/health" || true)
  SEC=$(( $(date +%s) - DEPLOY_START ))
  if [ "$STATUS" = "200" ]; then
    STARTED_AT=$(python3 -c "import json; d=json.load(open('/tmp/3anhem-health.json')); print(int(d.get('started_at',0)))" 2>/dev/null || echo "0")
    if [ "$STARTED_AT" -gt "$DEPLOY_START" ]; then
      echo "✅ New container confirmed!  $(_bar $MAX_WAIT $MAX_WAIT)  ${SEC}s"
      NEW_CONTAINER_CONFIRMED=true
      break
    elif [ "$STARTED_AT" -gt "0" ] && [ "$i" -ge "6" ]; then
      echo "✅ Container healthy (same image, no restart)  ${SEC}s"
      NEW_CONTAINER_CONFIRMED=true
      break
    fi
  fi
  echo "$(_bar $i $MAX_WAIT) ${SEC}s — waiting for container..."
  sleep 5
done

if [ "$NEW_CONTAINER_CONFIRMED" != "true" ]; then
  echo "❌ Container not healthy within timeout"
  echo "   Restore manually: curl -X POST -H 'X-Admin-Secret: \$SECRET_KEY' -H 'Content-Type: application/json' -d @$BACKUP_FILE $ENDPOINT/api/admin/restore"
  exit 1
fi

# ── Step 5/5: Restore ─────────────────────────────────────────────────────────
if [ -f "$BACKUP_FILE" ] && [ "$HTTP_STATUS" = "200" ]; then
  _header "♻️  [5/5] Restore"
  RESTORE_OK=false
  for attempt in 1 2 3; do
    RESTORE_RESP=$(curl -s --max-time 30 -X POST \
      -H "X-Admin-Secret: $SECRET_KEY" -H "Content-Type: application/json" \
      -d @"$BACKUP_FILE" "$ENDPOINT/api/admin/restore")
    RESTORE_STATUS=$(echo "$RESTORE_RESP" | python3 -c "import json,sys; print(json.load(sys.stdin).get('status','?'))" 2>/dev/null || echo "error")
    if [ "$RESTORE_STATUS" = "ok" ]; then
      INSERTED=$(echo "$RESTORE_RESP" | python3 -c "
import json,sys; d=json.load(sys.stdin)
ins=d['inserted']; skp=d['skipped']
print(f\"inserted: users={ins['users']} repos={ins['repositories']} msgs={ins['chat_messages']}  |  skipped: users={skp['users']} repos={skp['repositories']} msgs={skp['chat_messages']}\")" 2>/dev/null || echo "")
      INSERTED_COUNT=$(echo "$RESTORE_RESP" | python3 -c "import json,sys; print(sum(json.load(sys.stdin)['inserted'].values()))" 2>/dev/null || echo "0")
      echo "✅ Attempt $attempt: $INSERTED"
      RESTORE_OK=true
      if [ "$INSERTED_COUNT" = "0" ] && [ $attempt -lt 3 ]; then
        echo "⏳ All skipped — retrying in 15s (container may still be restarting)..."
        sleep 15
      else
        break
      fi
    else
      echo "⚠️  Attempt $attempt failed: $RESTORE_RESP"
      [ $attempt -lt 3 ] && sleep 5
    fi
  done
  if [ "$RESTORE_OK" != "true" ]; then
    echo "❌ Restore failed. Manual restore:"
    echo "   curl -X POST -H 'X-Admin-Secret: \$SECRET_KEY' -H 'Content-Type: application/json' -d @$BACKUP_FILE $ENDPOINT/api/admin/restore"
  fi
else
  _header "⏭️  [5/5] Restore skipped (no backup)"
fi

TOTAL=$(( $(date +%s) - SCRIPT_START ))
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Deploy complete!  Total: ${TOTAL}s"
echo "   Image:    $REGISTRY:$TAG"
echo "   Endpoint: $ENDPOINT"
[ -f "$BACKUP_FILE" ] && echo "   Backup:   $BACKUP_FILE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
