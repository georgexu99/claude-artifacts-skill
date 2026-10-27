---
name: claude-artifacts
description: Mirror a published claude.ai Artifact to the user's own GitHub Pages site (<owner>/claude-artifacts, gh-pages branch) so people without claude.ai access can open it, with a landing gallery and a sidebar index. Use right after publishing or republishing an Artifact when the user wants it mirrored, when asked to "mirror to pages", "put it on GitHub Pages", "share the artifact outside claude.ai", to list or remove mirrored pages, or to change a mirrored page's group, state or "next" line.
---

# Mirror an artifact to GitHub Pages

After you publish or republish an Artifact with the `Artifact` tool, mirror the same
local HTML file with `publish.sh` (next to this file):

```
github.com:  https://<owner>.github.io/claude-artifacts/<slug>/
GHE:         https://pages.<host>/<owner>/claude-artifacts/<slug>/
landing:     the same URL without <slug>/
```

The artifact is stored untouched at `<slug>/page.html`; `<slug>/index.html` is a shell
that frames it in an iframe and draws a sidebar from `manifest.json` at load time, so
adding a page never rewrites the others. The landing page has a hero with counts, a
"Come back to" rail of open work, a "Recently updated" rail, a state filter and one card
section per topic group. Templates live in `site/` (`shell.html`, `gallery.html`,
`site.css`, `site.js`).

## Setup (once)

- `gh` installed and authenticated for the host (`gh auth login`), plus `python3`.
- `git clone https://github.com/georgexu99/claude-artifacts-skill ~/.claude/skills/claude-artifacts`
- `~/.claude/skills/claude-artifacts/publish.sh init` creates `<owner>/claude-artifacts`
  (public unless `ARTIFACTS_PRIVATE=1`), the `gh-pages` branch as default, `.nojekyll`,
  and enables Pages. If enabling Pages fails, ask the user to switch it on under
  Settings → Pages. Pages on a private github.com repo needs a paid plan.

Config is by environment: `ARTIFACTS_GH_HOST` (default `github.com`), `ARTIFACTS_OWNER`
(default: the authenticated user), `ARTIFACTS_REPO` (default `claude-artifacts`),
`ARTIFACTS_TITLE` / `ARTIFACTS_SUBTITLE` (site branding, applied on the next publish or
`rebuild`).

## Visibility: this is wider than the claude.ai artifact

A claude.ai artifact is private by default. The mirror is readable by anyone who can see
the Pages site: on github.com that is the public internet unless the repo is private on a
paid plan; on GitHub Enterprise it is usually everyone on that instance. Before
mirroring, check the page is fine for that audience: no customer data, secrets, personal
info or unannounced plans. If it isn't, skip the mirror and say so in one line.
`publish.sh` refuses on credential patterns, but it cannot judge confidentiality.

## Publish or update

```bash
~/.claude/skills/claude-artifacts/publish.sh publish <file.html> \
  --title "Same title as the artifact" --emoji "📊" \
  --summary "One sentence, the same as the Artifact description" \
  --project "owner/repo" --group "🧪 Build experiments" \
  --state Open --next "What happens next, one line" \
  --claude-url "<claude.ai artifact URL>" --no-open
```

- Use the same file you passed to `Artifact` as `file_path`.
- `--group` is the topic the landing page and sidebar group by, emoji first. Reuse an
  existing group's exact spelling (`publish.sh list` shows them); a new spelling makes a
  new group. `--project` is metadata only.
- `--state` is `Open` (default), `Waiting` (on someone else: a review, a decision),
  `Done` or `Dropped`. It drives the dots, pills, the "Come back to" rail and the filter.
  `--next` is the one line shown on Open/Waiting cards; keep it current.
- `--nav monitoring` or `--nav prs` pins a page into the Monitoring or Pull requests
  sidebar section instead of a topic group (dashboards, PR overviews).
- **Re-using a `--slug` overwrites in place**, which is how updates work; `created`
  survives. When republishing an Artifact, run `publish.sh list` and reuse the slug its
  mirror already has, so the URL stays stable.
- Takes ~10–40 s (Contents API PUTs + waiting for the Pages build).
- `--force` skips the credential scan. Look at the hit first.

Metadata changes without a new page go through `set`, which leaves `updated` alone
unless you pass `--touch`:

