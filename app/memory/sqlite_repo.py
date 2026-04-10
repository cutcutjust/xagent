"""SQLite persistence — local task and content tracking."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Generator

from app.core.config import get_settings
from app.core.logger import logger
from app.schemas.content import CollectedContent, PlatformDraft, UniversalDraft
from app.schemas.task import TaskRecord, TaskStatus


def _db_path() -> Path:
    s = get_settings()
    p = s.data_path / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p / "xagent.db"


@contextmanager
def _conn() -> Generator[sqlite3.Connection, None, None]:
    db = sqlite3.connect(str(_db_path()))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    try:
        yield db
        db.commit()
    finally:
        db.close()


def init_db() -> None:
    with _conn() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS collected_content (
                content_id TEXT PRIMARY KEY,
                platform TEXT,
                source_url TEXT,
                author TEXT,
                title TEXT,
                body_text TEXT,
                summary TEXT,
                relevance_score REAL,
                tags TEXT,
                metrics TEXT,
                images TEXT,
                screenshots TEXT,
                notion_page_id TEXT,
                published_at TEXT,
                collected_at TEXT,
                external_links TEXT,
                comment_links TEXT
            );

            CREATE TABLE IF NOT EXISTS research_references (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE,
                platform TEXT,
                visited_at TEXT,
                content_id TEXT,
                title TEXT,
                was_collected INTEGER DEFAULT 0,
                source TEXT
            );

            CREATE TABLE IF NOT EXISTS universal_drafts (
                draft_id TEXT PRIMARY KEY,
                topic TEXT,
                angle TEXT,
                title TEXT,
                summary TEXT,
                body_markdown TEXT,
                key_points TEXT,
                ref_urls TEXT,
                suggested_assets TEXT,
                source_content_ids TEXT,
                status TEXT,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS platform_drafts (
                draft_id TEXT PRIMARY KEY,
                universal_draft_id TEXT,
                platform TEXT,
                post_type TEXT,
                title TEXT,
                body TEXT,
                thread_posts TEXT,
                images TEXT,
                links TEXT,
                tags TEXT,
                metadata TEXT,
                status TEXT,
                published_url TEXT,
                published_at TEXT,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS comments (
                content_id TEXT,
                author TEXT,
                text TEXT,
                likes INTEGER DEFAULT 0,
                url TEXT,
                collected_at TEXT,
                FOREIGN KEY (content_id) REFERENCES collected_content(content_id)
            );

            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                kind TEXT,
                platform TEXT,
                status TEXT,
                params TEXT,
                result TEXT,
                error TEXT,
                created_at TEXT,
                started_at TEXT,
                finished_at TEXT
            );
            """
        )
    logger.debug("SQLite DB initialised")


# ── CollectedContent ──────────────────────────────────────────────────────────

