import asyncio
import logging
from typing import Optional

import httpx

from utils import get_config, get_config_bool

logger = logging.getLogger(__name__)


async def send_digest(
    top_videos: list[dict],
    ai_analyses: Optional[list[dict]] = None,
) -> bool:
    enabled = get_config_bool('ENABLE_TELEGRAM', False)
    if not enabled:
        logger.info("Telegram disabled")
        return False

    token = get_config('TELEGRAM_BOT_TOKEN')
    chat_id = get_config('TELEGRAM_CHAT_ID')

    if not token or not chat_id:
        logger.warning("Telegram token/chat_id not configured")
        return False

    analysis_map = {}
    if ai_analyses:
        for a in ai_analyses:
            analysis_map[a.get('video_id')] = a.get('ai_analysis', '')

    for i, v in enumerate(top_videos[:10]):
        caption = (v.get('caption') or 'Без описания')[:100]
        analysis = analysis_map.get(v.get('video_id'), '')
        lines = (analysis.strip().split('\n')[:3] if analysis else [])
        insight = '\n'.join(lines)[:200]

        text = (
            f'📹 *{i + 1}. {caption}*\n'
            f'👤 {v.get("author_username", "unknown")}\n'
            f'👁 {v.get("views", "N/A")} views\n'
            f'❤️ {v.get("likes", "N/A")} | ER {v.get("engagement_rate", 0):.1%}\n'
            f'🔗 {v.get("url", "#")}\n'
        )
        if insight:
            text += f'\n💡 {insight}\n'

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f'https://api.telegram.org/bot{token}/sendMessage',
                    json={
                        'chat_id': chat_id,
                        'text': text,
                        'parse_mode': 'Markdown',
                        'disable_web_page_preview': False,
                    },
                )
                resp.raise_for_status()
                logger.info(f"Telegram msg {i + 1} sent")
        except Exception as e:
            logger.error(f"Telegram failed: {e}")

        if i < min(len(top_videos[:10]), 10) - 1:
            await asyncio.sleep(0.5)

    return True
