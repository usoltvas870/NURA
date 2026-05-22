# Video Assembler v2

Автоматическая сборка видео для NURA по JSON-сценарию.
FFmpeg subprocess бэкенд с GPU-ускорением.

## Архитектура

```
scenarios/*.json
    │
    ▼
core/services/video_assembler.py
    │
    ├── Pydantic-валидация сценария
    ├── SRT-генерация (manual / Whisper, с adjustment под транзишены)
    ├── FFmpeg filter_complex граф (subprocess)
    │   ├── trim + setpts (нарезка сцен)
    │   ├── zoompan + easing (zoom с cubic-bezier)
    │   ├── drawtext (текстовые оверлеи)
    │   ├── movie + overlay (PiP-видео / изображения)
    │   ├── xfade (переходы между сценами — dissolve, slide, fade, wipe…)
    │   ├── acrossfade (аудио-кроссфейд)
    │   └── subtitles (libass, стилизованные субтитры)
    └── libx264 / hevc_nvenc → MP4
        │
        ▼
    videos/output/*.mp4
```

## Зависимости

| Пакет | Обязательный | Зачем |
|-------|-------------|-------|
| `imageio_ffmpeg` | ✅ Да | Встроенный FFmpeg (прямая зависимость, не через moviepy) |
| `faster-whisper>=1.1` | ❌ Нет | Автоматические субтитры по голосу |

FFmpeg 7.1 essentials входит в `imageio_ffmpeg`. Используются фильтры: `xfade`, `acrossfade`, `zoompan`, `drawtext`, `overlay`, `subtitles`, `colorbalance`, `curves`, `gblur`, `blend`.

## JSON-сценарий

### Полная схема

```json
{
  "name": "nura_promo",
  "nura_video": "videos/media/nura_talking.mp4",
  "subtitles": {
    "enabled": true,
    "mode": "manual",
    "font_size": 20,
    "color": "#FFFFFF",
    "stroke_color": "#000000",
    "stroke_width": 2.0
  },
  "scenes": [
    {
      "start": 0,
      "duration": 5,
      "transition": {"type": "dissolve", "duration": 0.5},
      "nura_text": "Текст который говорит Нура в этом отрезке.",
      "overlays": [...]
    }
  ]
}
```

### Поля сцены

| Поле | Тип | По умолч. | Описание |
|------|-----|-----------|----------|
| `start` | float | 0 | Начало сцены в исходном видео (сек) |
| `duration` | float | — | Длительность сцены (сек). **0 = авто:** оставшаяся длительность исходного видео от `start` до конца. |
| `transition` | object \| null | null | Переход на входе этой сцены |
| `transition.type` | str | `"dissolve"` | Тип: `dissolve`, `fade`, `fadeblack`, `fadewhite`, `slideleft`, `slideright`, `slideup`, `slidedown`, `smoothleft`, `smoothright`, `smoothup`, `smoothdown`, `zoomin`, `wipe`, `pixelize`, `hblur`, `circleclip`, `rectcrop` и др. (~30 типов) |
| `transition.duration` | float | 0.5 | Длительность перехода (сек) |
| `nura_text` | str \| null | null | Текст речи Nura (для субтитров) |

**Важно:** transition указывается на **входной** сцене. Пример: переход между Scene[0] и Scene[1] задаётся в `scenes[1].transition`.

### Типы оверлеев

**text** — текстовое наложение через `drawtext`:
```json
{
  "type": "text",
  "text": "НУРА",
  "start": 0, "end": 3.0,
  "x": 0, "y": -0.3,
  "font_size": 48,
  "color": "#FF6B00"
}
```
- `start`, `end` — время показа (сек, относительно начала сцены)
- `x, y` — float (-1..1 = процент экрана, >1 = пиксели, или строка `"center"`, `"left"`, `"right"`, `"top"`, `"bottom"`)

**zoom** — плавное приближение/отдаление с easing:
```json
{
  "type": "zoom",
  "start": 1.0,
  "duration": 2.0,
  "from_scale": 1.0,
  "to_scale": 1.15,
  "easing": "cubic-in-out"
}
```
- `easing`: `"linear"`, `"cubic-in"`, `"cubic-out"`, `"cubic-in-out"` (по умолчанию)

**video** — PiP-видео поверх Nura:
```json
{
  "type": "video",
  "src": "videos/media/stock.mp4",
  "start": 0, "end": 5.0,
  "x": 0.5, "y": 0,
  "width": 0.35
}
```
- `width, height` — float (0-1 = процент экрана) или int (пиксели)

