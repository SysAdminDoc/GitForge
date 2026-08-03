import json
import os
import subprocess

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

