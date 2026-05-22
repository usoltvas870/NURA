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
            video = _parse_item(item)
            if video and video.get('url'):
                video['source_type'] = source_type
                video['source_value'] = source_value
                videos.append(video)

        if videos:
            return videos

    if playlist_fallback:
        return _parse_playlist_items(playlist_fallback, source_type, source_value)

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
        links = await page.query_selector_all('a[href*="/video/"]')
        seen: set[str] = set()
        for link in links:
            href = await link.get_attribute('href')
            if not href:
                continue
            url = _resolve_url(href)
            video_id = _extract_video_id(url)
            if not video_id or video_id in seen:
                continue
            seen.add(video_id)
            videos.append({'video_id': video_id, 'url': url})
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


def _resolve_url(href: str) -> str:
    if href.startswith('http'):
        return href
    if href.startswith('/'):
        return f'https://www.tiktok.com{href}'
    return f'https://www.tiktok.com/{href}'
