#!/usr/bin/env python3
"""
禅道数据实时刷新 — 本地中转服务（托管报告 + 代理API）

用法:
    py _live_refresh_server.py [port]
    默认端口 8900

然后浏览器打开 http://localhost:8900/ 即可查看当日所有报告。
点击报告中的刷新按钮即可实时拉取最新禅道数据。
"""
import http.server
import io
import json
import urllib.parse
import sys
import os
import time
import mimetypes
from datetime import date, datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Windows 控制台 UTF-8 兼容
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from _zentao_config import get_zentao_api, get_credentials_dict

ZENTAO = get_zentao_api()
CREDENTIALS = get_credentials_dict()
BASE_DIR = Path(__file__).parent

def get_report_dir():
    """Return today's report directory (computed at call time, not server startup)"""
    return BASE_DIR / date.today().isoformat()

# 流水线状态追踪
PIPELINE_STATUS = {
    "running": False,
    "start_time": None,
    "end_time": None,
    "elapsed": 0,
    "git_push_time": None,  # 记录 git push 完成时间，浏览器据此计算 GH Pages 部署倒计时
    "error": None,
}


def get_token():
    now = time.time()
    if TOKEN_CACHE["token"] and now < TOKEN_CACHE["expires"]:
        return TOKEN_CACHE["token"]
    resp = requests.post(f"{ZENTAO}/tokens", json=CREDENTIALS, verify=False, timeout=10)
    TOKEN_CACHE["token"] = resp.json()["token"]
    TOKEN_CACHE["expires"] = now + 240
    return TOKEN_CACHE["token"]


def get_all_pages(path, key, token, params=None):
    items, page = [], 1
    while True:
        data = requests.get(
            f"{ZENTAO}{path}",
            headers={"Token": token},
            params={**(params or {}), "limit": 200, "page": page},
            verify=False, timeout=30,
        ).json()
        batch = data.get(key, [])
        if not batch: break
        items.extend(batch)
        if len(items) >= data.get("total", 0) or len(batch) < 200: break
        page += 1
        if page > 100: break
    return items


