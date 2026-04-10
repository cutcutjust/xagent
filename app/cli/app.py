"""
XAgent CLI  —  xagent <command>

Commands:
  setup      初始化项目（首次使用）
  observe    实时屏幕观察器
  research   全屏视觉调研 X
  analyze    爆款风格分析
  write      根据调研生成草稿
  publish    发布草稿到 X
  status     查看数据总览
"""
from __future__ import annotations

import asyncio
import platform as _plat
import shutil

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from app.core.config import get_settings, load_yaml
from app.memory.sqlite_repo import (
    init_db,
    load_pending_platform_drafts,
    load_collected_content,
    load_tasks,
    save_platform_draft,
    save_universal_draft,
)

cli = typer.Typer(
    name="xagent",
    help="XAgent — X 平台视觉 AI 调研与操作 Agent",
    rich_markup_mode="rich",
    add_completion=False,
)
console = Console()

# ── 视觉常量 ─────────────────────────────────────────────────────────

BRAND = "#6C63FF"  # 主题紫
ACCENT = "#00D4AA"  # 主题绿
WARN = "#FF6B6B"    # 警告红
INFO = "#58A6FF"    # 信息蓝

def _header(text: str) -> Panel:
    return Panel(
        Text(text, style=f"bold {BRAND}"),
        border_style=BRAND,
        padding=(0, 2),
    )

def _step(text: str, done: bool = False) -> None:
    icon = "[bold green]✓[/bold green]" if done else f"[{BRAND}▶[/]"
    style = "dim" if done else ""
    console.print(f"    {icon} [{style}]{text}[/{style}]")

def _rule(text: str = "") -> None:
    console.print(Rule(text, style=f"dim {BRAND}"))

def _banner(text: str, subtitle: str = "") -> None:
    lines = [f"[bold {BRAND}]{text}[/bold {BRAND}]"]
    if subtitle:
        lines.append(f"[dim]{subtitle}[/dim]")
    w = shutil.get_terminal_size().columns
    console.print("")
    console.print(Panel(
        "\n".join(lines),
        border_style=BRAND,
        padding=(1, 2),
    ))
    console.print("")


# ── setup ─────────────────────────────────────────────────────────────────────

@cli.command()
def setup():
    """初始化项目 — 首次使用运行此命令。"""
    _banner("XAgent 初始化", "X 平台视觉 AI 调研 Agent v0.1.0")

    s = get_settings()

    # Step 1: 检查 Python
    py_ver = f"{_plat.python_version()} {_plat.python_implementation()}"
    _step(f"Python 环境: {py_ver}", done=True)

    # Step 2: 检查配置
    has_key = bool(s.llm_api_key)
    _step(f"LLM API Key: {'已配置 ✓' if has_key else '未配置 ✗'}", done=has_key)
    if not has_key:
        console.print(f"    [{WARN}]请在 .env 中设置 LLM_API_KEY[/{WARN}]")

    # Step 3: 创建目录
    dirs = [
        ("数据目录", s.data_path),
        ("资源目录", s.assets_path),
        ("截图缓存", s.data_path / "screenshots"),
        ("桌面截图", s.data_path / "desktop_screenshots"),
        ("草稿目录", s.data_path / "drafts"),
        ("缓存目录", s.data_path / "cache"),
        ("运行日志", s.data_path / "runs"),
    ]
    _step("创建目录结构...")
    for name, path in dirs:
        path.mkdir(parents=True, exist_ok=True)
    _step("目录结构创建完成", done=True)

    # Step 4: 初始化数据库
    _step("初始化 SQLite 数据库...")
    init_db()
    _step("数据库初始化完成", done=True)

    # Step 5: 检查权限
    _step("检查 macOS 权限...")
    from app.desktop.permissions import (
        check_screen_recording,
        check_accessibility,
    )
    screen_ok = check_screen_recording()
    access_ok = check_accessibility()
    if screen_ok and access_ok:
        _step("Screen Recording + Accessibility 权限正常", done=True)
    else:
        console.print("")
        if not screen_ok:
            console.print(f"    [{WARN}]✗ Screen Recording 权限未授予[/{WARN}]")
            console.print(f"    [dim]系统设置 → 隐私与安全性 → 屏幕录制 → 启用终端[/{dim}]")
        if not access_ok:
            console.print(f"    [{WARN}]✗ Accessibility 权限未授予[/{WARN}]")
            console.print(f"    [dim]系统设置 → 隐私与安全性 → 辅助功能 → 启用终端[/{dim}]")
        console.print(f"    [dim]授予权限后需重启 Terminal 生效[/{dim}]")

    # Summary
    _rule()
    console.print("")
    summary = Table.grid(padding=(0, 2))
    summary.add_column("项目", style=BRAND)
    summary.add_column("值")
    summary.add_row("数据目录", str(s.data_path))
    summary.add_row("资源目录", str(s.assets_path))
    summary.add_row("LLM 模型", s.llm_vision_model)
    summary.add_row("数据库", "SQLite ✓")
    summary.add_row("Notion", "已配置 ✓" if s.notion_token else "未配置")
    console.print(Panel(summary, title="[bold green]Setup 完成[/bold green]", border_style="green"))
    console.print("")
    console.print("  [dim]下一步: [bold white]xagent research \"你的主题\"[/bold white][/dim]")
    console.print("")


