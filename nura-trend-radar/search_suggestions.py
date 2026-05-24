#!/usr/bin/env python3
"""Собрать поисковые подсказки TikTok и составить итоговый отчёт."""
import asyncio
import json
import sys
import logging
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent / 'src'))
from utils import load_env, setup_logging

logger = logging.getLogger('suggest')

import httpx

async def fetch_suggestions(keyword: str) -> list[str]:
    url = f'https://www.tiktok.com/api/search/suggest/?keyword={quote(keyword)}&aid=1988'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://www.tiktok.com/',
    }
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url, headers=headers, timeout=10, follow_redirects=True)
        if r.status_code != 200:
            return []
        data = r.json()
        return [
            item.get('keyword') or item.get('suggest_word') or ''
            for item in data.get('data', []) or data.get('suggestions', [])
            if item.get('keyword') or item.get('suggest_word')
        ]
    except Exception as e:
        logger.debug(f'Suggest error "{keyword}": {e}')
        return []

async def fetch_search_suggest_v2(keyword: str) -> list[str]:
    """Fallback: поиск через Google Suggest для TikTok."""
    url = f'https://suggestqueries.google.com/complete/search?client=youtube&ds=yt&q=tiktok+{quote(keyword)}'
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url, timeout=5)
        if r.status_code == 200:
            data = r.json()
            raw = data[1] if len(data) > 1 else []
            return [s.replace('tiktok ', '').replace('tiktok', '').strip() for s in raw if s]
        return []
    except:
        return []

async def main():
    setup_logging()
    load_env()

    base_terms = [
        'матрица судьбы', 'нумерология', 'кармический хвост',
        'предназначение по дате рождения', 'число судьбы',
        'жизненный путь', 'женская энергия',
        'destiny matrix', 'numerology', 'life path number',
        'karmic lesson', 'soul purpose',
    ]

    all_suggestions = {}
    for term in base_terms:
        sug = await fetch_suggestions(term)
        if not sug:
            sug = await fetch_search_suggest_v2(term)
        all_suggestions[term] = sug[:12]
        logger.info(f'"{term}": {", ".join(sug[:8]) if sug else "нет"}')
        await asyncio.sleep(1.5)

    print('\n\n' + '=' * 60)
    print('ПОИСКОВЫЕ ПОДСКАЗКИ TIKTOK')
    print('=' * 60)
    for term, sug in all_suggestions.items():
        if sug:
            print(f'\n  "{term}":')
            for i, s in enumerate(sug, 1):
                print(f'    {i:2d}. {s}')
        else:
            print(f'\n  "{term}": нет подсказок')

    save = Path(__file__).parent / 'data' / 'search_suggestions.json'
    save.parent.mkdir(parents=True, exist_ok=True)
    with open(save, 'w', encoding='utf-8') as f:
        json.dump(all_suggestions, f, ensure_ascii=False, indent=2)
    print(f'\nСохранено: {save}')

if __name__ == '__main__':
    asyncio.run(main())
