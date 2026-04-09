"""
SightOps CLI  —  sightops <command>

Commands:
  observe    实时屏幕观察器（截图 + LLM 分析 + 操作计划）
  research   全屏视觉调研 X（像真人一样操作电脑）
  analyze    爆款风格分析
  write      根据调研生成草稿
  publish    发布草稿到 X
  status     查看草稿和任务状态
  setup      初始化目录和数据库
"""
from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.table import Table

from app.core.config import get_settings, load_yaml
from app.memory.sqlite_repo import (
    init_db,
    load_pending_platform_drafts,
    load_recent_content,
    load_tasks,
    save_platform_draft,
    save_universal_draft,
)

cli = typer.Typer(name="sightops", help="全屏视觉 AI 调研 Agent — 像真人一样操作电脑")
console = Console()


# ── setup ─────────────────────────────────────────────────────────────────────

@cli.command()
def setup():
    """初始化目录和数据库。"""
    s = get_settings()
    s.data_path.mkdir(parents=True, exist_ok=True)
    s.assets_path.mkdir(parents=True, exist_ok=True)
    (s.data_path / "screenshots").mkdir(exist_ok=True)
    (s.data_path / "desktop_screenshots").mkdir(exist_ok=True)
    (s.data_path / "drafts").mkdir(exist_ok=True)
    (s.data_path / "cache").mkdir(exist_ok=True)
    (s.data_path / "runs").mkdir(exist_ok=True)
    init_db()
    console.print("[bold green]Setup 完成[/bold green]")
    console.print(f"  数据目录: {s.data_path}")
    console.print(f"  资源目录: {s.assets_path}")


# ── observe ──────────────────────────────────────────────────────────────────

@cli.command()
def observe(
    interval: float = typer.Option(8.0, "--interval", "-i", help="截图间隔（秒）"),
):
    """实时屏幕观察器 — 全屏截图 + LLM 分析 + 操作计划，显示在小窗口中。"""
    from app.observer.viewer import start_viewer
    start_viewer(interval=interval)


# ── research ──────────────────────────────────────────────────────────────────

@cli.command()
def research(
    topics: list[str] = typer.Argument(None, help="搜索主题（默认用 topics.yaml）"),
    limit: int = typer.Option(60, "--limit", "-n", help="最多采集帖子数"),
):
    """全屏视觉调研 — 像真人一样操作电脑，每条实时记录。"""
    asyncio.run(_research_async(topics or [], limit))


async def _research_async(topics: list[str], limit: int):
    from app.core.errors import HumanReviewRequired
    from app.desktop.permissions import check_all_permissions
    from app.desktop.research_agent import DesktopXResearcher
    from app.memory.sqlite_repo import count_references

    check_all_permissions()
    init_db()

    console.print("[bold cyan]启动全屏调研 — 像真人一样操作电脑，每条实时记录[/bold cyan]")
    console.print("[dim]紧急终止：鼠标移到屏幕左上角[/dim]\n")

    researcher = DesktopXResearcher()

    console.print("[cyan]正在搜索 X 内容...[/cyan]")
    posts = await researcher.discover(topics or None)
    if not posts:
        console.print("[yellow]未发现相关帖子[/yellow]")
        return

    console.print(f"找到 [bold]{len(posts)}[/bold] 个候选帖子 — 最多采集 {limit} 条")

    collected = 0
    for i, post in enumerate(posts[:limit], 1):
        author = post.get("author", "?")
        preview = post.get("text_preview", "")[:40]
        console.print(f"  [{i}/{min(len(posts), limit)}] @{author} — {preview}")
        try:
            content = await researcher.collect(post)
            if content:
                collected += 1
        except HumanReviewRequired as e:
            console.print(f"    [yellow]需要人工: {e}[/yellow]")
        except Exception as e:
            console.print(f"    [red]失败: {e}[/red]")

    total_refs, collected_refs = count_references("x")
    console.print(
        f"\n[bold green]调研完成:[/bold green] {collected} 条已采集\n"
        f"[dim]引用记录: {total_refs} 条 URL "
        f"({collected_refs} 已采集, {total_refs - collected_refs} 已浏览/跳过)[/dim]"
    )


# ── analyze ───────────────────────────────────────────────────────────────────

@cli.command()
def analyze(
    days: int = typer.Option(7, "--days", "-d", help="分析最近 N 天的内容"),
    platform: str = typer.Option("x", "--platform", "-p"),
):
    """对已采集内容做爆款风格分析。"""
    asyncio.run(_analyze_async(days, platform))


async def _analyze_async(days: int, platform: str):
    from app.analysis.style_miner import mine_style

    init_db()
    items = load_recent_content(platform=platform, days=days)
    if not items:
        console.print(f"[yellow]最近 {days} 天没有 {platform} 内容。[/yellow]")
        return

    console.print(f"[cyan]正在分析 {len(items)} 条内容...[/cyan]")
    patterns = []
    for item in items[:20]:
        try:
            pattern = await mine_style(item)
            patterns.append(pattern)
            console.print(
                f"  [green]{item.author}[/green] hook={pattern.hook_type} "
                f"structure={pattern.narrative_structure}"
            )
        except Exception as e:
            console.print(f"  [yellow]{item.author} 分析失败: {e}[/yellow]")

    if patterns:
        from collections import Counter
        hooks = Counter(p.hook_type for p in patterns if p.hook_type)
        structures = Counter(p.narrative_structure for p in patterns if p.narrative_structure)
        console.print(f"\n[bold]热门开头类型:[/bold] {dict(hooks.most_common(3))}")
        console.print(f"[bold]热门结构:[/bold] {dict(structures.most_common(3))}")


