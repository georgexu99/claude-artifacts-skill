#!/usr/bin/env bash
#
# Mirror a self-contained HTML page to your own GitHub Pages site.
#
#   publish.sh init                       # one time: create the repo, gh-pages branch and Pages site
#   publish.sh publish <file> --title "T" [--slug s] [--emoji e] [--summary s]
#                            [--project p] [--group "🧪 Topic"] [--state Open|Waiting|Done|Dropped]
#                            [--next "one line"] [--nav monitoring|prs] [--claude-url u] [--no-open] [--force]
#   publish.sh set <slug> [--title ..] [--group ..] [--state ..] [--next ..] [--nav ..] [--summary ..] [--touch]
#   publish.sh put <repo-path> <file>   # one extra file next to a page (e.g. reports/detail.html)
#   publish.sh list
#   publish.sh rm <slug>
#   publish.sh rebuild            # re-push site chrome + every slug's shell
#
# Manifest fields: group is the topic the gallery and sidebar group by, state drives the
# dots/pills/"come back to" rail, next is the one-liner on open cards, nav lifts a page
# into the Monitoring or Pull requests sidebar section instead of a group.
#
# Each slug is <slug>/page.html (the artifact, untouched) behind <slug>/index.html
# (a shell that adds the project sidebar, rendered at load time from manifest.json).
# Pages are readable by anyone who can see the Pages site: on github.com that is the
# public internet unless the repo is private on a paid plan. There is no per-page ACL,
# which is why the secret scan is not optional.
#
# Environment:
#   ARTIFACTS_GH_HOST   GitHub host (default github.com; set to your GHE host otherwise)
#   ARTIFACTS_OWNER     repo owner (default: the authenticated gh user on that host)
#   ARTIFACTS_REPO      repo name (default claude-artifacts)
#   ARTIFACTS_PRIVATE   1 = `init` creates a private repo
#   ARTIFACTS_TITLE     site title (default "Claude Artifacts")
#   ARTIFACTS_SUBTITLE  site subtitle (default "Pages from my Claude Code sessions")
#   ARTIFACTS_SKILL_URL link to this skill's repo, shown in the gallery's replicate prompt

set -euo pipefail

HOST="${ARTIFACTS_GH_HOST:-github.com}"
REPO="${ARTIFACTS_REPO:-claude-artifacts}"
BRANCH=gh-pages
SITE_TITLE="${ARTIFACTS_TITLE:-Claude Artifacts}"
SITE_SUBTITLE="${ARTIFACTS_SUBTITLE:-Pages from my Claude Code sessions}"
SKILL_URL="${ARTIFACTS_SKILL_URL:-https://github.com/georgexu99/claude-artifacts-skill}"
OWNER="" API="" SITE=""

die() { printf 'error: %s\n' "$*" >&2; exit 1; }
note() { printf '%s\n' "$*" >&2; }

need() { command -v "$1" >/dev/null 2>&1 || die "$1 is required but not on PATH"; }

api() { gh api --hostname "$HOST" "$@"; }

# Resolved lazily so a usage error never needs the network.
resolve() {
  need gh
  need python3
  OWNER="${ARTIFACTS_OWNER:-}"
  if [ -z "$OWNER" ]; then
    OWNER=$(api user --jq .login 2>/dev/null) || die "gh is not authenticated for $HOST; run: gh auth login --hostname $HOST"
  fi
  [ -n "$OWNER" ] || die "could not determine the repo owner; set ARTIFACTS_OWNER"
  API="/repos/$OWNER/$REPO"
  if [ "$HOST" = github.com ]; then
    SITE="https://$OWNER.github.io/$REPO"
  else
    SITE="https://pages.$HOST/$OWNER/$REPO"
  fi
}

require_repo() {
  api "$API" --jq .full_name >/dev/null 2>&1 || die "$OWNER/$REPO not found on $HOST; run: publish.sh init"
}

# `gh api` prints a 404 body to stdout even under --jq; gate on exit status.
remote_sha() {
  local out
  if out=$(api "$API/contents/$1?ref=$BRANCH" --jq '.sha // empty' 2>/dev/null); then
    printf '%s' "$out"
  fi
}

blob_sha() {
  python3 -c 'import hashlib,sys;b=open(sys.argv[1],"rb").read();print(hashlib.sha1(b"blob %d\0"%len(b)+b).hexdigest())' "$1"
}