**image** — статичное изображение:
```json
{
  "type": "image",
  "src": "videos/media/logo.png",
  "start": 0, "end": 3.0,
  "x": -0.4, "y": -0.4,
  "width": 0.15
}
```

### Цветокоррекция (per-scene)

Добавляется полем `color_grading` в сцену:

```json
{
  "start": 0,
  "duration": 10,
  "color_grading": {
    "enabled": true,
    "shadows_red": 0.05,
    "shadows_blue": -0.05,
    "midtones_red": 0.08,
    "midtones_green": 0.03,
    "highlights_red": 0.03,
    "highlights_blue": 0.05,
    "glow": true,
    "glow_radius": 12,
    "glow_opacity": 0.15
  }
}
```

**Color balance** (FFmpeg `colorbalance`): 9 параметров `shadows_*` / `midtones_*` / `highlights_*` для R/G/B каналов. Диапазон -1..1. Ноль — без изменений.

**Glow/bloom** (`split` → `gblur` → `blend` screen): мягкое свечение. `glow_radius` — sigma размытия, `glow_opacity` — интенсивность.

## CLI

```bash
python scripts/assemble.py scenarios/example.json
```

## Output

- `videos/output/{name}.mp4` — готовое видео (H.264 или HEVC)
- `videos/output/{name}_subtitles.srt` — субтитры с adjusted таймингами

## Пути

Все относительные пути резолвятся от корня проекта (`NURA_ROOT`).
Пример: `videos/media/test.mp4` → `C:\git\NURA\videos\media\test.mp4`

## Субтитры

### make_srt (основной API)
`make_srt(cfg, video_path)` — выбирает режим по `cfg.subtitles.mode`:
- `"manual"` → `_srt_lines()` — разбивка текста на чанки по ~3s
- `"auto"` → `_auto_srt()` — Whisper-транскрипция

В `assemble()` всегда вызывается `make_srt`, а не `_srt_lines` напрямую.

### Manual (по умолчанию)
Текст режется на чанки по ~3 секунды равномерно. Тайминги автоматически корректируются с учётом транзишенов (каждый переход сокращает таймлайн на `transition.duration`).

### Auto (требуется `faster-whisper`)
Whisper транскрибирует аудио, получает покадровые тайминги.

```bash
pip install faster-whisper
```

## GPU-ускорение

Автоматически определяется доступность `hevc_nvenc` и загружаемость CUDA-драйвера.

| Кодек | Скорость | Качество |
|-------|----------|----------|
| libx264 (CPU) | 0.5-1.5x realtime | CRF 18 — отличное |
| hevc_nvenc (GPU) | 3-10x realtime | CQ 23 — визуально идентично |

Без NVIDIA GPU всегда используется libx264.

## Сборка: что под капотом

Для сценария с 3 сценами генерируется фильтр-граф из ~13 нод:

```
[0:v]trim=0:5,setpts=PTS-STARTPTS,fps=24     → сцена 0 видео
[0:a]atrim=0:5,asetpts=PTS-STARTPTS           → сцена 0 аудио
zoompan + drawtext                             → эффекты сцены 0
[0:v]trim=5:10,...                             → сцена 1
movie source + overlay                         → PiP сцены 1
xfade(сцена0, сцена1)                          → переход
acrossfade(аудио0, аудио1)                     → аудио-переход
[0:v]trim=10:15,...                            → сцена 2
xfade(prev, сцена2)                            → второй переход
subtitles                                      → libass субтитры
→ libx264 / hevc_nvenc → MP4
```

## Celery-задача

```python
# Асинхронная сборка видео
from core.tasks import assemble_video
assemble_video.delay("example")  # загрузит scenarios/example.json
```

Задача `core.tasks.assemble_video` принимает имя сценария (без `.json`), загружает его из `scenarios/`, собирает видео и возвращает путь к выходному MP4.

## Известные ограничения
- Оверлеи video/image используют `movie`-фильтр (не `-i`), что может не поддерживать некоторые экзотические кодеки
- Позиционирование текста: `y=-0.3` = 30% от верха (top-left), см. `_pos_px()`
- Множественные zoom-эффекты в одной сцене — поддерживаются (обрабатываются все, не только первый)

## Рабочий процесс

1. Генерируешь видео с говорящей головой Nura → `videos/media/`
2. Готовишь стоковые видео/B-roll → туда же
3. Прописываешь JSON-сценарий → `scenarios/`
4. Запускаешь сборку → получаешь MP4
5. Правишь JSON, пересобираешь заново
