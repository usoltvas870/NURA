import json
import re
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def extract_from_api_responses(
    api_data: list[dict], source_type: str, source_value: str
) -> list[dict]:
    playlist_fallback = None

    for body in api_data:
        items = body.get('itemList') or body.get('data') or body.get('items') or []
        if not items and isinstance(body, list):
            items = body

        if not items:
            pitems = body.get('playList')
            if pitems is not None and playlist_fallback is None:
                playlist_fallback = pitems
            continue

        videos = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if 'item' in item and isinstance(item.get('item'), dict):
                item = item['item']
            video = _parse_item(item)
            if video and video.get('url'):
                video['source_type'] = source_type
                video['source_value'] = source_value
                videos.append(video)

        if videos:
            return videos

    return []


def extract_playlists_from_api(
    api_data: list[dict], source_type: str, source_value: str
) -> list[dict]:
    for body in api_data:
        items = body.get('itemList') or body.get('data') or body.get('items') or []
        if items:
            continue
        pitems = body.get('playList')
        if pitems:
            return _parse_playlist_items(pitems, source_type, source_value)
    return []


def _parse_playlist_items(
    items: list[dict], source_type: str, source_value: str
) -> list[dict]:
    playlists = []
    for item in items:
        creator = item.get('creator') or {}
        unique_id = creator.get('uniqueId')
        playlist_id = item.get('id') or item.get('mixId')
        name = item.get('name') or item.get('mixName')

        if not playlist_id or not unique_id:
            continue

        url = f'https://www.tiktok.com/@{unique_id}/video/{playlist_id}'

        playlists.append({
            'video_id': str(playlist_id),
            'url': url,
            'author_username': unique_id,
            'caption': f'[Playlist] {name}' if name else '[Playlist]',
            'views': None,
            'likes': None,
            'comments': None,
            'shares': None,
            'publish_time': '',
            'author_followers': None,
            'source_type': source_type,
            'source_value': source_value,
            'is_playlist': True,
        })

    return playlists


async def extract_video_data(
    page: Any, source_type: str, source_value: str
) -> list[dict]:
    videos = await _extract_from_json(page)
    if videos:
        for v in videos:
            v['source_type'] = source_type
            v['source_value'] = source_value
        return videos

    videos = await _extract_from_dom(page)
    if videos:
        for v in videos:
            v['source_type'] = source_type
            v['source_value'] = source_value
        return videos

    videos = await _extract_links(page)
    for v in videos:
        v['source_type'] = source_type
        v['source_value'] = source_value
    return videos


async def _extract_from_json(page: Any) -> list[dict]:
    selectors = [
        '#__UNIVERSAL_DATA_FOR_REHYDRATION__',
        '#__NEXT_DATA__',
        'script[type="application/json"]',
    ]

    json_data = None
    for selector in selectors:
        try:
            el = await page.query_selector(selector)
            if el:
                text = await el.text_content()
                if text and len(text) > 50:
                    json_data = json.loads(text)
                    break
        except Exception:
            continue

    if not json_data:
        return []

    items = _find_items(json_data)
    videos = []
    for item in items:
        video = _parse_item(item)
        if video and video.get('url'):
            videos.append(video)
    return videos


