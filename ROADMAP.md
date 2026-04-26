# ROADMAP

Backlog for GitForge. Power-user GitHub bulk manager with a PyQt6 UI. Stays focused on bulk +
cross-repo workflows that GitHub Desktop and Fork don't cover.

## Planned Features

### Cross-forge support
- **GitLab provider** — same bulk operations across a GitLab account (personal + groups), using
  GitLab's REST v4 API.
- **Gitea / Forgejo provider** for self-hosted forges (single-tenant setups common in homelab).
- **Bitbucket Cloud** (read-only initially for migration scenarios).
- **Provider-agnostic repo abstraction** so UI is identical across providers.

### Local repo ops
- **Interactive rebase GUI** — drag to reorder, pick/squash/fixup/drop, edit messages.
- **Cherry-pick across repos** — select a commit from one repo, apply to another via patch.
- **Worktree manager** — list/create/remove `git worktree` entries per repo from the UI.
- **Submodule dashboard** — list all submodules across repos, bulk init/update/sync.
- **LFS awareness** — flag repos using Git LFS, show LFS quota via GitHub API.

### GitHub API coverage
- **Releases manager** — list releases per repo, bulk create/retag/delete, attach artifacts.
- **Branch protection rule editor** — bulk apply a rule to every repo or a filtered subset.
- **Actions / Workflow browser** — list workflow files across repos, find stale / failing ones,
  bulk enable/disable.
- **Secrets + Variables editor** — bulk propagate an org secret to repos, with safety
  confirmation.
- **Webhooks inventory** — find repos with webhooks, detect orphaned hooks pointing at dead URLs.
- **Collaborator audit** — across every repo, report outside collaborators, admins, pending
  invites.

### Search / insights
- **Cross-repo regex grep on history** (not just working tree) via `git log -G`.
- **Dependency inventory** — parse `package.json` / `requirements.txt` / `pyproject.toml` /
  `Cargo.toml` / `go.mod` across repos, show aggregate deps and outdated versions.
- **License audit** — detect LICENSE per repo, flag missing/unknown.
- **Commit frequency heatmap** per repo, and org-wide.
- **Top contributors across your account** combined.

### Safety
- **Dry-run everywhere** — every destructive API op has a "preview the request bodies" step.
- **Rate-limit-aware scheduler** — when near limit, queue and pace requests automatically.
- **Backup before API changes** — snapshot repo metadata before bulk visibility / archive
  changes so rollback is trivial.
- **Two-factor API key usage reminder** — nudge when token is older than 90 days.

### UI / UX
- **Hotkey-driven palette** (`Ctrl+K`) for action launch (against project rule on global shortcuts;
  scope in-panel only).
- **Multi-select with shift / checkbox column everywhere**.
- **Column customization** per tab; persist per-user profile.
- **Dark-theme options** — Catppuccin Mocha default, GitHub Dark, Nord, Solarized Dark.
- **Export any table** to CSV/Markdown.

### Distribution
- **PyInstaller signed exe** with `multiprocessing.freeze_support()` guard (requests + PyQt6 +
  subprocess can combine badly on frozen Windows builds).
- **macOS `.app` notarized**, Linux AppImage.
- **Scoop + Winget manifests**.

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

- **Script runner** — user drops a Python snippet into a window, it executes with a `gh` /
  `git` / `requests` context pre-wired for the selected repo set.
- **Org-level dashboards** — switch context from personal user to an org you admin.
- **Template-repo deploy** — apply a cookiecutter/template-repo to N existing repos (e.g. add a
  standard `.github/workflows` set).
- **Abandoned-repo detector** — flag repos with no activity > N months for archival candidate
  list.
- **AI-generated commit message suggestion** using staged diff (opt-in, user-supplied API).
- **Offline mode** — read cached API data when offline, queue writes for next online session.

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
