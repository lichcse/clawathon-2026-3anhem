#!/usr/bin/env bash
# deploy.sh — backup → build → push → update runtime → restore
set -euo pipefail

ENDPOINT="https://endpoint-55a2ec46-1573-44d8-be75-75ff6c63983d.agentbase-runtime.aiplatform.vngcloud.vn"
REGISTRY="vcr.vngcloud.vn/111480-abp111764/3anhem-agent"
RUNTIME_ID="runtime-ab14b14d-77dd-4f33-bc5f-dcbbcf4f9e6f"
FLAVOR="runtime-s2-general-2x4"
BACKUP_FILE="/tmp/3anhem-backup-$(date +%Y%m%d%H%M%S).json"

# Read SECRET_KEY from .env
SECRET_KEY=$(grep '^SECRET_KEY=' .env 2>/dev/null | cut -d= -f2- | tr -d '"' || true)
if [ -z "$SECRET_KEY" ]; then
  echo "❌ SECRET_KEY not found in .env — cannot authenticate backup/restore"
  exit 1
fi

# ── Step 1: Backup live data ─────────────────────────────────────────────────
echo "📦 [1/5] Backing up live data..."
HTTP_STATUS=$(curl -s -o "$BACKUP_FILE" -w "%{http_code}" \
  -H "X-Admin-Secret: $SECRET_KEY" \
  "$ENDPOINT/api/admin/backup")

if [ "$HTTP_STATUS" != "200" ]; then
  echo "⚠️  Backup failed (HTTP $HTTP_STATUS) — check if live is reachable"
  echo "   Backup file: $BACKUP_FILE"
  read -p "Continue deploy WITHOUT backup? [y/N] " confirm
  [ "$confirm" = "y" ] || exit 1
else
  COUNTS=$(python3 -c "import json,sys; d=json.load(open('$BACKUP_FILE')); c=d['counts']; print(f\"users={c['users']} repos={c['repositories']} messages={c['chat_messages']}\")" 2>/dev/null || echo "")
  echo "   ✅ Backup saved: $BACKUP_FILE ($COUNTS)"

  # Warn if backup appears empty — likely from a previous failed deploy
  HAS_DATA=$(python3 -c "import json; d=json.load(open('$BACKUP_FILE')); print('yes' if d['counts']['users']>0 else 'no')" 2>/dev/null || echo "no")
  if [ "$HAS_DATA" = "no" ]; then
    echo "   ⚠️  Backup is EMPTY — live container has no data (previous deploy may have lost data)"
    echo "   Check /tmp/ for older backup files to restore from manually."
    ls -t /tmp/3anhem-backup-*.json 2>/dev/null | head -5 || true
  fi
fi

# ── Step 2: Build Docker image ───────────────────────────────────────────────
echo "🔨 [2/5] Building Docker image..."
bash .claude/skills/agentbase/scripts/cr.sh credentials docker-login > /dev/null 2>&1

TAG="v$(date +%Y%m%d%H%M%S)"
echo "   Tag: $REGISTRY:$TAG"
docker build --platform linux/amd64 -t "$REGISTRY:$TAG" .
echo "   ✅ Built: $REGISTRY:$TAG"

# ── Step 3: Push image ───────────────────────────────────────────────────────
echo "📤 [3/5] Pushing image..."
docker push "$REGISTRY:$TAG"
echo "   ✅ Pushed: $REGISTRY:$TAG"

# ── Step 4: Update runtime ───────────────────────────────────────────────────
echo "🚀 [4/5] Updating runtime..."
DEPLOY_START=$(date +%s)

echo "   Calling AgentBase API to update runtime..."
bash .claude/skills/agentbase/scripts/runtime.sh update "$RUNTIME_ID" \
  --image "$REGISTRY:$TAG" \
  --flavor "$FLAVOR" \
  --from-cr \
  --min-replicas 1 --max-replicas 1 --cpu-scale 50 --mem-scale 50
echo "   ✅ Runtime update requested"