```bash
publish.sh set <slug> --state Done
publish.sh set <slug> --next "Waiting on review" --touch
publish.sh list                      # slug, updated, state, title · group
publish.sh rm <slug>                 # only when the user asks
publish.sh put <repo-path> <file>    # one extra file next to a page, same secret scan
publish.sh rebuild                   # after editing site/*: re-push chrome + every shell
```

Keep states honest: when the work lands, `set` the page to `Done`; when it stalls on
someone else, `Waiting` with a `--next` naming what it waits on. A page untouched for
30+ days that is still Open/Waiting shows a "stale" pill. Uploads skip files whose
content is unchanged, so `rebuild` and repeat publishes only cost what differs.

## Pull-request pages

Two stdlib-only Python scripts next to `publish.sh` build pages for the Pull requests
sidebar section from your own PRs, through `gh api` / `gh api graphql` only. Each writes
standalone HTML that links `../site.css`, then prints the exact publish commands.

- `pr-explainers.py <out dir>`: an index grouped by repo, plus one page per PR
  (`pr-<owner>-<repo>-<n>.html`) with state, size, review status per reviewer, requested
  reviewers, CI rollup with failing checks, branches, labels, linked issues, files grouped
  by top-level directory, commit headlines and the description rendered by GitHub's
  Markdown API, whatever its format. Default set: your open PRs plus those merged in the
  last `ARTIFACTS_PR_MERGED_DAYS` days. Refresh when a PR opens, merges or changes review/CI
  state.
- `pr-activity.py <out dir>`: one page of PRs opened and merged per week, reviews given
  per week (PRs by bots excluded), median time to merge, a per-repo table and the merged
  list. Refresh weekly.

```bash
dir=$(mktemp -d)
~/.claude/skills/claude-artifacts/pr-explainers.py "$dir/pr-explainers"
publish.sh publish "$dir/pr-explainers/index.html" --slug pr-explainers --title "PR Explainers" --emoji 💡 --nav prs --no-open
for f in "$dir"/pr-explainers/pr-*.html; do publish.sh put "pr-explainers/$(basename "$f")" "$f"; done

~/.claude/skills/claude-artifacts/pr-activity.py "$dir/pr-activity"
publish.sh publish "$dir/pr-activity/index.html" --slug pr-activity --title "PR Activity" --emoji 📈 --nav prs --no-open
```

| Variable | Default | Used by |
|---|---|---|
| `ARTIFACTS_PR_HOSTS` | `github.com` | both; comma list, e.g. `github.com,ghe.example.com` |
| `ARTIFACTS_PR_REPOS` | all repos | both; comma list of `owner/repo` to restrict to |
| `ARTIFACTS_PR_MERGED_DAYS` | `30` | explainers; `0` = open PRs only |
| `ARTIFACTS_PR_QUERY` | unset | explainers; one search query replacing the defaults, e.g. `repo:<owner>/<repo> is:pr is:open` |
| `ARTIFACTS_ACTIVITY_WEEKS` | `12` | activity |

PR titles, descriptions and file paths become public with the site, so run the visibility
check first: with private repos in scope, set `ARTIFACTS_PR_REPOS` or skip the mirror.
Write the output outside any git checkout; the scripts delete stale `pr-*.html` in the
out dir on each run.

## What doesn't carry over

- **Single file only.** Multi-file artifacts (`files` map, uploaded assets) need their
  supporting files inlined first, or the mirror renders broken.
- **No runtime capabilities.** `window.claude.*` (db, live data, ask-Claude) doesn't
  exist on Pages; the script warns. Mirror only if the page still reads sensibly as a
  static snapshot, otherwise skip and say why.
- No comments, no version picker (git history on `gh-pages` is the log). Typed
  artifacts (Docs, Slides) have no single HTML file, so don't mirror them.
- The outer URL's `#hash` is forwarded into the iframe and kept in sync, so deep links
  work. `<slug>/page.html` is the bare page (the sidebar footer links to it).

## Report back

Give both links, one per line: the claude.ai artifact and the Pages mirror.

## Gotchas

- `publish`, `set` and `rm` each rewrite `manifest.json` (fetch, edit, PUT), so run them
  one after another, never in parallel.
- On GitHub Enterprise, Pages may sit behind a login, so `curl` with a token lands on a
  sign-in page. Verify with the build status the script prints, or preview locally: copy
  `site/*` plus a fetched `manifest.json` into a folder, add a `<slug>/page.html` and a
  templated `<slug>/index.html`, and serve it with `python3 -m http.server`; `site.js`
  resolves everything relative to its own URL.
