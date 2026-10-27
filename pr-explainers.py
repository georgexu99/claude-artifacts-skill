#!/usr/bin/env python3
"""Build a PR explainers index plus one standalone page per pull request.

    pr-explainers.py <out dir>

Writes <out dir>/index.html and <out dir>/pr-<owner>-<repo>-<n>.html, then prints the
publish.sh commands that upload them. Every page links ../site.css, so publish the index
as a page (it lands at pr-explainers/page.html) and `put` the PR pages next to it.

Environment:
  ARTIFACTS_PR_HOSTS        comma list of GitHub hosts (default github.com)
  ARTIFACTS_PR_MERGED_DAYS  also include PRs merged in the last N days (default 30)
  ARTIFACTS_PR_REPOS        comma list of owner/repo to restrict to (default: all)
  ARTIFACTS_PR_QUERY        replace the default searches with this one search query
                            (e.g. "repo:cli/cli is:pr is:open"); REPOS still applies
"""

import datetime as dt
import html
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import OrderedDict

FILE_CAP = 100
COMMIT_CAP = 50
THEME_BOOT = ("<script>try{var t=localStorage.getItem('claude-artifacts-theme');"
              "if(t)document.documentElement.dataset.theme=t}catch(e){}</script>")
LOCAL_TIME = ("<script>document.querySelectorAll('time[datetime]').forEach(function(t){"
              "var d=new Date(t.getAttribute('datetime'));if(!isNaN(d))t.textContent="
              "d.toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'})})</script>")

STATE_COLORS = {"Draft": "#6b7280", "Open": "#1a7f37", "Merged": "#8250df", "Closed": "#cf222e"}
CI_COLORS = {"SUCCESS": "#1a7f37", "FAILURE": "#cf222e", "ERROR": "#cf222e",
             "PENDING": "#b45309", "EXPECTED": "#b45309", "NONE": "#6b7280"}
REVIEW_COLORS = {"APPROVED": "#1a7f37", "CHANGES_REQUESTED": "#cf222e",
                 "REVIEW_REQUIRED": "#b45309", "COMMENTED": "#6b7280", "DISMISSED": "#6b7280",
                 "PENDING": "#6b7280"}
