# SightOps

全屏视觉 AI 调研 Agent — 像真人一样操作你的 Mac，实时记录每条调研结果。

**技术栈**：Qwen3.6-Plus（视觉）· PyAutoGUI（全局控制）· Notion API · SQLite · Python 3.13

---

## 快速上手

```bash
# 1. 安装
pip install -e .

# 2. 系统授权：系统设置 > 隐私与安全性 > 屏幕录制 + 辅助功能 → 启用 Terminal
#    （授权后重启 Terminal）

# 3. 初始化
sightops setup

# 4. 编辑 .env，填入 LLM API Key
#    LLM_API_KEY=sk-xxx

# 5. 观察屏幕（可选，用于调试）
sightops observe

# 6. 开始调研
sightops research "AI agent" -n 5
```

---

## 详细配置

编辑 `.env` 文件，配置以下参数：

### LLM（必需）
```
LLM_API_KEY=sk-xxx
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen3.6-plus
```

### Notion（可选，用于同步调研内容）

1. 在 Notion 创建三个数据库：Research / Templates / Drafts
2. 把 Integration Share 到这三个库
3. 数据库 ID 填入 `.env`：

```
NOTION_TOKEN=ntn_xxx
NOTION_RESEARCH_DB_ID=xxx
NOTION_TEMPLATE_DB_ID=xxx
NOTION_DRAFT_DB_ID=xxx
```

---

## 使用流程

### Step 0 — 实时屏幕观察

```bash
# 打开观察窗口 — 全屏截图 + LLM 分析 + 操作计划
sightops observe

# 自定义间隔（默认 8 秒）
sightops observe -i 5
```

打开一个 900x600 的小窗口，每 8 秒：
1. **截全屏** → base64 编码
2. **LLM 分析** → 描述当前屏幕状态
3. **生成计划** → 下一步操作建议
4. **实时更新** → 窗口自动刷新截图和分析

> 适合调试调研流程、观察 LLM 如何理解屏幕、验证视觉定位效果。

### Step 1 — 调研（全屏视觉，每条实时记录）

```bash
# 用 topics.yaml 关键词搜索 X
sightops research

# 指定主题和数量
sightops research "AI agent" "vibe coding" --limit 10
```

**工作流程**：
1. 全屏截图 → Qwen 视觉模型识别界面元素
2. PyAutoGUI 在对应坐标点击/输入，像真人一样操作
3. 每采集到一条帖子 → **立刻保存**到 SQLite + 同步 Notion
4. 不批量等待，逐条记录

> 紧急终止：鼠标移到屏幕左上角（PyAutoGUI FAILSAFE）

### Step 2 — 分析

```bash
# 对最近 7 天采集的内容做爆款风格分析
sightops analyze
```

### Step 3 — 写作

```bash
# 生成 X 长文
sightops write --type article --topic "AI Agent 趋势"

# 生成 Thread
sightops write --type thread

# 生成短帖
sightops write --type short_post
```

### Step 4 — 发布

```bash
# 查看待发布草稿
sightops status

# 发布最新草稿（全屏视觉操作 X 发布）
sightops publish
```

---

## 项目结构

```
app/
  core/         配置、错误、日志
  schemas/      数据模型
  llm/          Qwen3.6-Plus 客户端（OpenAI 兼容）
  desktop/      桌面级控制：全屏截图 + PyAutoGUI + 视觉定位
    observer.py       screencapture 全屏截图
    executor.py       PyAutoGUI 全局鼠标/键盘
    action_planner.py 视觉模型 → 屏幕坐标动作计划
    research_agent.py X 调研 Agent（发现 + 采集 + 实时记录）
    publisher.py      X 发布器
    permissions.py    macOS 权限检查
  observer/     实时屏幕观察器（截图 → LLM 分析 → 操作计划 → 小窗口显示）
    viewer.py         pywebview 实时观察窗口
  analysis/     爆款风格挖掘
  writing/      内容生成
  integrations/ Notion API
  assets/       图片下载
  memory/       SQLite 本地存储
  platforms/x/  X 平台规则常量
  cli/          Typer CLI 入口
prompts/        LLM prompt 模板
configs/        YAML 配置
data/           运行时数据（screenshots / drafts / cache / runs）
```