# Body goes through a temp file, never argv: a large page blows past ARG_MAX.
put_file() {
  local repo_path="$1" local_file="$2" message="$3"
  local sha payload
  sha=$(remote_sha "$repo_path")
  if [ -n "$sha" ] && [ "$sha" = "$(blob_sha "$local_file")" ]; then
    echo unchanged; return 0
  fi
  payload=$(mktemp "${TMPDIR:-/tmp}/artifact-put.XXXXXX")
  python3 - "$local_file" "$message" "$BRANCH" "$sha" >"$payload" <<'PY'
import base64, json, sys
path, message, branch, sha = sys.argv[1:5]
with open(path, 'rb') as fh:
    body = {
        "message": message,
        "branch": branch,
        "content": base64.b64encode(fh.read()).decode("ascii"),
    }
if sha:
    body["sha"] = sha
json.dump(body, sys.stdout)
PY
  api -X PUT "$API/contents/$repo_path" --input "$payload" --jq '.content.sha[0:8]' >/dev/null
  rm -f "$payload"
  [ -n "$sha" ] && echo updated || echo created
}

fetch_manifest() {
  local out
  if out=$(api "$API/contents/manifest.json?ref=$BRANCH" --jq '.content // empty' 2>/dev/null) \
     && [ -n "$out" ]; then
    printf '%s' "$out" | base64 -d 2>/dev/null && return 0
  fi
  echo '[]'
}

# -E, not GNU `\+`: BSD sed treats `\+` as a literal plus.
slugify() {
  printf '%s' "$1" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E -e 's/[^a-z0-9]+/-/g' -e 's/^-+//' -e 's/-+$//' \
    | cut -c1-60
}

# Everything published is readable by anyone who can see the site, so scan before, not after.
scan_secrets() {
  local file="$1" hits
  hits=$(grep -nEo 'xox[abposr]-[A-Za-z0-9-]{8,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}' "$file" \
    | cut -d: -f1 | sort -un | tr '\n' ' ' || true)
  if [ -n "$hits" ]; then
    note "Possible credential on line(s): $hits"
    note "Every published page is readable by anyone who can see $SITE/."
    die "refusing to publish; remove it, or pass --force if this is a false positive"
  fi
}

SITE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/site"
[ -d "$SITE_DIR" ] || die "site templates not found at $SITE_DIR"

# Fills {{SITE_TITLE}}, {{SITE_SUBTITLE}}, {{SKILL_URL}} and any extra NAME=value pairs.
render() {
  python3 - "$@" <<'PY'
import html, sys
tpl, pairs = sys.argv[1], sys.argv[2:]
out = open(tpl, encoding="utf-8").read()
for pair in pairs:
    key, _, val = pair.partition("=")
    raw = key.startswith("raw:")
    key = key[4:] if raw else key
    out = out.replace("{{" + key + "}}", val if raw else html.escape(val))
sys.stdout.write(out)
PY
}

brand_pairs() {
  printf '%s\n' "SITE_TITLE=$SITE_TITLE" "SITE_SUBTITLE=$SITE_SUBTITLE" "SKILL_URL=$SKILL_URL"
}

# Pushes the shared chrome (only files whose content changed) and seeds .nojekyll.
# The gallery and every shell render themselves from manifest.json at load time.
publish_site() {
  local gallery line pairs=()
  while IFS= read -r line; do pairs+=("$line"); done < <(brand_pairs)
  gallery=$(mktemp "${TMPDIR:-/tmp}/artifact-gallery.XXXXXX")
  render "$SITE_DIR/gallery.html" "${pairs[@]}" >"$gallery"
  put_file site.css "$SITE_DIR/site.css" "Update site.css" >/dev/null
  put_file site.js "$SITE_DIR/site.js" "Update site.js" >/dev/null
  put_file index.html "$gallery" "Update gallery" >/dev/null
  rm -f "$gallery"
  if [ -z "$(remote_sha .nojekyll)" ]; then
    local empty
    empty=$(mktemp "${TMPDIR:-/tmp}/artifact-nojekyll.XXXXXX")
    put_file .nojekyll "$empty" "Add .nojekyll" >/dev/null
    rm -f "$empty"
  fi
}

# claude.ai's wrapper supplies the doctype and charset; on Pages a bare artifact
# renders in quirks mode as Latin-1 ("·" becomes "Â·"). Doctype must come first.
normalize_page() {
  local head
  head=$(head -c 2048 "$1")
  printf '%s' "$head" | grep -qi '<!doctype' || printf '<!doctype html>\n'
  printf '%s' "$head" | grep -qi 'charset' || printf '<meta charset="utf-8">\n'
  cat "$1"
}

