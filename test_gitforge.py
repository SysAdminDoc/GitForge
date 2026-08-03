import json
import subprocess
from datetime import datetime, timedelta, timezone

import gitforge


class FakeResponse:
    def __init__(self, payload, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def put(self, url, **kwargs):
        return self.request("PUT", url, **kwargs)

    def patch(self, url, **kwargs):
        return self.request("PATCH", url, **kwargs)

    def delete(self, url, **kwargs):
        return self.request("DELETE", url, **kwargs)


def test_provider_factory_uses_defaults_and_custom_endpoint():
    github = gitforge.create_provider({"provider": "github", "username": "alice"})
    assert isinstance(github, gitforge.GitHubAPI)
    assert github.BASE == "https://api.github.com"

    forgejo = gitforge.create_provider({
        "provider": "forgejo",
        "username": "alice",
        "provider_base_url": "https://forge.example/api/v1/",
    })
    assert isinstance(forgejo, gitforge.ForgejoAPI)
    assert forgejo.base_url == "https://forge.example/api/v1"


def test_gitlab_fetch_normalizes_projects_and_follows_next_page():
    session = FakeSession([
        FakeResponse([{
            "id": 10,
            "name": "one",
            "path": "one",
            "path_with_namespace": "team/one",
            "visibility": "private",
            "http_url_to_repo": "https://gitlab.example/team/one.git",
            "ssh_url_to_repo": "git@gitlab.example:team/one.git",
            "web_url": "https://gitlab.example/team/one",
            "last_activity_at": "2026-01-01T00:00:00Z",
            "namespace": {"full_path": "team"},
        }], headers={"X-Next-Page": "2"}),
        FakeResponse([]),
    ])
    provider = gitforge.GitLabAPI(identity="alice", token="secret", session=session)

    repos = provider.fetch_all_repos()

    assert [repo["full_name"] for repo in repos] == ["team/one"]
    assert repos[0]["private"] is True
    assert session.calls[0][1].endswith("/projects")
    assert session.calls[0][2]["params"]["membership"] == "true"


def test_gitea_fetch_includes_org_repos_without_duplicates():
    session = FakeSession([
        FakeResponse([{"id": 1, "name": "one", "full_name": "alice/one", "owner": {"login": "alice"}}]),
        FakeResponse([{"id": 2, "name": "two", "full_name": "team/two", "owner": {"login": "team"}}]),
    ])
    provider = gitforge.GiteaAPI(identity="alice", token="secret", namespace="team", session=session)

    repos = provider.fetch_all_repos()

    assert {repo["full_name"] for repo in repos} == {"alice/one", "team/two"}
    assert session.calls[1][1].endswith("/orgs/team/repos")


def test_bitbucket_is_read_only_and_follows_next_link():
    session = FakeSession([
        FakeResponse({
            "values": [{
                "name": "one",
                "slug": "one",
                "workspace": {"slug": "team"},
                "links": {
                    "clone": [
                        {"name": "https", "href": "https://bitbucket.org/team/one.git"},
                        {"name": "ssh", "href": "git@bitbucket.org:team/one.git"},
                    ],
                    "html": {"href": "https://bitbucket.org/team/one"},
                },
            }],
            "next": "https://api.bitbucket.org/2.0/repositories/team?page=2",
        }),
        FakeResponse({"values": []}),
    ])
    provider = gitforge.BitbucketAPI(identity="team", session=session)

    repos = provider.fetch_all_repos()

    assert repos[0]["clone_url"].endswith("one.git")
    assert provider.read_only is True
    assert session.calls[1][1].endswith("page=2")


def test_github_advanced_api_methods_preserve_payloads_and_redact_scope():
    session = FakeSession([
        FakeResponse({"id": 7, "tag_name": "v3.0.0"}, status_code=201),
        FakeResponse({"required_pull_request_reviews": {"required_approving_review_count": 2}}, status_code=200),
        FakeResponse({"workflows": [{"id": 12, "name": "CI", "state": "active"}]}, status_code=200),
        FakeResponse({"values": [{"id": 44, "active": True, "events": ["push"], "config": {"url": "secret"}}]}, status_code=200),
        FakeResponse([{"login": "outside", "permissions": {"push": True}}], status_code=200),
    ])
    api = gitforge.GitHubAPI("alice", "token", session=session)

    release = api.create_release("alice/project", "v3.0.0", name="Release", body="notes", draft=True)
    protection = api.get_branch_protection("alice/project", "release/3")
    workflows = api.list_workflows("alice/project")
    hooks = api.list_webhooks("alice/project")
    collaborators = api.audit_collaborators([{"full_name": "alice/project"}])

    assert release["id"] == 7
    assert protection["required_pull_request_reviews"]["required_approving_review_count"] == 2
    assert workflows[0]["name"] == "CI"
    assert hooks[0]["config"]["url"] == "secret"
    assert collaborators[0]["login"] == "outside"
    assert session.calls[0][0] == "POST"
    assert session.calls[0][2]["json"]["draft"] is True
    assert "/branches/release%2F3/protection" in session.calls[1][1]


def test_github_namespace_fetch_merges_personal_and_org_repositories():
    session = FakeSession([
        FakeResponse([{"name": "personal", "full_name": "alice/personal", "private": False, "fork": False, "clone_url": "https://example/personal.git", "ssh_url": "git@example:personal.git", "html_url": "https://example/personal"}]),
        FakeResponse([{"name": "shared", "full_name": "team/shared", "private": True, "fork": False, "clone_url": "https://example/shared.git", "ssh_url": "git@example:shared.git", "html_url": "https://example/shared"}]),
    ])
    api = gitforge.GitHubAPI("alice", "token", namespace="team", session=session)

    repos = api.fetch_all_repos()

    assert {repo["full_name"] for repo in repos} == {"alice/personal", "team/shared"}
    assert session.calls[1][1].endswith("/orgs/team/repos")


def test_graphql_metadata_and_research_helpers_are_offline_safe(tmp_path):
    session = FakeSession([FakeResponse({
        "data": {"user": {"repositories": {"nodes": [{
            "name": "one", "nameWithOwner": "alice/one", "isPrivate": False, "isFork": False,
            "isArchived": False, "url": "https://example/one", "sshUrl": "git@example:one",
            "diskUsage": 10, "primaryLanguage": {"name": "Python"},
            "defaultBranchRef": {"name": "main"}, "stargazerCount": 2, "forkCount": 1,
            "issues": {"totalCount": 3}, "updatedAt": "2026-01-01", "pushedAt": "2026-01-01",
        }]}}}
    })])
    api = gitforge.GitHubAPI("alice", "token", session=session)
    repos = api.fetch_repo_metadata_graphql("alice")
    assert repos[0]["language"] == "Python"
    assert session.calls[0][2]["json"]["variables"] == {"login": "alice"}

    cache_dir = tmp_path / "diff-cache"
    gitforge.save_content_addressed("repo|HEAD", "diff text", str(cache_dir))
    assert gitforge.load_content_addressed("repo|HEAD", str(cache_dir)) == "diff text"
    mapped = gitforge.parallel_repo_map(["b", "a"], lambda value: value.upper(), max_workers=2)
    assert [item["value"] for item in mapped] == ["A", "B"]
    assert gitforge.restic_backup("restic", tmp_path, "repo", dry_run=True)["stdout"] == "DRY RUN"
    assert gitforge.schedule_windows_backup("GitForge-Test", "python gitforge.py", dry_run=True)["returncode"] == 0


def _init_repo(path, git):
    subprocess.run([git, "init", "-b", "main", str(path)], check=True, capture_output=True)
    gitforge.run_git(git, path, ["config", "user.name", "Test User"])
    gitforge.run_git(git, path, ["config", "user.email", "test@example.invalid"])


def _commit_file(path, git, filename, content, message):
    (path / filename).write_text(content, encoding="utf-8")
    gitforge.run_git(git, path, ["add", filename])
    gitforge.run_git(git, path, ["commit", "-m", message])


def test_local_operations_cover_worktrees_lfs_and_rebase_todos(tmp_path):
    git = gitforge.find_git()
    assert git
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo, git)
    _commit_file(repo, git, "README.txt", "base\n", "base")
    _commit_file(repo, git, "README.txt", "change\n", "change")
    (repo / ".gitattributes").write_text("*.bin filter=lfs diff=lfs merge=lfs -text\n", encoding="utf-8")

    worktree = tmp_path / "feature"
    gitforge.create_worktree(git, repo, worktree, "feature", new_branch=True)
    worktrees = gitforge.list_worktrees(git, repo)
    assert any(item["path"] == str(worktree) and item["branch"] == "feature" for item in worktrees)

    info = gitforge.lfs_info(git, repo)
    assert info["enabled"] is True
    assert gitforge.discover_local_repos(str(tmp_path)) == sorted([str(repo), str(worktree)])
    status = gitforge.scan_local_repo_status(git, repo, fetch=False)
    assert status["branch"] == "main"
    assert status["dirty"] >= 1

    commits = gitforge.rebase_commits(git, repo, 2)
    todo = gitforge.build_rebase_todo(commits)
    parsed = gitforge.parse_rebase_todo(todo)
    assert [entry["sha"] for entry in parsed] == [commit["sha"] for commit in commits]


