#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub Actions 禅道数据自动采集 Pipeline
=========================================
触发方式: GitHub repository_dispatch → workflow → 本脚本
功能: 拉取禅道三平台数据 → 生成 6 路任务报告 + 延期报告 + 迭代总览 + 趋势 → 提交推送

用法:
  python scripts/pipeline.py              # 完整 pipeline
  python scripts/pipeline.py --dry-run    # 只拉取不提交
  python scripts/pipeline.py --skip-push  # 生成报告但不推送
"""

import os, sys, json, time, re, shutil
from pathlib import Path
from datetime import date, datetime, timedelta
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests, urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── 环境自适应 ──
WORKSPACE = Path(os.environ.get('GITHUB_WORKSPACE',
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
TODAY = date.today().isoformat()
TODAY_DATE = date.today()
OUTPUT_DIR = WORKSPACE / TODAY
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

ZENTAO_BASE = os.environ.get('ZENTAO_BASE', 'https://ztpm.gree.com:8888')
ZENTAO_ACCOUNT = os.environ.get('ZENTAO_ACCOUNT', 'A80065')
ZENTAO_PASSWORD = os.environ.get('ZENTAO_PASSWORD', '')

print(f"  Workspace : {WORKSPACE}")
print(f"  Output    : {OUTPUT_DIR}")
print(f"  Date      : {TODAY}")
print(f"  Zentao    : {ZENTAO_BASE}")

# ════════════════════════════════════════════════════
# Part 1: Zentao API
# ════════════════════════════════════════════════════

TOKEN = None

def refresh_token():
    global TOKEN
    resp = requests.post(f"{ZENTAO_BASE}/api.php/v1/tokens",
        json={"account": ZENTAO_ACCOUNT, "password": ZENTAO_PASSWORD},
        verify=False, timeout=30)
    if resp.status_code in (200, 201):
        TOKEN = resp.json().get("token", "")
        print(f"  [Auth] Token obtained")
    else:
        raise Exception(f"Auth failed: {resp.status_code} {resp.text[:200]}")
    return TOKEN

def api_get(path, params=None, retry=True):
    global TOKEN
    if TOKEN is None:
        refresh_token()
    try:
        resp = requests.get(f"{ZENTAO_BASE}{path}", headers={"Token": TOKEN},
            params=params or {}, verify=False, timeout=30)
        if resp.status_code == 401 and retry:
            refresh_token()
            return api_get(path, params, retry=False)
        return resp.json() if resp.text else {}
    except Exception as e:
        print(f"  [API Error] {path}: {e}")
        return {}

def get_all_pages(path, key, params=None):
    all_items = []
    page = 1
    params = params or {}
    while True:
        params["limit"] = 100; params["page"] = page
        data = api_get(path, params)
        items = data.get(key, [])
        if not items: break
        all_items.extend(items)
        total = data.get("total", 0)
        page += 1
        if len(all_items) >= total or len(items) < 100 or page > 100: break
    return all_items

# ════════════════════════════════════════════════════
# Part 2: Data Fetching & Classification
# ════════════════════════════════════════════════════

PLATFORM_MAP = {
    "网批2.0": {"project_id": 902, "product_id": 115},
    "集采平台": {"project_id": 1244, "product_id": 161},
    "分销平台": {"project_id": 1245, "product_id": 160},
}

CATEGORY_RULES = [
    ("product",  lambda t: (t.get("type") or "").startswith("ab")),
    ("backend",  lambda t: (t.get("type") or "") in ("a_dev4_control", "a_dev")),
    ("frontend", lambda t: (t.get("type") or "") == "a_dev2_front"),
    ("mobile",   lambda t: (t.get("type") or "") == "a_dev6_mobile"),
    ("test",     lambda t: (t.get("type") or "") in {"ae2_test", "ae1_test_des"}),
]

CAT_CONFIG = {
    "product":  {"label": "产品任务", "func": "12", "html_name": "未完成ab类型任务_详细任务.html", "color": "#667eea"},
    "backend":  {"label": "后端开发", "func": "13", "html_name": "未完成后端开发任务_详细任务.html", "color": "#4facfe"},
    "frontend": {"label": "前端开发", "func": "14", "html_name": "未完成前端开发任务_详细任务.html", "color": "#43e97b"},
    "mobile":   {"label": "移动端开发", "func": "15", "html_name": "未完成移动端开发任务_详细任务.html", "color": "#f5576c"},
    "test":     {"label": "测试任务", "func": "17", "html_name": "未完成测试任务_详细任务.html", "color": "#26c6da"},
}

PERSON_COLORS = ["667eea","f093fb","4facfe","43e97b","f5576c","ffa726","26c6da",
                 "ab47bc","ef5350","66bb6a","ff7043","5c6bc0","29b6f6","8e24aa","d84315","00897b"]
PRI_COLORS = {1:"#f5576c",2:"#ffa726",3:"#4facfe",4:"#66bb6a"}
PRI_NAMES = {1:"1-紧急",2:"2-高",3:"3-中",4:"4-低"}
STATUS_BADGES = {"wait":"badge-wait","doing":"badge-doing","pause":"badge-pause"}
STATUS_NAMES = {"wait":"待处理","doing":"进行中","pause":"暂停"}
SKIPPED_STATUS = {"closed", "cancel", "done", "pause"}

EXEC_CACHE = {}
TASK_CACHE = {}

def get_execs_cached(project_id):
    if project_id not in EXEC_CACHE:
        data = api_get(f"/api.php/v1/projects/{project_id}/executions", {"limit": 1000})
        EXEC_CACHE[project_id] = data.get("executions", [])
    return EXEC_CACHE[project_id]

def fetch_tasks_for_exec(exec_id):
    if exec_id not in TASK_CACHE:
        try:
            TASK_CACHE[exec_id] = get_all_pages(
                f"/api.php/v1/executions/{exec_id}/tasks", "tasks")
        except:
            TASK_CACHE[exec_id] = []
    return TASK_CACHE[exec_id]

def fetch_all_platforms(max_workers=15):
    t0 = time.time()
    print("\n[Fetch] Getting execs for 3 platforms...")
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(get_execs_cached, PLATFORM_MAP[p]["project_id"]): p
                   for p in PLATFORM_MAP}
        for f in as_completed(futures): pass

    all_execs = [(e["id"], e.get("name","")) for pname, pinfo in PLATFORM_MAP.items()
                 for e in get_execs_cached(pinfo["project_id"])]
    if not all_execs:
        print("  [WARN] No execs found!")
        return {k: [] for k, _ in CATEGORY_RULES}, []

    print(f"  Fetching tasks for {len(all_execs)} execs ({max_workers}t)...")
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(fetch_tasks_for_exec, eid): eid for eid, _ in all_execs}
        for f in as_completed(futures): pass

    cats = {cat: [] for cat, _ in CATEGORY_RULES}
    overdue_tasks = []
    dedup = set()

    for exec_id, exec_name in all_execs:
        tasks = TASK_CACHE.get(exec_id, [])
        platform = "未知"
        for pname, pinfo in PLATFORM_MAP.items():
            execs_list = EXEC_CACHE.get(pinfo["project_id"], [])
            if any(e.get("id") == exec_id for e in execs_list):
                platform = pname; break

        for task in tasks:
            tid = task.get("id")
            if tid in dedup: continue
            dedup.add(tid)
            if task.get("status","") in SKIPPED_STATUS: continue
            task["_exec_name"] = exec_name
            task["_platform"] = platform
            task["_assignee_name"] = (
                task.get("assignedTo",{}).get("realname","未指派")
                if isinstance(task.get("assignedTo"), dict) else "未指派")
            deadline = task.get("deadline","")
            if deadline and len(deadline) >= 10:
                try:
                    dl = date.fromisoformat(deadline[:10])
                    task["_days_overdue"] = (TODAY_DATE - dl).days if dl < TODAY_DATE else 0
                except: task["_days_overdue"] = 0
            else: task["_days_overdue"] = 0

            classified = False
            for cat, rule in CATEGORY_RULES:
                if rule(task):
                    cats[cat].append(task); classified = True; break
            if task["_days_overdue"] > 0:
                overdue_tasks.append(task)

    elapsed = time.time() - t0
    total = sum(len(v) for v in cats.values())
    print(f"  Classified: {total} tasks + {len(overdue_tasks)} overdue ({elapsed:.1f}s)")
    for cat in cats: print(f"    {cat}: {len(cats[cat])}")
    return cats, overdue_tasks

def _task_to_dict(t):
    return {
        "id": t.get("id"), "name": t.get("name"), "type": t.get("type"),
        "status": t.get("status"), "assignee": t["_assignee_name"],
        "exec_name": t["_exec_name"], "deadline": t.get("deadline"),
        "days_overdue": t["_days_overdue"], "estimate": t.get("estimate"),
        "consumed": t.get("consumed"), "left": t.get("left"), "pri": t.get("pri"),
        "openedDate": t.get("openedDate",""), "platform": t.get("_platform"),
    }

def build_output(cat_key, tasks):
    by_assignee = defaultdict(list)
    for t in tasks: by_assignee[t["_assignee_name"]].append(t)
    type_counts = defaultdict(int)
    for t in tasks: type_counts[t.get("type","未知")] += 1
    result = {
        "check_date": TODAY,
        "config_key": cat_key,
        "task_label": CAT_CONFIG[cat_key]["label"],
        "platform": "三平台汇总",
        "total_incomplete": len(tasks),
        "type_breakdown": dict(type_counts),
        "summary": {
            "wait": sum(1 for t in tasks if t.get("status")=="wait"),
            "doing": sum(1 for t in tasks if t.get("status")=="doing"),
            "overdue": sum(1 for t in tasks if t.get("_days_overdue",0)>0),
        },
        "by_assignee": {},
    }
    for assignee, tl in sorted(by_assignee.items(), key=lambda x: -len(x[1])):
        result["by_assignee"][assignee] = {
            "count": len(tl),
            "wait": sum(1 for t in tl if t.get("status")=="wait"),
            "doing": sum(1 for t in tl if t.get("status")=="doing"),
            "estimate": sum(t.get("estimate",0) for t in tl),
            "consumed": sum(t.get("consumed",0) for t in tl),
            "left": sum(t.get("left",0) for t in tl),
            "tasks": [_task_to_dict(t) for t in tl],
        }
    return result


# ════════════════════════════════════════════════════
# Part 3: HTML Generation (5/28 Style)
# ════════════════════════════════════════════════════

_CSS_528 = '''<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif; background: #f0f2f5; color: #333; padding: 20px; }
.header { text-align: center; padding: 20px 0; }
.header h1 { font-size: 24px; color: #1a1a2e; }
.header p { color: #888; margin-top: 4px; font-size:13px; }
.cards { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 20px; }
.card { flex: 1; min-width: 120px; background: #fff; border-radius: 10px; padding: 16px; text-align: center; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
.card .num { font-size: 28px; font-weight: 700; }
.card .label { font-size: 12px; color: #888; margin-top: 4px; }
.card-total .num { color: #667eea; }
.card-wait .num { color: #f5576c; }
.card-doing .num { color: #43e97b; }
.card-overdue .num { color: #ffa726; }
.card-people .num { color: #4facfe; }
.charts { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 20px; }
.chart-box { flex: 1; min-width: 320px; background: #fff; border-radius: 10px; padding: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
.chart-box h3 { font-size: 14px; color: #555; margin-bottom: 10px; text-align: center; }
.chart-container { position: relative; height: 300px; }
.chart-container canvas { max-height: 300px; }
details { background: #fff; border-radius: 10px; margin-bottom: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); overflow: hidden; }
summary { padding: 12px 16px; cursor: pointer; font-weight: 600; display: flex; align-items: center; gap: 8px; flex-wrap: nowrap; user-select: none; overflow-x: auto; }
summary::-webkit-details-marker { display: none; }
.assignee-name { font-size: 15px; }
.assignee-stats { display: flex; gap: 6px; flex-wrap: nowrap; margin-left: auto; flex-shrink: 0; }
.stat-badge { font-size: 11px; padding: 2px 8px; border-radius: 10px; background: #eee; color: #555; font-weight: normal; white-space:nowrap; }
.stat-wait { background: #fde8e8; color: #c62828; }
.stat-doing { background: #e8f5e9; color: #2e7d32; }
.stat-overdue { background: #fff3e0; color: #e65100; }
.stat-h { background: #e3f2fd; color: #1565c0; }
.table-wrapper { overflow-x: auto; padding: 0 16px 16px; }
table { width: 100%; border-collapse: collapse; font-size: 12px; }
th { background: #f5f6f8; padding: 8px 6px; text-align: left; font-weight: 600; white-space: nowrap; position: sticky; top: 0; }
td { padding: 6px; border-bottom: 1px solid #f0f0f0; white-space: nowrap; }
tr:hover { background: #fafbfc; }
tr.row-overdue { background: #fff5f5 !important; }
tr.row-overdue td:first-child { border-left: 3px solid #ef4444; }
tr.row-overdue:hover { background: #fee2e2 !important; }
.badge-wait { display: inline-block; padding: 1px 6px; border-radius: 8px; font-size: 11px; background: #fde8e8; color: #c62828; }
.badge-doing { display: inline-block; padding: 1px 6px; border-radius: 8px; font-size: 11px; background: #e8f5e9; color: #2e7d32; }
.badge-pause { display: inline-block; padding: 1px 6px; border-radius: 8px; font-size: 11px; background: #f5f5f5; color: #666; }
.badge-overdue { display: inline-block; padding: 1px 6px; border-radius: 8px; font-size: 11px; background: #fff3e0; color: #e65100; }
.back-link { text-align: center; margin-bottom: 16px; }
.back-link a { color: #667eea; text-decoration: none; font-size: 13px; padding: 6px 16px; border-radius: 16px; background: #e8ecf4; border: 1px solid #d0d5e0; display: inline-block; transition: background 0.2s; }
.back-link a:hover { background: #d0d5e0; }
.footer { text-align: center; color: #aaa; font-size: 12px; padding: 20px; }
</style>'''

def _esc(s):
    return (s or "-").replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;").replace("'","&#39;")

def generate_528_html(label, total, summary, by_assignee, type_breakdown=None, output_path=""):
    wait_cnt, doing_cnt, overdue_cnt = summary["wait"], summary["doing"], summary["overdue"]
    people_cnt = len(by_assignee)
    pri_map = defaultdict(int)
    for a, info in by_assignee.items():
        for t in info.get("tasks",[]):
            pri_map[t.get("pri",0)] += 1
    person_names = list(by_assignee.keys())
    person_counts = [by_assignee[a]["count"] for a in person_names]
    person_colors = [f"#{PERSON_COLORS[i%len(PERSON_COLORS)]}" for i in range(len(person_names))]
    type_desc = ""
    if type_breakdown:
        type_desc = " | 类型: " + " . ".join(f"{k}({v})" for k,v in sorted(type_breakdown.items()))

    html = '<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n<meta charset="UTF-8">\n'
    html += '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
    html += f'<title>未完成{label}任务明细</title>\n'
    html += '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>\n'
    html += _CSS_528 + '\n</head>\n<body>\n'
    html += f'<div class="header"><h1>未完成{label}任务明细</h1>\n'
    html += f'<p>统计日期: {TODAY} | 总计: {total} 个未完成任务 | 涉及 {people_cnt} 人{type_desc}</p></div>\n'
    html += '<div class="back-link"><a href="../index.html">← 返回报告中心</a></div>\n'
    html += '<div class="cards">\n'
    html += f'<div class="card card-total"><div class="num">{total}</div><div class="label">任务总数</div></div>\n'
    html += f'<div class="card card-wait"><div class="num">{wait_cnt}</div><div class="label">待处理</div></div>\n'
    html += f'<div class="card card-doing"><div class="num">{doing_cnt}</div><div class="label">进行中</div></div>\n'
    html += f'<div class="card card-overdue"><div class="num">{overdue_cnt}</div><div class="label">延期</div></div>\n'
    html += f'<div class="card card-people"><div class="num">{people_cnt}</div><div class="label">负责人</div></div>\n'
    html += '</div>\n'
    top_n = min(len(person_names), 14)
    html += '<div class="charts">\n'
    html += f'<div class="chart-box"><h3>负责人任务分布 (Top{top_n})</h3><div class="chart-container"><canvas id="barChart"></canvas></div></div>\n'
    html += '<div class="chart-box"><h3>任务状态分布</h3><div class="chart-container"><canvas id="statusPie"></canvas></div></div>\n'
    html += '<div class="chart-box"><h3>优先级分布</h3><div class="chart-container"><canvas id="priPie"></canvas></div></div>\n'
    html += '</div>\n'
    html += '<div class="details">\n<h3 style="margin-bottom:10px;">按负责人明细（点击展开）</h3>\n'
    for i, (assignee, info) in enumerate(by_assignee.items()):
        color = f"#{PERSON_COLORS[i%len(PERSON_COLORS)]}"
        open_attr = " open" if i == 0 else ""
        i_wait, i_doing = info.get("wait",0), info.get("doing",0)
        i_est, i_con, i_left = info.get("estimate",0), info.get("consumed",0), info.get("left",0)
        i_overdue = sum(1 for t in info.get("tasks",[]) if t.get("days_overdue",0)>0)
        html += f'    <details{open_attr}>\n'
        html += f'        <summary style="background:{color}15; border-left:4px solid {color};">\n'
        html += f'            <span class="assignee-name">{assignee}</span>\n'
        html += f'            <span class="assignee-stats">\n'
        html += f'                <span class="stat-badge">共{info["count"]}个</span>\n'
        html += f'                <span class="stat-badge stat-wait">待处理{i_wait}</span>\n'
        html += f'                <span class="stat-badge stat-doing">进行中{i_doing}</span>\n'
        html += f'                <span class="stat-badge stat-overdue">延期{i_overdue}</span>\n'
        html += f'                <span class="stat-badge stat-h">预估{i_est}h</span>\n'
        html += f'            </span>\n'
        html += f'        </summary>\n<div class="table-wrapper">\n<table>\n<thead>\n<tr>\n'
        html += f'<th>ID</th><th>任务名称</th><th>状态</th><th>优先级</th><th>类型</th><th>执行</th><th>截止日期</th><th>延期</th><th>预估h</th></tr>\n</thead>\n<tbody>\n'
        sorted_tasks = sorted(info.get("tasks",[]), key=lambda t:(0 if t.get("status")=="doing" else 1, t.get("deadline") or "9999"))
        for t in sorted_tasks:
            st = t.get("status","wait")
            badge_cls = STATUS_BADGES.get(st,"badge-wait")
            st_name = STATUS_NAMES.get(st,st)
            pri_name = PRI_NAMES.get(t.get("pri",0),str(t.get("pri",0)))
            overdue_val = t.get("days_overdue",0)
            overdue_display = f"+{overdue_val}天" if overdue_val > 0 else ""
            row_cls = ' class="row-overdue"' if overdue_val > 0 else ""
            html += f'<tr{row_cls}><td>{t.get("id","-")}</td><td title="{_esc(t.get("name","-"))}">{t.get("name","-")}</td><td><span class="{badge_cls}">{st_name}</span></td><td>{pri_name}</td><td>{t.get("type","-")}</td><td>{t.get("exec_name","-")}</td><td>{t.get("deadline","-")}</td><td>{overdue_display}</td><td>{t.get("estimate","-")}</td></tr>\n'
        html += '</tbody>\n</table>\n</div>\n</details>\n'
    html += '</div>\n'
    html += f'<div class="footer">禅道项目管理系统 . 自动生成于 {TODAY}</div>\n'
    chart_labels = json.dumps(person_names[:top_n])
    chart_data_js = json.dumps(person_counts[:top_n])
    chart_colors = json.dumps(person_colors[:top_n])
    pri_keys = sorted(pri_map.keys())
    pri_labels = json.dumps([PRI_NAMES.get(k,str(k)) for k in pri_keys])
    pri_chart_data = json.dumps([pri_map[k] for k in pri_keys])
    pri_chart_colors = json.dumps([PRI_COLORS.get(k,"#4facfe") for k in pri_keys])
    html += '<script>\n'
    html += f"new Chart(document.getElementById('barChart'),{{type:'bar',data:{{labels:{chart_labels},datasets:[{{label:'任务数',data:{chart_data_js},backgroundColor:{chart_colors},borderRadius:6}}]}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{display:false}}}},scales:{{y:{{beginAtZero:true,ticks:{{stepSize:1}}}}}}}}}});\n"
    html += f"new Chart(document.getElementById('statusPie'),{{type:'pie',data:{{labels:{json.dumps(['待处理','进行中'])},datasets:[{{data:{json.dumps([wait_cnt,doing_cnt])},backgroundColor:{json.dumps(['#f5576c','#43e97b'])}}}]}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{position:'bottom'}}}}}}}});\n"
    html += f"new Chart(document.getElementById('priPie'),{{type:'pie',data:{{labels:{pri_labels},datasets:[{{data:{pri_chart_data},backgroundColor:{pri_chart_colors}}}]}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{position:'bottom'}}}}}}}});\n"
    html += '</script>\n</body>\n</html>'
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
    return html

def generate_overdue_html(overdue_tasks, output_path):
    total = len(overdue_tasks)
    if total == 0:
        html = f'<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>延期任务</title></head><body style="font-family:sans-serif;text-align:center;padding-top:60px"><h1>无延期任务</h1><p>{TODAY}</p></body></html>'
        with open(output_path, "w", encoding="utf-8") as f: f.write(html)
        return
    by_assignee = defaultdict(list)
    for t in overdue_tasks: by_assignee[t["_assignee_name"]].append(t)
    wait_c = sum(1 for t in overdue_tasks if t.get("status")=="wait")
    doing_c = sum(1 for t in overdue_tasks if t.get("status")=="doing")
    num_people = len(by_assignee)
    pri_counter = defaultdict(int)
    for t in overdue_tasks: pri_counter[t.get("pri",3)] += 1
    platform_stats = defaultdict(int)
    for t in overdue_tasks: platform_stats[t.get("_platform","未知")] += 1
    assignees = sorted(by_assignee.keys(), key=lambda a: -len(by_assignee[a]))
    html = '<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n<meta charset="UTF-8">\n'
    html += '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
    html += f'<title>延期任务统计报告 - {TODAY}</title>\n'
    html += '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>\n'
    html += _CSS_528 + '\n</head>\n<body>\n'
    html += '<div class="back-link"><a href="../index.html">← 返回报告中心</a></div>\n'
    html += f'<div class="header"><h1>延期任务统计报告</h1>\n'
    platform_desc = " . ".join(f"{p}:{c}" for p,c in sorted(platform_stats.items()))
    html += f'<p>{TODAY} | 共 {total} 个延期任务 | {platform_desc}</p></div>\n'
    html += '<div class="cards">\n'
    html += f'<div class="card card-total"><div class="num">{total}</div><div class="label">延期总数</div></div>\n'
    html += f'<div class="card card-wait"><div class="num">{wait_c}</div><div class="label">待处理</div></div>\n'
    html += f'<div class="card card-doing"><div class="num">{doing_c}</div><div class="label">进行中</div></div>\n'
    html += f'<div class="card card-people"><div class="num">{num_people}</div><div class="label">涉及人员</div></div>\n'
    html += '</div>\n'
    person_labels = json.dumps(assignees)
    person_values = json.dumps([len(by_assignee[a]) for a in assignees])
    person_colors_chart = json.dumps([f"#{PERSON_COLORS[i%len(PERSON_COLORS)]}80" for i in range(len(assignees))])
    pri_keys = sorted(pri_counter.keys())
    pri_labels = json.dumps([PRI_NAMES.get(k,str(k)) for k in pri_keys])
    pri_values = json.dumps([pri_counter[k] for k in pri_keys])
    html += '<div class="charts">\n'
    html += f'<div class="chart-box"><h3>延期任务按人员分布</h3><div class="chart-container"><canvas id="barChart"></canvas></div></div>\n'
    html += f'<div class="chart-box"><h3>优先级分布</h3><div class="chart-container"><canvas id="priPie"></canvas></div></div>\n'
    html += '</div>\n'
    html += '<div class="details">\n<h3 style="margin-bottom:10px;">按负责人明细</h3>\n'
    for i, a in enumerate(assignees):
        info = by_assignee[a]
        color = PERSON_COLORS[i%len(PERSON_COLORS)]
        doing_c_a = sum(1 for t in info if t.get("status")=="doing")
        wait_c_a = sum(1 for t in info if t.get("status")=="wait")
        max_days = max(t.get("_days_overdue",0) for t in info)
        open_attr = ' open' if i==0 else ''
        html += f'    <details{open_attr}>\n'
        html += f'        <summary style="background:#{color}15; border-left:4px solid #{color};">\n'
        html += f'            <span class="assignee-name">{a}</span>\n'
        html += f'            <span class="assignee-stats">\n'
        html += f'                <span class="stat-badge">共{len(info)}个</span>\n'
        html += f'                <span class="stat-badge stat-wait">待处理{wait_c_a}</span>\n'
        html += f'                <span class="stat-badge stat-doing">进行中{doing_c_a}</span>\n'
        html += f'                <span class="stat-badge stat-overdue">最长{max_days}天</span>\n'
        html += f'            </span>\n'
        html += f'        </summary>\n<div class="table-wrapper">\n<table>\n<thead>\n<tr>\n'
        html += f'<th>ID</th><th>任务名称</th><th>状态</th><th>优先级</th><th>类型</th><th>所属迭代</th><th>截止日期</th><th>超期天数</th></tr>\n</thead>\n<tbody>\n'
        for t in sorted(info, key=lambda x: x.get("_days_overdue",0), reverse=True):
            status_cn = STATUS_NAMES.get(t.get("status",""),t.get("status",""))
            pri_name = PRI_NAMES.get(t.get("pri",3),"3-中")
            html += f'<tr class="row-overdue"><td>{t.get("id","-")}</td><td title="{_esc(t.get("name","-"))}">{t.get("name","-")}</td><td><span class="badge-wait">{status_cn}</span></td><td>{pri_name}</td><td>{t.get("type","-")}</td><td>{t.get("_exec_name","-")}</td><td>{t.get("deadline","-")}</td><td style="color:#ef4444;font-weight:700;">{t.get("_days_overdue",0)}天</td></tr>\n'
        html += '</tbody>\n</table>\n</div>\n</details>\n'
    html += '</div>\n'
    html += '<script>\n'
    html += f"new Chart(document.getElementById('barChart'),{{type:'bar',data:{{labels:{person_labels},datasets:[{{label:'延期任务数',data:{person_values},backgroundColor:{person_colors_chart},borderRadius:6}}]}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{display:false}}}},scales:{{y:{{beginAtZero:true,ticks:{{stepSize:1}}}}}}}}}});\n"
    html += f"new Chart(document.getElementById('priPie'),{{type:'pie',data:{{labels:{pri_labels},datasets:[{{data:{pri_values},backgroundColor:{json.dumps(['#ef4444','#f5576c','#ffa726','#666'][:len(pri_keys)])}}}]}},options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{position:'bottom'}}}}}}}});\n"
    html += '</script>\n</body>\n</html>'
    with open(output_path, "w", encoding="utf-8") as f: f.write(html)


# ════════════════════════════════════════════════════
# Part 4: Generate Root Overview (index.html)
# ════════════════════════════════════════════════════

def json_name_for(cat_key):
    return {"product":"未完成ab类型任务_统计.json",
            "backend":"未完成后端开发任务_统计.json",
            "frontend":"未完成前端开发任务_统计.json",
            "mobile":"未完成移动端开发任务_统计.json",
            "test":"未完成测试任务_统计.json"}.get(cat_key, "")

def generate_overview_html(cats_data, overdue_count, overdue_people_count, history_dates, iteration_summaries):
    pc, bc, fc, mc, tc = [len(cats_data.get(k,[])) for k in ["product","backend","frontend","mobile","test"]]
    def cs(tasks): return (sum(1 for t in tasks if t.get("status")=="wait"),
                           sum(1 for t in tasks if t.get("status")=="doing"))
    def cp(tasks): return len(set(t.get("_assignee_name","") for t in tasks))
    p_w, p_d = cs(cats_data.get("product",[]))
    b_w, b_d = cs(cats_data.get("backend",[]))
    f_w, f_d = cs(cats_data.get("frontend",[]))
    m_w, m_d = cs(cats_data.get("mobile",[]))
    t_w, t_d = cs(cats_data.get("test",[]))
    p_n, b_n, f_n, m_n, t_n = [cp(cats_data.get(k,[])) for k in ["product","backend","frontend","mobile","test"]]
    now_display = f"{TODAY} {datetime.now().strftime('%H:%M')} 更新"

    # Trend rows
    trend_rows = ""
    for d in history_dates[-14:]:
        date_dir = WORKSPACE / d
        if not date_dir.exists(): continue
        day_data = {"product":0,"backend":0,"frontend":0,"mobile":0}
        jmap = [("product","未完成ab类型任务_统计.json"),("backend","未完成后端开发任务_统计.json"),
                ("frontend","未完成前端开发任务_统计.json"),("mobile","未完成移动端开发任务_统计.json")]
        for ck, jn in jmap:
            jf = date_dir / jn
            if jf.exists():
                try: day_data[ck] = json.loads(jf.read_text(encoding="utf-8")).get("total_incomplete",0)
                except: pass
        total = sum(day_data.values())
        is_today = d == TODAY
        tr_cls = ' class="today"' if is_today else ""
        trend_rows += f'<tr{tr_cls}><td>{d}{" ←" if is_today else ""}</td>'
        for ck, css_cls in [("product","trend-c-p"),("backend","trend-c-b"),("frontend","trend-c-f"),("mobile","trend-c-m")]:
            v = day_data[ck]
            prev_v = 0
            if is_today and history_dates.index(d) > 0:
                prev_d = history_dates[history_dates.index(d)-1]
                pjf = WORKSPACE / prev_d / json_name_for(ck)
                if pjf.exists():
                    try: prev_v = json.loads(pjf.read_text(encoding="utf-8")).get("total_incomplete",0)
                    except: pass
            delta = v - prev_v
            dh = ""
            if is_today and delta != 0:
                dh = f' <span class="trend-delta trend-up">+{delta}</span>' if delta > 0 else f' <span class="trend-delta trend-down">{delta}</span>'
            trend_rows += f'<td class="{css_cls}">{v}{dh}</td>'
        trend_rows += f'<td>{total}</td></tr>\n'

    # Iteration rows
    iter_rows = ""
    for it in iteration_summaries:
        progress = it.get("progress",0)
        color = "#43e97b" if progress >= 100 else ("#ffa726" if progress >= 80 else ("#f5576c" if progress < 50 else "#4facfe"))
        pt = it.get('platform','').replace('网批2.0','wp').replace('集采平台','jc').replace('分销平台','fx')
        iter_rows += f'<tr><td><a href="{TODAY}/迭代_{it["name"]}_执行进展报告.html" target="_blank">{it["name"]}</a></td><td><span class="tag tag-{pt}">{it.get("platform","")}</span></td><td>{it.get("begin","")} ~ {it.get("end","")}</td><td><div class="progress-bar"><div class="progress-fill" style="width:{progress}%;background:{color};"></div></div> {progress}%</td><td class="stat-num tasks">{it.get("task_total",0)}</td><td class="stat-num stories">{it.get("story_count",0)}</td><td class="stat-num bugs">{it.get("active_bugs",0)}</td><td>{it.get("doing",0)}/{it.get("wait",0)}</td></tr>\n'

    history_links = "".join(f'<a href="{d}/">{d}</a>' for d in history_dates[-7:])

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>禅道任务报告 · 导航</title>
<link rel="stylesheet" href="data:text/css;base64, placeholder"/>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,"Microsoft YaHei","PingFang SC",sans-serif;background:linear-gradient(135deg,#0f0c29 0%,#302b63 50%,#24243e 100%);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:40px 20px}}
.container{{width:100%;max-width:900px}}
.header{{text-align:center;margin-bottom:12px}}
.header .logo{{font-size:36px;margin-bottom:8px;display:block;animation:float 3s ease-in-out infinite}}
@keyframes float{{0%,100%{{transform:translateY(0)}}50%{{transform:translateY(-6px)}}}}
.header h1{{font-size:28px;font-weight:700;background:linear-gradient(120deg,#667eea,#f093fb,#4facfe);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;margin-bottom:4px}}
.header .subtitle{{color:#8892b0;font-size:14px;letter-spacing:1px}}
.date-tag{{display:block;text-align:center;margin-bottom:8px;font-size:13px;color:#a5b4fc}}
.date-tag span{{display:inline-block;padding:4px 14px;border-radius:20px;background:rgba(102,126,234,0.12);border:1px solid rgba(102,126,234,0.25)}}
.refresh-btn{{display:inline-flex;align-items:center;gap:6px;margin:0 auto 16px;padding:8px 18px;border:none;border-radius:20px;background:rgba(102,126,234,0.15);border:1px solid rgba(102,126,234,0.3);color:#a5b4fc;font-size:13px;font-weight:500;cursor:pointer;font-family:inherit;transition:all .3s}}
.refresh-btn:hover{{background:rgba(102,126,234,0.25);transform:scale(1.03)}}
.refresh-btn.loading{{opacity:0.6;pointer-events:none}}
.refresh-spin{{display:inline-block;transition:transform 0.6s}}
.refresh-btn.loading .refresh-spin{{animation:spin 0.8s linear infinite}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
.refresh-toast{{position:fixed;top:20px;left:50%;transform:translateX(-50%);z-index:9999;padding:10px 24px;border-radius:10px;font-size:13px;font-weight:500;opacity:0;transition:opacity 0.4s;pointer-events:none}}
.refresh-toast.show{{opacity:1}}
.refresh-toast.ok{{background:#10b981;color:#fff}}
.refresh-toast.err{{background:#ef4444;color:#fff}}
.refresh-toast.info{{background:#4facfe;color:#fff}}
.summary-bar{{display:flex;flex-wrap:nowrap;gap:8px;justify-content:center;margin-bottom:24px;overflow-x:auto}}
.summary-item{{background:rgba(255,255,255,0.04);border-radius:10px;padding:10px 14px;border:1px solid rgba(255,255,255,0.06);text-align:center;min-width:80px;flex-shrink:0}}
.summary-item .num{{font-size:20px;font-weight:700}}
.summary-item .label{{font-size:11px;color:#666;margin-top:4px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:20px}}
.card{{position:relative;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:36px 24px 30px;border-radius:16px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);text-decoration:none;cursor:pointer;transition:all 0.3s cubic-bezier(0.4,0,0.2,1);overflow:hidden;backdrop-filter:blur(10px)}}
.card::before{{content:'';position:absolute;inset:0;border-radius:16px;opacity:0;transition:opacity 0.3s;z-index:0}}
.card:nth-child(1)::before{{background:linear-gradient(135deg,rgba(102,126,234,0.25),rgba(240,147,251,0.15))}}
.card:nth-child(2)::before{{background:linear-gradient(135deg,rgba(67,233,123,0.20),rgba(102,126,234,0.15))}}
.card:nth-child(3)::before{{background:linear-gradient(135deg,rgba(240,147,251,0.25),rgba(79,172,254,0.15))}}
.card:nth-child(4)::before{{background:linear-gradient(135deg,rgba(255,167,38,0.20),rgba(239,83,80,0.12))}}
.card:nth-child(5)::before{{background:linear-gradient(135deg,rgba(38,198,218,0.20),rgba(79,172,254,0.12))}}
.card:nth-child(6)::before{{background:linear-gradient(135deg,rgba(79,172,254,0.25),rgba(102,126,234,0.15))}}
.card:nth-child(7)::before{{background:linear-gradient(135deg,rgba(239,83,80,0.22),rgba(255,167,38,0.12))}}
.card:nth-child(8)::before{{background:linear-gradient(135deg,rgba(251,191,36,0.22),rgba(245,158,11,0.12))}}
.card:hover::before{{opacity:1}}
.card:hover{{transform:translateY(-6px);border-color:rgba(255,255,255,0.18);box-shadow:0 20px 48px rgba(0,0,0,0.35)}}
.card:active{{transform:translateY(-2px)}}
.card .icon{{font-size:42px;margin-bottom:16px;position:relative;z-index:1;filter:drop-shadow(0 4px 12px rgba(0,0,0,0.3))}}
.card .name{{font-size:17px;font-weight:600;color:#e2e8f0;margin-bottom:6px;position:relative;z-index:1}}
.card .desc{{font-size:13px;color:#8892b0;position:relative;z-index:1;text-align:center;line-height:1.5}}
.card.product .name{{color:#a5b4fc}}
.card.backend .name{{color:#66eea6}}
.card.frontend .name{{color:#f093fb}}
.card.mobile .name{{color:#ffa726}}
.card.test .name{{color:#26c6da}}
.trend-section{{margin-top:40px;background:rgba(255,255,255,0.04);border-radius:16px;border:1px solid rgba(255,255,255,0.08);overflow:hidden}}
.trend-title{{padding:20px 24px 0;font-size:16px;font-weight:600;color:#e2e8f0;display:flex;align-items:center;gap:8px}}
.trend-wrap{{overflow-x:auto;padding:16px 24px 24px}}
.trend-table{{width:100%;border-collapse:collapse;font-size:13px;min-width:600px}}
.trend-table th{{background:rgba(0,0,0,0.25);padding:10px 14px;text-align:center;font-weight:600;color:#aaa;border-bottom:2px solid rgba(255,255,255,0.08);white-space:nowrap}}
.trend-table th:first-child{{text-align:left;border-radius:8px 0 0 0}}
.trend-table th:last-child{{border-radius:0 8px 0 0}}
.trend-table td{{padding:10px 14px;text-align:center;border-bottom:1px solid rgba(255,255,255,0.04);color:#ccc}}
.trend-table td:first-child{{text-align:left;color:#8892b0;font-weight:500}}
.trend-table tr:last-child td{{border-bottom:none}}
.trend-table tr:hover td{{background:rgba(255,255,255,0.03)}}
.trend-table .today td{{background:rgba(102,126,234,0.08)}}
.trend-table .today td:first-child{{color:#a5b4fc;font-weight:700}}
.trend-delta{{font-size:11px;margin-left:4px}}
.trend-up{{color:#ef5350}}
.trend-down{{color:#43e97b}}
.trend-flat{{color:#78909c}}
.trend-c-p{{color:#a5b4fc}}
.trend-c-b{{color:#66eea6}}
.trend-c-f{{color:#f093fb}}
.trend-c-m{{color:#ffa726}}
.footer{{text-align:center;margin-top:40px;color:#4a5568;font-size:12px;letter-spacing:0.5px}}
.footer a{{color:#667eea;text-decoration:none}}
.footer a:hover{{text-decoration:underline}}
.history-nav{{margin-bottom:16px;color:#667eea;font-size:14px;font-weight:600}}
.history-links{{display:flex;gap:10px;justify-content:center;flex-wrap:wrap;margin-bottom:20px}}
.history-links a{{padding:6px 14px;border-radius:20px;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.08);font-size:13px;text-decoration:none;color:#8892b0;transition:all 0.2s}}
.history-links a:first-child{{color:#4facfe;border-color:rgba(79,172,254,0.25);background:rgba(79,172,254,0.12)}}
.history-links a:hover{{border-color:#667eea;color:#667eea}}
.iter-section{{margin-top:30px;background:rgba(255,255,255,0.04);border-radius:16px;border:1px solid rgba(255,255,255,0.08);overflow:hidden}}
.iter-title{{padding:20px 24px 0;font-size:16px;font-weight:600;color:#e2e8f0;display:flex;align-items:center;gap:8px}}
.iter-wrap{{overflow-x:auto;padding:16px 24px 24px}}
.iter-table{{width:100%;border-collapse:collapse;font-size:13px;min-width:700px}}
.iter-table th{{background:rgba(0,0,0,0.25);padding:10px 14px;text-align:left;font-weight:600;color:#aaa;border-bottom:2px solid rgba(255,255,255,0.08);white-space:nowrap}}
.iter-table td{{padding:10px 14px;border-bottom:1px solid rgba(255,255,255,0.04);color:#ccc}}
.iter-table tr:hover td{{background:rgba(255,255,255,0.03)}}
.progress-bar{{width:100px;height:6px;background:rgba(255,255,255,0.1);border-radius:3px;overflow:hidden;display:inline-block;vertical-align:middle;margin-right:6px}}
.progress-fill{{height:100%;border-radius:3px;transition:width 0.3s}}
.tag{{display:inline-block;padding:2px 8px;border-radius:8px;font-size:11px;margin-right:4px}}
.tag-wp{{background:rgba(102,126,234,0.2);color:#a5b4fc}}
.tag-jc{{background:rgba(67,233,123,0.2);color:#66eea6}}
.tag-fx{{background:rgba(255,167,38,0.2);color:#ffa726}}
.stat-num{{font-weight:700;font-size:13px}}
.stat-num.tasks{{color:#667eea}}
.stat-num.stories{{color:#16a34a}}
.stat-num.bugs{{color:#ef4444}}
a{{color:#4facfe;text-decoration:none;font-weight:600}}
a:hover{{text-decoration:underline}}
@media(max-width:500px){{.header h1{{font-size:22px}}.header .logo{{font-size:32px}}.card{{padding:28px 16px 22px}}.card .icon{{font-size:34px}}}}
</style>
</head>
<body>
<div class="container">
<div class="header">
<span class="logo">📊</span>
<h1>禅道任务报告中心</h1>
<div style="text-align:center;margin-top:8px">
<button class="refresh-btn" onclick="triggerGithubRefresh()" id="refreshBtn">
<span class="refresh-spin">🔄</span> 实时刷新禅道数据</button></div>
<p class="subtitle">Zentao Task Dashboard</p></div>
<div class="date-tag"><span>{now_display}</span></div>
<div class="summary-bar">
<div class="summary-item"><div class="num" style="color:#a5b4fc;">{pc}</div><div class="label">📋 产品 (待{p_w}/做{p_d})</div></div>
<div class="summary-item"><div class="num" style="color:#66eea6;">{bc}</div><div class="label">⚙️ 后端 (待{b_w}/做{b_d})</div></div>
<div class="summary-item"><div class="num" style="color:#f093fb;">{fc}</div><div class="label">🎨 前端 (待{f_w}/做{f_d})</div></div>
<div class="summary-item"><div class="num" style="color:#ffa726;">{mc}</div><div class="label">📱 移动端 (待{m_w}/做{m_d})</div></div>
<div class="summary-item"><div class="num" style="color:#26c6da;">{tc}</div><div class="label">🧪 测试 (待{t_w}/做{t_d})</div></div>
<div class="summary-item"><div class="num" style="color:#ef5350;">{overdue_count}</div><div class="label">🚨 延期任务 ({overdue_people_count}人)</div></div>
</div>
<div class="grid">
<a href="{TODAY}/未完成ab类型任务_详细任务.html" class="card product" target="_blank"><span class="icon">📋</span><span class="name">产品任务</span><span class="desc">需求 / AB 类型<br>{pc}个未完成 · {p_n}人</span></a>
<a href="{TODAY}/未完成后端开发任务_详细任务.html" class="card backend" target="_blank"><span class="icon">⚙️</span><span class="name">后端开发</span><span class="desc">后端开发任务<br>{bc}个未完成 · {b_n}人</span></a>
<a href="{TODAY}/未完成前端开发任务_详细任务.html" class="card frontend" target="_blank"><span class="icon">🎨</span><span class="name">前端开发</span><span class="desc">前端开发任务<br>{fc}个未完成 · {f_n}人</span></a>
<a href="{TODAY}/未完成移动端开发任务_详细任务.html" class="card mobile" target="_blank"><span class="icon">📱</span><span class="name">移动端开发</span><span class="desc">移动端开发任务<br>{mc}个未完成 · {m_n}人</span></a>
<a href="{TODAY}/未完成测试任务_详细任务.html" class="card test" target="_blank"><span class="icon">🧪</span><span class="name">测试任务</span><span class="desc">测试执行 + 测试设计<br>{tc}个未完成 · {t_n}人</span></a>
<a href="{TODAY}/" class="card" target="_blank" style="border-color:rgba(79,172,254,0.3)"><span class="icon">📊</span><span class="name" style="color:#4facfe;">迭代执行进展</span><span class="desc">{len(iteration_summaries)} 个进行中迭代<br>报告总览 →</span></a>
<a href="{TODAY}/延期任务统计报告.html" class="card" target="_blank" style="border-color:rgba(239,83,80,0.3)"><span class="icon">🚨</span><span class="name" style="color:#ef5350;">延期任务</span><span class="desc">{overdue_count}个延期 / {overdue_people_count}人<br>全平台超期追踪</span></a>
<a href="{TODAY}/团队产出效率分析_202606.html" class="card" target="_blank" style="border-color:rgba(251,191,36,0.3)"><span class="icon">💪</span><span class="name" style="color:#fbbf24;">员工负载</span><span class="desc">按角色分组工时分析<br>完成/进行中负载对比</span></a>
</div>
<div class="iter-section">
<div class="iter-title"><span>📊</span> 迭代进度总览</div>
<div class="iter-wrap"><table class="iter-table"><thead><tr><th>迭代名称</th><th>平台</th><th>周期</th><th>进度</th><th>任务</th><th>需求</th><th>活跃Bug</th><th>进行中/待处理</th></tr></thead><tbody>{iter_rows}</tbody></table></div>
</div>
<div class="trend-section">
<div class="trend-title"><span class="icon">📈</span> 任务数量趋势</div>
<div class="trend-wrap"><table class="trend-table"><thead><tr><th>日期</th><th>📋 产品</th><th>⚙️ 后端</th><th>🎨 前端</th><th>📱 移动端</th><th>📊 合计</th></tr></thead><tbody>{trend_rows}</tbody></table></div>
</div>
<div class="footer">
<div class="history-nav">📅 历史报告</div>
<div class="history-links">{history_links}</div>
数据来源：禅道管理系统 &nbsp;|&nbsp;
<a href="https://github.com/Yang-chad/tasks" target="_blank">GitHub Tasks</a>
&nbsp;|&nbsp; <span style="font-size:11px;color:#555">⚡ GitHub Actions 自动刷新</span>
</div>
</div>
<div id="rtoast" class="refresh-toast"></div>
<script>
var REFRESH_TOKEN='GITHUB_PAT_PLACEHOLDER';
function toast(msg,type){{var t=document.getElementById('rtoast');t.textContent=msg;t.className='refresh-toast show '+(type||'ok');setTimeout(function(){{t.className='refresh-toast'}},5000)}}
function triggerGithubRefresh(){{var btn=document.getElementById('refreshBtn');if(!btn)return;if(REFRESH_TOKEN==='GITHUB_PAT_PLACEHOLDER'){{toast('请先配置 GitHub Personal Access Token','err');return}}btn.classList.add('loading');toast('触发云端刷新...','info');var API='https://api.github.com/repos/Yang-chad/tasks';var H={{'Authorization':'token '+REFRESH_TOKEN,'Accept':'application/vnd.github.v3+json'}};fetch(API+'/commits/main?per_page=1',{{headers:H}}).then(function(r){{return r.json()}}).then(function(d){{var oldSha=d.sha;return fetch(API+'/dispatches',{{method:'POST',headers:H,body:JSON.stringify({{event_type:'refresh-data'}})}}).then(function(r){{if(r.status!==204)throw new Error('HTTP '+r.status);var s=0,poll=setInterval(function(){{s+=3;fetch(API+'/commits/main?per_page=1',{{headers:H}}).then(function(rr){{return rr.json()}}).then(function(dd){{if(dd.sha!==oldSha){{clearInterval(poll);btn.classList.remove('loading');toast('数据已刷新，页面更新中...','ok');setTimeout(function(){{location.reload()}},800)}}else if(s>=120){{clearInterval(poll);btn.classList.remove('loading');location.reload()}}else{{var remain=Math.max(0,120-s);toast('生成中... 预计'+remain+'秒','info')}}}}).catch(function(){{if(s>=120){{clearInterval(poll);btn.classList.remove('loading');location.reload()}}}})}},3000)}})}}).catch(function(e){{btn.classList.remove('loading');toast('失败: '+e.message,'err')}})}}
</script>
</body></html>'''


# ════════════════════════════════════════════════════
# Part 5: Iteration Data Collection
# ════════════════════════════════════════════════════

def fetch_iterations_and_generate_reports():
    """拉取活跃迭代摘要数据"""
    print("\n[Iterations] Fetching active iteration data...")
    PROJECTS = [(902,'网批2.0'),(1244,'集采平台'),(1245,'分销平台')]
    SKIP_IDS = {1132,1690,1691,3394,3405,3404}
    summaries = []
    token = TOKEN
    for pid, pname in PROJECTS:
        execs = get_execs_cached(pid)
        for ex in execs:
            eid = ex.get('id')
            if eid in SKIP_IDS: continue
            if ex.get('status') == 'closed': continue
            name = ex.get('name','')
            if any(kw in name for kw in ['系统安全','需求池','专项分析','长期跟踪']): continue
            try:
                resp = requests.get(f"{ZENTAO_BASE}/api.php/v1/executions/{eid}",
                    headers={"Token":token}, verify=False, timeout=15).json()
                tasks = get_all_pages(f"/api.php/v1/executions/{eid}/tasks","tasks")
                stories = get_all_pages(f"/api.php/v1/executions/{eid}/stories","stories")
                bugs = get_all_pages(f"/api.php/v1/executions/{eid}/bugs","bugs")
                progress = float(resp.get("progress",0) or 0)
                ts = defaultdict(int)
                for t in tasks: ts[t.get("status","?")] += 1
                active_bugs = [b for b in bugs if b.get("status") not in ("closed","resolved","postponed","delay")]
                summaries.append({
                    "name": resp.get("name",""), "platform": pname,
                    "begin": resp.get("begin",""), "end": resp.get("end",""),
                    "progress": progress, "task_total": len(tasks),
                    "story_count": len(stories), "active_bugs": len(active_bugs),
                    "doing": ts.get("doing",0), "wait": ts.get("wait",0),
                    "status": resp.get("status",""),
                })
            except Exception as e:
                print(f"  [Skip] {name}: {e}")
    print(f"  Found {len(summaries)} active iterations")
    return summaries


# ════════════════════════════════════════════════════
# Part 6: Main Pipeline & Git
# ════════════════════════════════════════════════════

def git_commit_and_push():
    import subprocess
    print("\n[Git] Committing and pushing...")
    os.chdir(str(WORKSPACE))

    # 用 GITHUB_PAT 设置 HTTPS 远程地址，确保有写入权限
    if GITHUB_PAT:
        remote_url = f"https://x-access-token:{GITHUB_PAT}@github.com/Yang-chad/tasks.git"
        subprocess.run(["git", "remote", "set-url", "origin", remote_url], capture_output=True)
        print("  Remote set to HTTPS (GITHUB_PAT)")

    subprocess.run(["git", "config", "user.name", "GitHub Actions"], capture_output=True)
    subprocess.run(["git", "config", "user.email", "actions@github.com"], capture_output=True)
    subprocess.run(["git", "add", "."], capture_output=True)

    r = subprocess.run(["git", "commit", "-m", f"auto: {TODAY} 禅道数据刷新 (GitHub Actions)"],
                       capture_output=True, text=True)
    if r.returncode == 0:
        print(f"  Commit OK: {r.stdout.strip()[:150]}")
    elif "nothing to commit" in (r.stdout + r.stderr):
        print("  Commit: nothing to commit (no changes)")
        return
    else:
        print(f"  Commit FAILED: {r.stdout} {r.stderr}")

    r = subprocess.run(["git", "push", "origin", "main"], capture_output=True, text=True)
    if r.returncode == 0:
        print(f"  Push OK")
    else:
        print(f"  Push FAILED:\n  STDOUT: {r.stdout.strip()[:300]}\n  STDERR: {r.stderr.strip()[:300]}")
        # Fallback: try with force
        r2 = subprocess.run(["git", "push", "origin", "main", "--force"], capture_output=True, text=True)
        print(f"  Force Push: {'OK' if r2.returncode == 0 else r2.stderr.strip()[:200]}")

def main():
    dry_run = "--dry-run" in sys.argv
    skip_push = "--skip-push" in sys.argv
    t_total = time.time()

    print("="*60)
    print("  GitHub Actions 禅道数据采集 Pipeline")
    print(f"  Date: {TODAY} | Workspace: {WORKSPACE}")
    print("="*60)
    if dry_run: print("  DRY RUN - will skip git push")

    # Step 1: Auth
    refresh_token()

    # Step 2: Fetch all data
    cats, overdue_tasks = fetch_all_platforms()

    # Step 3: Generate task reports (parallel) + Step 4: Overdue + Step 5: Iterations
    # ── 并行：报告生成 || 迭代数据 ──
    print("\n[Generate] Task reports & iteration data (parallel)...")
    by_a = defaultdict(list)
    for t in overdue_tasks: by_a[t["_assignee_name"]].append(t)
    iteration_summaries_ref = [None]

    def gen_all_reports():
        """生成所有任务报告 + 延期报告"""
        def gen_cat_html(cat_key):
            tasks = cats.get(cat_key, [])
            cfg = CAT_CONFIG[cat_key]
            output = build_output(cat_key, tasks)
            json_root = WORKSPACE / f"未完成{cfg['label']}_统计.json"
            json_today = OUTPUT_DIR / f"未完成{cfg['label']}_统计.json"
            for p in [json_root, json_today]:
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(output, f, ensure_ascii=False, indent=2)
            html_path = OUTPUT_DIR / cfg["html_name"]
            generate_528_html(cfg["label"], len(tasks), output["summary"],
                output["by_assignee"], output.get("type_breakdown"), str(html_path))
            s = output["summary"]
            print(f"  {cfg['label']}: {len(tasks)} (wait:{s['wait']}/doing:{s['doing']}/overdue:{s['overdue']})")

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = {pool.submit(gen_cat_html, ck): ck for ck in CAT_CONFIG}
            for f in as_completed(futures):
                try: f.result()
                except Exception as e: print(f"  [Error] {futures[f]}: {e}")

        # Overdue report
        print(f"\n[Overdue] {len(overdue_tasks)} tasks")
        od_json = {"check_date": TODAY, "total_overdue": len(overdue_tasks), "tasks_by_assignee": {}}
        for a, tl in sorted(by_a.items(), key=lambda x: -len(x[1])):
            od_json["tasks_by_assignee"][a] = {
                "count": len(tl), "max_overdue_days": max(t.get("_days_overdue",0) for t in tl),
                "tasks": [_task_to_dict(t) for t in tl]}
        for p in [WORKSPACE / "延期任务统计.json", OUTPUT_DIR / "延期任务统计.json"]:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(od_json, f, ensure_ascii=False, indent=2)
        generate_overdue_html(overdue_tasks, str(OUTPUT_DIR / "延期任务统计报告.html"))

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_reports = pool.submit(gen_all_reports)
        f_iter = pool.submit(lambda: iteration_summaries_ref.__setitem__(0, fetch_iterations_and_generate_reports()))
        f_reports.result()
        f_iter.result()

    iteration_summaries = iteration_summaries_ref[0]
    overdue_people_count = len(by_a)

    # Step 6: Update root index.html using compute_trend.py (保持本地格式)
    print("\n[Overview] Updating root index.html with compute_trend.py...")
    import subprocess as sp
    r = sp.run([sys.executable, str(WORKSPACE / "scripts" / "compute_trend.py"), "--update-index"],
               capture_output=True, text=True, cwd=str(WORKSPACE))
    print(f"  compute_trend: {r.stdout.strip()[:300]}")
    if r.returncode != 0:
        print(f"  compute_trend ERROR: {r.stderr.strip()[:300]}")

    # Step 6b: Restore original liveRefreshRoot() script (no token, calls local server)
    index_path = WORKSPACE / "index.html"
    if index_path.exists():
        content = index_path.read_text(encoding="utf-8")
        # Ensure onclick is liveRefreshRoot
        content = content.replace('onclick="triggerGithubRefresh()"', 'onclick="liveRefreshRoot()"')
        content = content.replace('onclick="location.reload()"', 'onclick="liveRefreshRoot()"')
        # Replace the entire script block with original local-server version (no token)
        orig_script = '''<script>
function rtoast(msg,type){
  var t=document.getElementById('rtoast');
  if(!t){t=document.createElement('div');t.id='rtoast';t.className='refresh-toast';document.body.appendChild(t);}
  t.textContent=msg; t.className='refresh-toast show '+(type||'ok');
  setTimeout(function(){t.className='refresh-toast';},4000);
}
function liveRefreshRoot(){
  var btn=document.getElementById('refreshBtn'); if(!btn) return;
  var isGH=window.location.origin.indexOf('github.io')>=0;
  if(isGH || window.location.protocol==='file:'){
    btn.classList.add('loading');
    var SVR='http://172.28.52.91:8900';
    fetch(SVR+'/trigger-pipeline',{mode:'no-cors'})
    .then(function(){ rtoast('已触发后台刷新，约40秒后自动刷新','ok'); })
    .catch(function(){ btn.classList.remove('loading'); rtoast('自动刷新中(每30分钟)，或在本机运行 _live_refresh_server.py','ok'); location.reload(); });
    return;
  }
  btn.classList.add('loading');
  fetch(window.location.origin+'/api/refresh-root')
  .then(function(r){return r.json();}).then(function(d){
    if(d.error) throw new Error(d.error);
    var sumItems=document.querySelectorAll('.summary-item .num');
    if(sumItems[0]) sumItems[0].textContent=d.product_count||0;
    if(sumItems[1]) sumItems[1].textContent=d.backend_count||0;
    if(sumItems[2]) sumItems[2].textContent=d.frontend_count||0;
    if(sumItems[3]) sumItems[3].textContent=d.mobile_count||0;
    if(sumItems[4]) sumItems[4].textContent=d.overdue_count||0;
    var dt=document.querySelector('.date-tag span');
    if(dt){ var now=new Date().toLocaleTimeString('zh-CN',{hour12:false});
      dt.textContent=document.querySelector('.date-tag span').textContent.replace(/\\d+:\\d+/,'')+' '+now+' 更新';}
    btn.classList.remove('loading');
    var now=new Date().toLocaleTimeString('zh-CN',{hour12:false});
    var tsEl=btn.querySelector('.refresh-time'); if(tsEl) tsEl.textContent=now;
    rtoast('实时刷新完成 - '+now,'ok');
  }).catch(function(e){
    btn.classList.remove('loading');
    rtoast('本地刷新服务未启动，请运行: py _live_refresh_server.py 8900','err');
  });
}
</script>'''
        import re
        content = re.sub(r'<script>.*?</script>', orig_script, content, flags=re.DOTALL)
        index_path.write_text(content, encoding="utf-8")
        print("  Script restored to original liveRefreshRoot()")

    # Step 7: Git push
    if not dry_run and not skip_push:
        git_commit_and_push()
    elif dry_run:
        print("\n[Dry Run] Skipping git push")

    total = time.time() - t_total
    total_tasks = sum(len(v) for v in cats.values())
    print(f"\n{'='*60}")
    print(f"  Pipeline complete: {total:.1f}s")
    print(f"  Tasks: {total_tasks} | Overdue: {len(overdue_tasks)} | Iterations: {len(iteration_summaries)}")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
