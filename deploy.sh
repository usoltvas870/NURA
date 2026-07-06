#!/bin/bash
set -e
echo "→ Pulling from GitHub main..."
cd /opt/nura
git pull origin main

echo "→ Copying landing page..."
cp index.html /var/www/nura-ai.ru/index.html 2>/dev/null || true
cp privacy.html /var/www/nura-ai.ru/privacy.html 2>/dev/null || true
cp offer.html /var/www/nura-ai.ru/offer.html 2>/dev/null || true
cp contacts.html /var/www/nura-ai.ru/contacts.html 2>/dev/null || true
cp mini.html /var/www/nura-ai.ru/mini.html 2>/dev/null || true
cp personal-data-consent.html /var/www/nura-ai.ru/personal-data-consent.html 2>/dev/null || true
cp marketing-consent.html /var/www/nura-ai.ru/marketing-consent.html 2>/dev/null || true
cp theme.css /var/www/nura-ai.ru/theme.css 2>/dev/null || true

echo "→ Copying PWA app..."
cp -r frontend/pwa/app/* /var/www/nura-ai.ru/app/ 2>/dev/null || true
cp -r frontend/pwa/*.js /var/www/nura-ai.ru/ 2>/dev/null || true

echo "→ Copying admin panel..."
mkdir -p /var/www/nura-ai.ru/admin
cp frontend/admin/index.html /var/www/nura-ai.ru/admin/index.html

echo "→ Copying PWA root files..."
cp frontend/manifest.json /var/www/nura-ai.ru/manifest.json 2>/dev/null || true
cp frontend/service-worker.js /var/www/nura-ai.ru/service-worker.js 2>/dev/null || true
cp frontend/pwa-install.js /var/www/nura-ai.ru/pwa-install.js 2>/dev/null || true
cp frontend/offline.html /var/www/nura-ai.ru/offline.html 2>/dev/null || true

echo "→ Copying icons..."
mkdir -p /var/www/nura-ai.ru/icons
cp -r frontend/icons/* /var/www/nura-ai.ru/icons/ 2>/dev/null || true

echo "→ Copying fonts..."
mkdir -p /var/www/nura-ai.ru/fonts
cp -r frontend/fonts/* /var/www/nura-ai.ru/fonts/ 2>/dev/null || true

echo "→ Copying favicon and images..."
cp favicon.ico /var/www/nura-ai.ru/favicon.ico 2>/dev/null || true
cp favicon.png /var/www/nura-ai.ru/favicon.png 2>/dev/null || true
cp hero.png /var/www/nura-ai.ru/hero.png 2>/dev/null || true
cp frontend/nura-hero.webp /var/www/nura-ai.ru/nura-hero.webp 2>/dev/null || true

echo "→ Updating nginx config..."
cp nura_app/nginx/nura-ai.ru.conf /etc/nginx/sites-available/nura-ai.ru.conf 2>/dev/null || true

echo "→ Reloading nginx..."
nginx -t && systemctl reload nginx

echo "→ Rebuilding API container..."
cd /opt/nura/nura_app
docker compose up -d --build api --no-deps
cd /opt/nura

echo "✓ Deploy complete"