# ── observe ──────────────────────────────────────────────────────────────────

@cli.command()
def observe(
    interval: float = typer.Option(8.0, "--interval", "-i", help="截图间隔（秒）"),
):
    """实时屏幕观察器 — 全屏截图 + LLM 分析 + 操作计划。"""
    _banner("屏幕观察器", f"间隔 {interval}s · 移到左上角紧急停止")
    from app.observer.viewer import start_viewer
    start_viewer(interval=interval)


# ── research ──────────────────────────────────────────────────────────────────

@cli.command()
def research(
    topics: list[str] = typer.Argument(None, help="搜索主题（默认用 topics.yaml）"),
    limit: int = typer.Option(50, "--limit", "-n", help="目标采集帖子数（默认50）"),
    min_comments: int = typer.Option(10, "--min-comments", "-c", help="每个帖子最少评论数（默认10）"),
):
    """X API 调研 — 搜索 → 热度排序 → 深度采集 → 实时保存 MD + Notion。"""
    asyncio.run(_research_async(topics or [], limit, min_comments))


async def _research_async(topics: list[str], limit: int, min_comments: int):
    from app.desktop.permissions import check_all_permissions
    from app.desktop.research_agent import DesktopXResearcher
    from app.memory.sqlite_repo import count_references

    init_db()
    check_all_permissions()

    _banner("XAgent 调研启动", f"API 搜索 · 热度排序 · 实时保存 · 目标 {limit} 帖")

    topic_cfg = load_yaml("configs/topics.yaml")
    if not topics:
        topics = topic_cfg.get("keywords", [])

    # Show plan
    plan = Table.grid(padding=(0, 1))
    plan.add_column("步骤", style=BRAND)
    plan.add_column("内容")
    plan.add_row("1", "打开 Safari → 导航到 x.com")
    plan.add_row("2", f"X API 搜索 {len(topics)} 个主题，按互动量排序: {', '.join(topics[:5])}{'...' if len(topics) > 5 else ''}")
    plan.add_row("3", f"逐个点开高热度帖子 → 正文/图片/API 评论({min_comments}+) → 权重打分")
    plan.add_row("4", "实时保存: SQLite + 本地 MD + Notion（每帖立即保存）")
    plan.add_row("5", f"目标采集 {limit} 条")
    plan.add_row("6", "生成调研报告（带引用）: xagent report")
    console.print(Panel(plan, title="[bold]执行计划[/bold]", border_style=BRAND))
    console.print("")

    researcher = DesktopXResearcher()

    console.print(f"[{BRAND}]▸ 开始 API 搜索 X 内容...[/]")
    posts = await researcher.discover(topics or None, target_posts=limit, min_comments=min_comments)
    if not posts:
        console.print(f"[{WARN}]未发现相关帖子[/]")
        return

    # Summary
    avg_score = sum(p.get("engagement_score", 0) for p in posts) / len(posts) if posts else 0
    total_likes = sum(p.get("likes", 0) for p in posts)
    total_comments = sum(p.get("replies", 0) for p in posts)

    total_refs, collected_refs = count_references("x")

    _rule()
    console.print("")
    summary = Table.grid(padding=(0, 2))
    summary.add_column("指标", style=BRAND)
    summary.add_column("值", style="bold")
    summary.add_row("帖子深度采集", str(len(posts)))
    summary.add_row("总互动量", f"❤{total_likes} 💬{total_comments}")
    summary.add_row("平均权重分", f"{avg_score:.0f}")
    summary.add_row("总引用记录", str(total_refs))
    summary.add_row("已深度采集", str(collected_refs))
    summary.add_row("已浏览/跳过", str(total_refs - collected_refs))
    console.print(Panel(summary, title="[bold green]调研完成[/bold green]", border_style="green"))
    console.print("")
    console.print(f"  [dim]生成报告: [bold white]xagent report \"你的主题\"[/bold white][/dim]")
    console.print("")


