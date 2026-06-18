
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
    subprocess.run(["git", "config", "user.name", "GitHub Actions"], capture_output=True)
    subprocess.run(["git", "config", "user.email", "actions@github.com"], capture_output=True)
    subprocess.run(["git", "add", "."], capture_output=True)
    r = subprocess.run(["git", "commit", "-m", f"auto: {TODAY} 禅道数据刷新 (GitHub Actions)"],
                       capture_output=True, text=True)
    out = r.stdout.strip() + r.stderr.strip()
    print(f"  Commit: {out[:200]}")
    r = subprocess.run(["git", "push", "origin", "main"], capture_output=True, text=True)
    out = r.stdout.strip() + r.stderr.strip()
    print(f"  Push: {out[:200]}")

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

    # Step 3: Generate task reports (parallel)
    print("\n[Generate] Task reports...")
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

    # Step 4: Overdue report
    print(f"\n[Overdue] {len(overdue_tasks)} tasks")
    by_a = defaultdict(list)
    for t in overdue_tasks: by_a[t["_assignee_name"]].append(t)
    od_json = {"check_date": TODAY, "total_overdue": len(overdue_tasks), "tasks_by_assignee": {}}
    for a, tl in sorted(by_a.items(), key=lambda x: -len(x[1])):
        od_json["tasks_by_assignee"][a] = {
            "count": len(tl), "max_overdue_days": max(t.get("_days_overdue",0) for t in tl),
            "tasks": [_task_to_dict(t) for t in tl]}
    for p in [WORKSPACE / "延期任务统计.json", OUTPUT_DIR / "延期任务统计.json"]:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(od_json, f, ensure_ascii=False, indent=2)
    generate_overdue_html(overdue_tasks, str(OUTPUT_DIR / "延期任务统计报告.html"))

    # Step 5: Iteration summaries
    iteration_summaries = fetch_iterations_and_generate_reports()
    overdue_people_count = len(by_a)

    # Step 6: Root overview page
    print("\n[Overview] Generating index.html...")
    history_dates = sorted([d.name for d in WORKSPACE.iterdir()
        if d.is_dir() and re.match(r'\d{4}-\d{2}-\d{2}', d.name)])
    overview_html = generate_overview_html(cats, len(overdue_tasks), overdue_people_count,
                                           history_dates, iteration_summaries)
    with open(WORKSPACE / "index.html", "w", encoding="utf-8") as f:
        f.write(overview_html)
    print(f"  index.html written ({len(overview_html)} bytes)")

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
