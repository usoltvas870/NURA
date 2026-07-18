#!/bin/bash
set -e
WEB_ROOT=/var/www/nura-ai.ru

echo "→ Pulling from GitHub main..."
cd /opt/nura
git pull origin main

echo "→ Checking required sources..."
for f in index.html landing-v2.css landing-v2.js \
  frontend/nura-hero-final.webp frontend/nura-hero-final-mobile.webp \
  frontend/landing-v2/tools-matrix.webp frontend/landing-v2/tools-tarot.webp \
  frontend/landing-v2/tools-dialogue.webp \
  frontend/landing-v2/pwa-home-neutral.webp \
  frontend/landing-v2/pwa-tarot-neutral.webp; do
  if ! test -f "$f"; then
    echo "Missing required file: $f" >&2
    exit 1
  fi
done
if ! test -d frontend/landing-v2; then
  echo "Missing required directory: frontend/landing-v2" >&2
  exit 1
fi

echo "→ Copying landing page..."
cp index.html /var/www/nura-ai.ru/index.html 2>/dev/null || true
cp privacy.html /var/www/nura-ai.ru/privacy.html 2>/dev/null || true
cp offer.html /var/www/nura-ai.ru/offer.html 2>/dev/null || true
cp contacts.html /var/www/nura-ai.ru/contacts.html 2>/dev/null || true
cp mini.html /var/www/nura-ai.ru/mini.html 2>/dev/null || true
cp personal-data-consent.html /var/www/nura-ai.ru/personal-data-consent.html 2>/dev/null || true
cp marketing-consent.html /var/www/nura-ai.ru/marketing-consent.html 2>/dev/null || true
cp acceptable-use.html /var/www/nura-ai.ru/acceptable-use.html 2>/dev/null || true
cp theme.css /var/www/nura-ai.ru/theme.css 2>/dev/null || true
install -m 0644 landing-v2.css "$WEB_ROOT/landing-v2.css"
install -m 0644 landing-v2.js "$WEB_ROOT/landing-v2.js"

echo "→ Copying PWA app..."
cp -r frontend/pwa/app/* /var/www/nura-ai.ru/app/ 2>/dev/null || true
cp -r frontend/pwa/*.js /var/www/nura-ai.ru/ 2>/dev/null || true
mkdir -p /var/www/nura-ai.ru/assets
cp -r frontend/assets/* /var/www/nura-ai.ru/assets/ 2>/dev/null || true

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
cp frontend/nura-hero-final.webp /var/www/nura-ai.ru/nura-hero-final.webp 2>/dev/null || true
install -m 0644 frontend/nura-hero-final-mobile.webp "$WEB_ROOT/nura-hero-final-mobile.webp"
mkdir -p "$WEB_ROOT/landing-v2"
cp -a frontend/landing-v2/. "$WEB_ROOT/landing-v2/"

echo "→ Updating nginx config..."
cp nura_app/nginx/nura-ai.ru.conf /etc/nginx/sites-available/nura-ai.ru.conf 2>/dev/null || true

echo "→ Reloading nginx..."
nginx -t && systemctl reload nginx

echo "→ Rebuilding API container..."
cd /opt/nura/nura_app
docker compose up -d --build api --no-deps
cd /opt/nura

echo "✓ Deploy complete"
