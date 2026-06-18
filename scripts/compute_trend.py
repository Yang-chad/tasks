#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""计算趋势表中今日新增/减少任务数

通过比较昨日和今日的JSON任务ID集合，计算每个类型的:
- 今日新增（红色）: 今日未完成任务中存在、昨日没有的
- 今日减少（绿色）: 昨日未完成任务中存在、今日已完成的

用法: python _compute_trend_data.py [--yesterday YYYY-MM-DD] [--today YYYY-MM-DD]
"""
import json, os, sys, argparse
from pathlib import Path
from datetime import date, timedelta

BASE = Path(os.environ.get('GITHUB_WORKSPACE', os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

JSON_CONFIG = [
    ("未完成产品任务_统计.json", "产品"),
    ("未完成后端开发_统计.json", "后端"),
    ("未完成前端开发_统计.json", "前端"),
    ("未完成移动端开发_统计.json", "移动端"),
]


def get_task_ids(json_path):
    """从JSON文件提取所有任务ID (向后兼容)"""
    if not json_path.exists():
        return set()
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    ids = set()
    for person, info in data.get("by_assignee", {}).items():
        for t in info.get("tasks", []):
            ids.add(t["id"])
    return ids


def get_task_info(json_path):
    """从JSON文件提取任务ID→openedDate映射 (新增)

    Returns:
        dict: {task_id: {"openedDate": "2026-06-17T09:30:00", ...}}
        如果JSON中没有openedDate字段，值设为空字符串
    """
    if not json_path.exists():
        return {}
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    result = {}
    for person, info in data.get("by_assignee", {}).items():
        for t in info.get("tasks", []):
            result[t["id"]] = {
                "openedDate": t.get("openedDate", ""),
                "status": t.get("status", ""),
                "assignee": t.get("assignee", ""),
                "name": t.get("name", ""),
            }
    return result


def compute(yesterday_dir, today_dir, today_str=None):
    """返回 {label: {added, removed, created_today, migrated}}

    added:        今日有/昨日无 的ID总数 (与旧版一致)
    removed:      昨日有/今日无 的ID总数 (与旧版一致)
    created_today: added中 openedDate 以 today_str 开头的 (今天真正创建的)
    migrated:     added中 openedDate 不以 today_str 开头的 (迭代迁移/重新激活)
    """
    results = {}
    for fn, lb in JSON_CONFIG:
        y_ids = get_task_ids(yesterday_dir / fn)
        t_ids = get_task_ids(today_dir / fn)
        t_info = get_task_info(today_dir / fn)

        added_ids = t_ids - y_ids
        removed = len(y_ids - t_ids)
        added = len(added_ids)

        # 区分"今天创建" vs "迁移/重现"
        created_today = 0
        migrated = 0
        if today_str and t_info:
            for tid in added_ids:
                od = t_info.get(tid, {}).get("openedDate", "")
                if od.startswith(today_str):
                    created_today += 1
                else:
                    migrated += 1
        else:
            # 没有openedDate字段时无法区分，全部归入added
            migrated = added

        results[lb] = {
            "added": added,
            "removed": removed,
            "created_today": created_today,
            "migrated": migrated,
        }

        detail = f"{lb}: 新增+{added}(红) / 减少-{removed}(绿) = 净变{len(t_ids)-len(y_ids)}"
        if created_today > 0 or migrated > 0:
            detail += f"  [新建{created_today}·迁移{migrated}]"
        print(detail)
    return results


def update_summary_bar(content, base_dir):
    """更新根 index.html 摘要栏数字，使其与 JSON 数据一致。"""
    import re

    # (color_hex, json_filename, icon_label, uses_overdue_format)
    specs = [
        ("#a5b4fc", "未完成产品任务_统计.json",     "产品",    False),
        ("#66eea6", "未完成后端开发_统计.json",     "后端",    False),
        ("#f093fb", "未完成前端开发_统计.json",     "前端",    False),
        ("#ffa726", "未完成移动端开发_统计.json",   "移动端",  False),
        ("#26c6da", "未完成测试任务_统计.json",     "测试",    False),
        ("#ef5350", "延期任务统计.json",            "延期任务", True),
    ]

    emoji_map = {"产品": "📋", "后端": "⚙️", "前端": "🎨", "移动端": "📱", "测试": "🧪", "延期任务": "🚨"}

    updated = 0
    for color, json_file, label, is_overdue in specs:
        jp = base_dir / json_file
        if not jp.exists():
            continue
        with open(jp, "r", encoding="utf-8") as f:
            jdata = json.load(f)

        if is_overdue:
            total = jdata.get("total_overdue", 0)
            people = len(jdata.get("tasks_by_assignee", {}))
            new_num = str(total)
            new_label = f'{emoji_map[label]} {label} ({people}人)'
        else:
            total = jdata.get("total_incomplete", 0)
            summary = jdata.get("summary", {"wait": 0, "doing": 0})
            new_num = str(total)
            new_label = f'{emoji_map[label]} {label} (待{summary["wait"]}/做{summary["doing"]})'

        # Match: <div class="num" style="color:COLOR;">OLD</div>
        num_pattern = re.compile(
            rf'(<div class="num" style="color:{re.escape(color)};">).+?(</div>)'
        )
        content, n1 = num_pattern.subn(rf'\g<1>{new_num}\g<2>', content, count=1)

        # Match: <div class="label">OLD_LABEL</div> (search after num update)
        # The label follows immediately after num div
        label_pattern = re.compile(
            rf'(<div class="num" style="color:{re.escape(color)};">{re.escape(new_num)}</div>\s*<div class="label">).+?(</div>)'
        )
        content, n2 = label_pattern.subn(rf'\g<1>{new_label}\g<2>', content, count=1)
        if n1 > 0 and n2 > 0:
            updated += 1

    print(f"  [summary] Updated {updated} summary items")
    return content


def update_card_descriptions(content, base_dir):
    """更新根 index.html 中所有卡片的描述文字，使其与 JSON 数据一致。"""
    import re

    # (card_name_hint, json_filename, desc_format, total_key, use_overdue_key)
    card_specs = [
        ("产品任务</span>",       "未完成产品任务_统计.json",     "需求 / AB 类型<br>{}个未完成 · {}人",        "total_incomplete", False),
        ("后端开发</span>",       "未完成后端开发_统计.json",     "后端开发任务<br>{}个未完成 · {}人",           "total_incomplete", False),
        ("前端开发</span>",       "未完成前端开发_统计.json",     "前端开发任务<br>{}个未完成 · {}人",          "total_incomplete", False),
        ("移动端开发</span>",     "未完成移动端开发_统计.json",   "移动端开发任务<br>{}个未完成 · {}人",         "total_incomplete", False),
        ("测试任务</span>",       "未完成测试任务_统计.json",     "测试执行 + 测试设计<br>{}个未完成 · {}人",     "total_incomplete", False),
        ("延期任务</span>",       "延期任务统计.json",            "{}个延期 / {}人<br>全平台超期追踪",           "total_overdue",   True),
    ]

    updated = 0
    for name_hint, json_file, fmt, total_key, use_overdue_ppl in card_specs:
        jp = base_dir / json_file
        if not jp.exists():
            continue
        with open(jp, "r", encoding="utf-8") as f:
            jdata = json.load(f)

        total = jdata.get(total_key, 0)
        if use_overdue_ppl:
            people = len(jdata.get("tasks_by_assignee", {}))
        else:
            people = len(jdata.get("by_assignee", {}))

        new_desc = fmt.format(total, people)
        pattern = re.compile(
            rf'({re.escape(name_hint)}\s*<span class="desc">).*?(</span>)',
            re.DOTALL
        )
        content, n = pattern.subn(rf'\g<1>{new_desc}\g<2>', content, count=1)
        if n > 0:
            updated += 1

    print(f"  [cards] Updated {updated} card descriptions")
    return content


def update_card_date(content, today_str):
    """更新根 index.html 中所有卡片链接的日期目录为今天。
    只在 <div class="grid"> 区域内替换，不影响历史导航链接。
    """
    import re

    grid_match = re.search(
        r'(<div class="grid">.*?</div>)', content, re.DOTALL)
    if not grid_match:
        print("  [links] Grid section not found, skipping card date update")
        return content

    grid_content = grid_match.group(1)
    old_date_match = re.search(r'href="(\d{4}-\d{2}-\d{2})/', grid_content)
    if not old_date_match:
        print("  [links] No date-based href in cards, skipping")
        return content

    old_date = old_date_match.group(1)
    if old_date == today_str:
        print(f"  [links] Card links already point to {today_str}")
        return content

    new_grid = re.sub(rf'href="{old_date}/', f'href="{today_str}/', grid_content)
    content = content.replace(grid_content, new_grid)
    print(f"  [links] Card links: {old_date} → {today_str}")
    return content


def update_history_nav(content, today_str):
    """更新历史导航：确保今天日期是第一个条目，并只保留最近7天。
    """
    import re
    from datetime import date, timedelta

    nav_match = re.search(
        r'(<div class="history-links">)(.*?)(</div>)', content, re.DOTALL)
    if not nav_match:
        print("  [nav] History nav section not found, skipping")
        return content

    links_block = nav_match.group(2)

    # 提取所有现有链接
    links = re.findall(r'<a\s+href="(\d{4}-\d{2}-\d{2})/"[^>]*>(\d{4}-\d{2}-\d{2})</a>', links_block)

    # 确定最近7天的日期范围
    today_dt = date.fromisoformat(today_str)
    cutoff = (today_dt - timedelta(days=6)).isoformat()  # 含今天在内共7天
    valid_dates = set()
    for i in range(7):
        valid_dates.add((today_dt - timedelta(days=i)).isoformat())

    # 构建新链接列表（去重 + 裁剪）
    seen = set()
    new_links = []
    for href, text in links:
        if href not in valid_dates:
            continue
        if href in seen:
            continue
        seen.add(href)
        new_links.append((href, text))

    # 确保今天在首位（如果不在则插入）
    if today_str not in seen:
        new_links.insert(0, (today_str, today_str))

    # 按日期降序排列
    new_links.sort(key=lambda x: x[0], reverse=True)

    # 重建 HTML
    new_block = '\n'.join(
        f'            <a href="{href}/">{text}</a>' for href, text in new_links[:7])
    new_nav = nav_match.group(1) + '\n' + new_block + '\n        ' + nav_match.group(3)
    content = content.replace(nav_match.group(0), new_nav)
    pruned = len(links) - len(new_links[:7])
    action = f"({len(links)}→{len(new_links[:7])}" + (f", 删{pruned}超期)" if pruned > 0 else ")")
    print(f"  [nav] History nav pruned to 7d {action}")
    return content


def update_index_html(today_str, data, index_path):
    """更新根 index.html 的今日趋势行 + 卡片描述。
    规则:
    1. 每天只有一条 today 行（同天运行多次→直接替换，不追加）
    2. 历史数据只保留最近 7 天
    """
    if not index_path.exists():
        print(f"[ERROR] index.html not found: {index_path}")
        return

    with open(index_path, "r", encoding="utf-8") as f:
        content = f.read()

    import re
    import time as tmod

    labels = ["产品", "后端", "前端", "移动端"]
    css_classes = {"产品": "trend-c-p", "后端": "trend-c-b", "前端": "trend-c-f", "移动端": "trend-c-m"}

    # Read today's total_incomplete from JSON (base dir)
    today_totals = {}
    for fn, lb in JSON_CONFIG:
        with open(BASE / fn, "r", encoding="utf-8") as f:
            today_totals[lb] = json.load(f)["total_incomplete"]

    total_all = sum(today_totals.values())
    total_added = sum(data[lb]["added"] for lb in labels)
    total_removed = sum(data[lb]["removed"] for lb in labels)
    total_created = sum(data[lb].get("created_today", 0) for lb in labels)
    total_migrated = sum(data[lb].get("migrated", 0) for lb in labels)

    def _build_added_split(d):
        """构建新增数字: +112"""
        added = d["added"]
        if added > 0:
            return f'+{added}'
        return ''

    # Build the today row HTML
    today_row_parts = [f'                    <tr class="today">\n',
                       f'                        <td>{today_str} ⬅</td>\n']
    for lb in labels:
        d = data[lb]
        cc = css_classes[lb]
        num = today_totals[lb]
        added_text = _build_added_split(d)
        if d["added"] > 0 and d["removed"] > 0:
            split = f' <span class="trend-delta trend-up">{added_text}</span> <span class="trend-delta trend-down">-{d["removed"]}</span>'
        elif d["added"] > 0:
            split = f' <span class="trend-delta trend-up">{added_text}</span>'
        elif d["removed"] > 0:
            split = f' <span class="trend-delta trend-down">-{d["removed"]}</span>'
        else:
            split = f' <span class="trend-delta trend-flat">--</span>'
        today_row_parts.append(f'                        <td class="{cc}">{num}{split}</td>\n')

    # 合计行
    total_added_text = _build_added_split({"added": total_added, "created_today": total_created, "migrated": total_migrated})
    if total_added > 0 and total_removed > 0:
        total_split = f' <span class="trend-delta trend-up">{total_added_text}</span> <span class="trend-delta trend-down">-{total_removed}</span>'
    elif total_added > 0:
        total_split = f' <span class="trend-delta trend-up">{total_added_text}</span>'
    else:
        total_split = f' <span class="trend-delta trend-down">-{total_removed}</span>'
    today_row_parts.append(f'                        <td>{total_all}{total_split}</td>\n')
    today_row_parts.append('                    </tr>')
    today_row = ''.join(today_row_parts)

    # ── Step 1: Handle existing today row ──
    old_today_pattern = r'(<tr class="today">.*?</tr>)'
    old_today_match = re.search(old_today_pattern, content, flags=re.DOTALL)
    old_today_date = ""
    if old_today_match:
        # Extract date from old today row
        date_match = re.search(r'<td>(\d{4}-\d{2}-\d{2})', old_today_match.group(1))
        if date_match:
            old_today_date = date_match.group(1)

    if old_today_date == today_str:
        # Same day: replace the today row in-place (no historical row created)
        new_content = content.replace(old_today_match.group(1), today_row)
        print(f"  [same-day] Replaced today row for {today_str}")
    else:
        # Different day: convert old today to regular, insert new today
        if old_today_match:
            old_row = old_today_match.group(1)
            regular_row = old_row.replace('class="today"', '')
            regular_row = re.sub(r' ⬅', '', regular_row)
            new_content = content.replace(old_today_match.group(1), regular_row + '\n' + today_row)
            print(f"  [new-day] Converted {old_today_date}→regular, inserted {today_str}")
        else:
            # No today row at all (first run)
            new_content = content + '\n' + today_row
            print(f"  [first-run] Inserted {today_str}")

    # ── Step 2: Remove duplicate regular rows for today's date ──
    dup_pattern = rf'(<tr >\s*<td>{today_str}</td>.*?</tr>)'
    dup_matches = list(re.finditer(dup_pattern, new_content, flags=re.DOTALL))
    if len(dup_matches) > 1:
        # Keep only the first occurrence, remove the rest
        for m in reversed(dup_matches[1:]):
            new_content = new_content[:m.start()] + new_content[m.end():]
        print(f"  [dedup] Removed {len(dup_matches)-1} duplicate regular row(s) for {today_str}")

    # ── Step 3: Prune to last 7 days ──
    from datetime import date, timedelta
    cutoff = (date.today() - timedelta(days=7)).isoformat()
    all_rows = list(re.finditer(
        r'<tr(?:\s+class="today")?>\s*<td>(\d{4}-\d{2}-\d{2})</td>.*?</tr>',
        new_content, flags=re.DOTALL))
    pruned = 0
    for m in reversed(all_rows):
        row_date = m.group(1)
        if row_date < cutoff and m.group(0).find('class="today"') == -1:
            new_content = new_content[:m.start()] + new_content[m.end():]
            pruned += 1
    if pruned:
        print(f"  [prune] Removed {pruned} old row(s) older than {cutoff}")

    # ── Step 4: Update timestamp (Beijing time UTC+8) ──
    from datetime import datetime, timezone, timedelta
    now = (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%H:%M")
    new_content = re.sub(
        r'(<div class="date-tag"><span>)\d{4}-\d{2}-\d{2} \d{2}:\d{2}( 更新</span></div>)',
        rf'\g<1>{today_str} {now}\g<2>',
        new_content
    )

    # ── Step 5: Update summary bar from JSON ──
    new_content = update_summary_bar(new_content, BASE)

    # ── Step 6: Update card descriptions from JSON ──
    new_content = update_card_descriptions(new_content, BASE)

    # ── Step 7: Update card href links to today's date ──
    new_content = update_card_date(new_content, today_str)

    # ── Step 8: Update history nav (today's link first) ──
    new_content = update_history_nav(new_content, today_str)

    with open(index_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    print(f"[OK] Updated {index_path} with add/remove split data + cards + timestamp {now}")


def main():
    parser = argparse.ArgumentParser(description="计算今日新增/减少任务数")
    parser.add_argument("--yesterday", type=str, default=None,
                        help="昨日目录 (default: today-1)")
    parser.add_argument("--today", type=str, default=None,
                        help="今日目录/日期 (default: today)")
    parser.add_argument("--update-index", action="store_true",
                        help="是否更新根 index.html")
    args = parser.parse_args()

    today = date.today()
    today_str = today.isoformat()
    if args.today:
        today_str = args.today

    yesterday = today - timedelta(days=1)
    yesterday_str = yesterday.isoformat()
    if args.yesterday:
        yesterday_str = args.yesterday

    # Find JSON files
    today_json_dir = BASE
    yesterday_json_dir = BASE / yesterday_str

    print(f"📊 趋势数据计算: {yesterday_str} → {today_str}")
    print(f"   昨日JSON: {yesterday_json_dir}")
    print(f"   今日JSON: {today_json_dir}")

    data = compute(yesterday_json_dir, today_json_dir, today_str=today_str)

    if args.update_index:
        update_index_html(today_str, data, BASE / "index.html")

    return 0


if __name__ == "__main__":
    sys.exit(main())
