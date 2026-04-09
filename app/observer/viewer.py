"""实时屏幕观察器 — 全屏截图 + LLM 视觉分析 + 操作计划，像日志一样竖向输出。"""
from __future__ import annotations

import base64
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

import webview

from app.llm.client import _sync_vision_chat

_tmp_dir = Path(tempfile.gettempdir()) / "sightops_observer"
_tmp_dir.mkdir(exist_ok=True)

# Log entries accumulated for display
_log_entries: list[dict] = []
_lock = threading.Lock()
_running = False


def _capture_screen() -> str | None:
    """截全屏，返回 base64 data URI。"""
    try:
        tmp = _tmp_dir / "screen.png"
        subprocess.run(["screencapture", "-x", str(tmp)], check=True, capture_output=True)
        data = base64.b64encode(tmp.read_bytes()).decode()
        return f"data:image/png;base64,{data}"
    except Exception:
        return None


def _analyze_screen(img_tmp: str) -> tuple[str, str]:
    """视觉分析 + 操作计划。"""
    analysis_prompt = (
        "描述这个 macOS 屏幕截图：\n"
        "1. 当前显示的应用/窗口/内容\n"
        "2. 可交互元素（按钮、输入框、菜单）\n"
        "3. 是否有错误或弹窗\n"
        "简洁，每行一条。"
    )
    analysis = _sync_vision_chat(text_prompt=analysis_prompt, image_path=img_tmp, max_tokens=512)

    plan_prompt = (
        "下一步应该做什么操作？\n"
        "列出 1-3 个具体步骤（点击位置、输入内容等）。\n"
        "简洁，每步一行。"
    )
    plan = _sync_vision_chat(text_prompt=plan_prompt, image_path=img_tmp, max_tokens=256)
    return analysis, plan


def _save_img_tmp(b64: str) -> str:
    """base64 → temp file。"""
    if b64.startswith("data:"):
        b64 = b64.split(",", 1)[1]
    tmp = _tmp_dir / "screen.png"
    tmp.write_bytes(base64.b64decode(b64))
    return str(tmp)


def _push_entry(window, entry: dict):
    """将一条日志追加到前端。"""
    js = (
        f"appendEntry({{"
        f"  time: '{entry['time']}',"
        f"  cycle: {entry['cycle']},"
        f"  img: {entry['img'] if entry['img'] else 'null'},"
        f"  analysis: `{entry['analysis'].replace('`', '\\x60')}`,"
        f"  plan: `{entry['plan'].replace('`', '\\x60')}`,"
        f"  error: `{entry.get('error', '')}`"
        f"}});"
    )
    try:
        window.evaluate_js(js)
    except Exception:
        pass


def _background_loop(window, interval: float):
    """后台循环：截图 → 分析 → 推送日志。"""
    global _running
    _running = True
    cycle = 0

    while _running:
        cycle += 1
        now = datetime.now().strftime("%H:%M:%S")
        entry = {"time": now, "cycle": cycle, "img": None, "analysis": "", "plan": "", "error": ""}

        try:
            img_b64 = _capture_screen()
            if not img_b64:
                entry["error"] = "截图失败"
            else:
                entry["img"] = img_b64
                img_tmp = _save_img_tmp(img_b64)
                entry["analysis"], entry["plan"] = _analyze_screen(img_tmp)
        except Exception as e:
            entry["error"] = str(e)

        _push_entry(window, entry)
        time.sleep(interval)


# ── HTML ─

HTML_PAGE = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,"PingFang SC",monospace;background:#0a0a0f;color:#c8c8d0;overflow:hidden}
.hdr{position:fixed;top:0;left:0;right:0;height:36px;background:#12121a;border-bottom:1px solid #2a2a3a;display:flex;align-items:center;padding:0 16px;z-index:10}
.hdr h1{font-size:13px;color:#e94560;margin-right:16px}
.st{font-size:11px;color:#555}
.st.on{color:#4ecca3}
.badge{background:#e94560;color:#fff;padding:1px 8px;border-radius:8px;font-size:10px;margin-left:8px}
.log{position:absolute;top:36px;left:0;right:0;bottom:0;overflow-y:auto;padding:12px}
.entry{border:1px solid #1e1e2e;border-radius:8px;margin-bottom:12px;background:#101018;overflow:hidden}
.entry-bar{background:#161622;padding:6px 12px;font-size:11px;color:#e94560;display:flex;align-items:center;gap:8px}
.entry-bar .t{color:#666;font-size:10px;margin-left:auto}
.img-wrap{padding:8px;background:#0a0a0f;text-align:center}
.img-wrap img{max-width:100%;max-height:300px;border-radius:4px;border:1px solid #2a2a3a}
.sec{padding:8px 12px;border-top:1px solid #1a1a28}
.sec .lbl{font-size:10px;color:#e94560;text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px}
.sec .txt{font-size:12px;line-height:1.6;color:#bbb;white-space:pre-wrap}
.err{padding:8px 12px;background:#1a0808;border-top:1px solid #3a1a1a;color:#e94560;font-size:12px}
::-webkit-scrollbar{width:5px}
::-webkit-scrollbar-thumb{background:#333;border-radius:3px}
</style></head><body>
<div class="hdr">
  <h1>SightOps 观察器</h1>
  <span class="st" id="st">● 启动中...</span>
  <span class="badge" id="bg">0</span>
</div>
<div class="log" id="log">
  <div style="text-align:center;color:#444;padding:60px 20px;font-size:13px;line-height:2">
    等待截图...<br>
    <span style="font-size:11px;color:#333">窗口打开后后台线程开始工作</span>
  </div>
</div>
<script>
var count=0;
window.appendEntry=function(e){
  count++;
  document.getElementById('bg').textContent=count;
  var log=document.getElementById('log');
  // 第一次清空提示
  if(count===1) log.innerHTML='';
  var d=document.createElement('div');
  d.className='entry';
  var h='<div class="entry-bar"><span>Cycle '+e.cycle+'</span><span class="t">'+e.time+'</span></div>';
  if(e.img) h+='<div class="img-wrap"><img src="'+e.img+'"></div>';
  if(e.analysis) h+='<div class="sec"><div class="lbl">屏幕分析</div><div class="txt">'+esc(e.analysis)+'</div></div>';
  if(e.plan) h+='<div class="sec"><div class="lbl">操作计划</div><div class="txt">'+esc(e.plan)+'</div></div>';
  if(e.error) h+='<div class="err">ERR '+esc(e.error)+'</div>';
  d.innerHTML=h;
  log.appendChild(d);
  log.scrollTop=log.scrollHeight;
};
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>')}
</script></body></html>"""


def start_viewer(interval: float = 10.0):
    """启动实时屏幕观察窗口。"""
    global _running

    def on_loaded(window):
        thread = threading.Thread(target=_background_loop, args=(window, interval), daemon=True)
        thread.start()
        # Update status after a delay
        def set_running():
            try:
                window.evaluate_js("document.getElementById('st').textContent='● 运行中';"
                                   "document.getElementById('st').className='st on';")
            except Exception:
                pass
        threading.Timer(1.0, set_running).start()

    window = webview.create_window(
        title="SightOps — 屏幕观察器",
        html=HTML_PAGE,
        width=550,
        height=850,
        min_size=(450, 500),
    )
    window.events.loaded += on_loaded
    webview.start(debug=False)
    _running = False
