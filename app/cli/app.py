"""
XAgent CLI  —  xagent <command>

Commands:
  research   X 调研（自动轮询方向 → API 搜索 → 视觉精读）
  report     生成调研报告
  analyze    爆款风格分析
  write      根据调研生成草稿
  publish    发布草稿到 X
  status     查看数据总览
  setup      初始化项目
  observe    实时屏幕观察器
"""
from __future__ import annotations

import asyncio
import json
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
    help="XAgent — X 平台 AI 调研与操作 Agent",
    rich_markup_mode="rich",
    add_completion=False,
    invoke_without_command=True,
)
console = Console()

# ── 视觉常量 ─────────────────────────────────────────────────────────

BRAND = "#6C63FF"
ACCENT = "#00D4AA"
WARN = "#FF6B6B"
INFO = "#58A6FF"


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
    console.print("")
    console.print(Panel(
        "\n".join(lines),
        border_style=BRAND,
        padding=(1, 2),
    ))
    console.print("")


def _next_steps(*steps: str) -> None:
    """显示下一步引导。"""
    console.print(Panel(
        "\n".join(f"  [bold white]{s}[/bold white]" for s in steps),
        title="[bold]下一步[/bold]",
        border_style=ACCENT,
    ))
    console.print("")


# ── 交互入口（无子命令时）────────────────────────────────────────────

@cli.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    """XAgent — X 平台 AI 调研与操作 Agent。"""
    if ctx.invoked_subcommand is not None:
        return

    _banner("XAgent", "X 平台 AI 调研与操作 Agent")
    menu = Table.grid(padding=(0, 2))
    menu.add_column("序号", style=BRAND, width=4)
    menu.add_column("功能")
    menu.add_column("说明", style="dim")
    menu.add_row("1", "🔍 调研", "输入主题，引导拆解方向 → API 搜索 → 视觉精读")
    menu.add_row("2", "📊 分析", "分析已采集内容的爆款风格")
    menu.add_row("3", "✍️  写作", "基于调研生成草稿")
    menu.add_row("4", "📋 总览", "查看数据统计")
    menu.add_row("5", "🚀 完整流程", "调研 → 报告 → 分析 → 写作")
    console.print(menu)
    console.print("")

    choice = typer.prompt("选择", type=int, default=1)

    if choice == 1:
        topics_str = typer.prompt("输入主题或概念", default="")
        topics = topics_str.split() if topics_str else []
        asyncio.run(_research_async(topics or [], 50, 10))
    elif choice == 2:
        days = typer.prompt("分析最近几天", type=int, default=7)
        asyncio.run(_analyze_async(days, "x"))
    elif choice == 3:
        topic = typer.prompt("主题提示", default="")
        asyncio.run(_write_async(topic, "article", 7, "x"))
    elif choice == 4:
        _status_impl()
    elif choice == 5:
        topics_str = typer.prompt("输入主题或概念", default="")
        topics = topics_str.split() if topics_str else []
        asyncio.run(_full_flow_async(topics))
    else:
        console.print(f"[{WARN}]无效选择[/]")


# ── 需求轮询 ──────────────────────────────────────────────────────────

async def _clarify_topics(topics: list[str]) -> list[str]:
    """对模糊/单一关键词做方向拆解，让用户确认后返回具体搜索词。"""
    if not topics or len(topics) > 3 or all(len(t) > 20 for t in topics):
        return topics

    keyword = " ".join(topics)
    console.print(f"\n    [{BRAND}]▶[/] 分析「{keyword}」的调研方向...")

    from app.llm.client import chat
    from app.desktop.research_agent import _safe_extract_json

    prompt = (
        f"用户想调研「{keyword}」，请拆解为 3-5 个具体的研究方向。\n"
        "每个方向需包含：\n"
        '  - id: 序号\n'
        '  - name: 方向名称（简短）\n'
        '  - description: 一句话说明\n'
        '  - keywords: 2-3 个搜索关键词（英文，适合 X 搜索）\n'
        '返回 JSON 数组，只返回 JSON。'
    )
    raw = await chat(
        [{"role": "user", "content": prompt}],
        json_mode=True, temperature=0.5, max_tokens=500,
    )

    try:
        directions = json.loads(_safe_extract_json(raw))
        if not isinstance(directions, list) or not directions:
            raise ValueError("空结果")
    except Exception:
        console.print(f"    [dim]无法拆解方向，直接搜索[/dim]")
        return topics

    # 显示方向
    console.print(f"\n    「{keyword}」可拆解为以下方向：\n")
    t = Table.grid(padding=(0, 2))
    t.add_column("序号", style=BRAND, width=4)
    t.add_column("方向")
    t.add_column("说明", style="dim")
    t.add_column("搜索词", style=INFO)
    for d in directions:
        kws = " ".join(d.get("keywords", []))
        t.add_row(str(d.get("id", 0)), d.get("name", ""), d.get("description", ""), kws)
    console.print(t)
    console.print("")

    choice = typer.prompt("选择方向（多选用逗号，0=全部）", default="0")
    selected = []
    if choice.strip() == "0":
        for d in directions:
            selected.extend(d.get("keywords", []))
    else:
        try:
            indices = [int(x.strip()) for x in choice.split(",") if x.strip()]
            for idx in indices:
                if 1 <= idx <= len(directions):
                    selected.extend(directions[idx - 1].get("keywords", []))
        except (ValueError, IndexError):
            selected = topics

    return selected if selected else topics


