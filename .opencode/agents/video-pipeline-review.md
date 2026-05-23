# Agent: Video Pipeline Review

Твоя задача — проанализировать новый конвейер автоматизации видео NURA, найти проблемы и предложить улучшения.

## Контекст

Построен двухэтапный пайплайн:
1. **Trend Radar** (`nura-trend-radar/`) — собирает TikTok видео, скорит, AI пишет сценарий
2. **Video Pipeline** (`nura_app/core/services/video_pipeline.py`) — читает топ-10 трендов → AI генерирует JSON сценарий → сохраняет в `scenarios/` → Video Assembler собирает MP4

## Файлы для анализа

### 1. Проблема обрезания сценариев (главное)

- `nura-trend-radar/src/ai_analyzer.py:94` — `max_tokens=2000` (слишком мало для сценария с 3+ сценами)
- `nura-trend-radar/prompts/pattern_analysis_ru.txt` — старый промпт, AI пишет в свободной форме с блоками `===СЦЕНАРИЙ N===`
- `nura-trend-radar/src/report.py:245` — `_parse_scenario_block()` хрупкий парсинг этих блоков
- `nura_app/core/prompts/video_scenario.txt` — новый промпт, но `video_pipeline.py` использует `max_tokens=4000` — тоже может быть мало

### 2. Весь пайплайн

- `nura-trend-radar/run_radar.py` — точка входа радара (экспорт `trend_top.json` для пайплайна)
- `nura-trend-radar/src/report.py` — генерация отчётов (MD, XLSX, txt)
- `nura_app/core/services/video_pipeline.py` — оркестратор
- `nura_app/core/services/video_assembler.py` — сборщик видео (FFmpeg subprocess)
- `nura_app/core/prompts/video_scenario.txt` — новый промпт для AI (генерация JSON по схеме ScenarioConfig)
- `scripts/run_pipeline.py` — CLI для запуска

### 3. Валидация

- `nura_app/core/services/video_assembler.py` — Pydantic схемы: `Scene`, `ScenarioConfig`, `Transition`, `ColorGrading`, оверлеи
- Сейчас новые JSON-сценарии валидируются через `ScenarioConfig.model_validate()`

## Что делать

1. **Изучи все файлы выше** — внимательно прочитай код, промпты, схемы
2. **Найди конкретные баги и узкие места**:
   - Где и почему AI-сценарии обрезаются/неполные (главная проблема пользователя)
   - max_tokens в обоих AI вызовах — хватает ли?
   - Парсинг ответа AI — есть ли fallback при невалидном JSON?
   - Совместимость форматов: что приходит из Trend Radar → что ожидает Pipeline → что нужно Assembler'y
   - source_keywords → матчинг локальных стоков работает?
   - Обработка ошибок: что если AI вернул не JSON?
   - Что если нет trend_top.json?
   - Celery задачи и синхронные вызовы — нет ли race condition?
   - Subtitles mode="auto" требует faster-whisper — есть ли fallback?
3. **Разберись с написанием сценариев**: почему в папке `data/reports/` и `data/scenarios/` AI-сценарии обрезанные/неполные. Проверь:
   - `ai_analyzer.py` format строки промпта
   - `_parse_scenario_block` — корректно ли парсит
   - Что AI реально возвращает (структура ответа, длина)
   - Сравни старый промпт (`pattern_analysis_ru.txt`) и новый (`video_scenario.txt`)
4. **Верни структурированный ответ**:

```markdown
## 🔴 Найденные проблемы

### Проблема 1: [короткое название]
- Где: файл:строка
- В чём: 
- Почему плохо:
- Как исправить:

### Проблема 2: ...
...

## 🟡 Уязвимости архитектуры
- ...

## 💡 Улучшения
- ...

## Главное: причины обрезания сценариев
- Причина 1:
- Причина 2:
- Решение:
```

Не предлагай изменения в коде — только анализ. Это ревью перед тем, как вносить правки.
