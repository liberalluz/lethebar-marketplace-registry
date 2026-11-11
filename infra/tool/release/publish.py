#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Publish a release body through the provider recorded in .nebula-scaffold.json.

The tool does not create or push tags. It expects the release tag to exist and
to be pushed already; it then creates the remote Release and writes a local
evidence bundle.

Usage:
    python infra/tool/release/publish.py --root . --version v1.2.3 \
        --docs-root ../<project>-docs --check
    python infra/tool/release/publish.py --root . --version v1.2.3 \
        --docs-root ../<project>-docs --apply
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from urllib.parse import urlparse


SCAFFOLD = ".nebula-scaffold.json"
CHANGELOG = "CHANGELOG.md"
TOOL_VERSION = "0.1.0"
PROVIDERS = ("github", "gitlab", "none")
VERSION_RE = re.compile(
    r"^v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z.-]+)?$"
)
H2_RE = re.compile(r"^##\s", re.MULTILINE)


class PublishError(Exception):
    """A user-facing publish input error."""


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PublishError(f"cannot read {path}: {exc}") from exc


def read_provider(root: Path) -> str:
    path = root / SCAFFOLD
    if not path.is_file():
        raise PublishError(f"missing {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PublishError(f"invalid {path}: {exc}") from exc
    policy = data.get("repoPolicy") if isinstance(data, dict) else None
    if not isinstance(policy, dict):
        raise PublishError("missing repoPolicy in .nebula-scaffold.json")
    provider = policy.get("provider")
    if provider not in PROVIDERS:
        raise PublishError(
            "repoPolicy.provider must be github, gitlab, or none; "
            f"got {provider!r}"
        )
    return provider


def run(root: Path, command: list[str]) -> str:
    try:
        proc = subprocess.run(
            command,
            cwd=root,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
        )
    except OSError as exc:
        raise PublishError(f"cannot run {command[0]}: {exc}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise PublishError(f"{' '.join(command)} failed: {detail}")
    return proc.stdout


def git(root: Path, *args: str) -> str:
    return run(root, ["git", *args])


def remote_url(root: Path) -> str:
    try:
        return git(root, "config", "--get", "remote.origin.url").strip()
    except PublishError:
        return ""


def repo_slug(remote: str) -> str:
    value = remote.strip()
    if not value:
        return ""
    if "://" in value:
        path = urlparse(value).path
    elif ":" in value:
        path = value.split(":", 1)[1]
    else:
        path = value
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    parts = [part for part in path.split("/") if part]
    if len(parts) < 2:
        return ""
    return "/".join(parts)


def current_commit(root: Path) -> str:
    value = git(root, "rev-parse", "HEAD").strip()
    if not value:
        raise PublishError("cannot resolve HEAD")
    return value


def tag_commit(root: Path, tag: str) -> str:
    try:
        return git(root, "rev-parse", "-q", "--verify", f"refs/tags/{tag}").strip()
    except PublishError:
        return ""


def tag_kind(root: Path, tag: str) -> str:
    try:
        return git(root, "cat-file", "-t", f"refs/tags/{tag}").strip()
    except PublishError:
        return ""


def validate_version(version: str) -> None:
    if not VERSION_RE.match(version):
        raise PublishError(f"version must look like v1.2.3, got {version!r}")


def validate_date(value: str) -> None:
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise PublishError(f"invalid date: {value!r}") from exc
    if not re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$", value):
        raise PublishError(f"date must be YYYY-MM-DD, got {value!r}")


def changelog_section(root: Path, version: str) -> str:
    path = root / CHANGELOG
    if not path.is_file():
        raise PublishError(f"missing {path}")
    text = read_text(path)
    pattern = re.compile(
        rf"^## {re.escape(version)}(?:\s*-\s*.*)?$",
        re.MULTILINE,
    )
    match = pattern.search(text)
    if not match:
        raise PublishError(f"{CHANGELOG} has no section for {version}")
    start = match.end()
    following = H2_RE.search(text, start)
    body = text[start : following.start() if following else len(text)].strip()
    if not body:
        raise PublishError(f"{version} section in {CHANGELOG} is empty")
    return body


def read_body(root: Path, version: str, body_file: str | None) -> tuple[str, str]:
    if body_file:
        path = Path(body_file)
        if not path.is_absolute():
            path = root / path
        if not path.is_file():
            raise PublishError(f"body file not found: {path}")
        body = read_text(path).strip()
        if not body:
            raise PublishError(f"body file is empty: {path}")
        try:
            source = path.relative_to(root.resolve()).as_posix()
        except ValueError:
            source = str(path)
        return body, source
    return changelog_section(root, version), CHANGELOG


def evidence_path(docs_root: Path, version: str, day: str) -> Path:
    return docs_root / "records" / f"{day[:7]}-release-{version}"


def release_options(
    provider: str,
    *,
    draft: bool = False,
    prerelease: bool = False,
    latest: bool = False,
) -> dict:
    if provider != "github" and (draft or prerelease or latest):
        raise PublishError(
            "--draft/--prerelease/--latest are only supported for github"
        )
    return {
        "draft": bool(draft),
        "prerelease": bool(prerelease),
        "latest": bool(latest),
    }


def auth_command(provider: str) -> list[str] | None:
    if provider == "github":
        return ["gh", "auth", "status"]
    if provider == "gitlab":
        return ["glab", "auth", "status"]
    return None


def check_auth(root: Path, provider: str) -> None:
    command = auth_command(provider)
    if command is not None:
        run(root, command)


def release_command(
    provider: str,
    *,
    tag: str,
    title: str,
    body_path: Path,
    repo: str,
    options: dict | None = None,
) -> list[str]:
    if provider == "github":
        command = [
            "gh",
            "release",
            "create",
            tag,
            "--title",
            title,
            "--notes-file",
            str(body_path),
            "--verify-tag",
        ]
        options = options or {}
        if options.get("draft"):
            command.append("--draft")
        if options.get("prerelease"):
            command.append("--prerelease")
        if options.get("latest"):
            command.append("--latest")
        if repo:
            command.extend(["--repo", repo])
        return command
    if provider == "gitlab":
        command = [
            "glab",
            "release",
            "create",
            tag,
            "--name",
            title,
            "--notes-file",
            str(body_path),
        ]
        if repo:
            command.extend(["--repo", repo])
        return command
    return []


def release_view_command(provider: str, *, tag: str, repo: str) -> list[str]:
    if provider == "github":
        command = ["gh", "release", "view", tag, "--json", "tagName"]
    elif provider == "gitlab":
        command = ["glab", "release", "view", tag]
    else:
        return []
    if repo:
        command.extend(["--repo", repo])
    return command


def release_exists(root: Path, provider: str, *, tag: str, repo: str) -> bool:
    command = release_view_command(provider, tag=tag, repo=repo)
    if not command:
        return False
    try:
        run(root, command)
    except PublishError:
        return False
    return True


def build_plan(
    root: Path,
    *,
    version: str,
    tag: str,
    body_file: str | None,
    docs_root: Path,
    day: str,
    repo: str,
    draft: bool = False,
    prerelease: bool = False,
    latest: bool = False,
) -> dict:
    validate_version(version)
    validate_date(day)
    if not docs_root.is_dir():
        raise PublishError(f"docs root is not a directory: {docs_root}")

    provider = read_provider(root)
    options = release_options(
        provider,
        draft=draft,
        prerelease=prerelease,
        latest=latest,
    )
    commit = current_commit(root)
    tag_value = tag_commit(root, tag)
    if not tag_value:
        raise PublishError(
            f"tag {tag} does not exist; create and push it before publishing"
        )
    kind = tag_kind(root, tag)
    if kind != "tag":
        raise PublishError(
            f"tag {tag} must be annotated; got {kind or 'missing'} "
            "(use git tag -a <tag> -m <message>)"
        )

    remote = remote_url(root)
    if provider != "none" and not remote:
        raise PublishError(
            f"provider {provider} requires a git remote named origin"
        )
    repository = repo or repo_slug(remote)
    if provider != "none" and not repository:
        raise PublishError(
            "cannot derive repository from origin; pass --repo OWNER/NAME"
        )

    body, body_source = read_body(root, version, body_file)

    return {
        "provider": provider,
        "version": version,
        "tag": tag,
        "tagCommit": tag_value,
        "commit": commit,
        "body": body,
        "bodySource": body_source,
        "evidence": evidence_path(docs_root, version, day),
        "remote": remote,
        "repo": repository,
        "repository": repository,
        "title": tag,
        "date": day,
        "options": options,
    }


def evidence_status(plan: dict) -> str | None:
    directory = plan["evidence"]
    if not directory.exists():
        return None
    metadata_path = directory / "release.json"
    if not metadata_path.is_file():
        raise PublishError(f"release evidence is incomplete: {directory}")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PublishError(f"release evidence is unreadable: {directory}") from exc
    status = metadata.get("status")
    if not isinstance(status, str) or not status:
        raise PublishError(f"release evidence has no status: {directory}")
    return status


def write_evidence(plan: dict, status: str, *, allow_existing: bool = False) -> Path:
    directory = plan["evidence"]
    if directory.exists():
        if not allow_existing:
            raise PublishError(f"release evidence already exists: {directory}")
        existing = evidence_status(plan)
        if existing not in {"pending", "failed"}:
            raise PublishError(f"release evidence already exists: {directory}")
        return update_evidence(plan, status)
    directory.mkdir(parents=True)
    (directory / "release-notes.md").write_text(
        plan["body"] + "\n", encoding="utf-8", newline="\n"
    )
    metadata = {
        "version": plan["version"],
        "tag": plan["tag"],
        "tagCommit": plan["tagCommit"],
        "headCommit": plan["commit"],
        "provider": plan["provider"],
        "repository": plan["repo"],
        "remote": plan["remote"],
        "bodySource": plan["bodySource"],
        "date": plan["date"],
        "options": plan.get("options", {}),
        "status": status,
    }
    (directory / "release.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (directory / "README.md").write_text(
        f"# Release {plan['version']}\n\n"
        f"- provider: `{plan['provider']}`\n"
        f"- tag: `{plan['tag']}`\n"
        f"- status: `{status}`\n"
        f"- body source: `{plan['bodySource']}`\n",
        encoding="utf-8",
        newline="\n",
    )
    return directory


def update_evidence(plan: dict, status: str) -> Path:
    directory = plan["evidence"]
    metadata_path = directory / "release.json"
    if not metadata_path.is_file():
        raise PublishError(f"release evidence is incomplete: {directory}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["status"] = status
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (directory / "README.md").write_text(
        f"# Release {plan['version']}\n\n"
        f"- provider: `{plan['provider']}`\n"
        f"- tag: `{plan['tag']}`\n"
        f"- status: `{status}`\n"
        f"- body source: `{plan['bodySource']}`\n",
        encoding="utf-8",
        newline="\n",
    )
    return directory


def apply_release(plan: dict, root: Path, *, repo: str) -> str:
    provider = plan["provider"]
    existing = evidence_status(plan)

    if provider == "none":
        if existing is not None:
            raise PublishError(f"release evidence already exists: {plan['evidence']}")
        status = "local-only"
        write_evidence(plan, status)
        return status

    check_auth(root, provider)

    if existing is not None:
        if existing in {"pending", "failed"}:
            if release_exists(root, provider, tag=plan["tag"], repo=repo):
                update_evidence(plan, "created")
                return "created"
            write_evidence(plan, "pending", allow_existing=True)
        else:
            raise PublishError(f"release evidence already exists: {plan['evidence']}")
    else:
        write_evidence(plan, "pending")

    body_fd, body_name = tempfile.mkstemp(prefix="nebula-release-", suffix=".md")
    body_path = Path(body_name)
    try:
        with os.fdopen(body_fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(plan["body"] + "\n")
        command = release_command(
            provider,
            tag=plan["tag"],
            title=plan["title"],
            body_path=body_path,
            repo=repo,
            options=plan.get("options"),
        )
        run(root, command)
    except Exception:
        try:
            update_evidence(plan, "failed")
        except PublishError:
            pass
        raise
    finally:
        body_path.unlink(missing_ok=True)

    try:
        update_evidence(plan, "created")
    except PublishError as exc:
        print(
            "warning: release exists but evidence was not marked created; "
            f"rerun --apply to reconcile: {exc}",
            file=sys.stderr,
        )
        raise
    return "created"


def print_plan(plan: dict) -> None:
    print(f"provider: {plan['provider']}")
    print(f"repository: {plan['repo'] or 'none'}")
    print(f"tag: {plan['tag']} -> {plan['tagCommit']}")
    print(f"body: {plan['bodySource']} ({len(plan['body'].splitlines())} lines)")
    print(f"evidence: {plan['evidence']}")
    options = plan.get("options", {})
    if options:
        print(f"options: {json.dumps(options, sort_keys=True)}")
    if plan["provider"] == "none":
        print("command: none (local evidence only)")
    else:
        print(f"auth: {' '.join(auth_command(plan['provider']) or [])}")
        command = release_command(
            plan["provider"],
            tag=plan["tag"],
            title=plan["title"],
            body_path=Path("<release-body.md>"),
            repo=plan["repo"],
            options=options,
        )
        print(f"command: {' '.join(command)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="publish a release body")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--version", default="")
    parser.add_argument("--tool-version", action="store_true", help="print the tool version and exit")
    parser.add_argument("--tag", default="")
    parser.add_argument("--body-file", default="")
    parser.add_argument("--docs-root", type=Path, default=None)
    parser.add_argument("--repo", default="", help="OWNER/NAME; optional")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--draft", action="store_true")
    parser.add_argument("--prerelease", action="store_true")
    parser.add_argument("--latest", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if args.tool_version:
        print(TOOL_VERSION)
        return 0
    if not args.version:
        print("--version is required", file=sys.stderr)
        return 2
    if args.docs_root is None:
        print("--docs-root is required", file=sys.stderr)
        return 2
    if args.check and args.apply:
        print("--check and --apply are mutually exclusive", file=sys.stderr)
        return 2

    root = args.root.resolve()
    docs_root = args.docs_root.resolve()
    tag = args.tag or args.version
    try:
        plan = build_plan(
            root,
            version=args.version,
            tag=tag,
            body_file=args.body_file or None,
            docs_root=docs_root,
            day=args.date,
            repo=args.repo,
            draft=args.draft,
            prerelease=args.prerelease,
            latest=args.latest,
        )
        if args.apply:
            status = apply_release(plan, root, repo=args.repo)
            print(f"release: {status}; evidence {plan['evidence']}")
            return 0
        print_plan(plan)
        return 0
    except PublishError as exc:
        print(f"release publish: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