FAILING = {"FAILURE", "ERROR", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE"}

SIGNED_IMG = re.compile(
    r"https://private-user-images\.githubusercontent\.com/\d+/\d+-"
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.[A-Za-z0-9]+\?jwt=[A-Za-z0-9._%-]+")

SEARCH_Q = """
query($q: String!, $after: String) {
  search(query: $q, type: ISSUE, first: 50, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes { ... on PullRequest { number repository { nameWithOwner } } }
  }
}"""

PR_Q = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      title url number state isDraft merged mergedAt createdAt updatedAt closedAt
      additions deletions changedFiles headRefName baseRefName headRefOid body
      author { login }
      reviewDecision
      labels(first: 30) { nodes { name color } }
      reviewRequests(first: 30) { nodes { requestedReviewer {
        __typename
        ... on User { login }
        ... on Bot { login }
        ... on Mannequin { login }
        ... on Team { slug organization { login } }
      } } }
      latestReviews(first: 50) { nodes { author { login } state submittedAt } }
      %CLOSING%
      last: commits(last: 1) { nodes { commit { statusCheckRollup {
        state
        contexts(first: 100) { nodes {
          __typename
          ... on CheckRun { name conclusion status }
          ... on StatusContext { context state }
        } }
      } } } }
      commits(first: %COMMITS%) { totalCount nodes { commit { abbreviatedOid messageHeadline } } }
      files(first: %FILES%) { totalCount nodes { path additions deletions } }
    }
  }
}""".replace("%COMMITS%", str(COMMIT_CAP)).replace("%FILES%", str(FILE_CAP))
CLOSING = "closingIssuesReferences(first: 20) { nodes { number title url state } }"


def die(msg):
    sys.exit(f"error: {msg}")


def gh(host, args, body=None):
    cmd = ["gh", "api", "--hostname", host] + args
    tmp = None
    if body is not None:
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump(body, tmp)
        tmp.close()
        cmd += ["--input", tmp.name]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
    finally:
        if tmp:
            os.unlink(tmp.name)
    if res.returncode != 0:
        raise RuntimeError((res.stderr or res.stdout).strip() or f"gh api {' '.join(args)} failed")
    return res.stdout


def graphql(host, query, variables):
    out = json.loads(gh(host, ["graphql"], {"query": query, "variables": variables}) or "{}")
    if out.get("errors") and not out.get("data"):
        raise RuntimeError("; ".join(e.get("message", "") for e in out["errors"]))
    return out.get("data") or {}


def search(host, query):
    found, after = [], None
    while True:
        page = graphql(host, SEARCH_Q, {"q": query, "after": after})["search"]
        found += [n for n in page["nodes"] if n]
        if not page["pageInfo"]["hasNextPage"]:
            return found
        after = page["pageInfo"]["endCursor"]


def fetch_pr(host, repo, number):
    owner, name = repo.split("/", 1)
    variables = {"owner": owner, "name": name, "number": number}
    try:
        data = graphql(host, PR_Q.replace("%CLOSING%", CLOSING), variables)
    except RuntimeError as err:
        # Older GitHub Enterprise servers lack closingIssuesReferences.
        if "closingIssuesReferences" not in str(err):
            raise
        data = graphql(host, PR_Q.replace("%CLOSING%", ""), variables)
    pr = (data.get("repository") or {}).get("pullRequest")
    if pr:
        pr["_host"], pr["_repo"] = host, repo
    return pr


def render_body(host, repo, body):
    if not (body or "").strip():
        return '<p class="muted">(No description)</p>'
    try:
        out = gh(host, ["-X", "POST", "markdown"], {"text": body, "mode": "gfm", "context": repo})
    except RuntimeError as err:
        print(f"warning: markdown render failed for {repo}: {err}", file=sys.stderr)
        out = f"<pre>{html.escape(body)}</pre>"
    return SIGNED_IMG.sub(lambda m: f"https://github.com/user-attachments/assets/{m.group(1)}", out)


def esc(s):
    return html.escape(str(s if s is not None else ""))


def iso(ts):
    return ts.replace("+00:00", "Z") if ts else ""


def time_tag(ts):
    if not ts:
        return ""
    return f'<time datetime="{esc(iso(ts))}">{esc(ts[:16].replace("T", " "))} UTC</time>'


def pill(label, color, title=None):
    t = f' title="{esc(title)}"' if title else ""
    return f'<span class="state-pill" style="--state:{color}"{t}>{esc(label)}</span>'


def pr_state(pr):
    if pr["merged"]:
        return "Merged"
    if pr["state"] == "CLOSED":
        return "Closed"
    return "Draft" if pr["isDraft"] else "Open"


def ci_info(pr):
    nodes = pr["last"]["nodes"]
    rollup = nodes[0]["commit"]["statusCheckRollup"] if nodes else None
    if not rollup:
        return "NONE", []
    failing = []
    for c in rollup["contexts"]["nodes"]:
        if c["__typename"] == "CheckRun" and (c.get("conclusion") or "") in FAILING:
            failing.append(c["name"])
        elif c["__typename"] == "StatusContext" and c.get("state") in ("FAILURE", "ERROR"):
            failing.append(c["context"])
    return rollup["state"], failing


def reviews(pr):
    author = (pr.get("author") or {}).get("login")
    out = OrderedDict()
    for r in pr["latestReviews"]["nodes"]:
        login = (r.get("author") or {}).get("login") or "ghost"
        if login != author:
            out[login] = r
    return out


def requested(pr):
    names = []
    for n in pr["reviewRequests"]["nodes"]:
        r = n.get("requestedReviewer") or {}
        if r.get("__typename") == "Team":
            names.append(f"{r['organization']['login']}/{r['slug']}")
        elif r.get("login"):
            names.append(r["login"])
    return names


def review_label(pr):
    decision = pr.get("reviewDecision")
    if decision:
        return decision
    states = {r["state"] for r in reviews(pr).values()}
    for s in ("CHANGES_REQUESTED", "APPROVED", "COMMENTED"):
        if s in states:
            return s
    return None


def nice(s):
    return s.replace("_", " ").capitalize() if s else ""


def page_name(pr):
    owner, name = pr["_repo"].split("/", 1)
    return f"pr-{owner}-{name}-{pr['number']}.html".lower()


def head(title):
    return ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<meta name="color-scheme" content="light dark"><title>{esc(title)}</title>'
            f'{THEME_BOOT}<link rel="stylesheet" href="../site.css"></head>'
            '<body class="doc-page"><main class="content"><div class="inner">\n')


FOOT = f"\n</div></main>{LOCAL_TIME}</body></html>\n"


def fact(label, value):
    return f"<dt>{esc(label)}</dt><dd>{value}</dd>" if value else ""


def pr_page(pr, body_html, generated):
    state = pr_state(pr)
    ci, failing = ci_info(pr)
    revs = reviews(pr)
    req = requested(pr)
    decision = review_label(pr)

    meta = " ".join([
        pill(state, STATE_COLORS[state]),
        f'<a href="{esc(pr["url"])}">{esc(pr["_repo"])}#{pr["number"]}</a>',
        f'<span class="adds">+{pr["additions"]:,}</span> <span class="dels">−{pr["deletions"]:,}</span>',
        f'<span>{pr["changedFiles"]} file{"s" if pr["changedFiles"] != 1 else ""}</span>',
        f'<code>{esc(pr["headRefOid"][:10])}</code>',
        f'<span>updated {time_tag(pr["updatedAt"])}</span>',
    ])

    review_html = ""
    if decision:
        review_html = pill(nice(decision), REVIEW_COLORS.get(decision, "#6b7280"))
    if revs:
        review_html += "<ul class=\"fact-list\">" + "".join(
            f'<li>{pill(nice(r["state"]), REVIEW_COLORS.get(r["state"], "#6b7280"))} '
            f'{esc(login)} <span class="muted">{time_tag(r.get("submittedAt"))}</span></li>'
            for login, r in revs.items()) + "</ul>"
    ci_html = ""
    if ci != "NONE" or not pr["merged"]:
        ci_html = pill(nice(ci) if ci != "NONE" else "No checks", CI_COLORS.get(ci, "#6b7280"))
        if failing:
            ci_html += f' <span class="muted">failing:</span> ' + ", ".join(
                f"<code>{esc(n)}</code>" for n in failing[:15])
            if len(failing) > 15:
                ci_html += f" and {len(failing) - 15} more"
    labels = " ".join(f'<span class="label-chip" style="--state:#{esc(l["color"] or "6b7280")}">'
                      f'{esc(l["name"])}</span>' for l in pr["labels"]["nodes"])
    issues = ", ".join(
        f'<a href="{esc(i["url"])}">#{i["number"]}</a> {esc(i["title"])}'
        for i in (pr.get("closingIssuesReferences") or {}).get("nodes", []))
    dates = f'created {time_tag(pr["createdAt"])}'
    if pr["mergedAt"]:
        dates += f' · merged {time_tag(pr["mergedAt"])}'
    elif pr["closedAt"]:
        dates += f' · closed {time_tag(pr["closedAt"])}'

    facts = "".join([
        fact("Review", review_html or '<span class="muted">No reviews yet</span>'),
        fact("Requested", ", ".join(esc(r) for r in req)),
        fact("CI", ci_html),
        fact("Branches", f'<code>{esc(pr["baseRefName"])}</code> ← <code>{esc(pr["headRefName"])}</code>'),
        fact("Labels", labels),
        fact("Closes", issues),
        fact("Dates", dates),
    ])

    files = pr["files"]["nodes"]
    groups = OrderedDict()
    for f in sorted(files, key=lambda f: f["path"]):
        top = f["path"].split("/", 1)[0] if "/" in f["path"] else "(root)"
        g = groups.setdefault(top, [0, 0, 0])
        g[0] += 1
        g[1] += f["additions"]
        g[2] += f["deletions"]
    rows = "".join(
        f'<tr><td><code>{esc(d)}</code></td><td class="num">{n}</td>'
        f'<td class="num adds">+{a:,}</td><td class="num dels">−{x:,}</td></tr>'
        for d, (n, a, x) in sorted(groups.items(), key=lambda kv: -(kv[1][1] + kv[1][2])))
    file_rows = "".join(
        f'<li><code>{esc(f["path"])}</code> <span class="adds">+{f["additions"]}</span> '
        f'<span class="dels">−{f["deletions"]}</span></li>' for f in sorted(files, key=lambda f: f["path"]))
    total_files = pr["files"]["totalCount"]
    cap_note = (f'<p class="muted">Showing the first {len(files)} of {total_files} files; '
                f'<a href="{esc(pr["url"])}/files">see all on GitHub</a>.</p>'
                if total_files > len(files) else "")
    changed = (f'<table class="data-table"><thead><tr><th>Directory</th><th class="num">Files</th>'
               f'<th class="num">Added</th><th class="num">Removed</th></tr></thead><tbody>{rows}</tbody></table>'
               f'{cap_note}<details class="file-list"><summary>All files ({len(files)})</summary>'
               f'<ul>{file_rows}</ul></details>') if files else '<p class="muted">No file changes.</p>'

    commits = pr["commits"]["nodes"]
    commit_note = ""
    if pr["commits"]["totalCount"] > len(commits):
        commit_note = f'<p class="muted">First {len(commits)} of {pr["commits"]["totalCount"]} commits.</p>'
    commit_html = "".join(
        f'<li><code>{esc(c["commit"]["abbreviatedOid"])}</code> {esc(c["commit"]["messageHeadline"])}</li>'
        for c in commits)

    return "".join([
        head(f'{pr["title"]} · {pr["_repo"]}#{pr["number"]}'),
        '<a class="backlink" href="./" target="_top">← All PR explainers</a>\n',
        f'<h1 class="doc-title">{esc(pr["title"])}</h1>\n',
        f'<div class="pr-meta">{meta}</div>\n',
        f'<h2>At a glance</h2><dl class="facts">{facts}</dl>\n',
        f'<h2>What changed</h2>{changed}\n',
        f'<h2>Commits</h2><ol class="commit-list">{commit_html}</ol>{commit_note}\n',
        f'<h2>Description</h2><div class="pr-body markdown-body">{body_html}</div>\n',
        f'<p class="muted page-foot">Snapshot rebuilt {time_tag(generated)}.</p>',
        FOOT,
    ])


def index_page(prs, generated, window):
    by_repo = OrderedDict()
    for pr in sorted(prs, key=lambda p: (p["_host"] != "github.com", p["_host"], p["_repo"].lower(), -p["number"])):
        key = pr["_repo"] if pr["_host"] == "github.com" else f'{pr["_host"]}/{pr["_repo"]}'
        by_repo.setdefault(key, []).append(pr)
    sections = []
    for repo, items in by_repo.items():
        rows = []
        for pr in items:
            state = pr_state(pr)
            ci, failing = ci_info(pr)
            decision = review_label(pr)
            mini = []
            if decision:
                mini.append(pill(nice(decision), REVIEW_COLORS.get(decision, "#6b7280")))
            if ci != "NONE":
                mini.append(pill("CI " + nice(ci).lower(), CI_COLORS.get(ci, "#6b7280"),
                                 ", ".join(failing) if failing else None))
            rows.append(
                f'<a class="recent-row" href="{esc(page_name(pr))}" target="_top">'
                f'<span class="recent-title">{pill(state, STATE_COLORS[state])}'
                f'<span class="pr-num">#{pr["number"]}</span>{esc(pr["title"])}</span>'
                f'<span class="recent-meta">{"".join(mini)}'
                f'<span class="recent-time">as of {time_tag(pr["updatedAt"])}</span></span></a>')
        sections.append(f'<h2 class="cat-heading"><span class="badge">📦</span>{esc(repo)}'
                        f'<span class="count">{len(items)}</span></h2>'
                        f'<div class="recent-list">{"".join(rows)}</div>')
    empty = '<p class="muted">No pull requests matched.</p>'
    return "".join([
        head("PR Explainers"),
        '<h1 class="doc-title">PR Explainers</h1>\n',
        f'<p class="pr-meta"><span>{len(prs)} pull request{"s" if len(prs) != 1 else ""}</span>'
        f'<span>{esc(window)}</span><span>rebuilt {time_tag(generated)}</span></p>\n',
        "\n".join(sections) or empty,
        FOOT,
    ])


def env_list(name, default=""):
    return [x.strip() for x in os.environ.get(name, default).split(",") if x.strip()]


def main():
    if len(sys.argv) != 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__.strip())
        sys.exit(0 if len(sys.argv) == 2 else 2)
    out_dir = os.path.abspath(sys.argv[1])
    os.makedirs(out_dir, exist_ok=True)
    for old in os.listdir(out_dir):
        if old.startswith("pr-") and old.endswith(".html"):
            os.unlink(os.path.join(out_dir, old))

    hosts = env_list("ARTIFACTS_PR_HOSTS", "github.com")
    repos = env_list("ARTIFACTS_PR_REPOS")
    custom = os.environ.get("ARTIFACTS_PR_QUERY", "").strip()
    try:
        days = int(os.environ.get("ARTIFACTS_PR_MERGED_DAYS", "30"))
    except ValueError:
        die("ARTIFACTS_PR_MERGED_DAYS must be an integer")
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    scope = " ".join(f"repo:{r}" for r in repos)
    if custom:
        queries = [f"{custom} {scope}".strip()]
        window = f"query: {custom}"
    else:
        queries = [f"is:pr author:@me is:open {scope}".strip()]
        if days > 0:
            queries.append(f"is:pr author:@me is:merged merged:>={since} {scope}".strip())
        window = f"open, plus merged in the last {days} days" if days > 0 else "open"
    if repos:
        window += " · " + ", ".join(repos)

    generated = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    prs = []
    for host in hosts:
        seen = OrderedDict()
        for q in queries:
            try:
                for n in search(host, q):
                    seen[(n["repository"]["nameWithOwner"], n["number"])] = True
            except RuntimeError as err:
                die(f"search on {host} failed ({q}): {err}")
        print(f"{host}: {len(seen)} pull request(s)", file=sys.stderr)
        for repo, number in seen:
            try:
                pr = fetch_pr(host, repo, number)
            except RuntimeError as err:
                print(f"warning: skipping {repo}#{number}: {err}", file=sys.stderr)
                continue
            if not pr:
                continue
            body = render_body(host, repo, pr.get("body"))
            with open(os.path.join(out_dir, page_name(pr)), "w", encoding="utf-8") as fh:
                fh.write(pr_page(pr, body, generated))
            prs.append(pr)

    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(index_page(prs, generated, window))

    here = os.path.dirname(os.path.abspath(__file__))
    pub = os.path.join(here, "publish.sh")
    print(f"wrote {len(prs)} PR page(s) + index.html to {out_dir}\n")
    print("Publish with:")
    print(f'  {pub} publish {out_dir}/index.html --slug pr-explainers --title "PR Explainers" --emoji 💡 --nav prs --no-open')
    print(f'  for f in {out_dir}/pr-*.html; do {pub} put "pr-explainers/$(basename "$f")" "$f"; done')


if __name__ == "__main__":
    main()