# ── setup ──────────────────────────────────────────────────────────────

@cli.command()
def setup():
    """初始化项目 — 首次使用运行此命令。"""
    _banner("XAgent 初始化", "X 平台视觉 AI 调研 Agent v0.1.0")

    s = get_settings()

    py_ver = f"{_plat.python_version()} {_plat.python_implementation()}"
    _step(f"Python 环境: {py_ver}", done=True)

    has_key = bool(s.llm_api_key)
    _step(f"LLM API Key: {'已配置 ✓' if has_key else '未配置 ✗'}", done=has_key)
    if not has_key:
        console.print(f"    [{WARN}]请在 .env 中设置 LLM_API_KEY[/{WARN}]")

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

    _step("初始化 SQLite 数据库...")
    init_db()
    _step("数据库初始化完成", done=True)

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
            console.print(f"    [dim]系统设置 → 隐私与安全性 → 屏幕录制 → 启用终端[/dim]")
        if not access_ok:
            console.print(f"    [{WARN}]✗ Accessibility 权限未授予[/{WARN}]")
            console.print(f"    [dim]系统设置 → 隐私与安全性 → 辅助功能 → 启用终端[/dim]")
        console.print(f"    [dim]授予权限后需重启 Terminal 生效[/dim]")

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
    _next_steps(
        'xagent research "你的概念"  — 调研（自动引导方向）',
        'xagent  — 交互模式',
    )


# ── observe ────────────────────────────────────────────────────────────

@cli.command()
def observe(
    interval: float = typer.Option(8.0, "--interval", "-i", help="截图间隔（秒）"),
):
    """实时屏幕观察器 — 全屏截图 + LLM 分析 + 操作计划。"""
    _banner("屏幕观察器", f"间隔 {interval}s · 移到左上角紧急停止")
    from app.observer.viewer import start_viewer
    start_viewer(interval=interval)


# ── research ──────────────────────────────────────────────────────────

@cli.command()
def research(
    topics: list[str] = typer.Argument(None, help="搜索主题（默认用 topics.yaml）"),
    limit: int = typer.Option(50, "--limit", "-n", help="目标采集帖子数（默认50）"),
    min_comments: int = typer.Option(10, "--min-comments", "-c", help="每个帖子最少评论数（默认10）"),
    mode: str = typer.Option("api", "--mode", "-m", help="调研模式: api | visual"),
    deep_read: int = typer.Option(3, "--deep-read", "-d", help="API 调研后视觉精读 Top N 帖子（0=关闭）"),
):
    """X 调研 — 轮询方向 → API 搜索 → 视觉精读 → 保存。"""
    if mode not in ("api", "visual"):
        console.print(f"[{WARN}]无效模式 '{mode}'，请使用 api 或 visual[/]")
        raise typer.Exit(1)
    asyncio.run(_research_async(topics or [], limit, min_comments, mode, deep_read))