# ── report ────────────────────────────────────────────────────────────────────

@cli.command()
def report(
    topic: str = typer.Argument("", help="报告主题"),
    report_type: str = typer.Option("research", "--type", "-t", help="research | article | summary"),
    days: int = typer.Option(7, "--days", "-d", help="加载最近 N 天的数据"),
):
    """基于采集的帖子生成调研报告（带引用）。"""
    asyncio.run(_report_async(topic, report_type, days))


async def _report_async(topic: str, report_type: str, days: int):
    init_db()

    _banner("生成调研报告", f"主题: {topic} · 类型: {report_type} · 最近 {days} 天")

    from app.analysis.report import generate_report, save_report_to_file

    console.print(f"    [{BRAND}]▶[/] 生成报告中...")
    markdown = await generate_report(topic, days=days, report_type=report_type)

    if not markdown.startswith("#"):
        console.print(f"[{WARN}]{markdown}[/]")
        return

    filepath = save_report_to_file(markdown, topic)
    console.print(f"    [{ACCENT}]✓ 报告已保存: {filepath}[/{ACCENT}]")
    console.print("")

    # Show preview
    preview = markdown[:800] + ("..." if len(markdown) > 800 else "")
    console.print(Panel(preview, title=f"[bold]{topic} — 预览[/bold]", border_style=ACCENT))
    console.print("")


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
    items = load_collected_content(platform=platform, days=days)
    if not items:
        console.print(f"[{WARN}]最近 {days} 天没有 {platform.upper()} 内容。先运行 research[/]")
        return

    _banner("爆款风格分析", f"最近 {days} 天 · {platform.upper()} · {len(items)} 条内容")

    console.print(f"    [{BRAND}]▶[/] 分析 {len(items)} 条内容...")
    patterns = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("分析中...", total=len(items[:20]))
        for item in items[:20]:
            try:
                pattern = await mine_style(item)
                patterns.append(pattern)
                progress.update(task, advance=1, description=f"  @{item.author}  ✓")
            except Exception as e:
                progress.update(task, advance=1, description=f"  @{item.author}  ✗ {e}")

    if not patterns:
        console.print(f"[{WARN}]所有分析均失败[/]")
        return

    # Results table
    from collections import Counter
    hooks = Counter(p.hook_type for p in patterns if p.hook_type)
    structures = Counter(p.narrative_structure for p in patterns if p.narrative_structure)

    _rule("分析结果")
    console.print("")

    t = Table(title="模式统计", border_style=BRAND)
    t.add_column("类型", style=BRAND)
    t.add_column("Top 3")
    hook_str = " | ".join(f"{k}: {v}" for k, v in hooks.most_common(3))
    struct_str = " | ".join(f"{k}: {v}" for k, v in structures.most_common(3))
    t.add_row("开头类型", hook_str)
    t.add_row("叙事结构", struct_str)
    t.add_row("分析样本", f"{len(patterns)} / {len(items[:20])}")
    console.print(t)
    console.print("")


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
    sources = load_collected_content(platform=platform, days=days)
    if not sources:
        console.print(f"[{WARN}]没有调研内容。先运行 [bold]xagent research[/bold][/]")
        return

    cfg = load_yaml("configs/app.yaml")
    k = cfg["writing"]["top_k_sources"]
    top = sorted(sources, key=lambda c: c.relevance_score, reverse=True)[:k]

    _banner("草稿生成", f"基于 {len(top)} 条来源 · {post_type} · {platform.upper()}")

    console.print(f"    [{BRAND}]▶[/] 提取写作风格...")
    styles = []
    for item in top[:5]:
        try:
            styles.append(await mine_style(item))
        except Exception:
            pass
    _step(f"提取 {len(styles)} 个风格模式", done=True)

    console.print(f"    [{BRAND}]▶[/] 生成通用草稿...")
    universal = await create_draft(top, styles, topic_hint=topic)
    save_universal_draft(universal)
    _step(f"通用草稿: {universal.title}", done=True)

    console.print(f"    [{BRAND}]▶[/] 适配 {platform.upper()} 格式...")
    platform_draft = await _adapt_to_platform(universal, post_type, platform)
    save_platform_draft(platform_draft)
    _step(f"{platform.upper()} 草稿已保存: {platform_draft.draft_id[:12]} ({len(platform_draft.body)} 字)", done=True)

    _rule()
    console.print("")
    preview = platform_draft.body[:300] + ("..." if len(platform_draft.body) > 300 else "")
    console.print(Panel(preview, title=f"[bold]{platform_draft.title}[/bold]", border_style=ACCENT))
    console.print("")
    console.print(f"  [dim]发布: [bold white]xagent publish --id {platform_draft.draft_id[:12]}[/bold white][/dim]")
    console.print("")


