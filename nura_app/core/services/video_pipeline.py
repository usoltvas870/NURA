import json
import logging
import re
import uuid
from pathlib import Path

import httpx

from core.config import settings
from core.services.video_assembler import (
    NURA_ROOT,
    ScenarioConfig,
)

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
TREND_DATA_DIR = NURA_ROOT.parent / "nura-trend-radar" / "data"
JOBS_DIR = NURA_ROOT / "jobs"


def _load_prompt(name: str) -> str:
    path = PROMPTS_DIR / name
    if path.exists():
        return path.read_text("utf-8")
    raise FileNotFoundError(f"Prompt not found: {path}")


def _load_trend_data(path: str | None = None) -> list[dict]:
    if path:
        p = Path(path)
    else:
        p = TREND_DATA_DIR / "trend_top.json"
    if not p.exists():
        raise FileNotFoundError(
            f"No trend_top.json found at {p}. "
            "Run trend radar first or specify --from-trend <path>"
        )
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def _sanitize_name(caption: str) -> str:
    name = caption.strip().lower()[:30]
    name = re.sub(r"[^a-zа-я0-9_]", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    return name or "untitled"


def _match_local_stock(keywords: list[str]) -> str | None:
    media_dir = NURA_ROOT / "videos" / "media"
    if not media_dir.exists():
        return None
    files = list(media_dir.glob("*.mp4")) + list(media_dir.glob("*.mov"))
    scored: list[tuple[int, Path]] = []
    stem_lower = {f: f.stem.lower() for f in files}
    for f in files:
        stem = stem_lower[f]
        matches = sum(1 for kw in keywords
                      if re.search(rf'\b{re.escape(kw.lower())}\b', stem))
        if matches > 0:
            scored.append((matches, f))
    if not scored:
        return None
    scored.sort(key=lambda x: -x[0])
    rel = scored[0][1].relative_to(NURA_ROOT)
    return str(rel).replace("\\", "/")


def _match_local_stock_to_scene(scene: dict) -> dict:
    keywords = scene.get("source_keywords") or []
    if not keywords or scene.get("source"):
        return scene
    matched = _match_local_stock(keywords)
    if matched:
        scene["source"] = matched
    return scene


class VideoPipeline:
    def __init__(
        self,
        trend_data_path: str | None = None,
        dry_run: bool = True,
        use_jobs_dir: bool = False,
    ):
        self.trend_data_path = trend_data_path
        self.dry_run = dry_run
        self.use_jobs_dir = use_jobs_dir
        self.generated: list[Path] = []

    async def run(self, top_n: int = 10) -> list[Path]:
        trend_videos = _load_trend_data(self.trend_data_path)
        videos = trend_videos[:top_n]

        logger.info(f"Pipeline: processing {len(videos)} videos")

        for i, v in enumerate(videos):
            caption = v.get("caption") or "Без описания"
            logger.info(f"[{i + 1}/{len(videos)}] {caption[:60]}")

            brief = None
            ai_analysis = v.get("ai_analysis", "")
            if ai_analysis:
                brief = await self._generate_brief(v, ai_analysis)

            scenario = await self._generate_scenario(v, brief)
            if scenario is None:
                logger.warning("  Skipped — AI returned no valid scenario")
                continue

            self._resolve_stock(scenario)

            if self.use_jobs_dir and brief:
                job_id = self._create_job_dir(brief, scenario, v)
                scenario_path = job_id
            else:
                scenario_path = self._save_scenario(scenario, v)

            self.generated.append(scenario_path)
            logger.info(f"  → {scenario_path.name if scenario_path.is_file() else scenario_path}")

        logger.info(f"Pipeline done. Generated {len(self.generated)} outputs")
        return self.generated

    async def _generate_brief(
        self, video: dict, ai_analysis: str
    ) -> dict | None:
        try:
            prompt_template = _load_prompt("brief_parser.txt")
            user_prompt = prompt_template.format(
                analysis_text=ai_analysis[:8000],
            )
        except FileNotFoundError:
            logger.warning("brief_parser.txt not found, skipping brief generation")
            return None

        system = (
            "Ты — парсер контент-аналитики. "
            "Извлеки из текста структурированный JSON Content Brief. "
            "Отвечай строго в Markdown-блоке ```json, без пояснений."
        )

        try:
            raw = await self._ai_chat(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                max_tokens=4000,
            )
        except Exception as e:
            logger.error(f"Brief generation failed: {e}")
            return None

        parsed = self._parse_json(raw)
        if parsed is None:
            logger.warning("Brief parsing returned no valid JSON")
            return None

        parsed.setdefault("video_id", video.get("video_id", ""))
        parsed.setdefault("url", video.get("url", ""))
        parsed.setdefault("author_username", video.get("author_username", ""))
        parsed.setdefault("original_caption", video.get("caption", ""))
        parsed.setdefault("views", video.get("views", 0))
        parsed.setdefault("likes", video.get("likes", 0))
        parsed.setdefault("comments", video.get("comments", 0))
        parsed.setdefault("shares", video.get("shares", 0))
        parsed.setdefault("engagement_rate", video.get("engagement_rate", 0.0))
        parsed.setdefault("comment_density", video.get("comment_density", 0.0))
        parsed.setdefault("viral_score", video.get("viral_score", 0.0))
        parsed.setdefault("final_score", video.get("final_score", 0.0))
        parsed.setdefault("source_type", video.get("source_type", ""))
        parsed.setdefault("source_value", video.get("source_value", ""))

        from core.schemas.brief import ContentBrief

        try:
            ContentBrief.model_validate(parsed)
        except Exception as e:
            logger.warning(f"Brief validation failed (using partial): {e}")

        return parsed

    async def _generate_scenario(
        self, video: dict, brief: dict | None = None
    ) -> dict | None:
        prompt_template = _load_prompt("video_scenario.txt")
        user_prompt = prompt_template.format(
            caption=(video.get("caption") or "Нет описания")[:500],
            views=video.get("views", "N/A"),
            likes=video.get("likes", "N/A"),
            comments=video.get("comments", "N/A"),
            shares=video.get("shares", "N/A"),
            engagement_rate=(
                f"{video.get('engagement_rate', 0):.2%}"
                if isinstance(video.get("engagement_rate"), (int, float))
                else str(video.get("engagement_rate", "N/A"))
            ),
            viral_score=video.get("viral_score", "N/A"),
            final_score=video.get("final_score", "N/A"),
            author_username=video.get("author_username", "N/A"),
            source_type=video.get("source_type", "N/A"),
            source_value=video.get("source_value", "N/A"),
        )

        if brief:
            user_prompt += (
                f"\n\nДОПОЛНИТЕЛЬНЫЙ КОНТЕКСТ ИЗ BRIEF:\n"
                f"Тема: {brief.get('topic', '')}\n"
                f"Тип хука: {brief.get('hook_type', '')}\n"
                f"Формат: {brief.get('recommended_format', 'type2')}\n"
                f"Тон: {brief.get('tone', '')}\n"
                f"Текст озвучки (draft): {brief.get('draft_voiceover', '')[:500]}\n"
                f"CTA: {brief.get('cta', '')}"
            )

        system = (
            "Ты — режиссёр вирусных видео для проекта NURA. "
            "Твоя задача — написать JSON-сценарий для сборки видео. "
            "Всегда следуй схеме из промпта. Отвечай строго в Markdown-блоке ```json."
        )

        try:
            raw = await self._ai_chat([
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ])
            parsed = await self._parse_json_with_retry(raw, system, user_prompt)
            if parsed is None:
                return None

            parsed.setdefault("nura_video", "videos/media/th_nura.mp4")
            parsed.setdefault("subtitles", {
                "enabled": True,
                "mode": "auto",
                "font_size": 50,
                "color": "#FFFFFF",
                "stroke_color": "#000000",
                "stroke_width": 3.0,
                "y_position": 0.7,
            })
            scenes = parsed.get("scenes", [])
            for s in scenes:
                s.setdefault("source_keywords", [])
                s.setdefault("overlays", [])
                s.setdefault("transition", None)
                s.setdefault("color_grading", {"enabled": False})

            parsed["name"] = _sanitize_name(
                video.get("caption") or video.get("video_id", "video")
            )

            try:
                ScenarioConfig.model_validate(parsed)
            except Exception as e:
                logger.error(f"  Generated scenario failed validation: {e}")
                return None

            return parsed
        except Exception as e:
            logger.error(f"  AI generation failed: {e}")
            return None

    async def _ai_chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 8000,
    ) -> str:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(
                f"{settings.deepseek_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.deepseek_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.deepseek_model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]

    def _parse_json(self, text: str) -> dict | None:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    async def _parse_json_with_retry(
        self, text: str, system: str, user: str
    ) -> dict | None:
        parsed = self._parse_json(text)
        if parsed is not None:
            return parsed

        retry_msg = (
            "Твой ответ содержит невалидный JSON. "
            "Исправь и выдай ТОЛЬКО валидный JSON строго по схеме из промпта "
            "в markdown-блоке ```json, без пояснений."
        )
        try:
            raw2 = await self._ai_chat([
                {"role": "system", "content": system},
                {"role": "user", "content": user},
                {"role": "assistant", "content": text[:2000]},
                {"role": "user", "content": retry_msg},
            ])
            parsed2 = self._parse_json(raw2)
            if parsed2 is not None:
                return parsed2
        except Exception as e:
            logger.error(f"  JSON parse retry failed: {e}")

        logger.error(f"Cannot parse AI response as JSON:\n{text[:500]}")
        return None

    def _resolve_stock(self, scenario: dict) -> None:
        for sc in scenario.get("scenes", []):
            _match_local_stock_to_scene(sc)
            for ov in sc.get("overlays", []):
                if ov.get("type") == "video" and not ov.get("src"):
                    keywords = sc.get("source_keywords") or []
                    matched = _match_local_stock(keywords)
                    if matched:
                        ov["src"] = matched

    def _create_job_dir(
        self, brief: dict, scenario: dict, video: dict
    ) -> Path:
        name = scenario.get("name") or _sanitize_name(
            video.get("caption") or video.get("video_id", "video")
        )
        job_id = f"{name}_{video.get('video_id', uuid.uuid4().hex[:8])[:12]}"
        job_dir = JOBS_DIR / job_id

        input_dir = job_dir / "input"
        media_dir = job_dir / "media"
        work_dir = job_dir / "work"
        output_dir = job_dir / "output"

        for d in (input_dir, media_dir, work_dir, output_dir):
            d.mkdir(parents=True, exist_ok=True)

        scenario_path = input_dir / "scenario.json"
        with open(scenario_path, "w", encoding="utf-8") as f:
            json.dump(scenario, f, ensure_ascii=False, indent=2)

        brief_path = input_dir / "brief.json"
        with open(brief_path, "w", encoding="utf-8") as f:
            json.dump(brief, f, ensure_ascii=False, indent=2)

        logger.info(f"  Job dir: {job_dir.name}")
        return job_dir

    def _save_scenario(self, scenario: dict, video: dict) -> Path:
        scenarios_dir = NURA_ROOT / "scenarios"
        scenarios_dir.mkdir(parents=True, exist_ok=True)

        name = scenario.get("name") or _sanitize_name(
            video.get("caption") or video.get("video_id", "video")
        )
        vid = video.get("video_id", "unknown")[:12]
        path = scenarios_dir / f"{name}_{vid}.json"

        with open(path, "w", encoding="utf-8") as f:
            json.dump(scenario, f, ensure_ascii=False, indent=2)

        return path

    def validate_scenario(self, path: Path) -> bool:
        try:
            raw = json.loads(path.read_text("utf-8"))
            ScenarioConfig.model_validate(raw)
            logger.info(f"  Validated: {path.name}")
            return True
        except Exception as e:
            logger.error(f"  Validation failed: {path.name}: {e}")
            return False

    async def assemble_all(self) -> list[Path]:
        from core.tasks import assemble_video, assemble_video_job

        outputs: list[Path] = []
        for sp in self.generated:
            if sp.is_dir():
                scenario_path = sp / "input" / "scenario.json"
                if not self.validate_scenario(scenario_path):
                    logger.warning(f"  Skipping assembly for {sp.name} (invalid)")
                    continue

                if self.dry_run:
                    logger.info(f"  (dry-run) would assemble job: {sp.name}")
                    continue

                logger.info(f"  Assembling job: {sp.name}")
                result = assemble_video_job(str(sp))
            else:
                name = sp.stem
                if not self.validate_scenario(sp):
                    logger.warning(f"  Skipping assembly for {name} (invalid)")
                    continue

                if self.dry_run:
                    logger.info(f"  (dry-run) would assemble: {name}")
                    continue

                logger.info(f"  Assembling: {name}")
                result = assemble_video(name)

            out = result.get("output")
            if out:
                if isinstance(out, list):
                    outputs.extend(Path(o) for o in out)
                else:
                    outputs.append(Path(out))
                logger.info(f"    Output: {out}")

        return outputs
