#!/usr/bin/env python3
"""Build a one-page summary of your pull-request activity over the last N weeks.

    pr-activity.py <out dir>

Writes <out dir>/index.html (standalone, links ../site.css) and prints the publish.sh
command for it.

Environment:
  ARTIFACTS_PR_HOSTS       comma list of GitHub hosts (default github.com)
  ARTIFACTS_ACTIVITY_WEEKS weeks to cover, ending with the current week (default 12)
  ARTIFACTS_PR_REPOS       comma list of owner/repo to restrict to (default: all)
"""

import datetime as dt
import html
import json
import os
import statistics
import subprocess
import sys
import tempfile
from collections import OrderedDict

THEME_BOOT = ("<script>try{var t=localStorage.getItem('claude-artifacts-theme');"
              "if(t)document.documentElement.dataset.theme=t}catch(e){}</script>")

SEARCH_Q = """
query($q: String!, $after: String) {
  search(query: $q, type: ISSUE, first: 100, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes { ... on PullRequest {
      number title url createdAt mergedAt state isDraft repository { nameWithOwner }
    } }
  }
}"""

REVIEWS_Q = """
query($from: DateTime!, $to: DateTime!, $after: String) {
  viewer { contributionsCollection(from: $from, to: $to) {
    pullRequestReviewContributions(first: 100, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes {
        occurredAt
        pullRequestReview { state }
        pullRequest { number url author { login } repository { nameWithOwner } }
      }
    }
  } }
}"""


def die(msg):
    sys.exit(f"error: {msg}")


def graphql(host, query, variables):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tmp:
        json.dump({"query": query, "variables": variables}, tmp)
    try:
        res = subprocess.run(["gh", "api", "--hostname", host, "graphql", "--input", tmp.name],
                             capture_output=True, text=True)
    finally:
        os.unlink(tmp.name)
    if res.returncode != 0:
        raise RuntimeError((res.stderr or res.stdout).strip())
    out = json.loads(res.stdout or "{}")
    if out.get("errors") and not out.get("data"):
        raise RuntimeError("; ".join(e.get("message", "") for e in out["errors"]))
    return out["data"]


def search(host, query):
    found, after = [], None
    while True:
        page = graphql(host, SEARCH_Q, {"q": query, "after": after})["search"]
        found += [n for n in page["nodes"] if n]
        if not page["pageInfo"]["hasNextPage"]:
            return found
        after = page["pageInfo"]["endCursor"]


def review_contributions(host, start, end):
    found = []
    lo = start
    # contributionsCollection rejects spans longer than one year.
    while lo < end:
        hi = min(end, lo + dt.timedelta(days=365))
        after = None
        while True:
            data = graphql(host, REVIEWS_Q, {"from": lo.isoformat(), "to": hi.isoformat(), "after": after})
            page = data["viewer"]["contributionsCollection"]["pullRequestReviewContributions"]
            found += [n for n in page["nodes"] if n]
            if not page["pageInfo"]["hasNextPage"]:
                break
            after = page["pageInfo"]["endCursor"]
        lo = hi
    return found


def parse(ts):
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00")) if ts else None


def esc(s):
    return html.escape(str(s if s is not None else ""))


def fmt_duration(hours):
    if hours is None:
        return "–"
    if hours < 48:
        return f"{hours:.0f}h"
    return f"{hours / 24:.1f}d"


