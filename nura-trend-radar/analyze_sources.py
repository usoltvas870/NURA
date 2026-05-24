#!/usr/bin/env python3
"""
Анализ хештегов и ключевых слов на основе реальных данных TikTok.
Собирает видео по текущим конфигам, извлекает хештеги,
собирает поисковые подсказки и выдаёт рекомендации.
"""

import asyncio
import json
import logging
import sys
import re
from pathlib import Path
from collections import Counter
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent / 'src'))
from utils import load_env, setup_logging, read_source_file
from collector import TikTokCollector

logger = logging.getLogger('analyze')

def extract_hashtags(text: str | None) -> list[str]:
    if not text:
        return []
    return re.findall(r'#(\w+)', text.lower())


async def fetch_search_suggestions(keyword: str) -> list[str]:
    """Получить поисковые подсказки TikTok через API."""
    url = f'https://www.tiktok.com/api/search/suggest/?keyword={quote(keyword)}'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://www.tiktok.com/',
    }
    import httpx
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(url, headers=headers, timeout=10, follow_redirects=True)
            if r.status_code != 200:
                return []
            data = r.json()
            suggestions = []
            for item in data.get('data', []):
                text = item.get('keyword') or item.get('suggest_word') or ''
                if text:
                    suggestions.append(text)
            return suggestions
        except Exception as e:
            logger.debug(f'Suggest API error for "{keyword}": {e}')
            return []