def _find_items(data: dict | list) -> list[dict]:
    if isinstance(data, list):
        return data

    paths = [
        lambda d: d.get('__DEFAULT_SCOPE__', {}).get('webapp.video-detail', {}).get('itemInfo', {}).get('itemStruct'),
        lambda d: d.get('__DEFAULT_SCOPE__', {}).get('webapp.search.search', {}).get('data', []),
        lambda d: d.get('__DEFAULT_SCOPE__', {}).get('webapp.user-detail', {}).get('userInfo', {}).get('posts', []),
        lambda d: d.get('__DEFAULT_SCOPE__', {}).get('webapp.user-detail', {}).get('userInfo', {}).get('videos', []),
        lambda d: d.get('__DEFAULT_SCOPE__', {}).get('webapp.user-detail', {}).get('userInfo', {}).get('itemList', []),
        lambda d: d.get('__DEFAULT_SCOPE__', {}).get('webapp.hashtag-detail', {}).get('data', []),
        lambda d: d.get('__DEFAULT_SCOPE__', {}).get('webapp.feed-list', {}).get('data', []),
        lambda d: d.get('props', {}).get('pageProps', {}).get('items', []),
        lambda d: d.get('props', {}).get('pageProps', {}).get('videos', []),
        lambda d: d.get('ItemModule', {}),
        lambda d: d.get('itemList', []),
    ]

    for fn in paths:
        try:
            result = fn(data)
            if result:
                if isinstance(result, dict):
                    return list(result.values())
                if isinstance(result, list):
                    return result
        except Exception:
            continue
    return []


def _parse_item(item: dict) -> Optional[dict]:
    try:
        struct = item.get('itemInfo', {}).get('itemStruct', item)

        video_id = (
            struct.get('id')
            or struct.get('video_id')
            or struct.get('video', {}).get('id')
        )

        author = struct.get('author', {})
        unique_id = author.get('uniqueId') or author.get('nickname')

        url = (
            f'https://www.tiktok.com/@{unique_id or "unknown"}/video/{video_id}'
            if video_id
            else None
        )
        if not url:
            url = struct.get('share_url') or struct.get('url')
        if not url:
            return None

        stats = struct.get('stats') or struct.get('statistics') or struct
        author_stats = struct.get('authorStats') or {}

        return {
            'video_id': video_id or _extract_video_id(url),
            'url': url,
            'author_username': unique_id,
            'caption': (
                struct.get('desc')
                or struct.get('description')
                or struct.get('text')
            ),
            'views': _safe_int(
                stats.get('playCount')
                or stats.get('play_count')
                or stats.get('views')
            ),
            'likes': _safe_int(
                stats.get('diggCount')
                or stats.get('digg_count')
                or stats.get('likes')
            ),
            'comments': _safe_int(
                stats.get('commentCount')
                or stats.get('comment_count')
                or stats.get('comments')
            ),
            'shares': _safe_int(
                stats.get('shareCount')
                or stats.get('share_count')
                or stats.get('shares')
            ),
            'publish_time': str(
                stats.get('createTime')
                or struct.get('createTime')
                or ''
            ),
            'author_followers': _safe_int(
                author_stats.get('followerCount')
                or stats.get('followerCount')
            ),
        }
    except Exception as e:
        logger.debug(f'Parse item error: {e}')
        return None


async def _extract_from_dom(page: Any) -> list[dict]:
    videos = []
    try:
        cards = await page.evaluate('''
            () => {
                const results = [];
                const links = document.querySelectorAll('a[href*="/video/"]');
                const seen = new Set();
                for (const link of links) {
                    const href = link.getAttribute('href') || link.href;
                    if (!href) continue;
                    const m = href.match(/\\/video\\/(\\d+)/);
                    if (!m || seen.has(m[1])) continue;
                    seen.add(m[1]);

                    const card = {
                        video_id: m[1],
                        url: href.startsWith('http') ? href : 'https://www.tiktok.com' + href,
                    };

                    const container = link.closest('div[class*="DivItemContainer"], '
                        + 'div[class*="search"], div[data-e2e="search-video-item"], '
                        + 'div[data-e2e="user-post-item"]') || link.parentElement;
                    const text = (container && container.innerText) || link.innerText || '';

                    const countMatch = text.match(/([\\d.]+\\s*[KMB]?)\\s*(?:views|просмотр)/i);
                    if (countMatch) card.views_raw = countMatch[1];

                    const authorEl = container
                        ? container.querySelector('[data-e2e="search-video-author"], p[class*="unique"], span[class*="nickname"]')
                        : null;
                    if (authorEl) card.author = authorEl.textContent.trim();

                    const descEl = container
                        ? container.querySelector('[data-e2e="search-video-desc"], div[class*="desc"], span[class*="caption"]')
                        : null;
                    if (descEl) card.caption = descEl.textContent.trim();

                    results.push(card);
                }
                return results;
            }
        ''')

        for card in cards:
            video_id = card.get('video_id')
            url = card.get('url')
            if not video_id or not url:
                continue
            author = (card.get('author') or '').lstrip('@').strip()
            videos.append({
                'video_id': video_id,
                'url': url,
                'author_username': author or None,
                'caption': card.get('caption'),
                'views': _parse_count(card.get('views_raw')),
                'likes': None,
                'comments': None,
                'shares': None,
                'publish_time': '',
                'author_followers': None,
            })
            if len(videos) >= 50:
                break
    except Exception as e:
        logger.debug(f'DOM extraction error: {e}')
    return videos