echo "   ⏳ Waiting for new container (deploy_start=$DEPLOY_START)..."
NEW_CONTAINER_CONFIRMED=false
for i in $(seq 1 40); do
  STATUS=$(curl -s -o /tmp/3anhem-health.json -w "%{http_code}" "$ENDPOINT/health" || true)
  if [ "$STATUS" = "200" ]; then
    STARTED_AT=$(python3 -c "import json; d=json.load(open('/tmp/3anhem-health.json')); print(int(d.get('started_at',0)))" 2>/dev/null || echo "0")
    if [ "$STARTED_AT" -gt "$DEPLOY_START" ]; then
      echo "   ✅ New container confirmed (started_at=$STARTED_AT > deploy_start=$DEPLOY_START)"
      NEW_CONTAINER_CONFIRMED=true
      break
    elif [ "$STARTED_AT" -gt "0" ] && [ "$i" -ge "6" ]; then
      # Container is running but started_at hasn't changed — likely same image, no restart.
      # Safe to restore against the running container.
      echo "   ✅ Container healthy (started_at=$STARTED_AT, image unchanged — no restart needed)"
      NEW_CONTAINER_CONFIRMED=true
      break
    else
      echo "   ⏳ Health OK but still old container (started_at=$STARTED_AT) — waiting..."
    fi
  fi
  sleep 5
done

if [ "$NEW_CONTAINER_CONFIRMED" != "true" ]; then
  echo "❌ Container did not become healthy within timeout"
  echo "   You can restore manually:"
  echo "   curl -X POST -H 'X-Admin-Secret: \$SECRET_KEY' -H 'Content-Type: application/json' -d @$BACKUP_FILE $ENDPOINT/api/admin/restore"
  exit 1
fi

# ── Step 5: Restore data ─────────────────────────────────────────────────────
if [ -f "$BACKUP_FILE" ] && [ "$HTTP_STATUS" = "200" ]; then
  echo "♻️  [5/5] Restoring data..."

  # Retry restore up to 3 times (in case container is still initializing)
  RESTORE_OK=false
  for attempt in 1 2 3; do
    RESTORE_RESP=$(curl -s --max-time 30 -X POST \
      -H "X-Admin-Secret: $SECRET_KEY" \
      -H "Content-Type: application/json" \
      -d @"$BACKUP_FILE" \
      "$ENDPOINT/api/admin/restore")

    RESTORE_STATUS=$(echo "$RESTORE_RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('status','?'))" 2>/dev/null || echo "error")
    if [ "$RESTORE_STATUS" = "ok" ]; then
      INSERTED=$(echo "$RESTORE_RESP" | python3 -c "import json,sys; d=json.load(sys.stdin)['inserted']; print(f\"users={d['users']} repos={d['repositories']} messages={d['chat_messages']}\")" 2>/dev/null || echo "")
      SKIPPED=$(echo "$RESTORE_RESP"  | python3 -c "import json,sys; d=json.load(sys.stdin)['skipped'];  print(f\"users={d['users']} repos={d['repositories']} messages={d['chat_messages']}\")" 2>/dev/null || echo "")
      echo "   ✅ Restore attempt $attempt: inserted=($INSERTED) skipped=($SKIPPED)"
      RESTORE_OK=true
      break
    else
      echo "   ⚠️  Restore attempt $attempt failed: $RESTORE_RESP"
      [ $attempt -lt 3 ] && sleep 5
    fi
  done

  if [ "$RESTORE_OK" != "true" ]; then
    echo "   ❌ Restore failed after 3 attempts. Backup kept at: $BACKUP_FILE"
    echo "   Restore manually:"
    echo "   curl -X POST -H 'X-Admin-Secret: \$SECRET_KEY' -H 'Content-Type: application/json' -d @$BACKUP_FILE $ENDPOINT/api/admin/restore"
  fi
else
  echo "   ⏭️  [5/5] Skipped restore (no backup)"
fi

echo ""
echo "✅ Deploy complete!"
echo "   Image:    $REGISTRY:$TAG"
echo "   Endpoint: $ENDPOINT"
[ -f "$BACKUP_FILE" ] && echo "   Backup:   $BACKUP_FILE"
