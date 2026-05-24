#!/usr/bin/env python3
"""Быстрая проверка ротационных записей через API TikTok."""
import asyncio
import json
import sys
import re
import logging
from pathlib import Path
from urllib.parse import quote

logging.basicConfig(level=logging.WARNING, format='%(message)s')

sys.path.insert(0, str(Path(__file__).parent / 'src'))
from utils import load_env

async def check_entry(sem, client, entry: str, mode: str) -> dict:
    async with sem:
        url = f'https://www.tiktok.com/tag/{entry}' if mode == 'hashtag' else f'https://www.tiktok.com/search?q={quote(entry)}'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Referer': url,
        }
        try:
            r = await client.get(url, headers=headers, timeout=10, follow_redirects=True)
            text = r.text.lower()
            # Если в HTML есть SSR данные с видео
            has_video_links = '/video/' in text
            video_count = text.count('/video/')
            return {'entry': entry, 'found': min(video_count, 999), 'status': 'OK' if has_video_links else 'FAIL'}
        except Exception as e:
            return {'entry': entry, 'found': 0, 'status': 'FAIL', 'error': str(e)}

def parse_rotational_file(path: Path) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        lines = [l.rstrip() for l in f]
    days = {}
    current_day = None
    current_section = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('День'):
            m = re.match(r'(День \d+:[\s\S]*?)(?=День|\Z)', line)
            current_day = stripped
            days[current_day] = {'hashtags': [], 'keywords': []}
            current_section = None
            continue
        if 'Добавить к Core hashtags' in stripped:
            current_section = 'hashtags'
            continue
        if 'Добавить к Core keywords' in stripped:
            current_section = 'keywords'
            continue
        if not stripped or stripped.startswith('#'):
            continue
        if current_day and current_section:
            days[current_day][current_section].append(stripped)
    return days

async def main():
    load_env()
    rot_path = Path(__file__).parent / 'Ротационные ключевики.txt'
    days = parse_rotational_file(rot_path)

    import httpx
    sem = asyncio.Semaphore(5)
    all_results = {}

    async with httpx.AsyncClient(timeout=15) as client:
        for day, content in days.items():
            print(f'\n=== {day} ===')
            all_results[day] = {'hashtags': {}, 'keywords': {}}

            tasks = []
            for tag in content['hashtags']:
                tasks.append(check_entry(sem, client, tag, 'hashtag'))
            for kw in content['keywords']:
                tasks.append(check_entry(sem, client, kw, 'keyword'))

            results = await asyncio.gather(*tasks)
            for r in results:
                entry = r['entry']
                if entry in content['hashtags']:
                    all_results[day]['hashtags'][entry] = r
                else:
                    all_results[day]['keywords'][entry] = r

            for tag in content['hashtags']:
                r = all_results[day]['hashtags'][tag]
                print(f'  #{tag:30s} -> {r["found"]:4d} {r["status"]}')
            for kw in content['keywords']:
                r = all_results[day]['keywords'][kw]
                print(f'  {kw:40s} -> {r["found"]:4d} {r["status"]}')

    # Сводка
    print('\n\n=== НЕРАБОЧИЕ ===')
    bad = 0
    for day, data in all_results.items():
        for section in ['hashtags', 'keywords']:
            for name, r in data[section].items():
                if r['found'] == 0:
                    typ = '#' if section == 'hashtags' else ''
                    print(f'  {typ}{name}')
                    bad += 1
    print(f'\nВсего нерабочих: {bad}' if bad else 'Все записи работают!')

    save = Path(__file__).parent / 'data' / 'rotational_check.json'
    save.parent.mkdir(parents=True, exist_ok=True)
    with open(save, 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f'\nОтчёт: {save}')

if __name__ == '__main__':
    asyncio.run(main())