# <slug>/index.html: the sidebar shell around page.html.
put_shell() {
  local slug="$1" title="$2" page="$3" out line pairs=()
  while IFS= read -r line; do pairs+=("$line"); done < <(brand_pairs)
  out=$(mktemp "${TMPDIR:-/tmp}/artifact-shell.XXXXXX")
  render "$SITE_DIR/shell.html" "${pairs[@]}" "TITLE=$title" "raw:PAGE=$page" >"$out"
  put_file "$slug/index.html" "$out" "Shell $slug"
  rm -f "$out"
}

wait_for_build() {
  local i status
  for i in $(seq 1 30); do
    status=$(api "$API/pages/builds/latest" --jq '.status // "pending"' 2>/dev/null || echo pending)
    case "$status" in
      built) return 0 ;;
      errored)
        note "Pages build errored: $(api "$API/pages/builds/latest" --jq '.error.message // "unknown"')"
        return 1 ;;
    esac
    sleep 3
  done
  note "Pages build still $status after 90s; the page may lag."
  return 0
}

# One time: repo (public unless ARTIFACTS_PRIVATE=1), gh-pages as default branch,
# .nojekyll, and Pages serving gh-pages from /. Safe to re-run.
cmd_init() {
  local private=false
  [ "${ARTIFACTS_PRIVATE:-0}" = 1 ] && private=true
  if api "$API" --jq .full_name >/dev/null 2>&1; then
    note "repo $OWNER/$REPO exists"
  else
    local endpoint=user/repos
    [ "$OWNER" = "$(api user --jq .login)" ] || endpoint="orgs/$OWNER/repos"
    api -X POST "$endpoint" -f name="$REPO" -F private="$private" -F auto_init=true \
      -f description="Claude artifacts mirrored to Pages" --jq .full_name >/dev/null
    note "created $OWNER/$REPO (private=$private)"
  fi
  if ! api "$API/git/ref/heads/$BRANCH" --jq .object.sha >/dev/null 2>&1; then
    local base head
    base=$(api "$API" --jq .default_branch)
    head=$(api "$API/git/ref/heads/$base" --jq .object.sha)
    api -X POST "$API/git/refs" -f ref="refs/heads/$BRANCH" -f sha="$head" >/dev/null
    note "created branch $BRANCH"
  fi
  api -X PATCH "$API" -f default_branch="$BRANCH" >/dev/null
  if [ -z "$(remote_sha .nojekyll)" ]; then
    local empty
    empty=$(mktemp "${TMPDIR:-/tmp}/artifact-nojekyll.XXXXXX")
    put_file .nojekyll "$empty" "Add .nojekyll" >/dev/null
    rm -f "$empty"
  fi
  if api "$API/pages" --jq .html_url >/dev/null 2>&1; then
    note "Pages already enabled"
  elif api -X POST "$API/pages" -f 'source[branch]'="$BRANCH" -f 'source[path]=/' >/dev/null 2>&1; then
    note "enabled Pages from $BRANCH /"
  else
    note "could not enable Pages; switch it on under Settings -> Pages (branch $BRANCH, folder /)."
    [ "$private" = true ] && [ "$HOST" = github.com ] && note "Pages on a private github.com repo needs a paid plan."
  fi
  publish_site
  printf 'site  %s/\n' "$SITE"
}