def save_content(c: CollectedContent) -> None:
    with _conn() as db:
        db.execute(
            """INSERT OR REPLACE INTO collected_content VALUES
               (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                c.content_id, c.platform, c.source_url, c.author, c.title,
                c.body_text, c.summary, c.relevance_score,
                json.dumps(c.tags), json.dumps(c.metrics.model_dump()),
                json.dumps(c.images), json.dumps(c.screenshots),
                c.notion_page_id,
                c.published_at.isoformat() if c.published_at else None,
                c.collected_at.isoformat(),
                json.dumps(c.external_links),
                json.dumps(c.comment_links),
            ),
        )
        # Save comments to separate table
        db.execute("DELETE FROM comments WHERE content_id = ?", (c.content_id,))
        for cm in c.comments:
            db.execute(
                "INSERT INTO comments (content_id, author, text, likes, url, collected_at) VALUES (?,?,?,?,?,?)",
                (c.content_id, cm.author, cm.text, cm.likes, cm.url, c.collected_at.isoformat()),
            )


def load_collected_content(
    platform: str = "x",
    days: int = 7,
    topic: str | None = None,
) -> list[CollectedContent]:
    """Load collected content, optionally filtered by topic keyword."""
    from datetime import timedelta
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with _conn() as db:
        if topic:
            rows = db.execute(
                "SELECT * FROM collected_content WHERE platform=? AND collected_at>=? "
                "AND (body_text LIKE ? OR title LIKE ? OR tags LIKE ?)",
                (platform, cutoff, f"%{topic}%", f"%{topic}%", f"%{topic}%"),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM collected_content WHERE platform=? AND collected_at>=? "
                "ORDER BY relevance_score DESC",
                (platform, cutoff),
            ).fetchall()
    return [_row_to_content(r) for r in rows]


def load_collected_content_by_id(content_id: str) -> CollectedContent | None:
    """Load a single CollectedContent by its content_id."""
    with _conn() as db:
        row = db.execute(
            "SELECT * FROM collected_content WHERE content_id=?",
            (content_id,),
        ).fetchone()
    return _row_to_content(row) if row else None


def save_content_to_md(c: CollectedContent) -> str:
    """Save a single post to local MD file. Returns file path."""
    s = get_settings()
    md_dir = s.data_path / "research_md"
    md_dir.mkdir(parents=True, exist_ok=True)

    from slugify import slugify
    safe_author = slugify(c.author or "unknown")
    safe_title = slugify(c.title or c.body_text[:50])[:40]
    filename = f"{safe_author}_{safe_title}.md"
    filepath = md_dir / filename

    lines = [
        f"# @{c.author}",
        f"",
        f"> {c.source_url}",
        f"> ❤ {c.metrics.likes} | 🔁 {c.metrics.reposts} | 💬 {len(c.comments)} | 👁 {c.metrics.views}",
        f"> 相关性: {c.relevance_score:.1f}",
        f"> 采集时间: {c.collected_at.strftime('%Y-%m-%d %H:%M')}",
        f"",
        f"## 正文",
        f"",
        c.body_text,
    ]

    if c.summary:
        lines.extend(["", "## 摘要", "", c.summary])

    if c.images:
        lines.extend(["", "## 图片", ""])
        for img in c.images:
            lines.append(f"- {img}")

    if c.comments:
        top_comments = sorted(c.comments, key=lambda cm: cm.likes, reverse=True)
        lines.extend(["", "## 热门评论", ""])
        for cm in top_comments[:15]:
            lines.append(f"- **@{cm.author or '?'}** (❤{cm.likes}): {cm.text}")

    if c.tags:
        lines.extend(["", f"## 标签", "", ", ".join(c.tags)])

    content = "\n".join(lines)
    filepath.write_text(content, encoding="utf-8")
    return str(filepath)



def _row_to_content(r: sqlite3.Row) -> CollectedContent:
    from app.schemas.content import Comment, Metrics
    keys = r.keys()
    content = CollectedContent(
        content_id=r["content_id"],
        platform=r["platform"],
        source_url=r["source_url"],
        author=r["author"],
        title=r["title"],
        body_text=r["body_text"] or "",
        summary=r["summary"] or "",
        relevance_score=r["relevance_score"] or 0.0,
        tags=json.loads(r["tags"] or "[]"),
        metrics=Metrics(**json.loads(r["metrics"] or "{}")),
        images=json.loads(r["images"] or "[]"),
        screenshots=json.loads(r["screenshots"] or "[]"),
        notion_page_id=r["notion_page_id"],
        external_links=json.loads(r["external_links"] or "[]") if "external_links" in keys else [],
        comment_links=json.loads(r["comment_links"] or "[]") if "comment_links" in keys else [],
    )
    # Load comments from separate table
    with _conn() as db:
        comment_rows = db.execute(
            "SELECT * FROM comments WHERE content_id = ? ORDER BY likes DESC",
            (content.content_id,),
        ).fetchall()
        content.comments = [
            Comment(author=cr["author"], text=cr["text"], likes=cr["likes"], url=cr["url"])
            for cr in comment_rows
        ]
    return content


# ── Research References ───────────────────────────────────────────────────────

def save_reference(
    url: str,
    platform: str,
    *,
    content_id: str | None = None,
    title: str = "",
    was_collected: bool = False,
    source: str = "search",
) -> None:
    """Record every URL encountered during research (even if not collected)."""
    with _conn() as db:
        db.execute(
            """INSERT INTO research_references (url, platform, visited_at, content_id, title, was_collected, source)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(url) DO UPDATE SET
                 was_collected = MAX(was_collected, excluded.was_collected),
                 content_id = COALESCE(excluded.content_id, content_id),
                 title = COALESCE(NULLIF(excluded.title,''), title)
            """,
            (
                url, platform, datetime.utcnow().isoformat(),
                content_id, title, int(was_collected), source,
            ),
        )


def load_references(platform: str = "x", days: int = 7) -> list[dict]:
    """Load all references seen in the last N days."""
    from datetime import timedelta
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with _conn() as db:
        rows = db.execute(
            "SELECT * FROM research_references WHERE platform=? AND visited_at>=? ORDER BY visited_at DESC",
            (platform, cutoff),
        ).fetchall()
    return [dict(r) for r in rows]


def count_references(platform: str = "x") -> tuple[int, int]:
    """Return (total_seen, total_collected) counts."""
    with _conn() as db:
        total = db.execute(
            "SELECT COUNT(*) FROM research_references WHERE platform=?", (platform,)
        ).fetchone()[0]
        collected = db.execute(
            "SELECT COUNT(*) FROM research_references WHERE platform=? AND was_collected=1", (platform,)
        ).fetchone()[0]
    return total, collected


# ── Tasks ─────────────────────────────────────────────────────────────────────

def save_task(t: TaskRecord) -> None:
    with _conn() as db:
        db.execute(
            """INSERT OR REPLACE INTO tasks VALUES
               (?,?,?,?,?,?,?,?,?,?)""",
            (
                t.task_id, t.kind.value, t.platform, t.status.value,
                json.dumps(t.params), json.dumps(t.result), t.error,
                t.created_at.isoformat(),
                t.started_at.isoformat() if t.started_at else None,
                t.finished_at.isoformat() if t.finished_at else None,
            ),
        )


def load_tasks(status: TaskStatus | None = None) -> list[TaskRecord]:
    from app.schemas.task import TaskKind
    with _conn() as db:
        if status:
            rows = db.execute(
                "SELECT * FROM tasks WHERE status=? ORDER BY created_at DESC", (status.value,)
            ).fetchall()
        else:
            rows = db.execute("SELECT * FROM tasks ORDER BY created_at DESC").fetchall()
    result = []
    for r in rows:
        result.append(TaskRecord(
            task_id=r["task_id"],
            kind=TaskKind(r["kind"]),
            platform=r["platform"],
            status=TaskStatus(r["status"]),
            params=json.loads(r["params"] or "{}"),
            result=json.loads(r["result"] or "{}"),
            error=r["error"],
        ))
    return result


# ── Drafts ────────────────────────────────────────────────────────────────────

def save_universal_draft(d: UniversalDraft) -> None:
    with _conn() as db:
        db.execute(
            """INSERT OR REPLACE INTO universal_drafts VALUES
               (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                d.draft_id, d.topic, d.angle, d.title, d.summary, d.body_markdown,
                json.dumps(d.key_points), json.dumps(d.references),
                json.dumps(d.suggested_assets), json.dumps(d.source_content_ids),
                d.status, d.created_at.isoformat(),
            ),
        )
        # Note: column is ref_urls but we pass d.references — sqlite positional order matches