async def _research_async(topics: list[str], limit: int, min_comments: int, mode: str = "api", deep_read: int = 3):
    from app.memory.sqlite_repo import count_references

    init_db()

    # ── Phase 0: 需求轮询 ────────────────────────────────────────────
    topic_cfg = load_yaml("configs/topics.yaml")
    if not topics:
        topics = topic_cfg.get("keywords", [])

    # 对模糊关键词做方向拆解
    topics = await _clarify_topics(topics)

    if mode == "visual":
        from app.desktop.permissions import check_all_permissions
        check_all_permissions()

    mode_label = "纯 API" if mode == "api" else "视觉 + API"
    _banner("XAgent 调研启动", f"{mode_label} · 综合评分 · 目标 {limit} 帖")

    # Show plan
    plan = Table.grid(padding=(0, 1))
    plan.add_column("步骤", style=BRAND)
    plan.add_column("内容")
    if mode == "api":
        plan.add_row("1", f"X API 搜索 {len(topics)} 个主题: {', '.join(topics[:5])}{'...' if len(topics) > 5 else ''}")
        plan.add_row("2", f"逐帖采集 → API 正文/评论({min_comments}+) → LLM 打分")
        plan.add_row("3", "综合评分（相关性×0.3 + 互动×0.4 + 时效×0.3）→ 筛选保存")
        if deep_read > 0:
            plan.add_row("4", f"视觉精读 Top {deep_read} 高权重帖子（图片/视频/完整正文）")
    else:
        plan.add_row("1", "打开 Safari → 导航到 x.com")
        plan.add_row("2", f"X API 搜索 {len(topics)} 个主题，按互动量排序")
        plan.add_row("3", f"逐个点开高热度帖子 → 正文/图片/API 评论({min_comments}+) → 权重打分")
    console.print(Panel(plan, title="[bold]执行计划[/bold]", border_style=BRAND))
    console.print("")

    # ── Phase 1: API 调研 ─────────────────────────────────────────────
    if mode == "api":
        from app.research.api_researcher import APIXResearcher
        researcher = APIXResearcher()
    else:
        from app.desktop.research_agent import DesktopXResearcher
        researcher = DesktopXResearcher()

    console.print(f"[{BRAND}]▸ 开始 API 搜索 X 内容...[/]")
    posts = await researcher.discover(topics or None, target_posts=limit, min_comments=min_comments)
    if not posts:
        console.print(f"\n[{WARN}]未发现相关帖子[/]")
        _next_steps(
            'xagent research "换个主题"  — 换个主题再试',
        )
        return

    # ── Phase 2: 视觉精读（仅 API 模式 + deep_read > 0）────────────
    if mode == "api" and deep_read > 0 and posts:
        try:
            from app.desktop.permissions import check_all_permissions
            check_all_permissions()

            from app.desktop.research_agent import DesktopXResearcher
            visual_reader = DesktopXResearcher()

            # 取 Top N 高权重帖子，附上 source_url 和 content_id
            top_sorted = sorted(posts, key=lambda x: x.get("final_score", 0), reverse=True)[:deep_read]
            top_with_url = []
            for p in top_sorted:
                from app.memory.sqlite_repo import load_collected_content_by_id
                cid = p.get("content_id", "")
                full = load_collected_content_by_id(cid) if cid else None
                top_with_url.append({
                    "source_url": full.source_url if full else "",
                    "content_id": cid,
                    "author": p.get("author", ""),
                    "final_score": p.get("final_score", 0),
                })

            await visual_reader.deep_read_posts(top_with_url)
        except Exception as e:
            console.print(f"\n    [{WARN}]视觉精读跳过（权限不足或出错: {e}）[/{WARN}]")

    # ── 结果展示 ──────────────────────────────────────────────────────
    avg_final = sum(p.get("final_score", 0) for p in posts) / len(posts) if posts else 0
    avg_relevance = sum(p.get("relevance_score", 0) for p in posts) / len(posts) if posts else 0
    total_likes = sum(p.get("likes", 0) for p in posts)
    total_comments = sum(p.get("replies", 0) for p in posts)
    total_reposts = sum(p.get("reposts", 0) for p in posts)
    total_views = sum(p.get("views", 0) for p in posts)

    total_refs, collected_refs = count_references("x")

    _rule()

    # 统计面板
    stats = Table.grid(padding=(0, 2))
    stats.add_column("指标", style=BRAND)
    stats.add_column("值", style="bold")
    stats.add_row("采集保存", f"{len(posts)} 条")
    stats.add_row("平均综合分", f"{avg_final:.1f}")
    stats.add_row("平均相关性", f"{avg_relevance:.1f}")
    stats.add_row("总互动", f"❤{total_likes:,} 🔁{total_reposts:,} 💬{total_comments:,} 👁{total_views:,}")
    stats.add_row("历史采集", f"共 {total_refs} 条，已深度 {collected_refs} 条")
    console.print(Panel(stats, title="[bold green]调研完成[/bold green]", border_style="green"))

    # Top 帖子
    if posts:
        top_table = Table(title="Top 帖子", border_style=BRAND, show_lines=True)
        top_table.add_column("#", width=3, style=BRAND)
        top_table.add_column("作者", width=16)
        top_table.add_column("内容", min_width=35, no_wrap=False)
        top_table.add_column("❤", justify="right", width=6)
        top_table.add_column("👁", justify="right", width=6)
        top_table.add_column("相关性", justify="right", width=5)
        top_table.add_column("综合分", justify="right", width=5, style=ACCENT)
        for i, p in enumerate(sorted(posts, key=lambda x: x.get("final_score", 0), reverse=True)[:10], 1):
            top_table.add_row(
                str(i),
                f"@{p.get('author', '')[:15]}",
                p.get("text_preview", "")[:50],
                str(p.get("likes", 0)),
                str(p.get("views", 0)),
                f"{p.get('relevance_score', 0):.1f}",
                f"{p.get('final_score', 0):.1f}",
            )
        console.print(top_table)
        console.print("")

    # 引导下一步
    topic_str = posts[0].get("topic", "") if posts else ""
    _next_steps(
        f'xagent report "{topic_str}"  — 生成调研报告',
        "xagent analyze  — 爆款风格分析",
        f'xagent research "{topic_str}" --deep-read 5  — 精读更多帖子',
    )


