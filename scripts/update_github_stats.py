#!/usr/bin/env python3
"""Aggregate GitHub language/tool stats and patch README.md."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone

README_PATH = "README.md"
SECTION_NAME = "waka"
LANG_COUNT = 10
TOOL_COUNT = 10
BAR_LENGTH = 25
BLOCKS = "░▒▓█"

TOOL_LANGUAGES = {
    "Batchfile",
    "CMake",
    "Dockerfile",
    "EditorConfig",
    "Git Config",
    "GitHub Actions Workflow",
    "Gradle",
    "HCL",
    "INI",
    "Ignore List",
    "Jsonnet",
    "Makefile",
    "Maven POM",
    "Nix",
    "PowerShell",
    "Procfile",
    "Shell",
    "Starlark",
    "TOML",
}

QUERY = """
query ($login: String!, $cursor: String) {
  user(login: $login) {
    repositories(
      first: 100
      after: $cursor
      ownerAffiliations: OWNER
      isFork: false
      privacy: PUBLIC
      orderBy: {field: UPDATED_AT, direction: DESC}
    ) {
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        name
        isArchived
        repositoryTopics(first: 20) {
          nodes {
            topic {
              name
            }
          }
        }
        languages(first: 20, orderBy: {field: SIZE, direction: DESC}) {
          edges {
            size
            node {
              name
            }
          }
        }
      }
    }
  }
}
"""


def github_graphql(token: str, variables: dict) -> dict:
    payload = json.dumps({"query": QUERY, "variables": variables}).encode("utf-8")
    request = urllib.request.Request(
        "https://api.github.com/graphql",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "marcosrachid-github-stats",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace")
        raise SystemExit(f"GitHub GraphQL HTTP {err.code}: {detail}") from err

    if body.get("errors"):
        raise SystemExit(f"GitHub GraphQL errors: {body['errors']}")
    return body["data"]


def fetch_repositories(token: str, login: str) -> list[dict]:
    cursor = None
    repositories: list[dict] = []
    while True:
        data = github_graphql(token, {"login": login, "cursor": cursor})
        connection = data["user"]["repositories"]
        repositories.extend(connection["nodes"])
        if not connection["pageInfo"]["hasNextPage"]:
            break
        cursor = connection["pageInfo"]["endCursor"]
    return repositories


def make_bar(percent: float) -> str:
    empty, fade, mid, full = list(BLOCKS)
    ratio = max(0.0, min(percent, 100.0)) / 100.0
    filled = ratio * BAR_LENGTH
    whole = int(filled)
    frac = filled - whole
    bar = [full] * whole
    if whole < BAR_LENGTH:
        if frac >= 0.75:
            bar.append(full)
        elif frac >= 0.5:
            bar.append(mid)
        elif frac >= 0.25:
            bar.append(fade)
        else:
            bar.append(empty)
        bar.extend([empty] * (BAR_LENGTH - len(bar)))
    return "".join(bar[:BAR_LENGTH])


def top_entries(totals: dict[str, float], limit: int) -> list[tuple[str, float, float]]:
    grand_total = sum(totals.values())
    if grand_total <= 0:
        return []
    ranked = sorted(totals.items(), key=lambda item: item[1], reverse=True)
    visible = ranked[:limit]
    leftover = ranked[limit:]
    rows: list[tuple[str, float, float]] = [
        (name, amount, amount / grand_total * 100.0) for name, amount in visible
    ]
    if leftover:
        other_amount = sum(amount for _, amount in leftover)
        rows.append(("Other", other_amount, other_amount / grand_total * 100.0))
    return rows


def render_table(title: str, rows: list[tuple[str, float, float]]) -> list[str]:
    lines = [title]
    if not rows:
        lines.append("No data yet.")
        return lines
    name_width = max(len(name) for name, _, _ in rows)
    name_width = max(name_width, 12)
    for name, _, percent in rows:
        lines.append(
            f"{name:<{name_width}}  {make_bar(percent)}  {percent:5.2f} %"
        )
    return lines


def collect_stats(repositories: list[dict]) -> tuple[dict[str, float], dict[str, float]]:
    languages: dict[str, float] = defaultdict(float)
    tools: dict[str, float] = defaultdict(float)

    for repo in repositories:
        if repo.get("isArchived"):
            continue
        for edge in repo.get("languages", {}).get("edges", []):
            name = edge["node"]["name"]
            size = float(edge["size"])
            if name in TOOL_LANGUAGES:
                tools[name] += size
            else:
                languages[name] += size
        for topic_node in repo.get("repositoryTopics", {}).get("nodes", []):
            topic = topic_node["topic"]["name"]
            if topic in {
                "docker",
                "kubernetes",
                "terraform",
                "ansible",
                "aws",
                "azure",
                "gcp",
                "mongodb",
                "postgresql",
                "mysql",
                "redis",
                "kafka",
                "rabbitmq",
                "nginx",
                "spring",
                "spring-boot",
                "react",
                "vue",
                "angular",
                "nextjs",
                "nodejs",
                "django",
                "flask",
                "laravel",
                "blockchain",
                "solidity",
                "hardhat",
                "ethereum",
                "graphql",
                "rest-api",
                "ci-cd",
                "github-actions",
                "helm",
                "prometheus",
                "grafana",
                "linux",
            }:
                tools[topic] += 1_000.0
    return languages, tools


def render_block(languages: dict[str, float], tools: dict[str, float], repo_count: int) -> str:
    today = datetime.now(timezone.utc).strftime("%d %B %Y")
    lines = [
        f"GitHub stats · {repo_count} public repos · updated {today}",
        "",
    ]
    lines.extend(render_table("Languages", top_entries(languages, LANG_COUNT)))
    lines.append("")
    lines.extend(render_table("Tools", top_entries(tools, TOOL_COUNT)))
    return "\n".join(lines)


def patch_readme(content: str, stats_block: str) -> str:
    start = f"<!--START_SECTION:{SECTION_NAME}-->"
    end = f"<!--END_SECTION:{SECTION_NAME}-->"
    pattern = re.compile(
        re.escape(start) + r".*?" + re.escape(end),
        flags=re.DOTALL,
    )
    replacement = f"{start}\n\n```txt\n{stats_block}\n```\n\n{end}"
    if not pattern.search(content):
        raise SystemExit(f"README is missing {start} / {end} markers")
    return pattern.sub(replacement, content)


def main() -> int:
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if not token:
        print("GITHUB_TOKEN is required", file=sys.stderr)
        return 1

    login = os.getenv("GITHUB_REPOSITORY_OWNER") or os.getenv("GH_USER") or "marcosrachid"
    repositories = fetch_repositories(token, login)
    languages, tools = collect_stats(repositories)
    active_repos = [repo for repo in repositories if not repo.get("isArchived")]
    stats_block = render_block(languages, tools, len(active_repos))

    with open(README_PATH, encoding="utf-8") as handle:
        original = handle.read()
    updated = patch_readme(original, stats_block)
    if updated != original:
        with open(README_PATH, "w", encoding="utf-8") as handle:
            handle.write(updated)
        print("README.md updated")
    else:
        print("README.md already up to date")
    print(stats_block)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
