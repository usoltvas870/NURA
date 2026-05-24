#!/usr/bin/env python3
"""Проверка Days 2-7 через Playwright (с куками и JS)."""
import asyncio, json, sys, re, logging
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent / 'src'))
from utils import load_env, get_cookie_path
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.WARNING, format='%(message)s')

def parse_days(path: Path) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        lines = [l.rstrip() for l in f]
    days = {}
    current_day = None
    current_section = None
    for line in lines:
        s = line.strip()
        if s.startswith('День'):
            current_day = s
            days[current_day] = {'hashtags': [], 'keywords': []}
            current_section = None
        elif 'Core hashtags' in s:
            current_section = 'hashtags'
        elif 'Core keywords' in s:
            current_section = 'keywords'
        elif s and not s.startswith('#') and current_day and current_section:
            days[current_day][current_section].append(s)
    return days

async def check_one(page, entry: str, mode: str, sem) -> dict:
    async with sem:
        url = f'https://www.tiktok.com/tag/{entry}' if mode == 'hashtag' else f'https://www.tiktok.com/search?q={quote(entry)}'
        api_data = []
        async def on_resp(response):
            if not response.ok:
                return
            if any(kw in response.url for kw in ['/api/', '/item_list/', '/search/', '/post/']):
                try:
                    body = await response.json()
                    if body:
                        api_data.append(body)
                except:
                    pass
        page.on('response', on_resp)
        try:
            await page.goto(url, wait_until='load', timeout=15000)
            await asyncio.sleep(2)
            # Ищем видео в API ответах
            found = 0
            for body in api_data:
                items = body.get('itemList') or body.get('data') or body.get('items') or []
                if isinstance(items, list):
                    found += len(items)
            if found == 0:
                # Fallback: DOM
                found = await page.evaluate('document.querySelectorAll("a[href*=\'/video/\']").length')
            return {'entry': entry, 'found': min(found, 999), 'status': 'OK' if found >= 5 else ('WARN' if found > 0 else 'FAIL')}
        except Exception as e:
            return {'entry': entry, 'found': 0, 'status': 'FAIL', 'error': str(e)}
        finally:
            page.remove_listener('response', on_resp)

async def main():
    load_env()
    rot_path = Path(__file__).parent / 'Ротационные ключевики.txt'
    all_days = parse_days(rot_path)

    # Только дни 2-7
    days = {k: v for k, v in all_days.items() if not k.startswith('День 1')}
    print(f'Проверка {len(days)} дней ({sum(len(v["hashtags"])+len(v["keywords"])) for v in days.values()} записей)')

    cookie_path = get_cookie_path()
    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=True, args=['--disable-blink-features=AutomationControlled'])
    storage_state = None
    if cookie_path.exists():
        with open(cookie_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list):
            storage_state = {'cookies': data, 'origins': []}
        else:
            storage_state = data
    context = await browser.new_context(storage_state=storage_state)
    sem = asyncio.Semaphore(3)
    results = {}

    for day, content in days.items():
        print(f'\n=== {day} ===')
        results[day] = {'hashtags': {}, 'keywords': {}}

        entries = content['hashtags'] + content['keywords']
        modes = ['hashtag'] * len(content['hashtags']) + ['keyword'] * len(content['keywords'])

        tasks = []
        for entry, mode in zip(entries, modes):
            page = await context.new_page()
            tasks.append(check_one(page, entry, mode, sem))

        outs = await asyncio.gather(*tasks)
        for r in outs:
            e = r['entry']
            sec = 'hashtags' if e in content['hashtags'] else 'keywords'
            results[day][sec][e] = r

        for tag in content['hashtags']:
            r = results[day]['hashtags'][tag]
            print(f'  #{tag:30s} -> {r["found"]:4d} {r["status"]}')
        for kw in content['keywords']:
            r = results[day]['keywords'][kw]
            print(f'  {kw:40s} -> {r["found"]:4d} {r["status"]}')

        # Закрыть страницы этого дня
        for page in context.pages:
            if not page.is_closed():
                try:
                    await page.close()
                except:
                    pass

    # Сводка
    print('\n\n=== НЕРАБОЧИЕ (FAIL) ===')
    bad = 0
    for day, data in results.items():
        for section in ['hashtags', 'keywords']:
            for name, r in data[section].items():
                if r['status'] == 'FAIL':
                    typ = '#' if section == 'hashtags' else ''
                    print(f'  {typ}{name}')
                    bad += 1
    print(f'\nВсего нерабочих: {bad}' if bad else 'Все записи работают!')

    save = Path(__file__).parent / 'data' / 'rotational_check_days2_7.json'
    save.parent.mkdir(parents=True, exist_ok=True)
    with open(save, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f'Отчёт: {save}')

    await browser.close()
    await p.stop()

if __name__ == '__main__':
    asyncio.run(main())