async def _extract_links(page: Any) -> list[dict]:
    videos = []
    try:
        urls = await page.evaluate('''
            () => {
                const links = new Set();
                document.querySelectorAll('a').forEach(a => {
                    const href = a.href || a.getAttribute('href');
                    if (href && (
                        href.includes('/video/')
                        || href.includes('/photo/')
                        || (href.includes('tiktok.com') && href.match(/\/video\/\d+/))
                    )) links.add(href);
                });
                return Array.from(links);
            }
        ''')
        seen: set[str] = set()
        for href in urls:
            url = _resolve_url(href)
            video_id = _extract_video_id(url)
            if video_id and video_id not in seen:
                seen.add(video_id)
                videos.append({'video_id': video_id, 'url': url})
    except Exception as e:
        logger.debug(f'Link extraction error: {e}')
    return videos


def _extract_video_id(url: str) -> Optional[str]:
    m = re.search(r'/video/(\d+)', url)
    return m.group(1) if m else None


def _safe_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _parse_count(raw: str | None) -> int | None:
    if not raw:
        return None
    raw = raw.upper().strip().replace('\u00a0', '').replace(' ', '')
    try:
        if 'K' in raw:
            return int(float(raw.replace('K', '')) * 1000)
        if 'M' in raw:
            return int(float(raw.replace('M', '')) * 1_000_000)
        if 'B' in raw:
            return int(float(raw.replace('B', '')) * 1_000_000_000)
        return int(float(raw))
    except (ValueError, TypeError):
        return None


def _resolve_url(href: str) -> str:
    if href.startswith('http'):
        return href
    if href.startswith('/'):
        return f'https://www.tiktok.com{href}'
    return f'https://www.tiktok.com/{href}'


def parse_detail_page_stats(json_data: dict) -> dict | None:
    items = _find_items_detail(json_data)
    if not items:
        return None
    return _parse_item(items[0])


def _find_items_detail(data: dict | list) -> list[dict]:
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]

    paths = [
        lambda d: (
            d.get('__DEFAULT_SCOPE__', {})
            .get('webapp.video-detail', {})
            .get('itemInfo', {})
            .get('itemStruct')
        ),
        lambda d: (
            d.get('__DEFAULT_SCOPE__', {})
            .get('webapp.video-detail', {})
            .get('itemInfo', {})
        ),
        lambda d: d.get('props', {}).get('pageProps', {}).get('itemInfo', {}).get('itemStruct'),
        lambda d: d.get('props', {}).get('pageProps', {}).get('itemInfo', {}),
        lambda d: d.get('ItemModule', {}),
        lambda d: d.get('itemList', []),
    ]

    for fn in paths:
        try:
            result = fn(data)
            if result:
                if isinstance(result, dict):
                    if result.get('id') or result.get('video', {}).get('id'):
                        return [result]
                    return list(result.values())
                if isinstance(result, list):
                    return result
        except Exception:
            continue
    return []
