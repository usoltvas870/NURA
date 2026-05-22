import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent.parent / 'data' / 'videos.db'


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT,
                url TEXT UNIQUE NOT NULL,
                platform TEXT DEFAULT 'tiktok',
                source_type TEXT NOT NULL,
                source_value TEXT NOT NULL,
                author_username TEXT,
                caption TEXT,
                views INTEGER,
                likes INTEGER,
                comments INTEGER,
                shares INTEGER,
                publish_time TEXT,
                author_followers INTEGER,
                is_playlist INTEGER DEFAULT 0,
                collected_at TEXT NOT NULL,
                run_id TEXT NOT NULL
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_video_id ON videos(video_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_run_id ON videos(run_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_url ON videos(url)')
        try:
            conn.execute('ALTER TABLE videos ADD COLUMN is_playlist INTEGER DEFAULT 0')
        except Exception:
            pass
        conn.commit()
        logger.info("Database initialized")
    finally:
        conn.close()


def save_video(conn: sqlite3.Connection, video: dict) -> bool:
    try:
        before = conn.total_changes
        conn.execute('''
            INSERT OR IGNORE INTO videos
            (video_id, url, platform, source_type, source_value,
             author_username, caption, views, likes, comments, shares,
             publish_time, author_followers, is_playlist, collected_at, run_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            video.get('video_id'),
            video['url'],
            video.get('platform', 'tiktok'),
            video['source_type'],
            video['source_value'],
            video.get('author_username'),
            video.get('caption'),
            video.get('views'),
            video.get('likes'),
            video.get('comments'),
            video.get('shares'),
            video.get('publish_time'),
            video.get('author_followers'),
            1 if video.get('is_playlist') else 0,
            video['collected_at'],
            video['run_id'],
        ))
        return conn.total_changes > before
    except Exception as e:
        logger.error(f"Failed to save video {video.get('url')}: {e}")
        return False


def get_videos_by_run_id(conn: sqlite3.Connection, run_id: str) -> list[dict]:
    cursor = conn.execute(
        'SELECT * FROM videos WHERE run_id = ? ORDER BY id', (run_id,)
    )
    return [dict(row) for row in cursor.fetchall()]


def get_top_videos(
    conn: sqlite3.Connection,
    run_id: str,
    limit: int = 30,
    min_views: int = 10000,
) -> list[dict]:
    cursor = conn.execute(
        'SELECT * FROM videos WHERE run_id = ? AND views >= ? ORDER BY views DESC LIMIT ?',
        (run_id, min_views, limit),
    )
    return [dict(row) for row in cursor.fetchall()]