async def main():
    setup_logging()
    load_env()
    logger.info('=' * 60)
    logger.info('Анализ источников: сбор статистики по хештегам и ключевым словам')
    logger.info('=' * 60)

    # Загружаем конфиги
    hashtags = read_source_file('hashtags.txt')
    keywords = read_source_file('keywords.txt')
    rotational_raw = read_source_file('rotational.txt')
    rotational_h = [e for e in rotational_raw if len(e.split()) == 1]
    rotational_k = [e for e in rotational_raw if len(e.split()) > 1]

    all_hashtags = list(dict.fromkeys(hashtags + rotational_h))
    all_keywords = list(dict.fromkeys(keywords + rotational_k))

    logger.info(f'Хештегов для анализа: {len(all_hashtags)}')
    logger.info(f'Ключевых слов для анализа: {len(all_keywords)}')

    # Сбор через коллектор
    collector = TikTokCollector(headless=False)
    await collector.start()

    hashtag_stats = {}
    keyword_stats = {}

    try:
        # --- Хештеги ---
        logger.info('\n--- Сбор по хештегам ---')
        for tag in all_hashtags:
            logger.info(f'  #{tag}...')
            videos = await collector.collect_from_hashtag(tag)
            await asyncio.sleep(2)

            all_tags = Counter()
            captions = []
            for v in videos[:30]:
                caption = v.get('caption', '') or ''
                captions.append(caption)
                for ht in extract_hashtags(caption):
                    all_tags[ht] += 1

            top_tags = all_tags.most_common(20)
            hashtag_stats[tag] = {
                'videos_found': len(videos),
                'unique_hashtags': len(all_tags),
                'top_tags': [{'tag': t, 'count': c} for t, c in top_tags],
                'example_captions': captions[:5],
            }
            logger.info(f'    Видео: {len(videos)}, уникальных хештегов: {len(all_tags)}')
            if top_tags:
                logger.info(f'    Топ-5: {", ".join(f"#{t} ({c})" for t, c in top_tags[:5])}')

        # --- Ключевые слова ---
        logger.info('\n--- Сбор по ключевым словам ---')
        for kw in all_keywords:
            logger.info(f'  "{kw}"...')
            videos = await collector.collect_from_keyword(kw)
            await asyncio.sleep(2)

            all_tags = Counter()
            captions = []
            for v in videos[:30]:
                caption = v.get('caption', '') or ''
                captions.append(caption)
                for ht in extract_hashtags(caption):
                    all_tags[ht] += 1

            keyword_stats[kw] = {
                'videos_found': len(videos),
                'unique_hashtags': len(all_tags),
                'top_tags': [{'tag': t, 'count': c} for t, c in all_tags.most_common(20)],
                'example_captions': captions[:5],
            }
            logger.info(f'    Видео: {len(videos)}, уникальных хештегов: {len(all_tags)}')
            if all_tags:
                logger.info(f'    Топ-5: {", ".join(f"#{t} ({c})" for t, c in all_tags.most_common(5))}')

    finally:
        await collector.close()

    # --- Поисковые подсказки ---
    logger.info('\n--- Поисковые подсказки TikTok ---')
    base_terms = [
        'матрица судьбы', 'нумерология', 'кармический хвост',
        'предназначение', 'женская энергия', 'число судьбы',
        'destiny matrix', 'numerology', 'life path',
    ]
    suggestions = {}
    for term in base_terms:
        s = await fetch_search_suggestions(term)
        suggestions[term] = s
        logger.info(f'  "{term}": {", ".join(s[:8]) if s else "нет подсказок"}')
        await asyncio.sleep(1)

    # --- Сводка ---
    print('\n\n' + '=' * 60)
    print('ОТЧЁТ ПО АНАЛИЗУ ИСТОЧНИКОВ')
    print('=' * 60)

    print(f'\n{"ХЕШТЕГ":25s} {"Видео":>8s} {"Уник.теги":>10s} {"Статус":>12s}')
    print('-' * 55)
    for tag in all_hashtags:
        s = hashtag_stats.get(tag, {})
        n = s.get('videos_found', 0)
        u = s.get('unique_hashtags', 0)
        status = '✅' if n >= 5 else ('⚠️' if n > 0 else '❌')
        print(f'  {tag:23s} {n:>8d} {u:>10d} {status:>12s}')

    print(f'\n{"КЛЮЧЕВОЕ СЛОВО":35s} {"Видео":>8s} {"Уник.теги":>10s} {"Статус":>12s}')
    print('-' * 65)
    for kw in all_keywords:
        s = keyword_stats.get(kw, {})
        n = s.get('videos_found', 0)
        u = s.get('unique_hashtags', 0)
        status = '✅' if n >= 5 else ('⚠️' if n > 0 else '❌')
        print(f'  {kw:33s} {n:>8d} {u:>10d} {status:>12s}')

    # Рекомендации
    print('\n\n--- РЕКОМЕНДУЕМЫЕ ХЕШТЕГИ (на основе реальных данных TikTok) ---')
    all_recommended = Counter()
    for tag in all_hashtags:
        for t in hashtag_stats.get(tag, {}).get('top_tags', []):
            all_recommended[t['tag']] += t['count']
    for kw in all_keywords:
        for t in keyword_stats.get(kw, {}).get('top_tags', []):
            all_recommended[t['tag']] += t['count']

    # Исключаем уже имеющиеся
    existing = set(h.lower() for h in all_hashtags)
    recommended = [(t, c) for t, c in all_recommended.most_common(30) if t not in existing]
    if recommended:
        for i, (tag, count) in enumerate(recommended[:20], 1):
            print(f'  {i:2d}. #{tag:30s} (встретился {count} раз)')
    else:
        print('  Нет новых рекомендаций')

    # Подсказки
    print('\n--- ПОИСКОВЫЕ ПОДСКАЗКИ TIKTOK ---')
    for term, sug in suggestions.items():
        if sug:
            print(f'  "{term}": {", ".join(sug[:8])}')

    # Сохраняем отчёт
    report = {
        'hashtag_stats': hashtag_stats,
        'keyword_stats': keyword_stats,
        'suggestions': suggestions,
        'recommended_hashtags': [{'tag': t, 'count': c} for t, c in recommended[:30]],
    }
    report_path = Path(__file__).parent / 'data' / 'source_analysis.json'
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    logger.info(f'\nПолный отчёт сохранён: {report_path}')

if __name__ == '__main__':
    asyncio.run(main())