cmd_publish() {
  local file="" title="" slug="" emoji="" project="" summary="" claude_url="" group="" state="" next="" nav="" open_after=1 force=0
  file="${1:-}"; shift || true
  [ -n "$file" ] || die "usage: publish.sh publish <file> --title \"T\""
  [ -f "$file" ] || die "no such file: $file"

  while [ $# -gt 0 ]; do
    case "$1" in
      --title)      title="${2:-}"; shift 2 ;;
      --slug)       slug="${2:-}"; shift 2 ;;
      --emoji)      emoji="${2:-}"; shift 2 ;;
      --project)    project="${2:-}"; shift 2 ;;
      --summary)    summary="${2:-}"; shift 2 ;;
      --claude-url) claude_url="${2:-}"; shift 2 ;;
      --group)      group="${2:-}"; shift 2 ;;
      --state)      state="${2:-}"; shift 2 ;;
      --next)       next="${2:-}"; shift 2 ;;
      --nav)        nav="${2:-}"; shift 2 ;;
      --no-open)    open_after=0; shift ;;
      --force)      force=1; shift ;;
      *) die "unknown flag: $1" ;;
    esac
  done

  [ -n "$title" ] || die "--title is required"

  case "$file" in
    *.html|*.htm) : ;;
    *) die "only .html or .htm can be published (got: $file)" ;;
  esac

  [ "$force" -eq 1 ] || scan_secrets "$file"

  if grep -q 'window\.claude' "$file"; then
    note "warning: page calls window.claude.*, which does not exist on Pages; those parts will be dead"
  fi

  local bytes
  bytes=$(wc -c <"$file" | tr -d ' ')
  [ "$bytes" -lt 20971520 ] || die "page is ${bytes} bytes; keep it under 20 MiB"

  [ -n "$slug" ] || slug=$(slugify "$title")
  [ -n "$slug" ] || die "could not derive a slug from --title; pass --slug"

  require_repo

  local fixed action
  fixed=$(mktemp "${TMPDIR:-/tmp}/artifact-page.XXXXXX")
  normalize_page "$file" >"$fixed"
  action=$(put_file "$slug/page.html" "$fixed" "Publish $slug")
  rm -f "$fixed"
  put_shell "$slug" "$title" page.html >/dev/null

  # Manifest carries the gallery's ordering and labels; created survives updates.
  local manifest count
  manifest=$(mktemp "${TMPDIR:-/tmp}/artifact-manifest.XXXXXX")
  fetch_manifest >"$manifest"
  count=$(python3 - "$manifest" "$slug" "$title" "$emoji" "$project" "$summary" "$claude_url" "$group" "$state" "$next" "$nav" <<'PY'
import json, sys, datetime
src, slug, title, emoji, project, summary, claude_url, group, state, nxt, nav = sys.argv[1:12]
try:
    with open(src) as fh:
        items = json.load(fh)
    if not isinstance(items, list):
        items = []
except Exception:
    items = []
now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
prev = next((i for i in items if i.get("slug") == slug), {})
entry = {k: v for k, v in prev.items()}
entry.update({"slug": slug, "title": title, "updated": now, "created": prev.get("created", now)})
for key, val in (("emoji", emoji), ("project", project), ("summary", summary), ("claude_url", claude_url),
                 ("group", group), ("state", state), ("next", nxt), ("nav", nav)):
    if val:
        entry[key] = val
items = [i for i in items if i.get("slug") != slug] + [entry]
items.sort(key=lambda i: i.get("updated", ""), reverse=True)
with open(src, "w") as fh:
    json.dump(items, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
print(len(items))
PY
)
  put_file manifest.json "$manifest" "Index $slug" >/dev/null
  publish_site
  rm -f "$manifest"

  wait_for_build || true

  local url="$SITE/$slug/"
  printf '\n%s  %s\n' "$action" "$url"
  printf 'gallery  %s/  (%s listed)\n' "$SITE" "$count"

  if [ "$open_after" -eq 1 ] && [ "${CLAUDE_CODE_ARTIFACT_AUTO_OPEN:-1}" != "0" ]; then
    command -v open >/dev/null 2>&1 && open "$url" || true
  fi
}

cmd_list() {
  fetch_manifest | python3 -c '
import json, sys
items = json.load(sys.stdin)
if not items:
    print("no artifacts published yet")
    sys.exit()
w = max(len(i.get("slug", "")) for i in items)
for i in items:
    where = i.get("nav") and ("[" + i["nav"] + "]") or i.get("group", "")
    print(i.get("slug", "").ljust(w), i.get("updated", "")[:10], (i.get("state") or "Open").ljust(7), i.get("title", ""), "·", where, sep="  ")
'
}

# Metadata only: no page upload, and `updated` stays put unless --touch.
cmd_set() {
  local slug="${1:-}"; shift || true
  [ -n "$slug" ] || die "usage: publish.sh set <slug> --state Done [--next ..] [--group ..] [--nav ..] [--title ..] [--summary ..] [--touch]"
  local kv=() touch=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --title|--emoji|--project|--summary|--claude-url|--group|--state|--next|--nav)
        kv+=("${1#--}=${2:-}"); shift 2 ;;
      --touch) touch=1; shift ;;
      *) die "unknown flag: $1" ;;
    esac
  done
  local manifest
  manifest=$(mktemp "${TMPDIR:-/tmp}/artifact-manifest.XXXXXX")
  fetch_manifest >"$manifest"
  python3 - "$manifest" "$slug" "$touch" "${kv[@]+"${kv[@]}"}" <<'PY'
import json, sys, datetime
src, slug, touch = sys.argv[1:4]
with open(src) as fh:
    items = json.load(fh)
entry = next((i for i in items if i.get("slug") == slug), None)
if entry is None:
    sys.exit(f"no such slug: {slug}")