# ── write ─────────────────────────────────────────────────────────────────────

@cli.command()
def write(
    topic: str = typer.Option("", "--topic", "-t", help="主题提示"),
    post_type: str = typer.Option("article", "--type", help="article | thread | short_post"),
    days: int = typer.Option(7, "--days", "-d"),
    platform: str = typer.Option("x", "--platform", "-p"),
):
    """根据调研内容生成草稿。"""
    asyncio.run(_write_async(topic, post_type, days, platform))


async def _write_async(topic: str, post_type: str, days: int, platform: str):
    from app.analysis.style_miner import mine_style
    from app.writing.drafter import create_draft

    init_db()
    sources = load_recent_content(platform=platform, days=days)
    if not sources:
        console.print("[yellow]没有调研内容。先运行 `sightops research`[/yellow]")
        return

    cfg = load_yaml("configs/app.yaml")
    k = cfg["writing"]["top_k_sources"]
    top = sorted(sources, key=lambda c: c.relevance_score, reverse=True)[:k]
    console.print(f"[cyan]基于 {len(top)} 条来源生成草稿...[/cyan]")

    styles = []
    for item in top[:5]:
        try:
            styles.append(await mine_style(item))
        except Exception:
            pass

    universal = await create_draft(top, styles, topic_hint=topic)
    save_universal_draft(universal)
    console.print(f"[green]通用草稿:[/green] {universal.title}")

    platform_draft = await _adapt_to_platform(universal, post_type, platform)
    save_platform_draft(platform_draft)
    console.print(
        f"[green]{platform.upper()} 草稿已保存:[/green] {platform_draft.draft_id} "
        f"({platform_draft.post_type}, {len(platform_draft.body)} 字)"
    )


async def _adapt_to_platform(universal, post_type: str, platform: str):
    """将通用草稿适配到平台格式。"""
    import uuid
    from datetime import datetime
    from app.schemas.content import PlatformDraft

    body = universal.content or ""
    if post_type == "short_post":
        body = body[:280]
    elif post_type == "thread":
        # 简单截断，后续可用视觉模型分段发布
        pass

    return PlatformDraft(
        draft_id=uuid.uuid4().hex[:12],
        platform=platform,
        post_type=post_type,
        title=universal.title,
        body=body,
        metadata={"universal_id": universal.draft_id},
        status="pending",
        created_at=datetime.utcnow(),
    )


# ── publish ───────────────────────────────────────────────────────────────────

@cli.command()
def publish(
    draft_id: str = typer.Option("", "--id", help="草稿 ID（不传用最新的）"),
    platform: str = typer.Option("x", "--platform", "-p"),
    skip_review: bool = typer.Option(False, "--skip-review", help="跳过审核（危险！）"),
):
    """发布草稿到 X。"""
    from app.desktop.permissions import check_all_permissions

    check_all_permissions()
    asyncio.run(_publish_async(draft_id, platform, skip_review))


async def _publish_async(draft_id: str, platform: str, skip_review: bool):
    from app.core.errors import HumanReviewRequired
    from app.desktop.publisher import DesktopXPublisher

    init_db()
    drafts = load_pending_platform_drafts(platform=platform)
    if not drafts:
        console.print(f"[yellow]没有待发布的 {platform} 草稿。先运行 `sightops write`[/yellow]")
        return

    if draft_id:
        draft = next((d for d in drafts if d.draft_id == draft_id), None)
        if not draft:
            console.print(f"[red]草稿 {draft_id} 不存在。[/red]")
            return
    else:
        draft = drafts[0]
        console.print(f"使用最新草稿: [cyan]{draft.draft_id}[/cyan]")

    publisher = DesktopXPublisher()
    try:
        url = await publisher.publish_draft(draft)
        console.print(f"\n[bold green]已发布:[/bold green] {url}")
    except HumanReviewRequired as e:
        console.print(f"\n[bold red]需要人工: {e}[/bold red]")
    except Exception as e:
        console.print(f"\n[bold red]发布失败: {e}[/bold red]")


# ── status ────────────────────────────────────────────────────────────────────

@cli.command()
def status():
    """查看任务和草稿状态。"""
    init_db()
    tasks = load_tasks()[:10]
    drafts = load_pending_platform_drafts()

    t = Table(title="最近任务")
    t.add_column("ID", style="dim")
    t.add_column("类型")
    t.add_column("状态")
    for task in tasks:
        t.add_row(task.task_id[:8], task.kind.value, task.status.value)
    console.print(t)

    d = Table(title="待发布草稿")
    d.add_column("ID", style="dim")
    d.add_column("平台")
    d.add_column("类型")
    d.add_column("标题")
    for dr in drafts[:10]:
        d.add_row(dr.draft_id[:8], dr.platform, dr.post_type, (dr.title or dr.body[:40]))
    console.print(d)


if __name__ == "__main__":
    cli()