def fetch_iteration_data(eid):
    token = get_token()
    it = requests.get(f"{ZENTAO}/executions/{eid}", headers={"Token": token}, verify=False, timeout=15).json()

    with ThreadPoolExecutor(max_workers=3) as ex:
        fs = ex.submit(get_all_pages, f"/executions/{eid}/stories", "stories", token)
        ft = ex.submit(get_all_pages, f"/executions/{eid}/tasks", "tasks", token)
        fb = ex.submit(get_all_pages, f"/executions/{eid}/bugs", "bugs", token)
        stories, tasks, bugs = fs.result(), ft.result(), fb.result()

    today = date.today()
    progress = float(it.get("progress", 0) or 0)

    try:
        begin = date.fromisoformat(it.get("begin", ""))
        end = date.fromisoformat(it.get("end", ""))
        total_days = (end - begin).days
        elapsed = (today - begin).days
    except:
        total_days = elapsed = 1
    time_pct = round(elapsed / max(total_days, 1) * 100, 1)

    task_status = defaultdict(int)
    for t in tasks: task_status[t.get("status", "?")] += 1

    story_status = defaultdict(int)
    for s in stories: story_status[s.get("status", "?")] += 1

    active_bugs = [b for b in bugs if b.get("status") not in ("closed", "resolved", "postponed", "delay")]

    stage_dist = defaultdict(int)
    for s in stories:
        st = s.get("stage", "")
        if st: stage_dist[st] += 1

    SL = {"projected": "\u5df2\u7acb\u9879", "developing": "\u5f00\u53d1\u4e2d",
          "developed": "\u5f00\u53d1\u5b8c\u6210", "testing": "\u6d4b\u8bd5\u4e2d",
          "tested": "\u5df2\u63d0\u6d4b", "verified": "\u5df2\u9a8c\u6536",
          "released": "\u5df2\u53d1\u5e03", "planned": "\u5df2\u89c4\u5212"}
    sk = ["projected", "developing", "tested", "developed", "verified", "released", "planned"]
    sl = [SL.get(k, k) for k in sk if stage_dist.get(k)]
    sv = [stage_dist[k] for k in sk if stage_dist.get(k)]
    if not sv: sl, sv = ["\u5df2\u7acb\u9879"], [len(stories)]

    SS = {"wait": "\u5f85\u5904\u7406", "doing": "\u8fdb\u884c\u4e2d", "done": "\u5df2\u5b8c\u6210",
          "closed": "\u5df2\u5173\u95ed", "pause": "\u6682\u505c", "cancel": "\u5df2\u53d6\u6d88", "changed": "\u5df2\u53d8\u66f4"}
    ssk = ["closed", "done", "doing", "wait", "changed", "pause"]
    ssl, ssv = [SS.get(k, k) for k in ssk], [task_status.get(k, 0) for k in ssk]

    TS = {"a_dev4_control": "\u540e\u7aef-control", "a_dev": "\u540e\u7aef", "a_dev2_front": "\u524d\u7aef",
          "a_dev6_mobile": "\u79fb\u52a8\u7aef", "ab1_needs_research": "\u4ea7\u54c1\u8c03\u7814",
          "ab2_request_des": "\u9700\u6c42\u8bbe\u8ba1", "ad1_UI_des": "UI\u8bbe\u8ba1",
          "ae1_test_des": "\u6d4b\u8bd5\u8bbe\u8ba1", "ae2_test": "\u6d4b\u8bd5",
          "affair": "\u4e8b\u52a1", "misc": "\u6742\u9879"}
    tt = defaultdict(int)
    for t in tasks: tt[t.get("type", "?")] += 1
    ti = sorted(tt.items(), key=lambda x: -x[1])
    tl, tv = [TS.get(k, k) for k, v in ti], [v for k, v in ti]

    return {
        "success": True, "today": today.isoformat(),
        "it": {"name": it.get("name", ""), "status": it.get("status", ""),
               "progress": progress, "time_pct": time_pct, "elapsed": elapsed,
               "total_days": total_days, "story_count": len(stories),
               "task_total": len(tasks), "bug_total": len(bugs),
               "doing": task_status.get("doing", 0), "wait": task_status.get("wait", 0),
               "active_bugs": len(active_bugs)},
        "story_stats": {"active": story_status.get("active", 0),
                        "closed": story_status.get("closed", 0),
                        "changed": story_status.get("changed", 0),
                        "draft": story_status.get("draft", 0)},
        "charts": {"stage": {"labels": sl, "data": sv},
                   "status": {"labels": ssl, "data": ssv},
                   "type": {"labels": tl, "data": tv}},
    }


