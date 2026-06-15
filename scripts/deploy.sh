#!/bin/bash
# NURA — Deploy script
# Usage: bash scripts/deploy.sh [service]
#   service: api, bot, celery-worker, celery-beat, all (default)

set -e

SERVICE="${1:-all}"

echo "=== NURA Deploy: $SERVICE ==="

# 1. Push to GitHub
echo ">>> Pushing to GitHub..."
git push origin main

# 2. SSH into VPS, pull and rebuild
echo ">>> Deploying to VPS..."
ssh nura-vps << 'EOF'
  cd /opt/nura
  git pull origin main
  cd nura_app

  if [ "$SERVICE" = "all" ]; then
    echo ">>> Rebuilding all containers..."
    docker compose up -d --build
  else
    echo ">>> Rebuilding $SERVICE..."
    docker compose up -d --build "$SERVICE"
  fi

  echo ">>> Containers:"
  docker ps --format "table {{.Names}}\t{{.Status}}"
EOF

echo "=== Deploy complete ==="
