# Changelog

All notable changes to GitForge will be documented in this file.

## [v3.0.1] - 2026-08-09

- Maintenance release with synchronized version metadata and verified test/build baselines.

## [v3.0.0] - 2026-08-03

- Added a provider-agnostic repository API with GitLab, Gitea, Forgejo, and read-only Bitbucket Cloud adapters.
- Added provider, API endpoint, and workspace configuration while preserving GitHub defaults.
- Added a Local Ops tab for bounded interactive rebase plans, cross-repository cherry-picks, worktrees, submodules, and Git LFS detection.
- Added Advanced API coverage for releases, branch protection, Actions workflows, secrets/variables, webhooks, and collaborator audits with dry-run previews.
- Added offline dependency inventory, commit-frequency heatmap, and cross-repository contributor analytics to Insights.
- Added 90-day token rotation/2FA reminders, a window-scoped Ctrl+K action palette, persisted table column profiles, extended row selection, and selectable dark themes.
- Added Automation tools for trusted local scripts, template deployment, organization-scoped repository listings, offline cache reads, and queued API writes.
- Added the PyInstaller multiprocessing freeze guard for reliable frozen Windows startup; release signing and non-Windows publication remain explicitly blocked.
- Added GraphQL metadata and pull-request APIs, account/org activity snapshots, optional restic and Task Scheduler adapters, bounded parallel Git status with pygit2 fallback, and content-addressed diff caching.

## [v2.1.0] - 2026-04-13

- Added: Add screenshot to README
- Added: Add files via upload

## Roadmap archive — 2026-08-10 — ROADMAP.md

<details>
<summary>Original roadmap snapshot</summary>

```markdown
# ROADMAP

Backlog for GitForge. Power-user GitHub bulk manager with a PyQt6 UI. Stays focused on bulk +
cross-repo workflows that GitHub Desktop and Fork don't cover.

## Planned Features

### Cross-forge support

### Local repo ops

### GitHub API coverage

### Search / insights

### Safety

### UI / UX

### Distribution

## Competitive Research

- **GitHub Desktop** — minimal, single-repo focus, no bulk. GitForge already fills this gap.
- **Fork / Tower** — per-repo UX is excellent; GitForge is complementary (launch Fork from a row
  in GitForge).
- **GitKraken** — integrated issue tracker + timeline view. GitForge should skip in-app issue
  management and defer to `gh issue` or the web UI.
- **`gh` CLI** — the truest peer. Treat `gh` as a first-class backend; some advanced ops can
  shell out to it rather than re-implement.
- **lab / glab / forgejo CLI** — equivalents for GitLab/Forgejo; leverage similarly.
- **LithiumGit / Sublime Merge** — emerging fast clients. Not direct competitors but reference UIs
  for single-repo views if that scope ever expands.

## Nice-to-Haves


## Open-Source Research (Round 2)

### Related OSS Projects
- **github-backup (josegonzalez)** — https://github.com/josegonzalez/python-github-backup — Comprehensive Python backup CLI: repos, wikis, gists, issues, PRs, releases, starred.
- **amitsaha/gitbackup** — https://github.com/amitsaha/gitbackup — Go binary backing up GitHub/GitLab/Bitbucket/Forgejo; Docker image; CLI-oriented.
- **camptocamp/github-backup** — https://github.com/camptocamp/github-backup — Python org backup: issues/PRs/comments/wikis/teams in readable format.
- **restic** — https://github.com/restic/restic — Best-in-class dedup + encryption backup tool; worth wrapping for git-mirror backups at rest.
- **lazygit** — https://github.com/jesseduffield/lazygit — TUI Git; single-repo ergonomics are top-tier; cross-reference for Diff/Stash UX.
- **gitui** — https://github.com/extrawurst/gitui — Rust TUI Git; async rendering model handles 10k-commit repos without stutter.
- **GitHub Desktop** — https://github.com/desktop/desktop — Electron reference; multi-repo list + PR integration model.
- **SourceGit** — https://github.com/sourcegit-scm/sourcegit — Avalonia cross-platform Git GUI; fast and multi-repo capable.
- **github.com/topics/github-backup** — https://github.com/topics/github-backup — Full topic index.

### Features to Borrow
- Wiki + gist + issues + PR export (`josegonzalez/python-github-backup`) — expand Backup tab past code-only to full account snapshot.
- `restic` encrypted backup repo target — pipe `git clone --mirror` tarballs into a restic repo for off-site dedup'd history.
- Org-mode dump (`camptocamp`) — clone every repo in an org + all members/teams metadata in one click; useful for ex-employee handover.
- LazyGit / GitUI per-repo drill-in — embed a TUI-style fast diff viewer in the Diff tab; current QPlainTextEdit is slow on huge diffs.
- GitHub Desktop-style PR list per-repo — show open PRs / CI status inline in the repo list (gh API already planned).
- Multi-provider (`amitsaha/gitbackup`) — add GitLab / Bitbucket / Codeberg / Forgejo as sync sources.
- Scheduled backups (`josegonzalez` cron wrapper recipes) — Task Scheduler / launchd integration for nightly full backups.

### Patterns & Architectures Worth Studying
- **Incremental backup via `git fetch` on existing mirrors** (`josegonzalez`): re-running backup is O(delta), not O(total). Already implied in your Sync tab — formalize as a Backup strategy.
- **pygit2 (libgit2 bindings) over shell git**: 10x faster status/fetch for large repo lists. `gitui` uses gitoxide in Rust; same win in Python via pygit2. Avoids subprocess overhead at scale (100+ repos).
- **Async `ThreadPoolExecutor` fan-out for N-repo operations** (`gitbackup` worker pool): current Sync tab likely serial; parallelize with a small worker pool + per-repo row progress.
- **GitHub GraphQL v4 for bulk metadata** (`github-backup` partial usage): one query can return 100 repos + stars + default branch + topics + last-push. Replaces many REST calls on dashboard refresh.
- **Content-addressable cache keyed by commit SHA** (`restic`, `lazygit`): diff/log/show results cached by SHA — re-opening a commit becomes instant. Useful for Diff tab.
```

</details>