# ── 完整流程 ──────────────────────────────────────────────────────────

async def _full_flow_async(topics: list[str]):
    """调研 → 报告 → 分析 → 写作 全流程。"""
    await _research_async(topics, 30, 10)

    topic = topics[0] if topics else ""

    console.print("\n[bold]── Step 2/4: 生成报告 ──[/bold]\n")
    from app.analysis.report import generate_report, save_report_to_file
    markdown = await generate_report(topic, days=7, report_type="research")
    if markdown.startswith("#"):
        filepath = save_report_to_file(markdown, topic)
        console.print(f"  [green]✓ 报告已保存: {filepath}[/green]")

    console.print("\n[bold]── Step 3/4: 爆款风格分析 ──[/bold]\n")
    await _analyze_async(7, "x")

    console.print("\n[bold]── Step 4/4: 生成草稿 ──[/bold]\n")
    await _write_async(topic, "article", 7, "x")

    _rule("完整流程结束")
    _next_steps(
        "xagent publish  — 发布草稿到 X",
        "xagent status   — 查看数据总览",
    )


# ── report ────────────────────────────────────────────────────────────

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

    preview = markdown[:800] + ("..." if len(markdown) > 800 else "")
    console.print(Panel(preview, title=f"[bold]{topic} — 预览[/bold]", border_style=ACCENT))
    console.print("")

    _next_steps(
        "xagent analyze  — 爆款风格分析",
        'xagent write --topic "主题"  — 生成草稿',
    )


# ── analyze ────────────────────────────────────────────────────────────

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

    _next_steps(
        'xagent write --topic "主题"  — 基于风格生成草稿',
        'xagent research "新方向"  — 继续调研',
    )


# ── write ─────────────────────────────────────────────────────────────

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

    _next_steps(
        f"xagent publish --id {platform_draft.draft_id[:12]}  — 发布到 X",
        "xagent status  — 查看所有草稿",
    )


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


# ── publish ────────────────────────────────────────────────────────────

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


# ── status ────────────────────────────────────────────────────────────

@cli.command()
def status():
    """查看数据总览。"""
    _status_impl()


def _status_impl():
    init_db()

    from app.memory.sqlite_repo import count_references

    total_refs, collected_refs = count_references("x")
    tasks = load_tasks()[:10]
    drafts = load_pending_platform_drafts()
    sources = load_collected_content(platform="x", days=30)

    _banner("数据总览", "XAgent")

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

    if sources:
        c = Table(title="最近采集内容 (Top 10)", border_style=BRAND)
        c.add_column("作者", style=BRAND)
        c.add_column("赞", justify="right")
        c.add_column("浏览", justify="right")
        c.add_column("评论", justify="right")
        c.add_column("综合分", justify="right", style=ACCENT)
        c.add_column("标题", min_width=30)
        for item in sorted(sources, key=lambda x: getattr(x, 'final_score', x.relevance_score), reverse=True)[:10]:
            c.add_row(
                f"@{item.author[:15]}",
                str(item.metrics.likes),
                str(item.metrics.views),
                str(len(item.comments)),
                f"{getattr(item, 'final_score', 0):.1f}",
                (item.title or item.body_text[:40])[:50],
            )
        console.print(c)
        console.print("")

    _next_steps(
        'xagent research "新方向"  — 继续调研',
        'xagent write  — 生成草稿',
    )


if __name__ == "__main__":
    cli()