async def _adapt_to_platform(universal, post_type: str, platform: str):
    import uuid
    from datetime import datetime
    from app.schemas.content import PlatformDraft

    body = universal.content or ""
    if post_type == "short_post":
        body = body[:280]
    elif post_type == "thread":
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
        console.print(f"[{WARN}]没有待发布的 {platform.upper()} 草稿。先运行 xagent write[/]")
        return

    if draft_id:
        draft = next((d for d in drafts if d.draft_id == draft_id), None)
        if not draft:
            console.print(f"[{WARN}]草稿 {draft_id} 不存在[/]")
            return
    else:
        draft = drafts[0]

    _banner("发布草稿", f"{platform.upper()} · {draft.title}")

    # Show draft preview
    preview = draft.body[:500] + ("..." if len(draft.body) > 500 else "")
    console.print(Panel(preview, title="[bold]草稿预览[/bold]", border_style=ACCENT))
    console.print("")

    publisher = DesktopXPublisher()
    try:
        console.print(f"    [{BRAND}]▶[/] 正在发布...")
        url = await publisher.publish_draft(draft)
        console.print(f"\n    [bold green]✓ 已发布: {url}[/bold green]\n")
    except HumanReviewRequired as e:
        console.print(f"\n    [{WARN}]需要人工介入: {e}[/{WARN}]\n")
    except Exception as e:
        console.print(f"\n    [{WARN}]✗ 发布失败: {e}[/{WARN}]\n")


# ── status ────────────────────────────────────────────────────────────────────

@cli.command()
def status():
    """查看数据总览。"""
    init_db()

    from app.memory.sqlite_repo import count_references

    total_refs, collected_refs = count_references("x")
    tasks = load_tasks()[:10]
    drafts = load_pending_platform_drafts()
    sources = load_collected_content(platform="x", days=30)

    _banner("数据总览", "XAgent")

    # Overview
    overview = Table.grid(padding=(0, 2))
    overview.add_column("指标", style=BRAND)
    overview.add_column("值", style="bold")
    overview.add_row("调研帖子", str(len(sources)))
    overview.add_row("已深度采集", str(collected_refs))
    overview.add_row("已浏览/跳过", str(total_refs - collected_refs))
    overview.add_row("待发布草稿", str(len(drafts)))
    overview.add_row("最近任务", str(len(tasks)))
    console.print(Panel(overview, title="[bold]总览[/bold]", border_style=BRAND))
    console.print("")

    # Drafts table
    if drafts:
        d = Table(title="待发布草稿", border_style=BRAND)
        d.add_column("ID", style="dim", width=12)
        d.add_column("平台", width=8)
        d.add_column("类型", width=12)
        d.add_column("标题", min_width=30)
        for dr in drafts[:10]:
            d.add_row(dr.draft_id[:12], dr.platform.upper(), dr.post_type, (dr.title or dr.body[:40]))
        console.print(d)
        console.print("")

    # Recent content
    if sources:
        c = Table(title="最近采集内容 (Top 10)", border_style=BRAND)
        c.add_column("作者", style=BRAND)
        c.add_column("赞", justify="right")
        c.add_column("浏览", justify="right")
        c.add_column("评论", justify="right")
        c.add_column("相关性", justify="right")
        c.add_column("标题", min_width=30)
        for item in sorted(sources, key=lambda x: x.relevance_score, reverse=True)[:10]:
            c.add_row(
                f"@{item.author[:15]}",
                str(item.metrics.likes),
                str(item.metrics.views),
                str(len(item.comments)),
                f"{item.relevance_score:.1f}",
                (item.title or item.body_text[:40])[:50],
            )
        console.print(c)
        console.print("")


if __name__ == "__main__":
    cli()
