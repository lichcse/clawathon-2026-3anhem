#!/usr/bin/env bash
# deploy-no-restore.sh — build → push → update runtime (no backup/restore)
set -euo pipefail

ENDPOINT="https://endpoint-55a2ec46-1573-44d8-be75-75ff6c63983d.agentbase-runtime.aiplatform.vngcloud.vn"
REGISTRY="vcr.vngcloud.vn/111480-abp111764/3anhem-agent"
RUNTIME_ID="runtime-ab14b14d-77dd-4f33-bc5f-dcbbcf4f9e6f"
FLAVOR="runtime-s2-general-2x4"

# ── Step 1: Build Docker image ───────────────────────────────────────────────
echo "🔨 [1/3] Building Docker image..."
bash .claude/skills/agentbase/scripts/cr.sh credentials docker-login > /dev/null 2>&1

TAG="v$(date +%Y%m%d%H%M%S)"
echo "   Tag: $REGISTRY:$TAG"
docker build --platform linux/amd64 -t "$REGISTRY:$TAG" .
echo "   ✅ Built: $REGISTRY:$TAG"

# ── Step 2: Push image ───────────────────────────────────────────────────────
echo "📤 [2/3] Pushing image..."
docker push "$REGISTRY:$TAG"
echo "   ✅ Pushed: $REGISTRY:$TAG"

# ── Step 3: Update runtime ───────────────────────────────────────────────────
echo "🚀 [3/3] Updating runtime..."
DEPLOY_START=$(date +%s)

echo "   Calling AgentBase API to update runtime..."
bash .claude/skills/agentbase/scripts/runtime.sh update "$RUNTIME_ID" \
  --image "$REGISTRY:$TAG" \
  --flavor "$FLAVOR" \
  --from-cr \
  --min-replicas 1 --max-replicas 1 --cpu-scale 50 --mem-scale 50
echo "   ✅ Runtime update requested"

echo "   ⏳ Waiting for container (deploy_start=$DEPLOY_START)..."
for i in $(seq 1 40); do
  STATUS=$(curl -s -o /tmp/3anhem-health.json -w "%{http_code}" "$ENDPOINT/health" || true)
  if [ "$STATUS" = "200" ]; then
    STARTED_AT=$(python3 -c "import json; d=json.load(open('/tmp/3anhem-health.json')); print(int(d.get('started_at',0)))" 2>/dev/null || echo "0")
    if [ "$STARTED_AT" -gt "$DEPLOY_START" ]; then
      echo "   ✅ New container confirmed (started_at=$STARTED_AT > deploy_start=$DEPLOY_START)"
      break
    elif [ "$STARTED_AT" -gt "0" ] && [ "$i" -ge "6" ]; then
      echo "   ✅ Container healthy (image unchanged — no restart needed)"
      break
    else
      echo "   ⏳ Health OK but still old container (started_at=$STARTED_AT) — waiting..."
    fi
  fi
  sleep 5
done

echo ""
echo "✅ Deploy complete!"
echo "   Image:    $REGISTRY:$TAG"
echo "   Endpoint: $ENDPOINT"