class Server(http.server.BaseHTTPRequestHandler):
    def log_request(self, code='-', size='-'):
        client = self.client_address[0]
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] {client} {self.command} {self.path} -> {code}")

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path or "/"

        # API: 实时刷新
        if path.startswith("/api/refresh/"):
            try:
                eid = int(path.rsplit("/", 1)[-1])
                data = fetch_iteration_data(eid)
                self._json(200, data)
            except Exception as e:
                import traceback; traceback.print_exc()
                self._json(500, {"error": str(e)})
            return

        # Root dashboard summary
        if path == "/api/refresh-root":
            self._json(200, fetch_root_summary())
            return

        # 流水线状态查询
        if path == "/api/pipeline-status":
            self._json(200, {
                "running": PIPELINE_STATUS["running"],
                "elapsed": round(time.time() - PIPELINE_STATUS["start_time"], 1) if PIPELINE_STATUS["start_time"] else 0,
                "git_push_time": PIPELINE_STATUS["git_push_time"],
                "error": PIPELINE_STATUS["error"],
            })
            return

        # 仪表盘：直接返回根 index.html（绕过 GitHub Pages CDN 延迟）
        if path == "/dashboard":
            dashboard_path = BASE_DIR / "index.html"
            if dashboard_path.exists():
                self._serve_file(dashboard_path)
                return
            self._html(404, "<h1>404</h1><p>Dashboard not found</p>")
            return

        # GitHub Pages 触发：后台跑完整管线
        if path == "/trigger-pipeline":
            self._trigger_pipeline()
            return

        # 效率分析刷新
        if path.startswith("/api/refresh-efficiency"):
            self._refresh_efficiency(path)
            return

        # Health
        if path == "/health":
            self._json(200, {"status": "ok", "service": "zentao-relay", "reports": str(get_report_dir())})
            return

        # Serve static files from today's report dir
        if path == "/":
            self._serve_index()
            return

        # Strip leading /
        filepath = get_report_dir() / path.lstrip("/")
        if filepath.exists() and filepath.is_file():
            self._serve_file(filepath)
        else:
            # Try with path as-is
            if not filepath.exists():
                self._html(404, f"<h1>404</h1><p>File not found: {path}</p>")
            else:
                self._serve_file(filepath)

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def _trigger_pipeline(self):
        """Run full pipeline in background, track status, push git early"""
        import subprocess, threading, shutil

        if PIPELINE_STATUS["running"]:
            self._html(200, """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title></title>
<style>body{font-family:-apple-system,sans-serif;background:#1a1a2e;color:#fff;text-align:center;padding-top:40px}
h2{color:#f59e0b;font-size:18px}p{color:#888;font-size:13px}</style>
</head><body><h2> 管线正在运行中</h2><p>请稍后再试，上次刷新尚未完成</p>
<script>setTimeout(function(){window.close();},2000);</script>
</body></html>""")
            return

        self._html(200, """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>刷新中...</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,sans-serif;background:#1a1a2e;color:#fff;text-align:center;padding-top:60px}
h2{color:#10b981;font-size:18px}p{color:#888;font-size:13px;margin-top:8px}
.elapsed{font-size:36px;font-weight:700;color:#667eea;margin:16px 0}
.bar{width:200px;height:4px;background:rgba(255,255,255,0.1);border-radius:2px;margin:16px auto;overflow:hidden}
.bar-inner{height:100%;width:0;background:linear-gradient(90deg,#667eea,#4facfe);border-radius:2px;animation:pulse 1.5s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:0.6}50%{opacity:1}}
</style>
</head><body><h2> 正在进行管线刷新</h2>
<p>拉取最新禅道数据、生成报告、推送 GitHub ...</p>
<div class="elapsed" id="elapsed">0s</div>
<div class="bar"><div class="bar-inner"></div></div>
<p style="margin-top:16px" id="status"></p>
<script>
var svr = location.origin;
var started = Date.now();
var timer = setInterval(function(){
  var e = document.getElementById('elapsed');
  e.textContent = Math.round((Date.now()-started)/1000) + 's';
  fetch(svr + '/api/pipeline-status').then(function(r){return r.json()}).then(function(s){
    if(!s.running && s.git_push_time){
      document.getElementById('status').textContent = ' 完成！等待 GitHub Pages 部署（约15秒）...';
      var done = Date.now();
      var wait = setInterval(function(){
        var rem = Math.max(0, 15 - Math.round((Date.now()-done)/1000));
        document.getElementById('elapsed').textContent = rem + 's 后刷新';
        if(rem <= 0){ clearInterval(wait); window.close(); }
      }, 500);
      clearInterval(timer);
    } else if(s.error){
      document.getElementById('status').textContent = ' 刷新失败: ' + s.error;
      clearInterval(timer);
      setTimeout(function(){window.close();}, 5000);
    }
  }).catch(function(){});
}, 2000);
// 120s 超时自动关闭
setTimeout(function(){ clearInterval(timer); window.close(); }, 120000);
</script>
</body></html>""")

        def run():
            PIPELINE_STATUS["running"] = True
            PIPELINE_STATUS["start_time"] = time.time()
            PIPELINE_STATUS["error"] = None
            PIPELINE_STATUS["git_push_time"] = None

            today = date.today().isoformat()
            tasks_dir = "C:/Users/gree/tasks"

            print(f"  [PIPELINE] Starting _run_full_parallel.py ...")
            try:
                result = subprocess.run(
                    [sys.executable, str(BASE_DIR / "_run_full_parallel.py")],
                    cwd=str(BASE_DIR), capture_output=True, text=True, timeout=180
                )
                print(f"  [PIPELINE] Done (rc={result.returncode})")
                for line in (result.stdout or "").strip().split('\n'):
                    if any(k in line for k in ['OK', 'Complete', 'func1', 'iter-', 'workload', 'trend', 'push', 'FAIL', 'Error', 'ERROR']):
                        print(f"    {line.strip()[:120]}")

                # 记录 git push 完成时间
                PIPELINE_STATUS["git_push_time"] = time.time()

                # 确保时间戳已更新：直接修改 index.html 的 date-tag
                try:
                    ts = time.strftime("%Y-%m-%d %H:%M", time.localtime())
                    idx_path = BASE_DIR / "index.html"
                    with open(idx_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    import re
                    content, n = re.subn(
                        r'(<div class="date-tag"><span>)\d{4}-\d{2}-\d{2} \d{2}:\d{2}( 更新</span></div>)',
                        rf'\g<1>{ts}\g<2>', content
                    )
                    if n > 0:
                        with open(idx_path, "w", encoding="utf-8") as f:
                            f.write(content)
                        print(f"  [PIPELINE] Timestamp updated to {ts}")
                    else:
                        print(f"  [PIPELINE] Timestamp update: pattern not found")
                except Exception as ts_err:
                    print(f"  [PIPELINE] Timestamp update failed: {ts_err}")

            except Exception as e:
                PIPELINE_STATUS["error"] = str(e)
                print(f"  [PIPELINE] Error: {e}")

            PIPELINE_STATUS["running"] = False
            PIPELINE_STATUS["end_time"] = time.time()
            PIPELINE_STATUS["elapsed"] = round(PIPELINE_STATUS["end_time"] - PIPELINE_STATUS["start_time"], 1)
            print(f"  [PIPELINE] Total: {PIPELINE_STATUS['elapsed']}s")

        threading.Thread(target=run, daemon=True).start()


    def _refresh_efficiency(self, path):
        """Refresh workload analysis report in background"""
        import subprocess, threading, shutil, glob
        parsed = urllib.parse.urlparse(path)
        params = urllib.parse.parse_qs(parsed.query)
        month = params.get("month", [date.today().strftime("%Y-%m")])[0]

        self._html(200, f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title></title>
<style>body{{font-family:-apple-system,sans-serif;background:#1a1a2e;color:#fff;text-align:center;padding-top:40px}}
h2{{color:#10b981;font-size:18px}}p{{color:#888;font-size:13px;margin-top:8px}}</style>
</head><body><h2> 已触发效率分析刷新</h2><p>正在拉取 {month} 全量数据并重新计算...</p><p style="color:#667eea;margin-top:16px">约 25 秒后刷新页面即可看到最新数据</p>
<script>setTimeout(function(){{window.close();}},3000);</script>
</body></html>""")
        def run():
            print(f"  [EFFICIENCY] Starting _workload_analysis.py --month {month} ...")
            try:
                result = subprocess.run(
                    [sys.executable, str(BASE_DIR / "_workload_analysis.py"), "--month", month],
                    cwd=str(BASE_DIR), capture_output=True, text=True, timeout=120
                )
                print(f"  [EFFICIENCY] Done (rc={result.returncode})")
                for line in (result.stdout or "").strip().split('\n'):
                    if any(k in line for k in ['OK', 'HTML', 'JSON', '当月', 'Top', '合计']):
                        print(f"    {line.strip()[:120]}")

                # Copy output to tasks repo and push
                tasks_dir = "C:/Users/gree/tasks"
                today_dir = date.today().isoformat()
                dst_dir = os.path.join(tasks_dir, today_dir)
                os.makedirs(dst_dir, exist_ok=True)

                # Find generated files (auto-detect by month param)
                month_slug = month.replace("-", "")
                src_html = os.path.join(str(get_report_dir()), f"团队产出效率分析_{month_slug}.html")
                src_json = os.path.join(str(get_report_dir()), f"团队工时负载分析_{month_slug}.json")
                if os.path.exists(src_html):
                    shutil.copy2(src_html, os.path.join(dst_dir, f"团队产出效率分析_{month_slug}.html"))
                if os.path.exists(src_json):
                    shutil.copy2(src_json, os.path.join(dst_dir, f"团队工时负载分析_{month_slug}.json"))

                git_result = subprocess.run(
                    ["git", "add", f"{today_dir}/团队产出效率分析_202606.html", f"{today_dir}/团队工时负载分析_202606.json"],
                    cwd=tasks_dir, capture_output=True, text=True, timeout=15
                )
                subprocess.run(["git", "commit", "-m", f"update: {today_dir} 效率分析刷新"], cwd=tasks_dir, capture_output=True, timeout=15)
                push_result = subprocess.run(["git", "push", "origin", "main"], cwd=tasks_dir, capture_output=True, text=True, timeout=30)
                print(f"  [EFFICIENCY] Git push: {'OK' if push_result.returncode == 0 else 'FAILED'}")

            except Exception as e:
                import traceback; traceback.print_exc()
                print(f"  [EFFICIENCY] Error: {e}")
        threading.Thread(target=run, daemon=True).start()


def fetch_root_summary():
    """Fetch summary counts for the root dashboard page (product/backend/frontend/mobile/overdue)"""
    import os, json, glob

    today_dir = BASE_DIR / date.today().isoformat()
    result = {"product_count": 0, "backend_count": 0, "frontend_count": 0, "mobile_count": 0, "overdue_count": 0}
    
    json_map = {
        "product_count": "未完成产品任务_统计.json",
        "backend_count": "未完成后端开发_统计.json",
        "frontend_count": "未完成前端开发_统计.json",
        "mobile_count": "未完成移动端开发_统计.json",
        "overdue_count": "延期任务统计.json",
    }
    for key, filename in json_map.items():
        path = today_dir / filename
        if path.exists():
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                result[key] = data.get("total_incomplete", data.get("total_overdue", data.get("total", data.get("count", len(data.get("tasks", []))))))
            except:
                pass
    return result

def _serve_index(self):
    """List all report files in today's directory"""
    if not get_report_dir().exists():
        self._html(200, f"<h1>No reports yet</h1><p>Directory {get_report_dir()} not found</p>")
        return

    files = sorted(get_report_dir().glob("*.html"))
    items = []
    for f in files:
        name = f.name
        size = f.stat().st_size
        label = name.replace("\u6267\u884c\u8fdb\u5c55\u62a5\u544a", "").replace(".html", "")
        if "\u8fed\u4ee3" in name:
            label = name.replace("_\u6267\u884c\u8fdb\u5c55\u62a5\u544a.html", "").replace("\u8fed\u4ee3", "\u8fed\u4ee3 ")
        items.append(f'<li><a href="{name}">{label}</a> <span style="color:#888;font-size:12px;">({size//1024}KB)</span></li>')

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>{date.today().isoformat()} \u62a5\u544a\u4e2d\u5fc3</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;background:linear-gradient(135deg,#1a1a2e,#16213e,#0f3460);min-height:100vh;display:flex;justify-content:center;padding:40px 20px}}
.card{{background:rgba(255,255,255,0.05);backdrop-filter:blur(10px);border-radius:20px;padding:40px;max-width:700px;width:100%;border:1px solid rgba(255,255,255,0.1)}}
h1{{color:#fff;font-size:24px;margin-bottom:8px}}h1 span{{color:#667eea}}
.sub{{color:rgba(255,255,255,0.5);font-size:13px;margin-bottom:30px}}
ul{{list-style:none}}li{{margin:6px 0}}
a{{color:#4facfe;text-decoration:none;font-size:15px;transition:.2s}}a:hover{{color:#7ec8f7;text-decoration:underline}}
.badge{{display:inline-block;padding:2px 10px;border-radius:12px;font-size:11px;margin-left:8px}}
.badge-report{{background:rgba(79,172,254,0.2);color:#4facfe}}
.badge-other{{background:rgba(255,255,255,0.1);color:#aaa}}
.status{{color:#10b981;font-size:13px;margin-top:30px;padding:12px;background:rgba(16,185,129,0.1);border-radius:10px;text-align:center}}
</style></head><body><div class="card">
<h1><span>\U0001f4ca</span> \u7f51\u6279\u9879\u76ee\u62a5\u544a\u4e2d\u5fc3</h1>
<div class="sub">{date.today().isoformat()} \u62a5\u544a &nbsp;|&nbsp; \u5171 {len(files)} \u4e2a\u6587\u4ef6</div>
<ul>{"".join(items)}</ul>
<div class="status">\U0001f504 \u5b9e\u65f6\u5237\u65b0\u670d\u52a1\u5df2\u542f\u52a8\uff08\u62a5\u544a\u5185\u70b9\u51fb\u5237\u65b0\u6309\u94ae\u5373\u53ef\u66f4\u65b0\u6570\u636e\uff09</div>
</div></body></html>"""
    self._html(200, html)

def _serve_file(self, filepath):
    content_type, _ = mimetypes.guess_type(str(filepath))
    content_type = content_type or "application/octet-stream"
    data = filepath.read_bytes()
    self.send_response(200)
    self.send_header("Content-Type", f"{content_type}; charset=utf-8")
    self.send_header("Content-Length", str(len(data)))
    self.send_header("Cache-Control", "no-cache")
    self.end_headers()
    self.wfile.write(data)

def _cors(self):
    self.send_header("Access-Control-Allow-Origin", "*")
    self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
    self.send_header("Access-Control-Allow-Headers", "Content-Type")
    self.send_header("Access-Control-Allow-Private-Network", "true")

def _json(self, code, data):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    self.send_response(code)
    self.send_header("Content-Type", "application/json; charset=utf-8")
    self._cors()
    self.send_header("Content-Length", str(len(body)))
    self.end_headers()
    self.wfile.write(body)

def _html(self, code, body):
    data = body.encode("utf-8")
    self.send_response(code)
    self.send_header("Content-Type", "text/html; charset=utf-8")
    self._cors()
    self.send_header("Content-Length", str(len(data)))
    self.end_headers()
    self.wfile.write(data)

def log_message(self, format, *args):
    path = args[0] if args else ""
    if "/api/" in str(path):
        print(f"  [API] {path}")
    else:
        pass

# 挂载到 Server 类（因这些方法定义在类外部）
Server._serve_index = _serve_index
Server._serve_file = _serve_file
Server._cors = _cors
Server._json = _json
Server._html = _html
Server.log_message = log_message


PORT = 8900


def main():
    global PORT
    if len(sys.argv) > 1:
        PORT = int(sys.argv[1])

    banner = f"""
\u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510
\u2502  \U0001f504 \u7985\u9053\u62a5\u544a\u4e2d\u5fc3 \u2014 \u5b9e\u65f6\u5237\u65b0\u670d\u52a1       \u2502
\u2502  \U0001f4e1 http://localhost:{PORT}                \u2502
\u2502  \U0001f4c2 {get_report_dir()}         \u2502
\u2502  \U0001f6e1  \u81ea\u52a8\u5b88\u62a4\u6a21\u5f0f\u5df2\u542f\u7528                      \u2502
\u2502  \u23f9  Ctrl+C \u505c\u6b62                            \u2502
\u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2518
"""
    restart_delay = 3
    print(banner)
    while True:
        try:
            server = http.server.HTTPServer(("0.0.0.0", PORT), Server)
            server.serve_forever()
        except KeyboardInterrupt:
            print("\n \u5df2\u505c\u6b62")
            try:
                server.shutdown()
            except:
                pass
            break
        except Exception as e:
            print(f"\n \u26a0 \u670d\u52a1\u5d29\u6e83: {e}")
            print(f"   {restart_delay}\u79d2\u540e\u81ea\u52a8\u91cd\u542f...\n")
            time.sleep(restart_delay)


if __name__ == "__main__":
    main()
