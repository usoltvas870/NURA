#!/bin/bash
set -e
echo "→ Pulling from GitHub main..."
cd /opt/nura
git pull origin main

echo "→ Copying landing page..."
cp index.html /var/www/nura-ai.ru/index.html 2>/dev/null || true

echo "→ Copying static assets..."
cp nura-ds.css /var/www/nura-ai.ru/static/nura-ds.css 2>/dev/null || true

echo "→ Copying PWA app..."
cp -r frontend/pwa/app/* /var/www/nura-ai.ru/app/ 2>/dev/null || true
cp -r frontend/pwa/*.js /var/www/nura-ai.ru/ 2>/dev/null || true

echo "→ Reloading nginx..."
nginx -t && systemctl reload nginx

echo "✓ Deploy complete"