def test_cherry_pick_transfers_commit_between_unrelated_repositories(tmp_path):
    git = gitforge.find_git()
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    _init_repo(source, git)
    _init_repo(target, git)
    _commit_file(source, git, "source.txt", "from source\n", "transfer me")
    _commit_file(target, git, "target.txt", "target\n", "target base")

    head = gitforge.run_git(git, source, ["rev-parse", "HEAD"])
    gitforge.cherry_pick_across_repos(git, source, target, head)

    assert "transfer me" in gitforge.run_git(git, target, ["log", "-1", "--format=%s"])
    assert (target / "source.txt").read_text(encoding="utf-8") == "from source\n"


def test_dependency_inventory_supports_requested_manifest_families(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "package.json").write_text(json.dumps({
        "dependencies": {"requests": "^1.0"},
        "devDependencies": {"pytest": "^8.0"},
    }), encoding="utf-8")
    (repo / "requirements.txt").write_text("httpx>=0.20\n# ignored\n-r other.txt\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text(
        "[project]\ndependencies = ['click>=8']\n[project.optional-dependencies]\ntest = ['pytest>=8']\n",
        encoding="utf-8",
    )
    (repo / "Cargo.toml").write_text("[dependencies]\nserde = '1'\n", encoding="utf-8")
    (repo / "go.mod").write_text("module example\n\nrequire github.com/pkg/errors v0.9.1\n", encoding="utf-8")

    records = gitforge.inventory_dependencies([str(repo)])
    names = {record["name"] for record in records}

    assert {"requests", "pytest", "httpx", "click", "serde", "github.com/pkg/errors"}.issubset(names)
    assert all(record["repo"] == "repo" for record in records)