def save_platform_draft(d: PlatformDraft) -> None:
    with _conn() as db:
        db.execute(
            """INSERT OR REPLACE INTO platform_drafts VALUES
               (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                d.draft_id, d.universal_draft_id, d.platform, d.post_type,
                d.title, d.body, json.dumps(d.thread_posts),
                json.dumps(d.images), json.dumps(d.links), json.dumps(d.tags),
                json.dumps(d.metadata), d.status, d.published_url,
                d.published_at.isoformat() if d.published_at else None,
                d.created_at.isoformat(),
            ),
        )


def load_pending_platform_drafts(platform: str = "x") -> list[PlatformDraft]:
    with _conn() as db:
        rows = db.execute(
            "SELECT * FROM platform_drafts WHERE platform=? AND status='pending' "
            "ORDER BY created_at DESC",
            (platform,),
        ).fetchall()
    return [_row_to_platform_draft(r) for r in rows]


def _row_to_platform_draft(r: sqlite3.Row) -> PlatformDraft:
    return PlatformDraft(
        draft_id=r["draft_id"],
        universal_draft_id=r["universal_draft_id"],
        platform=r["platform"],
        post_type=r["post_type"],
        title=r["title"],
        body=r["body"] or "",
        thread_posts=json.loads(r["thread_posts"] or "[]"),
        images=json.loads(r["images"] or "[]"),
        links=json.loads(r["links"] or "[]"),
        tags=json.loads(r["tags"] or "[]"),
        metadata=json.loads(r["metadata"] or "{}"),
        status=r["status"],
        published_url=r["published_url"],
    )