def nice_max(v):
    if v <= 4:
        return 4
    for step in (5, 10, 20, 25, 50, 100, 200, 250, 500, 1000):
        if v <= step * 4:
            return -(-v // step) * step
    return v


def bar_chart(weeks, series, title, desc, chart_id):
    """Grouped vertical bars; series = [(label, css class, [values per week])]."""
    w, h, left, right, top, bottom = 760, 240, 40, 12, 14, 36
    plot_w, plot_h = w - left - right, h - top - bottom
    ymax = nice_max(max([max(v) for _, _, v in series] + [1]))
    ticks = 4
    band = plot_w / len(weeks)
    gap = 2
    bar_w = max(3, min(18, (band * 0.7 - gap * (len(series) - 1)) / len(series)))
    group_w = bar_w * len(series) + gap * (len(series) - 1)
    out = [f'<svg class="chart" viewBox="0 0 {w} {h}" role="img" aria-labelledby="{chart_id}-t {chart_id}-d">',
           f'<title id="{chart_id}-t">{esc(title)}</title><desc id="{chart_id}-d">{esc(desc)}</desc>']
    for i in range(ticks + 1):
        val = ymax * i / ticks
        y = top + plot_h - plot_h * i / ticks
        out.append(f'<line class="grid{" base" if i == 0 else ""}" x1="{left}" x2="{w - right}" y1="{y:.1f}" y2="{y:.1f}"/>')
        out.append(f'<text class="tick" x="{left - 6}" y="{y + 4:.1f}" text-anchor="end">{val:g}</text>')
    label_every = max(1, -(-len(weeks) // 13))
    for i, wk in enumerate(weeks):
        x0 = left + band * i + (band - group_w) / 2
        for j, (label, cls, vals) in enumerate(series):
            v = vals[i]
            bh = plot_h * v / ymax
            x = x0 + j * (bar_w + gap)
            y = top + plot_h - bh
            tip = f"{label}, week of {wk:%b %-d}: {v}"
            if v:
                r = min(4, bar_w / 2, bh)
                out.append(f'<path class="bar {cls}" d="M{x:.1f},{top + plot_h:.1f}V{y + r:.1f}'
                           f'Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f}H{x + bar_w - r:.1f}'
                           f'Q{x + bar_w:.1f},{y:.1f} {x + bar_w:.1f},{y + r:.1f}V{top + plot_h:.1f}Z"/>')
            out.append(f'<rect class="hit" x="{x - 1:.1f}" y="{top}" width="{bar_w + 2:.1f}" height="{plot_h}">'
                       f'<title>{esc(tip)}</title></rect>')
        if i % label_every == 0:
            out.append(f'<text class="tick" x="{left + band * i + band / 2:.1f}" y="{h - bottom + 16}" '
                       f'text-anchor="middle">{wk:%b %-d}</text>')
    out.append(f'<text class="axis-label" x="{left + plot_w / 2:.1f}" y="{h - 4}" text-anchor="middle">Week starting</text>')
    out.append("</svg>")
    legend = "".join(f'<span><i class="swatch {cls}"></i>{esc(label)}</span>' for label, cls, _ in series)
    return f'<figure class="chart-figure"><figcaption class="chart-legend">{legend}</figcaption>{"".join(out)}</figure>'


def main():
    if len(sys.argv) != 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__.strip())
        sys.exit(0 if len(sys.argv) == 2 else 2)
    out_dir = os.path.abspath(sys.argv[1])
    os.makedirs(out_dir, exist_ok=True)

    hosts = [h.strip() for h in os.environ.get("ARTIFACTS_PR_HOSTS", "github.com").split(",") if h.strip()]
    repos = [r.strip() for r in os.environ.get("ARTIFACTS_PR_REPOS", "").split(",") if r.strip()]
    try:
        n_weeks = max(1, int(os.environ.get("ARTIFACTS_ACTIVITY_WEEKS", "12")))
    except ValueError:
        die("ARTIFACTS_ACTIVITY_WEEKS must be an integer")

    now = dt.datetime.now(dt.timezone.utc)
    this_monday = (now - dt.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    start = this_monday - dt.timedelta(weeks=n_weeks - 1)
    weeks = [(start + dt.timedelta(weeks=i)).date() for i in range(n_weeks)]
    scope = " ".join(f"repo:{r}" for r in repos)
    repo_ok = (lambda r: r in repos) if repos else (lambda r: True)

    prs, reviews = OrderedDict(), []
    for host in hosts:
        try:
            for q in (f"author:@me is:pr created:>={start:%Y-%m-%d} {scope}",
                      f"author:@me is:pr merged:>={start:%Y-%m-%d} {scope}"):
                for n in search(host, q.strip()):
                    n["_host"], n["_repo"] = host, n["repository"]["nameWithOwner"]
                    prs[(host, n["_repo"], n["number"])] = n
            for c in review_contributions(host, start, now):
                pr = c["pullRequest"]
                login = (pr.get("author") or {}).get("login") or ""
                repo = pr["repository"]["nameWithOwner"]
                if login.endswith("[bot]") or not repo_ok(repo):
                    continue
                c["_host"], c["_repo"] = host, repo
                reviews.append(c)
        except RuntimeError as err:
            die(f"{host}: {err}")
        print(f"{host}: {sum(1 for k in prs if k[0] == host)} PR(s), "
              f"{sum(1 for r in reviews if r['_host'] == host)} review(s)", file=sys.stderr)

    def week_of(ts):
        d = parse(ts)
        if not d or d < start:
            return None
        idx = (d - start).days // 7
        return idx if idx < n_weeks else None

    multi_host = len(hosts) > 1
    label = (lambda h, r: f"{h}/{r}") if multi_host else (lambda h, r: r)
    opened_w, merged_w, reviews_w = [0] * n_weeks, [0] * n_weeks, [0] * n_weeks
    per_repo = {}
    merged_list, ttm = [], []
    for pr in prs.values():
        key = label(pr["_host"], pr["_repo"])
        row = per_repo.setdefault(key, [0, 0, 0])
        wi = week_of(pr["createdAt"])
        if wi is not None:
            opened_w[wi] += 1
            row[0] += 1
        wm = week_of(pr["mergedAt"])
        if wm is not None:
            merged_w[wm] += 1
            row[1] += 1
            merged_list.append(pr)
            ttm.append((parse(pr["mergedAt"]) - parse(pr["createdAt"])).total_seconds() / 3600)
    for r in reviews:
        wr = week_of(r["occurredAt"])
        if wr is not None:
            reviews_w[wr] += 1
            per_repo.setdefault(label(r["_host"], r["_repo"]), [0, 0, 0])[2] += 1
    per_repo = {k: v for k, v in per_repo.items() if any(v)}

    opened, merged, given = sum(opened_w), sum(merged_w), sum(reviews_w)
    median = statistics.median(ttm) if ttm else None
    tiles = [("PRs opened", opened), ("PRs merged", merged), ("Median time to merge", fmt_duration(median)),
             ("Reviews given", given), ("Repos touched", len(per_repo))]
    tiles_html = "".join(f'<div class="stat-tile"><b>{esc(v)}</b><span>{esc(k)}</span></div>' for k, v in tiles)

    span = f"{weeks[0]:%b %-d, %Y} – {now:%b %-d, %Y}"
    chart1 = bar_chart(weeks, [("Opened", "s1", opened_w), ("Merged", "s2", merged_w)],
                       "Pull requests opened and merged per week",
                       f"Grouped bars per week from {span}: {opened} opened, {merged} merged.", "c1")
    chart2 = bar_chart(weeks, [("Reviews given", "s3", reviews_w)], "Reviews given per week",
                       f"Bars per week from {span}: {given} reviews given on others' pull requests.", "c2")
    data_rows = "".join(f'<tr><td>{wk:%Y-%m-%d}</td><td class="num">{o}</td><td class="num">{m}</td>'
                        f'<td class="num">{r}</td></tr>'
                        for wk, o, m, r in zip(weeks, opened_w, merged_w, reviews_w))
    table = (f'<details class="file-list"><summary>Weekly numbers as a table</summary>'
             f'<table class="data-table"><thead><tr><th>Week starting</th><th class="num">Opened</th>'
             f'<th class="num">Merged</th><th class="num">Reviews</th></tr></thead><tbody>{data_rows}</tbody></table></details>')

    repo_rows = "".join(f'<tr><td><code>{esc(k)}</code></td><td class="num">{o}</td><td class="num">{m}</td>'
                        f'<td class="num">{r}</td></tr>'
                        for k, (o, m, r) in sorted(per_repo.items(), key=lambda kv: (-sum(kv[1]), kv[0])))
    repo_table = (f'<table class="data-table"><thead><tr><th>Repository</th><th class="num">Opened</th>'
                  f'<th class="num">Merged</th><th class="num">Reviews</th></tr></thead><tbody>{repo_rows}</tbody></table>'
                  if per_repo else '<p class="muted">No activity in this window.</p>')

    merged_list.sort(key=lambda p: p["mergedAt"], reverse=True)
    merged_rows = "".join(
        f'<a class="recent-row" href="{esc(p["url"])}" target="_top"><span class="recent-title">'
        f'<span class="pr-num">{esc(label(p["_host"], p["_repo"]))}#{p["number"]}</span>{esc(p["title"])}</span>'
        f'<span class="recent-meta"><span class="recent-time">merged <time datetime="{esc(p["mergedAt"])}">'
        f'{esc(p["mergedAt"][:10])}</time></span></span></a>' for p in merged_list)
    merged_html = (f'<div class="recent-list">{merged_rows}</div>' if merged_list
                   else '<p class="muted">Nothing merged in this window.</p>')

    scope_note = f" · {esc(', '.join(repos))}" if repos else ""
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark"><title>PR Activity</title>
{THEME_BOOT}<link rel="stylesheet" href="../site.css"></head>
<body class="doc-page"><main class="content"><div class="inner">
<h1 class="doc-title">PR Activity</h1>
<p class="pr-meta"><span>Last {n_weeks} week{"s" if n_weeks != 1 else ""} ({esc(span)})</span><span>{esc(", ".join(hosts))}{scope_note}</span><span>rebuilt <time datetime="{now.isoformat(timespec="seconds")}">{now:%Y-%m-%d %H:%M} UTC</time></span></p>
<div class="stat-tiles">{tiles_html}</div>
<h2>Opened and merged per week</h2>
{chart1}
<h2>Reviews given per week</h2>
{chart2}
{table}
<h2>By repository</h2>
{repo_table}
<h2>Merged in this window</h2>
{merged_html}
<p class="muted page-foot">Reviews count each review you submitted on a pull request, excluding pull requests opened by bots.</p>
</div></main></body></html>
"""
    path = os.path.join(out_dir, "index.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(page)

    pub = os.path.join(os.path.dirname(os.path.abspath(__file__)), "publish.sh")
    print(f"wrote {path}\n")
    print("Publish with:")
    print(f'  {pub} publish {path} --slug pr-activity --title "PR Activity" --emoji 📈 --nav prs --no-open')


if __name__ == "__main__":
    main()
