#!/usr/bin/env python3
"""
Nura TikTok Viral Screening Radar — MVP

Сбор и анализ TikTok-роликов для поиска вирусного контента.
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from utils import (
    load_env, setup_logging, get_config_int, get_config_bool,
    read_source_file,
)
from storage import init_db, get_connection, save_video
from collector import TikTokCollector
from scoring import compute_scores
from ai_analyzer import analyze_top_videos
from telegram import send_digest
from report import generate_report, save_report, save_xlsx, save_ai_analyses, save_scenarios_xlsx, save_carousel_texts

logger = logging.getLogger('run_radar')


async def main():
    setup_logging()
    load_env()

    logger.info('=' * 60)
    logger.info('Nura TikTok Viral Screening Radar — MVP')
    logger.info('=' * 60)

    competitors = read_source_file('competitors.txt')
    hashtags = read_source_file('hashtags.txt')
    keywords = read_source_file('keywords.txt')
    rotational_raw = read_source_file('rotational.txt')

    rotational_h = [e for e in rotational_raw if len(e.split()) == 1]
    rotational_k = [e for e in rotational_raw if len(e.split()) > 1]

    logger.info(f'Competitors: {len(competitors)}, '
                f'Hashtags: {len(hashtags)}, '
                f'Keywords: {len(keywords)}, '
                f'Rotational: {len(rotational_h)} hashtags + {len(rotational_k)} keywords')

    sources = {
        'competitors': competitors,
        'hashtags': hashtags,
        'keywords': keywords,
        'rotational': {'hashtags': rotational_h, 'keywords': rotational_k},
    }

    total = len(competitors) + len(hashtags) + len(keywords) + len(rotational_raw)
    if total == 0:
        logger.warning('No sources found. Fill config files in config/')
        return

    init_db()
    conn = get_connection()

    try:
        headless = get_config_bool('HEADLESS', True)
        collector = TikTokCollector(headless=headless)

        await collector.start()
        try:
            videos = await collector.collect_all(sources)
            videos = await collector.enrich_missing_stats(videos)
        finally:
            await collector.close()

        logger.info(f'Total videos collected: {len(videos)}')
        if not videos:
            logger.warning('No videos found. Check config and TikTok availability.')
            return

        new_count = 0
        for v in videos:
            if save_video(conn, v):
                new_count += 1
        conn.commit()

        logger.info(f'New videos saved: {new_count}')

        def _is_playlist(v: dict) -> bool:
            if v.get('is_playlist'):
                return True
            caption = v.get('caption') or ''
            return caption.startswith('[Playlist]')

        real_videos = [v for v in videos if not _is_playlist(v)]
        playlists = [v for v in videos if _is_playlist(v)]

        min_views = get_config_int('MIN_VIEWS', 10000)

        scored = compute_scores(real_videos)
        with_views = [
            v for v in scored
            if v.get('views') is not None and v['views'] >= min_views
        ]
        without_views = [
            v for v in scored
            if v.get('views') is None
        ]
        top_videos = (with_views[:30] + without_views[:max(0, 30 - len(with_views))])[:30]

        logger.info(f'Videos with views >= {min_views}: {len(with_views)}, '
                    f'without views: {len(without_views)}, '
                    f'playlists: {len(playlists)}, '
                    f'in report: {len(top_videos)}')

        ai_analyses = []
        if get_config_bool('ENABLE_AI_ANALYSIS', False) and top_videos:
            logger.info('Running AI analysis on top 10...')
            ai_analyses = await analyze_top_videos(top_videos[:10])

        stats = {
            'date': collector.collected_at,
            'run_id': collector.run_id,
            'sources_processed': total,
            'videos_found': len(videos),
            'new_videos': new_count,
            'min_views': min_views,
        }

        report_md = generate_report(stats, top_videos, ai_analyses, playlists)
        report_path = save_report(report_md)

        analysis_map = {}
        if ai_analyses:
            for a in ai_analyses:
                analysis_map[a.get('video_id')] = a

        if get_config_bool('EXPORT_XLSX', True):
            xlsx_path = save_xlsx(top_videos, analysis_map)
        else:
            xlsx_path = None

        if ai_analyses:
            try:
                ai_dir = save_ai_analyses(top_videos, analysis_map)
            except Exception as e:
                logger.error(f'Failed to save AI analysis files: {e}')
                ai_dir = None
        else:
            ai_dir = None

        try:
            scenarios_path = save_scenarios_xlsx(top_videos, analysis_map)
        except Exception as e:
            logger.error(f'Failed to save scenarios XLSX: {e}')
            scenarios_path = None

        try:
            carousel_dir = save_carousel_texts(top_videos, analysis_map)
        except Exception as e:
            logger.error(f'Failed to save carousel texts: {e}')
            carousel_dir = None

        print()
        logger.info('=' * 60)
        logger.info(f'REPORT: {report_path}')
        if xlsx_path:
            logger.info(f'XLSX:   {xlsx_path}')
        if ai_dir:
            logger.info(f'AI:     {ai_dir}')
        if scenarios_path:
            logger.info(f'SCENARIOS: {scenarios_path}')
        if carousel_dir:
            logger.info(f'CAROUSELS: {carousel_dir}')
        logger.info('=' * 60)
        print()
        print(f'\u2502 Sources:     {total}')
        print(f'\u2502 Found:       {len(videos)}')
        print(f'\u2502 New:         {new_count}')
        print(f'\u2502 Top report:  {len(top_videos)}')
        print()

        if top_videos:
            print('TOP-5:')
            for i, v in enumerate(top_videos[:5]):
                cap = (v.get('caption') or '\u0411\u0435\u0437 \u043e\u043f\u0438\u0441\u0430\u043d\u0438\u044f')[:60]
                print(f'  {i + 1}. {cap}')
                print(f'     Views: {v.get("views", "?")}  '
                      f'Score: {v.get("final_score", 0)}  '
                      f'@{v.get("author_username", "?")}')
                print()

        # ── export top-10 for Video Pipeline ──
        try:
            import json as _json

            trend_data_path = Path(__file__).parent / 'data' / 'trend_top.json'
            trend_data_path.parent.mkdir(parents=True, exist_ok=True)
            export_data = []
            for v in top_videos[:10]:
                export_data.append({
                    'video_id': v.get('video_id'),
                    'url': v.get('url'),
                    'author_username': v.get('author_username'),
                    'caption': v.get('caption'),
                    'views': v.get('views'),
                    'likes': v.get('likes'),
                    'comments': v.get('comments'),
                    'shares': v.get('shares'),
                    'engagement_rate': v.get('engagement_rate'),
                    'comment_density': v.get('comment_density'),
                    'viral_score': v.get('viral_score'),
                    'final_score': v.get('final_score'),
                    'subscriber_potential': v.get('subscriber_potential'),
                    'source_type': v.get('source_type'),
                    'source_value': v.get('source_value'),
                    'ai_analysis': v.get('ai_analysis'),
                })
            with open(trend_data_path, 'w', encoding='utf-8') as f:
                _json.dump(export_data, f, ensure_ascii=False, indent=2)
            logger.info(f"Trend top-10 exported: {trend_data_path}")
        except Exception as e:
            logger.warning(f"Failed to export trend top-10: {e}")

        if get_config_bool('ENABLE_TELEGRAM', False):
            logger.info('Sending Telegram digest...')
            await send_digest(top_videos, ai_analyses)

        logger.info('Done!')
    finally:
        conn.close()


if __name__ == '__main__':
    asyncio.run(main())
