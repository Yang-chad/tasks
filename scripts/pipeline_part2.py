
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
