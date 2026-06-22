# NURA — Деплой в production

Полностью автоматический деплой лендинга и PWA-статик-ассетов на VPS `nura-ai.ru` через GitHub Actions. Push в `main` → деплой без ручных шагов.

> Для деплоя бэкенд-контейнеров (bot/api/celery) используйте `scripts/deploy.sh` (см. «Fallback» ниже) — этот workflow покрывает только лендинг/PWA-статику (`deploy.sh` в корне репозитория).

---

## Как теперь происходит деплой

```
push в main
   │
   ▼
GitHub Actions запускает job «deploy»
   │
   ▼
Workflow подключается по SSH к VPS (appleboy/ssh-action) и выполняет:
   1. Pre-flight: проверяет что working tree на сервере чистый
      └── если грязный → ЖЁСТКИЙ FAIL (см. раздел ниже), деплой НЕ начинается
   2. git fetch + git pull --ff-only origin main
   3. bash deploy.sh   (копирует index.html / theme.css / PWA / icons / fonts, reload nginx)
   4. Записывает /var/www/nura-ai.ru/VERSION (SHA + UTC-таймстемп)
   5. curl-проверка https://nura-ai.ru/ → 2xx

Результат: зелёная/красная галочка в Actions без какого-либо ручного шага.
```

Workflow-файл: [`.github/workflows/deploy.yml`](.github/workflows/deploy.yml)

Запустить вручную (без push) можно через Actions → «Deploy to production» → «Run workflow».

---

## Что нужно настроить один раз (через GitHub UI)

### 1. Secrets (Settings → Secrets and variables → Actions → New repository secret)

| Имя секрета | Значение |
|---|---|
| `VPS_HOST` | `45.144.178.118` |
| `VPS_USER` | `root` |
| `VPS_SSH_KEY` | Содержимое приватного SSH-ключа **целиком**, включая строки `-----BEGIN OPENSSH PRIVATE KEY-----` и `-----END OPENSSH PRIVATE KEY-----`. Это тот же ключ, что используется для `ssh -i C:\Users\Bayzel\.ssh\id_ed25519_astro root@45.144.178.118`. **Никогда не коммитьте этот ключ в репозиторий и не вставляйте в какие-либо файлы.** |

### 2. Секреты уже настроены

Если workflow падает с ошибкой «secret not found» — секреты (`VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`) не добавлены в репозиторий. Добавьте их по инструкции выше.

> **Заметка:** `environment: production` удалён из `deploy.yml` (июнь 2026) — деплой теперь полностью автоматический. Если в настройках репозитория остался environment `production` (Settings → Environments) — он больше не используется этим workflow, его наличие/отсутствие ни на что не влияет. Можно удалить через UI при желании.

---

## Деплой упал из-за «грязного working tree»

Pre-flight шаг намеренно падает, если на сервере в `/opt/nura` есть незакоммиченные/непрошенные изменения. Это защита prod-only правок (как было со шрифтами в `FONTS_DEPLOY_REPORT.md` / `INDEX_HTML_COMMIT_REPORT.md`): автоматический деплой НЕ пытается разрешить конфликт сам.

**Действия (паттерн из `PROD_DEPLOY_REPORT.md`):**

```bash
ssh root@45.144.178.118
cd /opt/nura

# 1. Сверка — что именно отличается
git status --porcelain
git diff --stat
git fetch origin
git log --oneline -3 HEAD
git log --oneline -3 origin/main

# 2. Резервная копия каждого изменённого файла (двойная страховка)
TS=$(date -u +%Y%m%d-%H%M%S)
for f in $(git status --porcelain | awk '{print $2}'); do
  cp "$f" "/tmp/${f##*/}.prod-bak-$TS"
done

# 3. Stash prod-only правок
git stash push -m "prod-only-changes-$TS"

# 4. Pull (должен пройти fast-forward)
git pull --ff-only origin main

# 5. Вернуть prod-only правки и разрешить конфликты ВРУЧНУЮ
git stash pop
#    При конфликте: открыть файл, разрешить, git add <file>
#    Если prod-правка уже в репо (дубликат) — взять upstream (//-сторону)
git stash drop stash@{0}   # после успешного resolve

# 6. Применить и зафиксировать
bash deploy.sh
git add -A && git commit -m "sync prod-only changes into repo" && git push origin main
#    push триггернет новый workflow-run — на этот раз pre-flight пройдёт.
```

Если прод-правки уже закоммичены в репо (как `index.html` после `INDEX_HTML_COMMIT_REPORT.md`) — `git stash pop` даст чистый apply, конфликтов не будет.

**Никогда не делайте `git pull` без проверки `git status` — это ровно то, от чего защищает pre-flight.**

---

## Fallback — ручной деплой по SSH

Используется если GitHub Actions недоступен, секреты не настроены, или нужен экстренный деплой.

### Лендинг / PWA-статика

```bash
ssh -i <ssh_key> root@45.144.178.118
cd /opt/nura
git status --porcelain          # ОБЯЗАТЕЛЬНО проверьте чистоту
git pull --ff-only origin main
bash deploy.sh
echo "$(git rev-parse HEAD) - $(date -u +%Y-%m-%dT%H:%M:%SZ)" > /var/www/nura-ai.ru/VERSION
curl -sf https://nura-ai.ru/ > /dev/null && echo OK
```

### Бэкенд-контейнеры (bot/api/celery)

```bash
# Локально (скрипт сам пушит и деплоит через ssh-алиас nura-vps)
bash scripts/deploy.sh          # все контейнеры
bash scripts/deploy.sh bot      # только bot
```

См. `AGENTS.md` → «Deploy commands» для docker-compose вариантов напрямую на сервере.

---

## Проверка после деплоя

```bash
cat /var/www/nura-ai.ru/VERSION                          # SHA + время
curl -sI https://nura-ai.ru/ | head -1                   # HTTP/1.1 200 OK
curl -s https://nura-ai.ru/ | grep -c font-face          # 8 (Manrope/Playfair)
curl -I https://nura-ai.ru/manifest.json | grep -i content-type  # одна строка application/manifest+json
```