def test_commit_heatmap_and_top_contributors_aggregate_local_history(tmp_path):
    git = gitforge.find_git()
    repo_a = tmp_path / "repo-a"
    repo_a.mkdir()
    _init_repo(repo_a, git)
    _commit_file(repo_a, git, "one.txt", "one\n", "one")
    _commit_file(repo_a, git, "two.txt", "two\n", "two")

    heatmap = gitforge.collect_commit_heatmap(git, [str(repo_a)])
    contributors = gitforge.top_contributors(git, [str(repo_a)])

    assert sum(heatmap["aggregate"].values()) == 2
    assert contributors[0]["email"] == "test@example.invalid"
    assert contributors[0]["commits"] == 2


def test_token_rotation_reminder_and_theme_palettes_are_deterministic():
    now = datetime(2026, 8, 3, tzinfo=timezone.utc)
    created = (now - timedelta(days=91)).isoformat()

    assert gitforge.token_age_days(created, now=now) == 91
    assert "Rotate it" in gitforge.token_rotation_message(created, now=now)
    assert "rotation reminder" in gitforge.token_rotation_message((now - timedelta(days=10)).isoformat(), now=now)
    assert "#0d1117" in gitforge.theme_style("GitHub Dark")


def test_cache_queue_script_runner_and_template_deploy(tmp_path):
    cache_dir = tmp_path / "cache"
    repos = [{"name": "one", "full_name": "alice/one"}]
    gitforge.save_repo_cache("github", "alice", repos, str(cache_dir))
    assert gitforge.load_repo_cache("github", "alice", str(cache_dir)) == repos

    queue_dir = tmp_path / "queue"
    gitforge.queue_offline_action("github", "alice", "PATCH", "/repos/alice/one", {"archived": True}, str(queue_dir))
    session = FakeSession([FakeResponse({}, status_code=200)])
    provider = gitforge.GitHubAPI("alice", "token", session=session)
    replay = gitforge.replay_offline_queue(provider, "alice", str(queue_dir))
    assert replay == {"applied": 1, "remaining": 0}
    assert session.calls[0][0] == "PATCH"

    git = gitforge.find_git()
    template = tmp_path / "template"
    target = tmp_path / "target"
    template.mkdir()
    target.mkdir()
    _init_repo(target, git)
    (template / ".github").mkdir()
    (template / ".github" / "workflow.yml").write_text("name: CI\n", encoding="utf-8")
    report = gitforge.deploy_template(str(template), [str(target)], git, commit_message="apply template")
    assert report[0]["status"] == "committed"
    assert (target / ".github" / "workflow.yml").is_file()

    result = gitforge.run_script_runner("print(len(repos)); print(git(repos[0], 'status', '--short'))", [str(target)], git, timeout=10)
    assert result["returncode"] == 0
    assert result["stdout"].splitlines()[0] == "1"

