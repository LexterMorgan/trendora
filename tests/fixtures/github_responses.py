"""Representative GitHub REST repository payloads. Not live responses."""

from __future__ import annotations

REPO_A_FULL_NAME = "octocat/hello-world"
REPO_B_FULL_NAME = "example/ml-lib"

REPO_A = {
    "id": 1296269,
    "name": "hello-world",
    "full_name": REPO_A_FULL_NAME,
    "html_url": "https://github.com/octocat/hello-world",
    "description": "My first repository on GitHub!",
    "language": "Python",
    "visibility": "public",
    "private": False,
    "default_branch": "main",
    "archived": False,
    "disabled": False,
    "topics": ["python", "machine-learning", "llm"],
    "license": {"key": "mit", "name": "MIT License", "spdx_id": "MIT"},
    "created_at": "2011-01-26T19:01:12Z",
    "updated_at": "2026-08-20T12:00:00Z",
    "pushed_at": "2026-08-19T08:30:00Z",
    "stargazers_count": 100,
    "forks_count": 20,
    "open_issues_count": 5,
    "watchers_count": 100,
    "subscribers_count": 8,
    "owner": {"login": "octocat", "id": 1},
}

REPO_B = {
    "id": 424242,
    "name": "ml-lib",
    "full_name": REPO_B_FULL_NAME,
    "html_url": "https://github.com/example/ml-lib",
    "description": None,
    "language": None,
    "visibility": "public",
    "private": False,
    "default_branch": "master",
    "archived": False,
    "disabled": False,
    "topics": [],
    "license": None,
    "created_at": "2020-02-02T00:00:00Z",
    "updated_at": "2020-02-02T00:00:00Z",
    "pushed_at": None,
    "stargazers_count": 0,
    "forks_count": 0,
    "open_issues_count": 0,
    "watchers_count": 0,
    "subscribers_count": 0,
    "owner": {"login": "example", "id": 99},
}

REPO_MALFORMED_METRICS = {
    "id": 7,
    "name": "odd-counts",
    "full_name": "example/odd-counts",
    "html_url": "https://github.com/example/odd-counts",
    "description": "Bad counters",
    "language": "Go",
    "stargazers_count": "not-a-number",
    "forks_count": -3,
    "open_issues_count": 4,
    "watchers_count": "nope",
    "owner": {"login": "example"},
}

REPO_MISSING_IDENTITY = {
    "description": "no name",
    "stargazers_count": 1,
}

RATE_LIMIT_ERROR = {
    "message": "API rate limit exceeded for 1.2.3.4.",
    "documentation_url": "https://docs.github.com/rest/overview/rate-limits",
}

HTTP_NOT_FOUND = {
    "message": "Not Found",
    "documentation_url": "https://docs.github.com/rest/repos/repos#get-a-repository",
}
