#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
团队成员每日完成任务流水清单
用法: python _daily_task_log.py [--month YYYY-MM] [--days N]
默认: 本月，最近30天
"""
import json, sys, os, time, argparse
from datetime import datetime, date, timedelta
from calendar import monthrange
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from _api_client import get_client
from _constants import (
    PLATFORMS, categorize_type, safe_float, STATUS_CN, parse_date, BASE_DIR_STR,
    ROLE_ORDER, ROLE_COLORS, ROLE_BG,
)

BASE_DIR = BASE_DIR_STR

# ── 任务类型中文 ──
TYPE_LABEL = {
    "产品": "产品", "后端": "后端", "前端": "前端", "移动端": "移动端",
    "测试": "测试", "UI设计": "UI", "其他": "其他"
}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", default=None, help="目标月份 YYYY-MM，默认本月")
    parser.add_argument("--days", type=int, default=None, help="最近N天，覆盖--month")
    args = parser.parse_args()

    today = date.today()
    if args.month:
        year_num, mon_num = map(int, args.month.split("-"))
    else:
        year_num, mon_num = today.year, today.month

    if args.days:
        # 最近N天模式
        start_date = today - timedelta(days=args.days - 1)
        end_date = today
        month_label_fetch = str(start_date.year)
    else:
        start_date = date(year_num, mon_num, 1)
        _, last_day = monthrange(year_num, mon_num)
        end_date = date(year_num, mon_num, min(last_day, today.day))
        month_label_fetch = str(year_num)

    output_dir = os.path.join(BASE_DIR, today.isoformat())
    os.makedirs(output_dir, exist_ok=True)

    print("=" * 70)
    print(f"  团队成员每日完成任务流水清单")
    print(f"  日期范围: {start_date} ~ {end_date}")
    print("=" * 70)

    # ── 1. 拉取全量任务 ──
    print("\n[1/3] 拉取全量迭代数据...")
    cli = get_client()

    def _fetch_platform(pf, year_str):
        pid = pf["id"]
        execs = cli.get_executions(pid, use_cache=True, status="all")
        target_execs = [e for e in execs if year_str in (e.get("name","") or "")]
        if not target_execs:
            target_execs = execs
        pf_tasks = []
        # 并行拉取任务（跟 workload 一样的模式）
        with ThreadPoolExecutor(max_workers=15) as fetch_pool:
            fetch_futures = {fetch_pool.submit(cli.get_tasks, e["id"], True): e for e in target_execs}
            for ff in as_completed(fetch_futures):
                e = fetch_futures[ff]
                try:
                    tasks = ff.result()
                except:
                    tasks = []
                for t in tasks:
                    t["_platform_name"] = pf["name"]
                    t["_execution_name"] = e.get("name", "")
                pf_tasks.extend(tasks)
        return pf, pf_tasks

    all_tasks = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(_fetch_platform, pf, month_label_fetch): pf for pf in PLATFORMS}
        for f in as_completed(futures):
            pf, pf_tasks = f.result()
            all_tasks.extend(pf_tasks)
            print(f"  {pf['name']}({pf['id']}): {len(pf_tasks)} 个任务")

    # 剔除"总任务"
    real_tasks = [t for t in all_tasks if "总任务" not in (t.get("name","") or "")]
    print(f"  有效任务: {len(real_tasks)}")

    # ── 2. 筛选已完成 + 按日期分组 ──
    print(f"\n[2/3] 筛选 {start_date}~{end_date} 已完成任务...")
    # closed 状态只有 finishedDate 存在时才计为"完成"（排除批量关闭的僵尸任务）
    # 例: status=closed + finishedDate=null → 跳过（今天只是归档，非真正完成工作）
    daily_log = defaultdict(lambda: defaultdict(list))
    for t in real_tasks:
        st = t.get("status", "")
        if st not in ("done", "closed"):
            continue
        fd = parse_date(t.get("finishedDate"))
        if fd is None:
            # closed 无 finishedDate → 非真实完成，跳过
            if st == "closed":
                continue
            # done 状态但无 finishedDate → 回退到 closedDate
            fd = parse_date(t.get("closedDate"))
        if fd is None:
            continue

        if not (start_date <= fd <= end_date):
            continue

        # 完成人
        fb = t.get("finishedBy", {})
        if isinstance(fb, dict) and fb.get("realname"):
            person = fb["realname"]
        else:
            person = "未知"

        cat = categorize_type(t.get("type", ""))
        daily_log[str(fd)][person].append({
            "id": t.get("id"),
            "name": t.get("name",""),
            "type": cat,
            "estimate": safe_float(t.get("estimate",0)),
            "consumed": safe_float(t.get("consumed",0)),
            "platform": t.get("_platform_name",""),
            "execution": t.get("_execution_name",""),
        })

    total_tasks = sum(len(tasks) for day_data in daily_log.values() for tasks in day_data.values())
    total_people = len(set(p for day_data in daily_log.values() for p in day_data))
    print(f"  完成: {total_tasks} 个任务, {total_people} 人, 覆盖 {len(daily_log)} 天")

    # ── 3. 生成 HTML ──
    print(f"\n[3/3] 生成 HTML...")

    sorted_dates = sorted(daily_log.keys(), reverse=True)

    # 收集所有人员及其任务总数 + 角色
    person_totals = defaultdict(lambda: {"count": 0, "hours": 0, "dates": set(), "type_counts": defaultdict(int)})
    for d, people in daily_log.items():
        for person, tasks in people.items():
            person_totals[person]["count"] += len(tasks)
            person_totals[person]["hours"] += sum(t.get("estimate", 0) for t in tasks)
            person_totals[person]["dates"].add(d)
            for t in tasks:
                person_totals[person]["type_counts"][t["type"]] += 1

    # 计算每人主角色
    for person in person_totals:
        tc = person_totals[person]["type_counts"]
        best = max(tc.items(), key=lambda x: x[1]) if tc else ("其他", 0)
        person_totals[person]["role"] = best[0] if best[1] > 0 else "其他"

    # 按角色分组排序
    role_order_map = {r: i for i, r in enumerate(ROLE_ORDER)}
    def sort_key(item):
        person, stats = item
        role_idx = role_order_map.get(stats["role"], 99)
        return (role_idx, -stats["count"])

    sorted_people = sorted(person_totals.items(), key=sort_key)

    # 按角色分组
    role_groups = {}
    for r in ROLE_ORDER:
        role_groups[r] = []
    for person, stats in sorted_people:
        role = stats["role"]
        if role not in role_groups:
            role_groups.setdefault("其他", []).append((person, stats))
        else:
            role_groups[role].append((person, stats))

    # 确保有人员的角色
    active_roles = [r for r in ROLE_ORDER if role_groups.get(r)]
    first_role = active_roles[0] if active_roles else "其他"

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>团队每日完成任务流水清单 — {start_date}~{end_date}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:"Microsoft YaHei","微软雅黑",PingFang SC,sans-serif; background:#f0f2f5; color:#333; font-size:14px; padding:20px; }}
.container {{ max-width:1400px; margin:0 auto; }}

/* 头部 */
.header {{ background:linear-gradient(135deg,#0f0c29,#302b63,#24243e); color:white; padding:32px 40px; border-radius:14px; margin-bottom:24px; }}
.header h1 {{ font-size:26px; font-weight:700; }}
.header .sub {{ margin-top:6px; font-size:13px; color:#8892b0; }}

/* 摘要卡片 */
.summary {{ display:flex; gap:16px; margin-bottom:24px; flex-wrap:wrap; }}
.scard {{ background:white; border-radius:12px; padding:18px 22px; box-shadow:0 2px 8px rgba(0,0,0,.08); flex:1; min-width:130px; text-align:center; }}
.scard .num {{ font-size:34px; font-weight:800; }}
.scard .label {{ font-size:13px; color:#999; margin-top:4px; }}

/* 视图切换 */
.view-tabs {{ display:flex;gap:4px;margin-bottom:20px; }}
.view-tab {{ padding:10px 22px;border:none;border-radius:10px;cursor:pointer;font-size:14px;font-weight:500;background:#fff;color:#94a3b8;transition:all .25s;box-shadow:0 1px 3px rgba(0,0,0,.06);font-family:inherit; }}
.view-tab:hover {{ color:#475569;background:rgba(99,102,241,.06); }}
.view-tab.active {{ color:#fff;font-weight:600;background:linear-gradient(135deg,#6366f1,#8b5cf6);box-shadow:0 4px 12px rgba(99,102,241,.3); }}

/* 胶囊角色标签（跟员工负载一致） */
.tab-bar {{ display:flex;gap:0;margin-bottom:20px;flex-wrap:wrap;background:#fff;border-radius:14px;padding:6px 8px;box-shadow:0 2px 12px rgba(0,0,0,0.06); }}
.tab-btn {{ background:transparent;border:none;padding:10px 20px;border-radius:10px;cursor:pointer;font-size:14px;font-weight:500;font-family:inherit;color:#94a3b8;transition:all .25s cubic-bezier(.4,0,.2,1);position:relative;overflow:hidden; }}
.tab-btn:hover {{ color:#475569;background:rgba(99,102,241,.06); }}
.tab-btn.active {{ color:#fff;font-weight:600;background:linear-gradient(135deg,#6366f1 0%,#8b5cf6 100%);box-shadow:0 4px 14px rgba(99,102,241,0.35),0 1px 3px rgba(0,0,0,0.12); }}

/* 面板切换 */
.view-panel {{ display:none; }}
.view-panel.show {{ display:block; }}
.role-section {{ display:none; }}
.role-section.show {{ display:block; }}

/* 表格 */
.table-wrap {{ background:white; border-radius:12px; box-shadow:0 2px 8px rgba(0,0,0,.07); overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; font-size:12px; }}
th {{ background:#f8f9fa; padding:10px 8px; text-align:center; font-weight:600; border-bottom:2px solid #e8e8e8; white-space:nowrap; position:sticky; top:0; z-index:1; }}
td {{ padding:7px 8px; text-align:center; border-bottom:1px solid #f0f0f0; white-space:nowrap; }}
tr:hover td {{ background:#f8f9ff; }}
td.name {{ text-align:left; font-weight:600; }}
td.total {{ font-weight:700; color:#1a73e8; }}
td.hours {{ color:#888; }}
td.has-task {{ background:#e8f5e9; color:#2e7d32; font-weight:600; border-radius:4px; }}
th.date-col {{ min-width:44px; font-size:11px; }}
.date-weekend {{ background:#fff3e0; }}

/* 任务类型标签 */
.task-item {{ display:flex;align-items:flex-start;padding:5px 0;border-bottom:1px dashed #eee;font-size:12px; }}
.task-item:last-child {{ border:none; }}
.task-type {{ display:inline-block;padding:1px 7px;border-radius:3px;font-size:10px;margin-right:6px;flex-shrink:0;font-weight:500; }}
.type-产品 {{ background:#ede9fe; color:#7c3aed; }}
.type-后端 {{ background:#d1fae5; color:#059669; }}
.type-前端 {{ background:#fce7f3; color:#be185d; }}
.type-移动端 {{ background:#ffedd5; color:#c2410c; }}
.type-测试 {{ background:#f3e8ff; color:#7c3aed; }}
.type-UI设计 {{ background:#ccfbf1; color:#0d9488; }}
.type-其他 {{ background:#f3f4f6; color:#6b7280; }}

/* 日期折叠 */
.person-section {{ margin-bottom:6px; }}
.person-summary {{ display:flex;align-items:center;gap:10px;padding:10px 16px;background:white;border-radius:10px;cursor:pointer;box-shadow:0 1px 3px rgba(0,0,0,.04);transition:.2s; }}
.person-summary:hover {{ box-shadow:0 2px 8px rgba(0,0,0,.1); }}

.footer {{ text-align:center;padding:24px;color:#bbb;font-size:12px; }}
</style>
</head>
<body>
<div class="container">

<div class="header">
  <h1>团队每日完成任务流水清单</h1>
  <div class="sub">{start_date} ~ {end_date} | {total_tasks} 个已完成任务 | {total_people} 人 | 覆盖 {len(daily_log)} 天</div>
</div>

<div class="summary">
  <div class="scard"><div class="num" style=color:#10b981>{total_tasks}</div><div class="label">已完成任务</div></div>
  <div class="scard"><div class="num" style=color:#6366f1>{total_people}</div><div class="label">参与人数</div></div>
  <div class="scard"><div class="num" style=color:#f59e0b>{len(daily_log)}</div><div class="label">覆盖天数</div></div>
  <div class="scard"><div class="num" style=color:#ea580c>{sum(stats['hours'] for _, stats in sorted_people):.0f}h</div><div class="label">预估工时</div></div>
</div>

<!-- 视图切换 -->
<div class="view-tabs">
  <button class="view-tab active" onclick="switchView('matrix')">人员×日期矩阵</button>
  <button class="view-tab" onclick="switchView('daily')">按日期明细</button>
</div>

<!-- ═══ 矩阵视图 ═══ -->
<div class="view-panel show" id="view-matrix">

<!-- 角色标签 -->
<div class="tab-bar matrix-tabs">
'''
    # 矩阵角色标签按钮
    for role in active_roles:
        is_active = ' class=tab-btn active' if role == first_role else ' class=tab-btn'
        rc = ROLE_COLORS.get(role, "#888")
        html += f'<button{is_active} onclick=switchMatrixTab("{role}")>{role}<span style="margin-left:4px;font-size:11px;opacity:.7;">({len(role_groups[role])}人)</span></button>\n'

    html += '</div>\n'

    # 为每个角色生成独立的矩阵表格
    for role in active_roles:
        people_in_role = role_groups[role]
        rc = ROLE_COLORS.get(role, "#888")
        is_show = ' show' if role == first_role else ''
        rh = sum(s["hours"] for _, s in people_in_role)
        rn = sum(s["count"] for _, s in people_in_role)

        html += f'''<div class="role-section{is_show}" data-role="{role}">
<div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;">
<span style="font-weight:700;font-size:15px;color:{rc};border-left:4px solid {rc};padding-left:8px;">{role}</span>
<span style="font-size:12px;color:#999;">{rn} 个任务 · {rh:.0f}h · {len(people_in_role)} 人</span>
</div>
<div class="table-wrap"><table>
<thead><tr><th>人员</th><th>合计</th><th>工时h</th>\n'''

        # 日期列头
        for d in sorted_dates:
            dt = datetime.strptime(d, "%Y-%m-%d")
            wd_cls = ' date-weekend' if dt.weekday() >= 5 else ''
            html += f'<th class="date-col{wd_cls}">{d[5:]}</th>\n'

        html += '</tr></thead><tbody>\n'

        for person, stats in people_in_role:
            html += f'<tr><td class=name>{person}</td>'
            html += f'<td class=total>{stats["count"]}</td>'
            html += f'<td class=hours>{stats["hours"]:.0f}</td>'
            for d in sorted_dates:
                tasks = daily_log[d].get(person, [])
                n = len(tasks) if tasks else ""
                cls = ' class=has-task' if n else ''
                html += f'<td{cls}>{n}</td>'
            html += '</tr>\n'

        html += f'''</tbody></table></div></div>\n'''

    html += '''</div><!-- /view-matrix -->

<!-- ═══ 按日期明细视图 ═══ -->
<div class="view-panel" id="view-daily">

<!-- 角色标签 -->
<div class="tab-bar daily-tabs">
'''

    # 明细视图的角色标签
    for role in active_roles:
        is_active = ' class=tab-btn active' if role == first_role else ' class=tab-btn'
        rc = ROLE_COLORS.get(role, "#888")
        html += f'<button{is_active} onclick=switchDailyTab("{role}")>{role}<span style="margin-left:4px;font-size:11px;opacity:.7;">({len(role_groups[role])}人)</span></button>\n'

    html += '</div>\n'

    # 为每个角色生成独立日期明细
    for role in active_roles:
        is_show = ' show' if role == first_role else ''
        html += f'<div class="role-section{is_show}" data-daily-role="{role}">\n'

        for d in sorted_dates:
            dt = datetime.strptime(d, "%Y-%m-%d")
            weekday = ["周一","周二","周三","周四","周五","周六","周日"][dt.weekday()]
            day_label = f"{d} ({weekday})"
            day_people = daily_log[d]

            # 只显示当前角色的成员
            role_members_today = [(p, day_people[p]) for p in sorted(day_people.keys(), key=lambda p: (
                role_order_map.get(person_totals[p]["role"], 99),
                -len(day_people[p])
            )) if person_totals[p]["role"] == role]

            if not role_members_today:
                continue

            day_total = sum(len(t) for _, t in role_members_today)

            html += f'''<details class="person-section" style="margin-bottom:8px;">
<summary class="person-summary" style="padding-left:16px;border-left:4px solid {ROLE_COLORS.get(role,'#888')};">
<span style="font-weight:700;font-size:13px;">{day_label}</span>
<span style="font-size:12px;color:#888;margin-left:8px;">{day_total}个任务 · {len(role_members_today)}人</span>
</summary>
<div style="padding:8px 16px;">\n'''

            for person, tasks in role_members_today:
                html += f'<div style="margin-bottom:6px;"><span style="font-weight:600;font-size:13px;">{person}</span>'
                html += f'<span style="font-size:11px;color:#aaa;margin-left:4px;">({len(tasks)}个)</span><div style="padding-left:8px;">'
                for t in tasks:
                    type_cls = f"type-{t['type']}"
                    html += f'<div class="task-item"><span class="task-type {type_cls}">{t["type"]}</span>'
                    html += f'<span>#{t["id"]} {t["name"]}</span>'
                    html += f'<span style="margin-left:auto;font-size:11px;color:#bbb;">{t["platform"]} · {t["execution"]}</span></div>'
                html += '</div></div>'

            html += '</div></details>\n'
        html += '</div><!-- /role-section -->\n'

    html += '''</div><!-- /view-daily -->

<div class="footer">禅道数据 · 自动生成于 ''' + today.isoformat() + ''' · WorkBuddy</div>

<script>
function switchView(v) {
  document.querySelectorAll('.view-panel').forEach(p => p.classList.remove('show'));
  document.getElementById('view-' + v).classList.add('show');
  document.querySelectorAll('.view-tab').forEach(b => b.classList.remove('active'));
  event.target.classList.add('active');
}

function switchMatrixTab(r) {
  // 切换矩阵面板内的角色标签
  document.querySelectorAll('#view-matrix .tab-bar.matrix-tabs .tab-btn').forEach(b => {
    b.classList.toggle('active', b.textContent.trim().startsWith(r));
  });
  document.querySelectorAll('#view-matrix .role-section').forEach(s => {
    s.classList.toggle('show', s.getAttribute('data-role') === r);
  });
}

function switchDailyTab(r) {
  document.querySelectorAll('#view-daily .tab-bar.daily-tabs .tab-btn').forEach(b => {
    b.classList.toggle('active', b.textContent.trim().startsWith(r));
  });
  document.querySelectorAll('#view-daily .role-section').forEach(s => {
    s.classList.toggle('show', s.getAttribute('data-daily-role') === r);
  });
}
</script>
</div>
</body></html>'''

    output_path = os.path.join(output_dir, "团队每日任务流水清单.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    # Write JSON summary for _compute_trend_data.py / dashboard
    import json as _json
    today_str = str(date.today())
    today_data = daily_log.get(today_str, {})
    today_done = sum(len(t) for t in today_data.values())
    today_people = len(today_data)
    summary = {
        "total_done": total_tasks,
        "total_people": total_people,
        "total_days": len(daily_log),
        "hours": round(sum(stats['hours'] for _, stats in sorted_people), 1),
        "today_done": today_done,
        "today_people": today_people,
        "by_role": {r: {"count": sum(s["count"] for p,s in role_groups.get(r,[])), "people": len(role_groups.get(r,[]))}
                     for r in active_roles},
    }
    summary_path = os.path.join(output_dir, "_daily_log_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        _json.dump(summary, f, ensure_ascii=False)

    print(f"  ✓ 已生成: {output_path}")
    print(f"  📊 {total_tasks} 个完成任务 | {total_people} 人 | {len(daily_log)} 天")
    print("=" * 70)

if __name__ == "__main__":
    main()
