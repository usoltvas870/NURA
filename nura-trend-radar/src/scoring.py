import logging
from typing import Optional

logger = logging.getLogger(__name__)


def compute_scores(videos: list[dict]) -> list[dict]:
    if not videos:
        return videos

    scored = []
    for v in videos:
        if v.get('views') is not None and v['views'] > 0:
            v['engagement_rate'] = _engagement_rate(v)
            v['comment_density'] = _comment_density(v)
            v['viral_score'] = _viral_score(v)
        else:
            v['engagement_rate'] = 0.0
            v['comment_density'] = 0.0
            v['viral_score'] = None
        scored.append(v)

    all_views = [
        v['views'] for v in scored
        if v.get('views') is not None and v['views'] > 0
    ]
    max_views = max(all_views) if all_views else 1

    for v in scored:
        v['final_score'] = _final_score(v, max_views)
        v['subscriber_potential'] = _subscriber_potential(v, max_views)

    scored.sort(key=lambda v: v.get('final_score', 0) or 0, reverse=True)
    return scored


def _engagement_rate(video: dict) -> float:
    views = video.get('views')
    if not views or views <= 0:
        return 0.0
    likes = video.get('likes') or 0
    comments = video.get('comments') or 0
    shares = video.get('shares') or 0
    return (likes + comments + shares) / views


def _comment_density(video: dict) -> float:
    views = video.get('views')
    if not views or views <= 0:
        return 0.0
    comments = video.get('comments') or 0
    return comments / views


def _viral_score(video: dict) -> Optional[float]:
    views = video.get('views')
    followers = video.get('author_followers')
    if views is not None and followers is not None and followers > 0:
        return views / followers
    return None


def _subscriber_potential(video: dict, max_views: int) -> float:
    views = video.get('views') or 0
    er = video.get('engagement_rate') or 0.0
    cd = video.get('comment_density') or 0.0

    views_norm = views / max_views if max_views > 0 else 0
    er_norm = min(er / 0.3, 1.0)
    cd_norm = min(cd / 0.01, 1.0)

    return round(views_norm * 6 + er_norm * 3 + cd_norm * 1, 2)


def _final_score(video: dict, max_views: int) -> float:
    views = video.get('views') or 0
    engagement = video.get('engagement_rate') or 0.0
    comment = video.get('comment_density') or 0.0
    viral = video.get('viral_score')

    views_norm = views / max_views if max_views > 0 else 0

    score = (
        views_norm * 0.5
        + engagement * 100 * 0.3
        + comment * 1000 * 0.2
    )

    if viral is not None and viral > 0:
        score += min(viral, 1.0) * 0.1

    return round(score, 4)
