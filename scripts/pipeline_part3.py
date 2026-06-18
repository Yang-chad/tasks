
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

    # History links
    history_links = "".join(f'<a href="{d}/">{d}</a>' for d in history_dates[-7:])

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>禅道任务报告 · 导航</title>
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
function triggerGithubRefresh(){{var btn=document.getElementById('refreshBtn');if(!btn)return;if(REFRESH_TOKEN==='GITHUB_PAT_PLACEHOLDER'){{toast('请先配置 GitHub Personal Access Token','err');return}}btn.classList.add('loading');toast('已触发云端刷新...','info');fetch('https://api.github.com/repos/Yang-chad/tasks/dispatches',{{method:'POST',headers:{{'Authorization':'token '+REFRESH_TOKEN,'Accept':'application/vnd.github.v3+json'}},body:JSON.stringify({{event_type:'refresh-data'}})}}).then(function(r){{if(r.status===204){{toast('刷新已触发！约90秒后页面自动刷新','ok');var c=90;var iv=setInterval(function(){{c--;if(c<=0){{clearInterval(iv);location.reload()}}else toast('刷新中... '+c+'秒','info')}},1000)}}else{{btn.classList.remove('loading');toast('触发失败: HTTP '+r.status,'err')}}}}).catch(function(e){{btn.classList.remove('loading');toast('网络错误','err')}})}}
</script>
</body></html>'''
