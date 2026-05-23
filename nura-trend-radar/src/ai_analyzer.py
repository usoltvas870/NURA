import logging
from typing import Optional

import httpx

from utils import get_config, get_config_bool, PROJECT_ROOT

logger = logging.getLogger(__name__)

PROMPT_PATH = PROJECT_ROOT / 'prompts' / 'pattern_analysis_ru.txt'


def load_prompt() -> str:
    if PROMPT_PATH.exists():
        with open(PROMPT_PATH, 'r', encoding='utf-8') as f:
            return f.read()

    return (
        'Ты — аналитик вирусного контента. Проанализируй TikTok-ролик по пунктам:\n'
        '1. Почему вирусным?\n'
        '2. Тип хука\n'
        '3. Эмоциональный триггер\n'
        '4. Структура ролика\n'
        '5. Адаптация под Nura\n'
        '6. 3 сценария для Nura\n\n'
        'Данные:\n'
        '- Caption: {caption}\n'
        '- Просмотры: {views}\n'
        '- Лайки: {likes}\n'
        '- Комментарии: {comments}\n'
        '- Репосты: {shares}\n'
        '- Engagement Rate: {engagement_rate:.2%}\n'
        '- Comment Density: {comment_density:.4%}\n'
        '- Viral Score: {viral_score}\n'
        '- Final Score: {final_score}\n'
        '- Subscriber Potential: {subscriber_potential}/10\n'
        '- Источник: {source_type} / {source_value}'
    )


async def analyze_video(video: dict) -> Optional[str]:
    enabled = get_config_bool('ENABLE_AI_ANALYSIS', False)
    if not enabled:
        return None

    api_key = get_config('DEEPSEEK_API_KEY')
    if not api_key:
        logger.warning("ENABLE_AI_ANALYSIS=true but DEEPSEEK_API_KEY not set")
        return None

    base_url = get_config('DEEPSEEK_BASE_URL', 'https://api.deepseek.com')
    model = get_config('DEEPSEEK_MODEL', 'deepseek-chat')
    prompt_template = load_prompt()

    system_prompt = (
        'Ты — аналитик вирусного контента проекта Nura. '
        'Nura — проект на стыке матрицы судьбы, нумерологии и психологии. '
        'Аудитория: женщины 25–40, ищущие ответы о предназначении, отношениях, '
        'самооценке, кармических сценариях. Отвечай на русском языке, '
        'структурируй ответ строго по запрошенным пунктам.'
    )

    user_prompt = prompt_template.format(
        caption=(video.get('caption') or 'Нет описания')[:500],
        views=video.get('views', 'N/A'),
        likes=video.get('likes', 'N/A'),
        comments=video.get('comments', 'N/A'),
        shares=video.get('shares', 'N/A'),
        engagement_rate=video.get('engagement_rate', 0),
        comment_density=video.get('comment_density', 0),
        viral_score=video.get('viral_score', 'N/A'),
        final_score=video.get('final_score', 'N/A'),
        subscriber_potential=video.get('subscriber_potential', 'N/A'),
        source_type=video.get('source_type', 'N/A'),
        source_value=video.get('source_value', 'N/A'),
        author_username=video.get('author_username', 'N/A'),
    )

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f'{base_url}/chat/completions',
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json',
                },
                json={
                    'model': model,
                    'messages': [
                        {'role': 'system', 'content': system_prompt},
                        {'role': 'user', 'content': user_prompt},
                    ],
                    'temperature': 0.7,
                    'max_tokens': 8000,
                },
            )
            resp.raise_for_status()
            result = resp.json()
            content = result['choices'][0]['message']['content']
            logger.info(f"AI analysis done for {video.get('video_id', '?')}")
            return content
    except Exception as e:
        logger.error(f"AI analysis failed: {e}")
        return None


async def analyze_top_videos(videos: list[dict]) -> list[dict]:
    eligible = [
        v for v in videos
        if v.get('views') is not None
        and v['views'] > 0
        and not (v.get('caption') or '').startswith('[Playlist]')
        and not v.get('is_playlist')
    ]
    skipped = len(videos) - len(eligible)
    if skipped:
        logger.warning(
            f'Skipping {skipped} videos for AI analysis '
            f'(no views, playlist, or junk data)'
        )

    top = eligible[:10]
    if not top:
        logger.warning('No eligible videos for AI analysis — all skipped')
        return []

    for i, v in enumerate(top):
        logger.info(f"AI analyzing {i + 1}/{len(top)}: {v.get('video_id', '?')}")
        analysis = await analyze_video(v)
        v['ai_analysis'] = analysis
        if i < len(top) - 1:
            import asyncio
            await asyncio.sleep(1)
    return top
