import asyncio
import logging
import os
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from playwright.async_api import async_playwright, Browser

from parser import extract_video_data, extract_from_api_responses, parse_detail_page_stats
from utils import get_config_int, get_config, async_random_sleep, extract_video_id, get_cookie_path

logger = logging.getLogger(__name__)

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
]


class TikTokCollector:
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.browser: Optional[Browser] = None
        self.context = None
        self.max_results = get_config_int('MAX_RESULTS_PER_SOURCE', 20)
        self.collected_at = datetime.now().isoformat()
        self.run_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.cookie_path = get_cookie_path()
        self.screenshots_dir = Path(__file__).resolve().parent.parent / 'data' / 'debug'
        self._hashtag_blocked = False
        self._debug_mode = os.getenv('LOG_LEVEL', '').upper() == 'DEBUG'

    async def start(self):
        p = await async_playwright().start()
        debug_port = get_config('CHROME_DEBUG_PORT')
        if debug_port:
            try:
                self.browser = await p.chromium.connect_over_cdp(
                    f'http://127.0.0.1:{debug_port}'
                )
                self.context = self.browser.contexts[0]
                logger.info(f'Connected to existing Chrome on port {debug_port}')
                return
            except Exception as e:
                logger.error(
                    f'Failed to connect to Chrome on port {debug_port}: {e}'
                )
                logger.warning(
                    '  ┌────────────────────────────────────────────────────┐\n'
                    '  │ CHROME_DEBUG_PORT указан, но Chrome не запущен     │\n'
                    '  │                                                  │\n'
                    '  │ 1. Закрой все окна Chrome                        │\n'
                    '  │ 2. Win+R → chrome.exe --remote-debugging-port=9222│\n'
                    '  │ 3. Войди в TikTok (tiktok.com)                   │\n'
                    '  │ 4. Запусти скрипт снова                         │\n'
                    '  │                                                  │\n'
                    '  │ Сейчас скрипт запустит свой браузер (headless)    │\n'
                    '  └────────────────────────────────────────────────────┘'
                )
        self.browser = await p.chromium.launch(headless=self.headless, args=[
            '--disable-blink-features=AutomationControlled',
        ])
        storage_state = None
        if self.cookie_path.exists():
            try:
                import json
                with open(self.cookie_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, list):
                    storage_state = {'cookies': data, 'origins': []}
                else:
                    storage_state = data
                logger.info(f'Loaded cookies from {self.cookie_path}')
            except Exception as e:
                logger.warning(f'Failed to load cookies: {e}')
                try:
                    self.cookie_path.unlink()
                except Exception:
                    pass

        if self.context is None:
            self.context = await self.browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                viewport={'width': 1280, 'height': 800},
                locale='ru-RU',
                storage_state=storage_state,
            )

        self._cleanup_old_screenshots()

        if storage_state:
            valid = await self._validate_cookies()
            if not valid and self.cookie_path.exists():
                logger.warning(
                    '  ┌────────────────────────────────────────────────┐\n'
                    '  │ Куки протухли. Нужно залогиниться заново.     │\n'
                    '  │ Откроется TikTok — просто войди в аккаунт.    │\n'
                    '  │ После входа скрипт сам подхватит куки.        │\n'
                    '  │ Ждать не больше 5 минут.                      │\n'
                    '  └────────────────────────────────────────────────┘'
                )
                page = await self.context.new_page()
                try:
                    await page.goto(
                        'https://www.tiktok.com/login/phone-or-email/email',
                        wait_until='load',
                        timeout=30000,
                    )
                    for _ in range(150):
                        await asyncio.sleep(2)
                        url = page.url.lower()
                        if 'login' not in url and 'auth' not in url:
                            logger.info('Login detected — saving fresh cookies')
                            break
                    else:
                        logger.warning('Login timeout — continuing with old cookies')
                finally:
                    await page.close()
                self.cookie_path.parent.mkdir(parents=True, exist_ok=True)
                cookies = await self.context.cookies()
                import json as _json
                with open(self.cookie_path, 'w', encoding='utf-8') as f:
                    _json.dump({'cookies': cookies, 'origins': []}, f)
                logger.info(f'Saved {len(cookies)} cookies to {self.cookie_path}')

        logger.info('Browser started')

    async def close(self):
        is_connected = get_config('CHROME_DEBUG_PORT') is not None
        if not is_connected and self.context and self.cookie_path:
            try:
                cookies = await self.context.cookies()
                import json
                self.cookie_path.parent.mkdir(parents=True, exist_ok=True)
                storage_data = {'cookies': cookies, 'origins': []}
                with open(self.cookie_path, 'w', encoding='utf-8') as f:
                    json.dump(storage_data, f)
                logger.info(f'Saved {len(cookies)} cookies to {self.cookie_path}')
            except Exception as e:
                logger.warning(f'Failed to save cookies: {e}')
        if self.browser:
            if is_connected:
                logger.info('Detached from Chrome (keeping browser open)')
            else:
                await self.browser.close()
                logger.info('Browser closed')

    async def collect_all(self, sources: dict) -> list[dict]:
        all_videos = []
        seen_urls: set[str] = set()

        for username in sources.get('competitors', []):
            try:
                videos = await self.collect_from_competitor(username)
                for v in videos:
                    url = v.get('url', '')
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_videos.append(v)
            except Exception as e:
                logger.error(f'Competitor @{username} failed: {e}')
            await async_random_sleep(3, 6)

        for hashtag in sources.get('hashtags', []):
            try:
                videos = await self.collect_from_hashtag(hashtag)
                for v in videos:
                    url = v.get('url', '')
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_videos.append(v)
            except Exception as e:
                logger.error(f'Hashtag #{hashtag} failed: {e}')
            await async_random_sleep(3, 6)

        for keyword in sources.get('keywords', []):
            try:
                videos = await self.collect_from_keyword(keyword)
                for v in videos:
                    url = v.get('url', '')
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_videos.append(v)
            except Exception as e:
                logger.error(f"Keyword '{keyword}' failed: {e}")
            await async_random_sleep(3, 6)

        rotational = sources.get('rotational', {})
        for entry in rotational.get('hashtags', []):
            try:
                videos = await self.collect_from_hashtag(entry)
                for v in videos:
                    url = v.get('url', '')
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_videos.append(v)
            except Exception as e:
                logger.error(f'Rotational hashtag #{entry} failed: {e}')
            await async_random_sleep(3, 6)

        for entry in rotational.get('keywords', []):
            try:
                videos = await self.collect_from_keyword(entry)
                for v in videos:
                    url = v.get('url', '')
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_videos.append(v)
            except Exception as e:
                logger.error(f"Rotational keyword '{entry}' failed: {e}")
            await async_random_sleep(3, 6)

        return all_videos

    async def _dismiss_overlays(self, page) -> None:
        try:
            await page.evaluate('''
                () => {
                    document.querySelectorAll('[class*="Modal-overlay"], [data-floating-ui-portal]')
                        .forEach(el => el.remove());
                }
            ''')
            await asyncio.sleep(0.5)
        except Exception:
            pass

    async def _save_debug_screenshot(self, page, name: str) -> None:
        if not self._debug_mode:
            return
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        safe_name = name.replace('/', '_').replace('\\', '_').replace(' ', '_')[:80]
        path = str(self.screenshots_dir / f'{self.run_id}_{safe_name}.png')
        await page.screenshot(path=path)
        logger.debug(f'Screenshot saved: {path}')

    def _cleanup_old_screenshots(self) -> None:
        if not self.screenshots_dir.exists():
            return
        cutoff = time.time() - 7 * 86400
        for f in self.screenshots_dir.glob('*.png'):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    logger.debug(f'Removed old screenshot: {f.name}')
            except Exception:
                pass

    async def _validate_cookies(self) -> bool:
        if not self.cookie_path.exists():
            logger.info('No cookie file found, running without cookies')
            return False

        check_profile = os.getenv('COOKIE_CHECK_PROFILE', 'amatrixxx').replace('@', '').strip()
        page = await self.context.new_page()
        try:
            await page.goto(
                f'https://www.tiktok.com/@{check_profile}',
                wait_until='load',
                timeout=20000,
            )
            await asyncio.sleep(3)

            blocked, reason = await self._is_blocked(page, 'cookie_check')
            if blocked:
                logger.warning(
                    'COOKIES ARE EXPIRED OR INVALID! '
                    f'Detected: {reason}. '
                    'Please refresh: export cookies from browser to data/tiktok_cookies.json'
                )
                return False

            has_ssr = await page.evaluate(
                'document.getElementById("__UNIVERSAL_DATA_FOR_REHYDRATION__") !== null'
            )
            logger.info(
                f'Cookies valid — profile loaded '
                f'({"SSR data found" if has_ssr else "no SSR, but no login wall"})'
            )
            return True
        except Exception as e:
            logger.warning(f'Cookie validation error: {e}')
            return False
        finally:
            await page.close()

    async def _activate_videos_tab(self, page) -> None:
        try:
            await page.evaluate('''
                () => {
                    const tab = document.querySelector('[data-e2e="videos-tab"]');
                    if (tab) {
                        tab.click();
                        return true;
                    }
                    return false;
                }
            ''')
            await asyncio.sleep(2)
        except Exception:
            pass

    async def _navigate_and_extract(
        self, url: str, source_type: str, source_value: str
    ) -> list[dict]:
        page = await self.context.new_page()
        api_data: list[dict] = []

        async def on_response(response):
            if not response.ok:
                return
            url_path = response.url
            if any(kw in url_path for kw in ['/api/', '/item_list/', '/search/', '/post/']):
                try:
                    body = await response.json()
                    if body:
                        api_data.append(body)
                        logger.debug(
                            f'API captured [{source_type}/{source_value}]: '
                            f'{url_path[:120]} | keys={list(body.keys())[:5]}'
                        )
                except Exception:
                    pass

        page.on('response', on_response)

        try:
            logger.info(f'Fetching {source_type}: {source_value}')

            for strategy in ('load', 'domcontentloaded'):
                try:
                    await page.goto(url, wait_until=strategy, timeout=30000)
                    break
                except Exception:
                    if strategy == 'domcontentloaded':
                        raise
                    logger.debug(
                        f'{strategy} timed out for {source_value}, '
                        f'falling back to domcontentloaded'
                    )

            await asyncio.sleep(3)
            try:
                await page.wait_for_selector(
                    'a[href*="/video/"], [data-e2e="user-post-item"], [data-e2e="search-video-item"]',
                    timeout=8000,
                )
            except Exception:
                pass

            await self._dismiss_overlays(page)

            blocked, reason = await self._is_blocked(page, source_value)
            if blocked:
                logger.warning(f'Blocked at {url} — {reason}')
                await self._save_debug_screenshot(page, f'blocked_{source_value}')
                return []

            await self._activate_videos_tab(page)

            await self._scroll(page, 4)
            await asyncio.sleep(2)

            try:
                await page.wait_for_selector(
                    'a[href*="/video/"], [data-e2e="user-post-item"]',
                    timeout=5000,
                )
            except Exception:
                pass

            videos = extract_from_api_responses(api_data, source_type, source_value)
            if videos:
                logger.info(f'  Got {len(videos)} videos (API)')
            else:
                videos = await extract_video_data(page, source_type, source_value)
                logger.info(f'  Got {len(videos)} videos (DOM)')

            if not videos:
                await self._save_debug_screenshot(page, f'empty_{source_value}')

            for v in videos:
                v['collected_at'] = self.collected_at
                v['run_id'] = self.run_id
                v['platform'] = 'tiktok'
                if not v.get('video_id'):
                    v['video_id'] = extract_video_id(v.get('url', ''))

            return videos[:self.max_results]

        except Exception as e:
            logger.error(f'Error at {url}: {e}')
            return []
        finally:
            page.remove_listener('response', on_response)
            await page.close()

    async def _fetch_video_stats(self, url: str) -> dict | None:
        page = await self.context.new_page()
        try:
            await page.goto(url, wait_until='domcontentloaded', timeout=20000)
            await asyncio.sleep(1)
            text = await page.content()
            import re as _re
            m = _re.search(
                r'<script[^>]*id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>'
                r'(.*?)</script>',
                text,
                _re.DOTALL,
            )
            if not m:
                return None
            import json as _json
            raw = m.group(1)
            json_data = _json.loads(raw)
            return parse_detail_page_stats(json_data)
        except Exception as e:
            logger.debug(f'Stats fetch failed for {url}: {e}')
            return None
        finally:
            await page.close()

    async def enrich_missing_stats(self, videos: list[dict]) -> list[dict]:
        need_stats = [
            (i, v) for i, v in enumerate(videos)
            if v.get('views') is None and not v.get('is_playlist')
        ]
        if not need_stats:
            return videos

        logger.info(
            f'Enriching stats for {len(need_stats)} videos (detail page visits)...'
        )
        enriched = 0
        for idx, v in need_stats:
            url = v.get('url', '')
            if not url:
                continue
            stats = await self._fetch_video_stats(url)
            if stats:
                for key in ('views', 'likes', 'comments', 'shares',
                            'author_followers', 'publish_time',
                            'caption', 'author_username'):
                    if stats.get(key) is not None and v.get(key) is None:
                        v[key] = stats[key]
                enriched += 1
            await asyncio.sleep(random.uniform(1.0, 2.0))

        logger.info(f'Stats enriched: {enriched}/{len(need_stats)}')
        return videos

    async def _is_blocked(self, page, label: str) -> tuple[bool, str]:
        try:
            url = page.url

            has_videos = await page.evaluate(
                'document.querySelectorAll("a[href*=\'/video/\']").length'
            )
            has_login_form = await page.evaluate(
                'document.querySelectorAll("input[type=\'password\'], input[name=\'password\']").length'
            )
            has_login_overlay = await page.evaluate('''
                () => {
                    const text = document.body.innerText.substring(0, 2000).toLowerCase();
                    const keywords = [
                        'log in to continue', 'войдите в аккаунт', 'login required',
                        'войдите или зарегистрируйтесь', 'вход', 'log in', 'sign in',
                    ];
                    return keywords.some(k => text.includes(k));
                }
            ''')

            redirect_to_login = 'login' in url.lower() or 'auth' in url.lower()

            if redirect_to_login:
                return True, f'redirect to login (url: {url})'
            if has_login_form and not has_videos:
                return True, 'login form detected, no video content'
            if has_login_overlay and not has_videos:
                return True, 'login overlay detected, no video content'

            return False, ''
        except Exception as e:
            return False, str(e)

    async def _scroll(self, page, times: int = 4):
        for _ in range(times):
            try:
                await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                await asyncio.sleep(random.uniform(2, 4))
            except Exception:
                break

    async def collect_from_competitor(self, username: str) -> list[dict]:
        name = username.replace('@', '').strip()
        url = f'https://www.tiktok.com/@{name}'
        return await self._navigate_and_extract(url, 'competitor', name)

    async def collect_from_hashtag(self, hashtag: str) -> list[dict]:
        tag = hashtag.replace('#', '').strip()
        url = f'https://www.tiktok.com/tag/{tag}'
        return await self._navigate_and_extract(url, 'hashtag', tag)

    async def collect_from_keyword(self, keyword: str) -> list[dict]:
        url = f'https://www.tiktok.com/search?q={quote(keyword)}'
        return await self._navigate_and_extract(url, 'keyword', keyword)