for pair in sys.argv[4:]:
    key, _, val = pair.partition("=")
    key = key.replace("-", "_")
    if val == "":
        entry.pop(key, None)
    else:
        entry[key] = val
if touch == "1":
    entry["updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
items.sort(key=lambda i: i.get("updated", ""), reverse=True)
with open(src, "w") as fh:
    json.dump(items, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
print(json.dumps({k: entry.get(k) for k in ("slug", "group", "state", "next", "nav")}, ensure_ascii=False))
PY
  put_file manifest.json "$manifest" "Set $slug" >/dev/null
  rm -f "$manifest"
}

# One extra file under the site, e.g. a detail page a published page links to. Same secret scan as publish.
cmd_put() {
  local repo_path="${1:-}" file="${2:-}"
  [ -n "$repo_path" ] && [ -f "$file" ] || die "usage: publish.sh put <repo-path> <file>"
  scan_secrets "$file"
  printf '%-10s %s/%s\n' "$(put_file "$repo_path" "$file" "Put $repo_path")" "$SITE" "$repo_path"
}

cmd_rm() {
  local slug="${1:-}"
  [ -n "$slug" ] || die "usage: publish.sh rm <slug>"

  local removed=0 path sha
  for path in "$slug/page.html" "$slug/index.html"; do
    sha=$(remote_sha "$path")
    if [ -n "$sha" ]; then
      api -X DELETE "$API/contents/$path" \
        -f message="Remove $slug" -f branch="$BRANCH" -f sha="$sha" >/dev/null
      removed=1
    fi
  done
  [ "$removed" -eq 1 ] || die "nothing published under slug: $slug"

  local manifest
  manifest=$(mktemp "${TMPDIR:-/tmp}/artifact-manifest.XXXXXX")
  fetch_manifest >"$manifest"
  python3 - "$manifest" "$slug" <<'PY'
import json, sys
src, slug = sys.argv[1:3]
with open(src) as fh:
    items = json.load(fh)
items = [i for i in items if i.get("slug") != slug]
with open(src, "w") as fh:
    json.dump(items, fh, indent=2, ensure_ascii=False)
    fh.write("\n")
PY
  put_file manifest.json "$manifest" "Unindex $slug" >/dev/null
  rm -f "$manifest"
  wait_for_build || true
  printf 'removed  %s\n' "$slug"
}

# Re-pushes the chrome, re-normalises every page.html and rewrites every shell.
# Also migrates pre-sidebar slugs, whose artifact still sits at <slug>/index.html.
cmd_rebuild() {
  require_repo
  publish_site
  local slug title src raw fixed
  while IFS=$'\t' read -r slug title; do
    src="$slug/page.html"
    if [ -z "$(remote_sha "$src")" ]; then
      src="$slug/index.html"
      if [ -z "$(remote_sha "$src")" ]; then note "$slug: nothing published under it"; continue; fi
    fi
    raw=$(mktemp "${TMPDIR:-/tmp}/artifact-raw.XXXXXX")
    fixed=$(mktemp "${TMPDIR:-/tmp}/artifact-fixed.XXXXXX")
    api "$API/contents/$src?ref=$BRANCH" --jq .content | base64 -d >"$raw"
    if grep -q 'claude-artifacts shell' "$raw"; then
      note "$slug: shell present but page.html missing; re-publish it"; rm -f "$raw" "$fixed"; continue
    fi
    normalize_page "$raw" >"$fixed"
    put_file "$slug/page.html" "$fixed" "Normalize $slug" >/dev/null
    rm -f "$raw" "$fixed"
    printf '%-10s %s\n' "$(put_shell "$slug" "$title" page.html)" "$SITE/$slug/"
  done < <(fetch_manifest | python3 -c '
import json, sys
for i in json.load(sys.stdin):
    print(i["slug"], i.get("title", i["slug"]), sep="\t")
')
  wait_for_build || true
  printf 'gallery  %s/\n' "$SITE"
}

case "${1:-}" in
  init)    shift; resolve; cmd_init ;;
  publish) shift; resolve; cmd_publish "$@" ;;
  set)     shift; resolve; cmd_set "$@" ;;
  put)     shift; resolve; cmd_put "$@" ;;
  list)    shift; resolve; cmd_list ;;
  rm)      shift; resolve; cmd_rm "$@" ;;
  rebuild) shift; resolve; cmd_rebuild ;;
  *) die "usage: publish.sh {init | publish <file> --title T | set <slug> .. | put <path> <file> | list | rm <slug> | rebuild}" ;;
esac
