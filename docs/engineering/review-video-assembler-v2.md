# Review Prompt: Video Assembler v2

Проверь реализацию Video Assembler v2. Файлы для ревью:

- `nura_app/core/services/video_assembler.py` — основной код
- `docs/engineering/video-assembler.md` — документация
- `scenarios/example.json` — пример сценария
- `scenarios/stock_test.json` — сценарий с PiP

## Контекст

Полная переработка: MoviePy → FFmpeg subprocess. Задача — CapCut-level качество сборки видео (переходы, easing, цветокоррекция) при автоматизации через JSON-сценарий.

## Что проверять

### 1. Корректность генерации filter_complex

- Разбери собранную filter_complex строку для сценария с 3 сценами (запусти `python scripts/assemble.py scenarios/example.json` с отловом ошибок)
- Убедись, что каждая сцена: trim→setpts→fps→эффекты→выходной label
- Убедись, что zoompan: d=1 (1 выходной кадр на 1 входной), fps=24, s=WxH
- Убедись, что drawtext: enable='between(t,start,end)', fontcolor=0xHEX, текст экранирован
- Убедись, что movie source + overlay: setpts=PTS+start/TB (сдвиг тайминга), enable на оверлее
- Убедись, что xfade: offset корректный (cur_dur - trans_dur), цепочка для N>2 сцен
- Убедись, что acrossfade: d=trans_dur, цепочка синхронно с xfade
- Убедись, что subtitles: original_size=WxH, путь с экранированным двоеточием (C\\:)

### 2. Транзишены

- Проверь расчёт offset для xfade: `offset = current_dur - transition.duration`
- Проверь накопление current_dur: `cur + scene[i].duration - td`
- Проверь, что transition берётся со **входной** сцены (`scenes[i].transition` для i>=1)
- Проверь случай 1 сцены (без xfade)
- Проверь случай DEFAULT transition (если transition=None, то 0.5s dissolve)

### 3. Easing на zoom

- Проверь `_zoom_z_expr()`: правильно ли строится выражение с `on` (output frame number)
- Проверь, что z=from_scale при on < z_start, z=to_scale при on > z_end, и easing между ними
- Проверь подстановку easing: `_ease_fn().replace("t", "(on-z0)/zd")`
- Проверь, что zoompan применяется к **относительному** таймлайну сцены (после trim+setpts)

### 4. SRT

- Проверь `_srt_lines()`: вычитается ли `off` (накопленный transition offset) из `sc.start`
- Проверь, что `off` инкрементируется ПОСЛЕ обработки сцены, на основе transitions[si+1]
- Проверь формат SRT: `HH:MM:SS,mmm --> HH:MM:SS,mmm`
- Проверь корректность при отсутствии transition (off=0)

### 5. PiP / Image overlays

- Проверь, что movie source использует `_ffpath_filter()` (escape двоеточия)
- Проверь, что PTS overlay сдвинут: `setpts=PTS+{start}/TB`
- Проверь, что enable на overlay совпадает с таймингом оверлея
- Проверь, что scale применяется ДО setpts+PTS (правильный порядок фильтров)

### 6. Безопасность и краевые случаи

- Путь с пробелами в drawtext/movie/subtitles — корректно ли экранируется
- Текст оверлея с кавычками/двоеточиями/равно — `_esc()` корректно?
- Путь с кириллицей
- overlay.end=None → end=sc.duration (длительность сцены)
- overlay.start == overlay.end → skip
- overlay.src не существует → warning + continue
- probed WxH с `0x31637661` hex-тегами — регекс `Stream.*Video.*[, ](\d+)x(\d+)[,\s\]]` не должен их цеплять

### 7. GPU detection

- `_has_gpu()` проверяет наличие `hevc_nvenc` в списке encoder-ов
- Дополнительная верификация через `-init_hw_device cuda=test:0` — падает если нет CUDA runtime
- Fallback на libx264 если GPU недоступен

### 8. Совместимость

- Публичный API: `assemble(cfg: ScenarioConfig) -> Path` — не изменился
- Pydantic модели: добавились `Transition`, `ZoomEffect.easing`, остальные поля без изменений
- Старые сценарии без `transition` и `easing` должны работать (default значения)

### 9. Ошибки и регрессии

- Проверь, что `_make_text()`, `_find_font()`, `_ZoomFunc`, moviepy-импорты удалены
- Проверь, что monkey-patch `compose_mask` удалён
- `import json` — не используется (удалён)

## Команды для тестирования

```bash
# Lint
cd nura_app && ruff check core/services/video_assembler.py

# Сборка базового сценария
python scripts/assemble.py scenarios/example.json

# Сборка с PiP
python scripts/assemble.py scenarios/stock_test.json

# Проверка output
ffprobe -hide_banner -i videos/output/nura_promo.mp4 2>&1
```

## Критерии приёмки

- [x] filter_complex корректен для 1, 2, 3+ сцен
- [x] xfade transition работает (dissolve, fade, slideleft проверены)
- [x] Zoom с easing работает (cubic-in-out плавный, не дёрганый)
- [x] drawtext появляется/исчезает по enable/between
- [x] PiP видео отображается в правильном окне
- [x] Субтитры совпадают с речью (adjusted тайминги)
- [x] GPU fallback корректный (CPU encoding при отсутствии CUDA)
- [x] ruff lint — 0 ошибок
- [x] Документация соответствует коду

## Результаты ревью (17.05.2026)

### 🔴 Найдены баги (исправлены)

| # | Баг | Файл | Исправление |
|---|-----|------|-------------|
| 1 | **Zoom break** — `break` после первого zoom, остальные игнорируются | `video_assembler.py:334` | Убран `break` |
| 2 | **duration=0** — `trim=duration=0` ломает сцену (нет кадров) | `video_assembler.py:327` | Добавлен `_probe_duration()`, при `duration=0` → `total_dur - start` |
| 3 | **Авто-субтитры не работают** — `assemble()` вызывает `_srt_lines` вместо `make_srt`, Whisper никогда не используется | `video_assembler.py:295` | Заменён вызов на `make_srt(cfg, vp)` |
| 4 | **moviepy не используется** — в requirements, но код работает через прямой FFmpeg subprocess | `requirements.txt` | Убран |
| 5 | **Нет Celery-задачи** — сборка только через CLI | `tasks.py` | Добавлена `assemble_video` |
