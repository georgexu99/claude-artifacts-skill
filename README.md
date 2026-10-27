# claude-artifacts

A Claude Code skill that mirrors your claude.ai Artifacts to your own GitHub Pages site,
so people without claude.ai access can open them. Each page gets a sidebar index, and
the site root is a gallery grouped by topic with Open / Waiting / Done / Dropped states.

Everything goes through `gh api`: no local clone of the site repo.

## Install

Requires [`gh`](https://cli.github.com/) (authenticated with `gh auth login`) and `python3`.

```bash
git clone https://github.com/georgexu99/claude-artifacts-skill ~/.claude/skills/claude-artifacts
~/.claude/skills/claude-artifacts/publish.sh init
```

`init` creates `<you>/claude-artifacts` (public by default), a `gh-pages` branch and
enables Pages. Your site is then at `https://<you>.github.io/claude-artifacts/`.

## Quick start

Claude picks the skill up after it publishes an Artifact. To run it by hand:

```bash
publish.sh publish page.html --title "My page" --group "🧪 Experiments" --state Open --next "Try the fix"
publish.sh set my-page --state Done
publish.sh list
publish.sh rm my-page
publish.sh rebuild   # after editing site/*
```

See `SKILL.md` for every flag and convention.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `ARTIFACTS_GH_HOST` | `github.com` | GitHub host; set to your GHE host for `https://pages.<host>/<owner>/<repo>/` |
| `ARTIFACTS_OWNER` | authenticated user | Repo owner (user or org) |
| `ARTIFACTS_REPO` | `claude-artifacts` | Repo name |
| `ARTIFACTS_PRIVATE` | unset | `1` makes `init` create a private repo (github.com Pages then needs a paid plan) |
| `ARTIFACTS_TITLE` | `Claude Artifacts` | Site title |
| `ARTIFACTS_SUBTITLE` | `Pages from my Claude Code sessions` | Site subtitle |
| `ARTIFACTS_SKILL_URL` | placeholder | Link to this repo, shown in the gallery's "replicate this site" prompt |

## Visibility

On github.com a Pages site is public unless the repo is private on a paid plan. Don't
mirror anything you wouldn't post publicly. `publish.sh` refuses pages containing common
credential patterns, but it can't judge confidentiality.

## License

MIT
