#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Project-local batch execution skeleton.

The tool is deliberately stack-agnostic. It owns a small state machine:

    plan -> approve -> start -> check -> pr -> merge

Checks and PR provider commands come from ``infra/tool/batch/config.json``. The
defaults only do local work; a project can add its own commands without
changing this file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[3]
STATE_DIR = ".batch"
CONFIG_REL = Path("infra") / "tool" / "batch" / "config.json"
SCAFFOLD_REL = Path(".nebula-scaffold.json")
DEFAULT_CONFIG: dict[str, Any] = {
    "base": "main",
    "branch_prefix": "batch/",
    "docs_root": "",
    "scope": {"ignore": [], "generated": []},
    "commit": {
        "types": [],
        "scopes": [],
        "body": [],
    },
    "checks": [],
    "release_checks": [],
    "pr_create": [],
    "translate": [],
    "merge": [],
}
ID_RE = re.compile(r"^(?:B[0-9]+[a-z]?|[0-9]{8}-[0-9a-f]{6})$")
DATED_ID_RE = re.compile(r"^[0-9]{8}-[0-9a-f]{6}$")
CARD_ID_RE = re.compile(r"^B[0-9]+[a-z]?$")
CARD_MARKER_RE = re.compile(r"<!--\s*batch-card\s*:\s*v1\s*-->")
CARD_JSON_RE = re.compile(r"```json[ \t]*\r?\n(.*?)\r?\n```", re.DOTALL)
PLAN_MARKER_RE = re.compile(
    r"<!--\s*planned\s*:\s*(?P<id>[A-Za-z0-9-]+)\s+(?P<hash>[0-9a-f]{8,64})\s+(?P<day>\d{4}-\d{2}-\d{2})\s*-->"
)
CARD_TYPES = {"feat", "fix", "process", "docs"}
BUDGET_DEFAULTS = {"docs": 150, "fix": 200, "process": 200, "feat": 400}
DEFAULT_BUDGET = 400
COMMIT_TYPES = ("feat", "fix", "docs", "test", "refactor", "chore", "ci")
COMMIT_SUBJECT_RE = re.compile(
    r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]+)\))?: (?P<subject>.+)$"
)
DOCS_PROCESS = "process"
DOCS_SDP = "sdp.md"
DOCS_BATCHES = "batches"
DOCS_RECORDS = "records"
RECORD_ID_RE = re.compile(r"(?<![A-Za-z0-9])B[0-9]+[a-z]?(?![A-Za-z0-9])")
ARCHIVE_DIR = "archive"
PAUSABLE_STATUSES = {"started", "checked", "check_failed"}
STAGE_SKILLS = {
    "nebula-project",
    "nebula-bootstrap",
    "nebula-requirements",
    "nebula-design",
    "nebula-verification",
    "nebula-planning",
    "nebula-delivery",
}
SKILL_ROOTS = (
    ".agents/skills",
    ".claude/skills",
    ".codex/skills",
    ".codebuddy/skills",
    ".workbuddy/skills",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def run_git(root: Path, args: Sequence[str]) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def git_required(root: Path) -> None:
    code, _, err = run_git(root, ["rev-parse", "--show-toplevel"])
    if code != 0:
        raise SystemExit(f"not a git repository: {root} ({err})")


def resolve_commit(root: Path, ref: str) -> str:
    """Resolve a branch or tag to the commit it points at, or return ""."""
    code, out, _ = run_git(root, ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"])
    return out if code == 0 else ""


def budget_anchor(root: Path, base: str, base_ref: str | None) -> str:
    """Return the commit to diff against when counting scope and budget.

    ``base`` is the branch point recorded when the batch started. If main moved
    on afterwards and the branch was cut from the newer commit, diffing against
    the old base would count the other PR's lines again. Prefer the merge base
    with the current base branch, and fall back to the recorded commit.
    """
    head = resolve_commit(root, "HEAD")
    ref = resolve_commit(root, base_ref) if base_ref else ""
    if head and ref and ref != head:
        code, out, _ = run_git(root, ["merge-base", head, ref])
        if code == 0 and out:
            return out.splitlines()[0]
    if head:
        code, out, _ = run_git(root, ["merge-base", head, base])
        if code == 0 and out:
            return out.splitlines()[0]
    return base


def config_path(root: Path) -> Path:
    return root / CONFIG_REL


def load_config(root: Path) -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    config["scope"] = dict(DEFAULT_CONFIG["scope"])
    config["commit"] = dict(DEFAULT_CONFIG["commit"])
    raw = load_json(config_path(root))
    if raw is not None:
        for key in DEFAULT_CONFIG:
            if key in raw:
                config[key] = raw[key]
    scope = config.get("scope")
    if not isinstance(scope, dict):
        raise SystemExit("config.scope must be an object")
    config["scope"] = dict(DEFAULT_CONFIG["scope"])
    for key in ("ignore", "generated"):
        value = scope.get(key, [])
        if not isinstance(value, list):
            raise SystemExit(f"config.scope.{key} must be a list")
        config["scope"][key] = [str(item) for item in value]
    if not isinstance(config.get("checks"), list):
        raise SystemExit("config.checks must be a list")
    if not isinstance(config.get("release_checks"), list):
        raise SystemExit("config.release_checks must be a list")
    commit = config.get("commit")
    if not isinstance(commit, dict):
        raise SystemExit("config.commit must be an object")
    for key in ("types", "scopes", "body"):
        value = commit.get(key, [])
        if not isinstance(value, list):
            raise SystemExit(f"config.commit.{key} must be a list")
    for key in ("pr_create", "translate", "merge"):
        value = config.get(key)
        if value and not isinstance(value, list):
            raise SystemExit(f"config.{key} must be a command array")
    return config


def scaffold_git(root: Path) -> dict[str, Any]:
    """Read the optional ``git`` preset written by bootstrap."""
    data = load_json(root / SCAFFOLD_REL) or {}
    block = data.get("git")
    return block if isinstance(block, dict) else {}


def commit_rule(root: Path, config: dict[str, Any]) -> dict[str, Any]:
    """Merge ``config.commit`` over the scaffold preset.

    An empty rule means "not configured": nothing is checked.
    """
    preset = scaffold_git(root)
    own = config.get("commit") or {}
    types = [str(item) for item in (own.get("types") or preset.get("types") or [])]
    scopes = [str(item) for item in (own.get("scopes") or preset.get("scopes") or [])]
    body = [str(item) for item in (own.get("body") or preset.get("body") or [])]
    return {
        "types": types,
        "scopes": scopes,
        "body": body,
        "enabled": bool(types or scopes or body),
    }


def state_root(root: Path) -> Path:
    return root / STATE_DIR


def batch_dir(root: Path, batch_id: str) -> Path:
    return state_root(root) / batch_id


def active_id(root: Path) -> str | None:
    path = state_root(root) / "active"
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def clear_active(root: Path) -> None:
    path = state_root(root) / "active"
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def set_active(root: Path, batch_id: str) -> None:
    write_text(state_root(root) / "active", batch_id + "\n")


def current_branch(root: Path) -> str:
    code, out, _ = run_git(root, ["branch", "--show-current"])
    return out if code == 0 else ""


def branch_exists(root: Path, branch: str) -> bool:
    if not branch:
        return False
    code, _, _ = run_git(
        root, ["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"]
    )
    return code == 0


def batch_branch_mismatch(root: Path, state: dict[str, Any], batch_id: str) -> str | None:
    """Explain why HEAD is not on the branch recorded when the batch started."""
    if state.get("branch_created") is not True:
        return None
    branch = str(state.get("branch") or "")
    if not branch:
        return None
    here = current_branch(root)
    if here == branch:
        return None
    return (
        f"batch {batch_id} is on branch {branch}, but HEAD is on "
        f"{here or 'a detached HEAD'}; run: git switch {branch}"
    )


def archive_aborted(root: Path, batch_id: str) -> bool:
    """Move an aborted batch aside so the same id can be planned again."""
    target = batch_dir(root, batch_id)
    state = load_json(target / "state.json") or {}
    if state.get("status") != "aborted":
        return False
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive = state_root(root) / ARCHIVE_DIR / f"{batch_id}-{stamp}"
    archive.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(target), str(archive))
    print(f"archived aborted batch {batch_id} to .batch/{ARCHIVE_DIR}/{archive.name}")
    return True


def resolve_id(root: Path, value: str | None) -> str:
    if value:
        if not ID_RE.fullmatch(value):
            raise SystemExit(f"invalid batch id: {value}")
        if not batch_dir(root, value).is_dir():
            raise SystemExit(f"batch not found: {value}")
        return value
    active = active_id(root)
    if active:
        return active
    if not state_root(root).is_dir():
        raise SystemExit("no batch found; run 'plan' first")
    candidates = sorted(
        (
            path.name
            for path in state_root(root).iterdir()
            if path.is_dir() and ID_RE.fullmatch(path.name)
        ),
        key=batch_sort_key,
    )
    if not candidates:
        raise SystemExit("no batch found; run 'plan' first")
    if len(candidates) > 1:
        raise SystemExit(
            f"multiple batches found ({', '.join(candidates)}); "
            "pass the batch id explicitly"
        )
    return candidates[0]


def batch_sort_key(value: str) -> tuple[int, int, str]:
    match = re.fullmatch(r"B([0-9]+)([a-z]?)", value)
    if match:
        return (0, int(match.group(1)), match.group(2))
    return (1, 0, value)


def branch_slug(value: str, limit: int = 40) -> str:
    """Turn a goal into a branch-name slug; empty when nothing ASCII is left."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:limit].strip("-")


def new_id(root: Path) -> str:
    prefix = datetime.now().strftime("%Y%m%d")
    for _ in range(50):
        candidate = f"{prefix}-{secrets.token_hex(3)}"
        if not batch_dir(root, candidate).exists():
            return candidate
    raise SystemExit("could not allocate a batch id")


def parse_list(values: list[str] | None, default: list[str]) -> list[str]:
    out: list[str] = []
    for value in values or []:
        for item in value.replace(";", ",").split(","):
            item = item.strip()
            if item and item not in out:
                out.append(item)
    return out or default


def card_hash(card: dict[str, Any]) -> str:
    canonical = json.dumps(card, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def read_card(root: Path, batch_id: str) -> dict[str, Any]:
    card = load_json(batch_dir(root, batch_id) / "card.json")
    if card is None:
        raise SystemExit(f"card not found: {batch_id}")
    return card


def source_relative(root: Path, path: Path) -> str:
    return Path(os.path.relpath(path, root)).as_posix()


def inside_project(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_card_hash(path: Path) -> str:
    """Hash a card source, ignoring the ``planned`` marker line."""
    text = path.read_text(encoding="utf-8", errors="replace")
    clean = PLAN_MARKER_RE.sub("", text).rstrip()
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()


def source_hashes(path: Path) -> set[str]:
    raw = path.read_bytes()
    text = path.read_text(encoding="utf-8", errors="replace")
    clean = PLAN_MARKER_RE.sub("", text).rstrip()
    return {
        hashlib.sha256(raw).hexdigest(),
        hashlib.sha256(clean.encode("utf-8")).hexdigest(),
    }


def plan_marker_hash(path: Path, batch_id: str) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError):
        return None
    for match in PLAN_MARKER_RE.finditer(text):
        if match.group("id") == batch_id:
            return match.group("hash")
    return None


def write_plan_marker(path: Path, batch_id: str, digest: str, day: str) -> None:
    text = path.read_text(encoding="utf-8")
    text = PLAN_MARKER_RE.sub("", text).rstrip() + "\n"
    text += f"<!-- planned: {batch_id} {digest[:8]} {day} -->\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def card_source_path(root: Path, card: dict[str, Any]) -> Path | None:
    source = card.get("source")
    if not source:
        return None
    return (root / str(source)).resolve()


def source_is_current(root: Path, card: dict[str, Any]) -> tuple[bool, str]:
    if card.get("legacy"):
        return False, "legacy card is read-only"
    path = card_source_path(root, card)
    if path is None:
        return True, ""
    if not path.is_file():
        return False, f"card source is missing: {card.get('source')}"
    expected = str(card.get("source_sha256", ""))
    if expected not in source_hashes(path):
        return False, "card source changed; re-plan and re-approve"
    return True, ""


def validate_planned_card(
    card: dict[str, Any], path: Path | None = None, types: set[str] | None = None
) -> None:
    def fail(message: str) -> None:
        raise ValueError(message)

    if not isinstance(card, dict):
        fail("card must be a JSON object")
    if card.get("legacy"):
        fail("legacy cards cannot be planned from a card source")
    required = (
        "id",
        "goal",
        "type",
        "base",
        "allowed",
        "acceptance",
        "changelog",
        "skills",
    )
    missing = [key for key in required if key not in card]
    if missing:
        fail(f"missing field(s): {', '.join(missing)}")

    card_id = card.get("id")
    if not isinstance(card_id, str) or not CARD_ID_RE.fullmatch(card_id):
        fail("id must be B followed by digits")
    if path is not None and path.stem != card_id:
        fail(f"card id {card_id} does not match file stem {path.stem}")

    if not isinstance(card.get("goal"), str) or not card["goal"].strip():
        fail("goal must be a non-empty string")
    if "pr_title" in card:
        pr_title = card.get("pr_title")
        if not isinstance(pr_title, str) or not pr_title.strip():
            fail("pr_title must be a non-empty string")
        if "\n" in pr_title or "\r" in pr_title:
            fail("pr_title must be a single line")
    allowed = types or CARD_TYPES
    if card.get("type") not in allowed:
        fail(f"type must be one of: {', '.join(sorted(allowed))}")
    base = card.get("base")
    if not isinstance(base, str) or not base.strip() or any(ch.isspace() for ch in base):
        fail("base must be a non-empty branch name")

    if "size_budget" in card:
        budget = card.get("size_budget")
        if type(budget) is not int or budget < 1:
            fail("size_budget must be an integer greater than zero")
    else:
        card["size_budget"] = BUDGET_DEFAULTS.get(str(card.get("type")), DEFAULT_BUDGET)
        card["size_budget_default"] = True
    if "release" in card and not isinstance(card["release"], bool):
        fail("release must be a boolean")

    for key, allow_empty in (("allowed", False), ("forbidden", True)):
        if key not in card and key == "forbidden":
            continue
        value = card.get(key)
        if not isinstance(value, list) or (not allow_empty and not value):
            fail(f"{key} must be a non-empty array")
        if not all(isinstance(item, str) and item.strip() for item in value):
            fail(f"{key} must contain non-empty strings")

    for key in ("acceptance", "changelog"):
        value = card.get(key)
        if not isinstance(value, list) or (key == "acceptance" and not value):
            fail(f"{key} must be a non-empty array")
        if not all(isinstance(item, str) and item.strip() for item in value):
            fail(f"{key} must contain non-empty strings")

    skills = card.get("skills")
    if not isinstance(skills, list) or len(skills) > 4:
        fail("skills must be an array with at most four entries")
    for item in skills:
        if not isinstance(item, dict):
            fail("each skill must be an object")
        skill_id = item.get("id")
        if not isinstance(skill_id, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9-]*", skill_id
        ):
            fail("skill id must be lower-case kebab-case")
        if skill_id == "using-agent-skills":
            fail("using-agent-skills is never installable")
        if skill_id in STAGE_SKILLS:
            fail(f"stage skill {skill_id} is not declared in a batch card")
        if not isinstance(item.get("required"), bool):
            fail(f"skill {skill_id}: required must be a boolean")
        if "reason" in item and not isinstance(item["reason"], str):
            fail(f"skill {skill_id}: reason must be a string")


def read_planned_card(
    path: Path, types: set[str] | None = None
) -> tuple[dict[str, Any], bytes]:
    data = path.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"card is not UTF-8: {exc}") from exc
    marker = CARD_MARKER_RE.search(text)
    if marker is None:
        raise ValueError("missing <!-- batch-card: v1 --> marker")
    block = CARD_JSON_RE.search(text, marker.end())
    if block is None:
        raise ValueError("missing fenced json block after the card marker")
    try:
        card = json.loads(block.group(1))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid card JSON: {exc}") from exc
    validate_planned_card(card, path, types)
    return card, data


def docs_root_from_card(source: Path) -> Path | None:
    """Return the docs root for a card at ``<docs>/process/batches/B<n>.md``."""
    parent = source.parent
    if parent.name == DOCS_BATCHES and parent.parent.name == DOCS_PROCESS:
        return parent.parent.parent
    return None


def configured_docs_root(root: Path, config: dict[str, Any]) -> Path | None:
    value = str(config.get("docs_root", "") or "").strip()
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else root / path


def sdp_batch_ids(sdp: Path) -> set[str]:
    """Read the ``| Batch |`` table and return the ids it lists."""
    lines = sdp.read_text(encoding="utf-8", errors="replace").splitlines()
    start = next(
        (
            index
            for index, line in enumerate(lines)
            if line.strip().startswith("| Batch |")
        ),
        None,
    )
    if start is None:
        return set()
    ids: set[str] = set()
    for line in lines[start + 1:]:
        stripped = line.strip()
        if not stripped.startswith("|"):
            break
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells:
            continue
        ident = cells[0].strip("` ")
        if CARD_ID_RE.fullmatch(ident):
            ids.add(ident)
    return ids


def docs_batch_ids(docs_root: Path, exclude: Path | None = None) -> dict[str, Path]:
    """Map every id already used in the docs repo to the path that uses it."""
    taken: dict[str, Path] = {}
    batches = docs_root / DOCS_PROCESS / DOCS_BATCHES
    if batches.is_dir():
        for path in sorted(batches.glob("B*.md")):
            match = re.fullmatch(r"(B[0-9]+[a-z]?)\.md", path.name)
            if match is None:
                continue
            if exclude is not None and path.resolve() == exclude:
                continue
            taken.setdefault(match.group(1), path)
    records = docs_root / DOCS_RECORDS
    if records.is_dir():
        for path in sorted(records.rglob("*")):
            match = RECORD_ID_RE.search(path.name)
            if match:
                taken.setdefault(match.group(0), path)
    return taken


def next_batch_id(ids: set[str]) -> str:
    highest = 0
    for value in ids:
        match = re.fullmatch(r"B([0-9]+)[a-z]?", value)
        if match:
            highest = max(highest, int(match.group(1)))
    return f"B{highest + 1}"


def duplicate_id_error(
    root: Path, card: dict[str, Any], config: dict[str, Any], batch_id: str
) -> str:
    """Return an error when another card or record already claims this id."""
    source = card_source_path(root, card)
    docs_root = configured_docs_root(root, config)
    if docs_root is None and source is not None:
        docs_root = docs_root_from_card(source)
    if docs_root is None or not docs_root.is_dir():
        return ""
    taken = docs_batch_ids(docs_root, exclude=source)
    if batch_id in taken:
        return f"batch id {batch_id} is already used by {taken[batch_id]}"
    return ""


def read_state(root: Path, batch_id: str) -> dict[str, Any]:
    state = load_json(batch_dir(root, batch_id) / "state.json")
    if state is None:
        raise SystemExit(f"batch not started: {batch_id}")
    return state


def glob_regex(pattern: str) -> re.Pattern[str]:
    i = 0
    out = ""
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile("^" + out + "$")


def matches(path: str, patterns: Sequence[str]) -> bool:
    normalized = path.replace("\\", "/")
    return any(glob_regex(pattern).fullmatch(normalized) for pattern in patterns)


def changed_paths(root: Path, anchor: str, config: dict[str, Any]) -> list[str]:
    paths: set[str] = set()
    for args in (
        ["diff", "--name-only", anchor],
        ["ls-files", "--others", "--exclude-standard"],
    ):
        code, out, _ = run_git(root, args)
        if code != 0:
            continue
        paths.update(line.strip() for line in out.splitlines() if line.strip())

    ignored = list(DEFAULT_CONFIG["scope"]["ignore"])
    ignored.extend(DEFAULT_CONFIG["scope"]["generated"])
    scope = config.get("scope")
    if isinstance(scope, dict):
        ignored.extend(str(item) for item in scope.get("ignore", []))
        ignored.extend(str(item) for item in scope.get("generated", []))
    ignored.extend([".batch/**", ".batch"])
    return sorted(
        path
        for path in paths
        if not matches(path, ignored) and path != ".batch"
    )


def check_scope(
    root: Path, card: dict[str, Any], anchor: str, config: dict[str, Any]
) -> tuple[list[str], list[str]]:
    allowed = [str(item) for item in card.get("allowed", [])] or ["**"]
    forbidden = [str(item) for item in card.get("forbidden", [])]
    changed = changed_paths(root, anchor, config)
    violations: list[str] = []
    for path in changed:
        if matches(path, forbidden):
            violations.append(f"forbidden: {path}")
        elif not matches(path, allowed):
            violations.append(f"out of scope: {path}")
    return changed, violations


def installed_skill(root: Path, skill_id: str) -> Path | None:
    for relative in SKILL_ROOTS:
        path = root / relative / skill_id / "SKILL.md"
        if path.is_file():
            return path
    return None


def check_skills(root: Path, card: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    violations: list[str] = []
    found: dict[str, str] = {}
    for item in card.get("skills", []):
        skill_id = str(item.get("id", ""))
        path = installed_skill(root, skill_id)
        if path is None:
            violations.append(f"skill {skill_id}: not installed in this project")
        else:
            found[skill_id] = source_relative(root, path)
    return violations, found


SKILL_EVIDENCE_DIR = Path("evidence") / "skills"
SKILL_EVIDENCE_STATUSES = {"applied", "partial", "skipped"}
VAGUE_CHANGE = {
    "applied",
    "used",
    "read",
    "loaded",
    "yes",
    "no",
    "n/a",
    "na",
    "none",
    "-",
    "skill applied",
    "used the skill",
    "read the skill",
    "loaded the skill",
}


def skill_evidence_path(root: Path, batch_id: str, skill_id: str) -> Path:
    return batch_dir(root, batch_id) / SKILL_EVIDENCE_DIR / f"{skill_id}.md"


def read_skill_evidence(path: Path) -> dict[str, str]:
    fields: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return fields
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip().lower()] = value.strip()
    return fields


def proof_looks_like_path(proof: str) -> bool:
    if proof.startswith(("http://", "https://")):
        return False
    if not re.fullmatch(r"[A-Za-z0-9_./-]+(?::[0-9]+)?", proof):
        return False
    return "/" in proof or "." in proof


def check_skill_evidence(
    root: Path, batch_id: str, card: dict[str, Any]
) -> tuple[list[str], list[str], dict[str, dict[str, Any]]]:
    errors: list[str] = []
    warnings: list[str] = []
    records: dict[str, dict[str, Any]] = {}
    for item in card.get("skills", []):
        skill_id = str(item.get("id", ""))
        required = bool(item.get("required"))
        path = skill_evidence_path(root, batch_id, skill_id)
        relative = source_relative(root, path)
        if not path.is_file():
            if required:
                errors.append(
                    f"skill {skill_id}: missing evidence file {relative} "
                    "(status, changed, proof)"
                )
            continue
        fields = read_skill_evidence(path)
        status = fields.get("status", "").lower()
        changed = fields.get("changed", "")
        proof = fields.get("proof", "")
        if status not in SKILL_EVIDENCE_STATUSES:
            errors.append(
                f"skill {skill_id}: evidence status must be applied, partial, or skipped"
            )
        if not changed or changed.strip().lower() in VAGUE_CHANGE:
            errors.append(
                f"skill {skill_id}: 'changed' must say what changed, "
                "not repeat the status"
            )
        elif len(changed) < 12:
            warnings.append(f"skill {skill_id}: 'changed' is very short")
        if not proof:
            errors.append(f"skill {skill_id}: 'proof' is empty")
        elif proof_looks_like_path(proof):
            target = proof.split(":", 1)[0]
            if not (root / target).exists():
                errors.append(f"skill {skill_id}: proof path does not exist: {proof}")
        if required and status == "skipped":
            errors.append(f"skill {skill_id}: a required skill cannot be skipped")
        records[skill_id] = {
            "status": status,
            "changed": changed,
            "proof": proof,
            "required": required,
            "file": relative,
        }
    return errors, warnings, records


def diff_stats(
    root: Path, anchor: str, changed: Sequence[str]
) -> tuple[int, int, int]:
    code, out, err = run_git(root, ["diff", "--numstat", "--no-renames", anchor])
    if code != 0:
        raise SystemExit(f"could not count batch diff: {err}")
    allowed = set(changed)
    added = 0
    deleted = 0
    binary = 0
    seen: set[str] = set()
    for line in out.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        raw_added, raw_deleted, path = parts
        path = path.replace("\\", "/")
        if path not in allowed:
            continue
        seen.add(path)
        if raw_added == "-" or raw_deleted == "-":
            binary += 1
            continue
        added += int(raw_added)
        deleted += int(raw_deleted)

    for path in changed:
        if path in seen:
            continue
        target = root / path
        if not target.is_file():
            continue
        data = target.read_bytes()
        if b"\0" in data:
            binary += 1
            continue
        added += data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
    return added, deleted, binary


def check_budget(
    root: Path, card: dict[str, Any], anchor: str, changed: Sequence[str]
) -> tuple[int, int, int, str | None]:
    budget = card.get("size_budget")
    if type(budget) is not int or budget < 1:
        return 0, 0, 0, None
    added, deleted, binary = diff_stats(root, anchor, changed)
    total = added + deleted
    if total > budget:
        message = f"budget: {total} changed lines exceeds {budget}"
        if binary:
            message += f" ({binary} binary file(s) not counted)"
        return added, deleted, binary, message
    return added, deleted, binary, None


def commit_subjects(root: Path, anchor: str) -> list[tuple[str, str, str]]:
    """Return (short sha, subject, body) for the commits this branch adds."""
    code, out, _ = run_git(
        root,
        ["log", "--no-merges", "--format=%h%x1f%s%x1f%b%x1e", f"{anchor}..HEAD"],
    )
    if code != 0:
        return []
    rows = []
    for record in out.split("\x1e"):
        line = record.strip("\n")
        if not line:
            continue
        sha, _, rest = line.partition("\x1f")
        subject, _, body = rest.partition("\x1f")
        if sha:
            rows.append((sha, subject, body))
    return rows


def subject_problems(
    rule: dict[str, Any], sha: str, subject: str, body: str
) -> list[str]:
    """Return every complaint about one commit message."""
    problems: list[str] = []
    match = COMMIT_SUBJECT_RE.match(subject)
    if not match:
        return [f"{sha}: subject must read type(scope): subject: {subject}"]
    kind = match.group("type")
    scope = match.group("scope")
    if rule["types"] and kind not in rule["types"]:
        problems.append(
            f"{sha}: type '{kind}' is not one of: {', '.join(rule['types'])}"
        )
    if rule["scopes"] and not scope:
        problems.append(
            f"{sha}: missing scope; choose one of: {', '.join(rule['scopes'])}"
        )
    if scope and rule["scopes"] and scope not in rule["scopes"]:
        problems.append(
            f"{sha}: scope '{scope}' is not one of: {', '.join(rule['scopes'])}"
        )
    missing = [token for token in rule["body"] if token not in body]
    if missing:
        problems.append(
            f"{sha}: commit body must contain {', '.join(missing)} "
            f"(write 'Batch: none' when there is no batch)"
        )
    return problems


def check_commit_titles(
    root: Path, anchor: str, config: dict[str, Any]
) -> list[str]:
    """Check every commit the branch adds against the configured rule."""
    rule = commit_rule(root, config)
    if not rule["enabled"]:
        return []
    problems: list[str] = []
    for sha, subject, body in commit_subjects(root, anchor):
        problems.extend(subject_problems(rule, sha, subject, body))
    return problems


def check_merged_commit(root: Path, config: dict[str, Any]) -> list[str]:
    """Check the squash commit that just landed on the base branch.

    This runs after the merge, so it can only report; it never blocks.
    """
    rule = commit_rule(root, config)
    if not rule["enabled"]:
        return []
    code, out, _ = run_git(
        root, ["log", "-1", "--format=%h%x1f%s%x1f%b"]
    )
    if code != 0 or not out.strip():
        return []
    sha, _, rest = out.partition("\x1f")
    subject, _, body = rest.partition("\x1f")
    return subject_problems(rule, sha, subject, body)


def check_changelog(
    root: Path, card: dict[str, Any], changed: Sequence[str]
) -> tuple[list[str], list[str]]:
    violations: list[str] = []
    warnings: list[str] = []
    card_type = str(card.get("type", ""))
    paths = [str(item) for item in card.get("changelog", [])]
    uses_changelog = (root / "changelog.d").is_dir()
    if card_type in {"feat", "fix"} and uses_changelog and not paths:
        violations.append("changelog: feat/fix must declare at least one fragment")
    if card_type in {"feat", "fix"} and not uses_changelog:
        warnings.append("changelog.d is absent; no fragment was required")

    changed_set = set(changed)
    for raw in paths:
        path = Path(raw)
        normalized = path.as_posix()
        if path.is_absolute() or ".." in path.parts:
            violations.append(f"changelog: path must stay inside the project: {raw}")
            continue
        if not normalized.startswith("changelog.d/"):
            violations.append(f"changelog: fragment must live under changelog.d/: {raw}")
            continue
        target = root / normalized
        if not target.is_file():
            violations.append(f"changelog: missing fragment: {raw}")
            continue
        if normalized not in changed_set:
            violations.append(f"changelog: fragment was not changed by this batch: {raw}")
            continue
        try:
            content = target.read_text(encoding="utf-8").strip()
        except UnicodeDecodeError:
            violations.append(f"changelog: fragment is not UTF-8: {raw}")
            continue
        if not content:
            violations.append(f"changelog: empty fragment: {raw}")
    return violations, warnings


def append_evidence(root: Path, batch_id: str, line: str) -> None:
    path = batch_dir(root, batch_id) / "evidence.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"[{utc_now()}] {line}\n")


def command_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return shlex.split(value)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    raise SystemExit("command must be a string or an array of strings")


def run_hook(
    root: Path, command: Sequence[str], values: dict[str, str]
) -> tuple[int, str, str]:
    merged = {"pr": "", **values}
    resolved = [
        re.sub(
            r"\{([a-z]+)\}",
            lambda match: str(merged.get(match.group(1), match.group(0))),
            item,
        )
        for item in command
    ]
    proc = subprocess.run(
        resolved,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def run_checks(
    root: Path, batch_id: str, checks: list[Any]
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for item in checks:
        if not isinstance(item, dict):
            raise SystemExit("each check must be an object")
        name = str(item.get("name", "")).strip()
        if not name or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            raise SystemExit(f"invalid check name: {name!r}")
        command = command_list(item.get("command"))
        timeout = int(item.get("timeout", 600))
        raw_cwd = str(item.get("cwd", ".") or ".").strip() or "."
        check_cwd = (root / raw_cwd).resolve()
        try:
            check_cwd.relative_to(root.resolve())
        except ValueError:
            raise SystemExit(f"check {name}: cwd escapes project root: {raw_cwd}")
        try:
            proc = subprocess.run(
                command,
                cwd=check_cwd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
            status = "pass" if proc.returncode == 0 else "fail"
            output = (proc.stdout + proc.stderr).strip()
            code = proc.returncode
        except subprocess.TimeoutExpired:
            status, output, code = "fail", f"timeout after {timeout}s", 124
        log = batch_dir(root, batch_id) / "evidence" / f"{name}.log"
        write_text(log, output + ("\n" if output else ""))
        results[name] = {"status": status, "exit": code, "at": utc_now()}
        append_evidence(root, batch_id, f"check {name}: {status.upper()} (exit {code})")
        print(f"[{status}] check {name}")
        if status == "fail":
            print(output[-2000:], file=sys.stderr)
    return results


def print_status(root: Path, batch_id: str, as_json: bool) -> None:
    card = read_card(root, batch_id)
    state = load_json(batch_dir(root, batch_id) / "state.json") or {}
    status = state.get("status") or ("legacy" if card.get("legacy") else "planned")
    payload = {
        "id": batch_id,
        "goal": card.get("goal"),
        "card_hash": card_hash(card)[:8],
        "status": status,
        "base": state.get("base"),
        "branch": state.get("branch"),
        "checks": state.get("checks", {}),
        "active": active_id(root) == batch_id,
        "legacy": bool(card.get("legacy")),
        "source": card.get("source"),
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(f"batch:  {batch_id}")
    print(f"goal:   {payload['goal'] or ''}")
    print(f"hash:   {payload['card_hash']}")
    print(f"status: {payload['status']}")
    if payload["base"]:
        print(f"base:   {payload['base']}")
    if payload["branch"]:
        print(f"branch: {payload['branch']}")
    if payload["source"]:
        print(f"source: {payload['source']}")
    if payload["checks"]:
        for name, result in payload["checks"].items():
            print(f"check:  {name} = {result.get('status')}")
    print(f"active: {'yes' if payload['active'] else 'no'}")


def cmd_plan(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    git_required(root)

    if args.source:
        extra = args.goal or args.allowed or args.forbidden or args.exit_criterion
        if extra:
            print(
                "--from cannot be combined with --goal, --allowed, --forbidden, "
                "or --exit-criterion",
                file=sys.stderr,
            )
            return 2
        source = Path(args.source)
        source = source if source.is_absolute() else root / source
        source = source.resolve()
        if not source.is_file():
            print(f"card source not found: {source}", file=sys.stderr)
            return 2
        config = load_config(root)
        rule = commit_rule(root, config)
        try:
            card, raw = read_planned_card(
                source, set(rule["types"]) if rule["types"] else None
            )
        except ValueError as exc:
            print(f"invalid card: {exc}", file=sys.stderr)
            return 2
        batch_id = card["id"]
        if args.id and args.id != batch_id:
            print(f"--id {args.id} does not match card id {batch_id}", file=sys.stderr)
            return 2
        target = batch_dir(root, batch_id)
        refresh = target.exists() and not archive_aborted(root, batch_id)
        if refresh:
            previous = load_json(target / "card.json")
            if previous is not None and previous.get("legacy"):
                print(f"batch already exists: {batch_id}", file=sys.stderr)
                return 1
            state = load_json(target / "state.json")
            if state is not None and state.get("status") not in {"planned", "approved"}:
                print(
                    f"batch already started: {batch_id} "
                    f"({state.get('status')}); abort it or use a new id",
                    file=sys.stderr,
                )
                return 1
        docs_root = configured_docs_root(root, config) or docs_root_from_card(source)
        if docs_root is None:
            print(
                "warning: docs repo not found; skipped SDP and duplicate-id checks",
                file=sys.stderr,
            )
        else:
            sdp = docs_root / DOCS_PROCESS / DOCS_SDP
            if not sdp.is_file():
                print(f"SDP not found: {sdp}", file=sys.stderr)
                return 2
            planned = sdp_batch_ids(sdp)
            if not planned:
                print(f"no '| Batch |' table in {sdp}", file=sys.stderr)
                return 2
            if batch_id not in planned:
                print(
                    f"card {batch_id} is not in the SDP batch table: {sdp}",
                    file=sys.stderr,
                )
                return 1
            taken = docs_batch_ids(docs_root, exclude=source)
            if batch_id in taken:
                print(
                    f"batch id {batch_id} is already used by {taken[batch_id]}",
                    file=sys.stderr,
                )
                print(
                    f"next unused id: {next_batch_id(planned | set(taken))}",
                    file=sys.stderr,
                )
                return 1
        snapshot = dict(card)
        snapshot["source"] = source_relative(root, source)
        snapshot["source_sha256"] = source_card_hash(source)
        digest = card_hash(snapshot)
        if refresh:
            previous = load_json(target / "card.json") or {}
            changed = [
                key
                for key in sorted(set(previous) | set(snapshot))
                if key not in {"source", "source_sha256"}
                and previous.get(key) != snapshot.get(key)
            ]
            if not changed and previous.get("source_sha256") == snapshot["source_sha256"]:
                write_plan_marker(source, batch_id, digest, utc_now()[:10])
                print(f"unchanged {batch_id}")
                print(f"hash: {digest[:8]}")
                return 0
            write_json(target / "card.json", snapshot)
            (target / "approval.json").unlink(missing_ok=True)
            print(f"updated {batch_id}: {', '.join(changed) or 'card source only'}")
            print("approval cleared; run: batch.py approve " + batch_id)
            print(f"hash: {digest[:8]}")
            write_plan_marker(source, batch_id, digest, utc_now()[:10])
            return 0
        write_json(target / "card.json", snapshot)
        write_plan_marker(source, batch_id, digest, utc_now()[:10])
        print(f"planned {batch_id} from {snapshot['source']}")
        print(f"hash: {digest[:8]}")
        return 0

    if not args.goal:
        print("plan needs --from or --goal", file=sys.stderr)
        return 2
    if args.id and CARD_ID_RE.fullmatch(args.id):
        print("planned B<n> cards require --from", file=sys.stderr)
        return 2
    batch_id = args.id or new_id(root)
    if not DATED_ID_RE.fullmatch(batch_id):
        print("ad-hoc id must be YYYYMMDD-<6 hex>", file=sys.stderr)
        return 2
    target = batch_dir(root, batch_id)
    if target.exists() and not archive_aborted(root, batch_id):
        print(f"batch already exists: {batch_id}", file=sys.stderr)
        return 1
    config = load_config(root)
    card = {
        "id": batch_id,
        "goal": args.goal,
        "type": "process",
        "base": str(config.get("base", "main")),
        "size_budget": 0,
        "allowed": parse_list(args.allowed, ["**"]),
        "forbidden": parse_list(args.forbidden, []),
        "acceptance": parse_list(args.exit_criterion, []),
        "changelog": [],
        "skills": [],
        "ad_hoc": True,
        "created_at": utc_now(),
    }
    write_json(target / "card.json", card)
    print(f"planned {batch_id}")
    print(f"hash: {card_hash(card)[:8]}")
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    batch_id = resolve_id(root, args.id)
    card = read_card(root, batch_id)
    if card.get("legacy"):
        print("legacy cards are read-only and cannot be approved", file=sys.stderr)
        return 1
    current, message = source_is_current(root, card)
    if not current:
        print(message, file=sys.stderr)
        return 1
    digest = card_hash(card)
    if args.confirm != digest[:8]:
        print(f"confirm mismatch: expected {digest[:8]}", file=sys.stderr)
        return 1
    approval = {
        "batch": batch_id,
        "card_hash": digest,
        "source_sha256": card.get("source_sha256"),
        "approved_by": args.by,
        "approved_at": utc_now(),
    }
    write_json(batch_dir(root, batch_id) / "approval.json", approval)
    print(f"approved {batch_id}")
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    git_required(root)
    batch_id = resolve_id(root, args.id)
    card = read_card(root, batch_id)
    if card.get("legacy"):
        print("legacy cards are read-only and cannot be started", file=sys.stderr)
        return 1
    approval = load_json(batch_dir(root, batch_id) / "approval.json")
    if approval is None or approval.get("card_hash") != card_hash(card):
        print("card is not approved (or approval is stale)", file=sys.stderr)
        return 1
    if approval.get("source_sha256") != card.get("source_sha256"):
        print("card source is not approved (or approval is stale)", file=sys.stderr)
        return 1
    current_source, message = source_is_current(root, card)
    if not current_source:
        print(message, file=sys.stderr)
        return 1
    current = active_id(root)
    if current:
        current_state = read_state(root, current)
        if current_state.get("status") in {"merged", "aborted"}:
            clear_active(root)
            print(
                f"cleared stale active batch {current} "
                f"({current_state.get('status')})"
            )
        else:
            print(f"another batch is active: {current}", file=sys.stderr)
            return 1

    config = load_config(root)
    base_ref = args.base or str(card.get("base") or config.get("base", "main"))
    base = resolve_commit(root, base_ref)
    if not base:
        print(f"base does not resolve to a commit: {base_ref}", file=sys.stderr)
        return 1
    skill_errors, skill_found = check_skills(root, card)
    if skill_errors:
        for item in skill_errors:
            print(item, file=sys.stderr)
        return 1
    slug = branch_slug(str(card.get("goal", "")))
    default_branch = f"{config.get('branch_prefix', 'batch/')}{batch_id}"
    if slug:
        default_branch = f"{default_branch}-{slug}"
    branch = args.branch or default_branch
    here = current_branch(root)
    prefix = str(config.get("branch_prefix", "batch/"))
    if not args.no_branch and here.startswith(prefix):
        print(
            f"you are on batch branch {here}; "
            f"switch to {base_ref} before starting another batch",
            file=sys.stderr,
        )
        return 1
    if not args.no_branch:
        code, _, err = run_git(root, ["switch", "-c", branch])
        if code != 0:
            print(f"could not create branch {branch}: {err}", file=sys.stderr)
            return 1

    state = {
        "batch": batch_id,
        "status": "started",
        "base": base,
        "base_ref": base_ref,
        "branch": branch,
        "branch_created": not args.no_branch,
        "card_hash": card_hash(card),
        "source_sha256": card.get("source_sha256"),
        "started_at": utc_now(),
        "skills": skill_found,
        "checks": {},
    }
    write_json(batch_dir(root, batch_id) / "state.json", state)
    set_active(root, batch_id)
    print(f"started {batch_id} on {branch} (base {base})")
    if skill_found:
        print("skills to load before editing:")
        for item in card.get("skills", []):
            skill_id = str(item.get("id", ""))
            plan = "required" if item.get("required") else "optional"
            print(f"  - {skill_id} ({plan})  {skill_found.get(skill_id, '')}")
        print(
            f"record each skill in .batch/{batch_id}/evidence/skills/<skill-id>.md"
        )
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    git_required(root)
    batch_id = resolve_id(root, args.id)
    card = read_card(root, batch_id)
    state = read_state(root, batch_id)
    mismatch = batch_branch_mismatch(root, state, batch_id)
    if mismatch:
        print(mismatch, file=sys.stderr)
        return 1
    if card.get("legacy"):
        print("legacy cards are read-only and cannot be checked", file=sys.stderr)
        return 1
    approval = load_json(batch_dir(root, batch_id) / "approval.json")
    if approval is None or approval.get("card_hash") != card_hash(card):
        print("card is not approved (or approval is stale)", file=sys.stderr)
        return 1
    current, message = source_is_current(root, card)
    if not current:
        state["status"] = "check_failed"
        state["source_error"] = message
        state["checked_at"] = utc_now()
        write_json(batch_dir(root, batch_id) / "state.json", state)
        append_evidence(root, batch_id, f"source: FAIL ({message})")
        print(message, file=sys.stderr)
        return 1
    source_path = card_source_path(root, card)
    if source_path is not None and source_path.is_file():
        marker = plan_marker_hash(source_path, batch_id)
        if marker and not card_hash(card).startswith(marker):
            print(
                f"[warn] card marker {marker} does not match the planned hash "
                f"{card_hash(card)[:8]}; re-plan",
                file=sys.stderr,
            )
    config = load_config(root)
    release = bool(card.get("release")) or bool(getattr(args, "release", False))
    checks = list(config.get("checks", []))
    if release:
        checks += list(config.get("release_checks", []))
    conflict = duplicate_id_error(root, card, config, batch_id)
    if conflict:
        state["status"] = "check_failed"
        state["id_error"] = conflict
        state["checked_at"] = utc_now()
        write_json(batch_dir(root, batch_id) / "state.json", state)
        append_evidence(root, batch_id, f"id: FAIL ({conflict})")
        print(conflict, file=sys.stderr)
        return 1
    base_ref = state.get("base") or str(config.get("base", "main"))
    base = resolve_commit(root, base_ref)
    if not base:
        state["status"] = "check_failed"
        state["base_error"] = f"base does not resolve to a commit: {base_ref}"
        state["checked_at"] = utc_now()
        write_json(batch_dir(root, batch_id) / "state.json", state)
        append_evidence(root, batch_id, f"base: FAIL ({state['base_error']})")
        print(state["base_error"], file=sys.stderr)
        return 1
    state["base"] = base
    state["base_ref"] = state.get("base_ref") or base_ref
    anchor = budget_anchor(root, base, state["base_ref"])
    state["scope_base"] = anchor
    changed, violations = check_scope(root, card, anchor, config)
    added, deleted, binary, budget_error = check_budget(root, card, anchor, changed)
    override_reason = str(getattr(args, "allow_over_budget", "") or "").strip()
    budget_override: dict[str, Any] | None = None
    if budget_error and override_reason:
        budget_override = {
            "budget": int(card.get("size_budget", 0)),
            "lines": added + deleted,
            "reason": override_reason,
        }
        budget_error = None
    elif budget_error:
        budget_error += '; rerun with --allow-over-budget "<why>" to record it'
    changelog_errors, changelog_warnings = check_changelog(root, card, changed)
    skill_errors, skill_found = check_skills(root, card)
    evidence_errors, evidence_warnings, skill_records = check_skill_evidence(
        root, batch_id, card
    )
    commit_errors = check_commit_titles(root, anchor, config)
    gate_errors = [
        *violations,
        *changelog_errors,
        *skill_errors,
        *evidence_errors,
        *commit_errors,
    ]
    if budget_error:
        gate_errors.append(budget_error)

    append_evidence(
        root,
        batch_id,
        f"scope: {'PASS' if not violations else 'FAIL'} ({len(changed)} changed paths)",
    )
    for path in changed:
        append_evidence(root, batch_id, f"changed: {path}")
    for violation in violations:
        append_evidence(root, batch_id, f"scope: {violation}")
    for violation in changelog_errors:
        append_evidence(root, batch_id, violation)
    for warning in changelog_warnings:
        append_evidence(root, batch_id, f"warn: {warning}")
    for violation in skill_errors:
        append_evidence(root, batch_id, violation)
    for violation in evidence_errors:
        append_evidence(root, batch_id, violation)
    for violation in commit_errors:
        append_evidence(root, batch_id, f"commit: {violation}")
    append_evidence(
        root,
        batch_id,
        "commit titles: "
        + ("PASS" if not commit_errors else f"FAIL ({len(commit_errors)})"),
    )
    append_evidence(
        root,
        batch_id,
        f"release: {'yes' if release else 'no'} ({len(checks)} checks)",
    )
    for warning in evidence_warnings:
        append_evidence(root, batch_id, f"warn: {warning}")
    if budget_error:
        append_evidence(root, batch_id, budget_error)
    if budget_override:
        append_evidence(
            root,
            batch_id,
            f"budget override: {budget_override['lines']} lines over "
            f"{budget_override['budget']} ({budget_override['reason']})",
        )
    for violation in gate_errors:
        print(f"[fail] {violation}", file=sys.stderr)
    for warning in [*changelog_warnings, *evidence_warnings]:
        print(f"[warn] {warning}", file=sys.stderr)

    results = run_checks(root, batch_id, checks) if not gate_errors else {}
    passed = not gate_errors and all(
        item.get("status") == "pass" for item in results.values()
    )
    state["status"] = "checked" if passed else "check_failed"
    state["checks"] = results
    state["release"] = release
    state["scope"] = {
        "budget": int(card.get("size_budget", 0)),
        "changed": len(changed),
        "added": added,
        "deleted": deleted,
        "binary": binary,
        "measured_from": anchor,
        "result": "pass" if not budget_error and not violations else "fail",
        "violations": violations,
        "override": bool(budget_override),
    }
    state["budget_override"] = budget_override
    state["changelog"] = {
        "declared": [str(item) for item in card.get("changelog", [])],
        "warnings": changelog_warnings,
    }
    state["skills"] = skill_found
    state["skill_evidence"] = skill_records
    state["checked_at"] = utc_now()
    write_json(batch_dir(root, batch_id) / "state.json", state)
    print(f"scope: {'PASS' if not violations else 'FAIL'} ({len(changed)} paths)")
    print(
        f"budget: {'SKIP' if not card.get('size_budget') else ('FAIL' if budget_error else 'PASS')}"
        f" ({added + deleted} lines from {anchor[:12]})"
        + (", override recorded" if budget_override else "")
    )
    print(f"changelog: {'FAIL' if changelog_errors else 'PASS'}")
    print(f"release: {'yes' if release else 'no'} ({len(checks)} checks)")
    print(
        f"skills: {'FAIL' if skill_errors or evidence_errors else 'PASS'}"
        + (
            " ("
            + ", ".join(
                f"{skill_id} {record['status']}"
                for skill_id, record in skill_records.items()
            )
            + ")"
            if skill_records
            else ""
        )
    )
    print(f"result: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


def pr_body(root: Path, batch_id: str) -> str:
    """Render the prepared PR body in the shape of the repository PR template."""
    card = read_card(root, batch_id)
    state = read_state(root, batch_id)
    anchor = str(state.get("scope_base") or state.get("base", "main"))
    changed = changed_paths(root, anchor, load_config(root))
    scope = state.get("scope") or {}
    checks = state.get("checks") or {}
    base = state.get("base_ref") or state.get("base", "")
    lines = [
        "## Summary",
        "",
        f"Batch `{batch_id}`: {card.get('goal', '')}",
        "",
        f"- Branch: `{state.get('branch', '')}`",
        f"- Base: `{base}`",
        "",
        "## Impact",
        "",
        "Allowed:",
        *[f"- `{item}`" for item in card.get("allowed", [])],
        "",
        f"Changed files: {len(changed)}",
        *[f"- `{item}`" for item in changed],
        "",
        "## Verification",
        "",
    ]
    if checks:
        lines.extend(
            f"- `{name}`: {item.get('status', 'unknown')}"
            for name, item in checks.items()
        )
    else:
        lines.append("- checks: none configured")
    budget = int(scope.get("budget") or 0)
    added = int(scope.get("added") or 0)
    deleted = int(scope.get("deleted") or 0)
    lines.append(
        f"- scope: {str(scope.get('result', 'unknown')).upper()} "
        f"({scope.get('changed', len(changed))} files, {added + deleted} lines, "
        f"budget {budget or 'none'})"
    )
    lines.append(f"- evidence: `.batch/{batch_id}/evidence.log`")
    lines.extend(["", "## Risks", ""])
    risks = [str(item) for item in scope.get("violations", [])]
    override = state.get("budget_override") or None
    if budget and added + deleted > budget:
        if override:
            risks.append(
                f"budget: {added + deleted} changed lines exceeds {budget} — "
                f"override: {override.get('reason', '')}"
            )
        else:
            risks.append(f"budget: {added + deleted} changed lines exceeds {budget}")
    if int(scope.get("binary") or 0):
        risks.append(f"binary files: {scope.get('binary')} (diff is not reviewable)")
    for key, label in (("id_error", "id"), ("source_error", "source")):
        if state.get(key):
            risks.append(f"{label}: {state[key]}")
    warnings = (state.get("changelog") or {}).get("warnings") or []
    risks.extend(str(item) for item in warnings)
    if risks:
        lines.extend(f"- {item}" for item in risks)
    else:
        lines.append("None recorded by the gate.")
    lines.extend(["", "## Self-check", ""])
    criteria = card.get("acceptance", card.get("exit_criteria", []))
    if criteria:
        lines.extend(f"- {item}" for item in criteria)
    else:
        lines.append("- none recorded")
    return "\n".join(lines)


def scaffold_language(root: Path) -> dict[str, Any]:
    """Resolve the language block used for PR body translations.

    Mirrors ``nebula-bootstrap/scripts/language.py``: a ``language`` block wins,
    legacy ``repoLocale``/``docsLocale`` blocks are mapped, and a missing or
    invalid block falls back to zh-CN. PR translations are best effort, so this
    only needs the primary, supported, and external values.
    """
    data = load_json(root / SCAFFOLD_REL) or {}
    block = data.get("language")
    if isinstance(block, dict) and isinstance(block.get("primary"), str):
        primary = block["primary"].strip()
        supported = [
            str(item).strip()
            for item in block.get("supported", [])
            if isinstance(item, str) and item.strip()
        ]
        if primary:
            supported = [primary, *[item for item in supported if item != primary]]
        external = str(block.get("external") or primary).strip()
        return {
            "primary": primary or "zh-CN",
            "supported": supported or ["zh-CN"],
            "external": external if external in supported else (primary or "zh-CN"),
        }
    repo = data.get("repoLocale") if isinstance(data.get("repoLocale"), dict) else {}
    docs = data.get("docsLocale") if isinstance(data.get("docsLocale"), dict) else {}
    primary = str(repo.get("primary") or docs.get("primary") or "zh-CN").strip() or "zh-CN"
    supported: list[str] = []
    for source in (repo.get("supported"), docs.get("supported")):
        for item in source or []:
            value = str(item).strip()
            if value and value not in supported:
                supported.append(value)
    if primary not in supported:
        supported.insert(0, primary)
    external = str(docs.get("external") or primary).strip()
    return {
        "primary": primary,
        "supported": supported,
        "external": external if external in supported else primary,
    }


def pr_translations(
    root: Path,
    batch_id: str,
    body_path: Path,
    digest: str,
    config: dict[str, Any],
    state: dict[str, Any],
) -> list[str]:
    """Write PR body translations through ``config.translate``; best effort."""
    language = scaffold_language(root)
    source_locale = language["external"]
    targets = [item for item in language["supported"] if item != source_locale]
    if not targets:
        return []
    command = config.get("translate")
    if not command:
        print(
            "config.translate is empty; skipped PR body translations",
            file=sys.stderr,
        )
        return []
    card = read_card(root, batch_id)
    directory = batch_dir(root, batch_id)
    translations: list[dict[str, Any]] = []
    for locale in targets:
        out = directory / f"pr-body.{locale}.md"
        out.unlink(missing_ok=True)
        code, out_text, err_text = run_hook(
            root,
            command,
            {
                "id": batch_id,
                "title": str(card.get("goal", batch_id)),
                "body": str(body_path),
                "branch": str(state.get("branch", "")),
                "root": str(root),
                "locale": locale,
                "out": str(out),
            },
        )
        if out_text:
            print(out_text)
        if code != 0:
            print(f"translation {locale} failed (exit {code})", file=sys.stderr)
            if err_text:
                print(err_text, file=sys.stderr)
            continue
        if not out.exists() or not out.read_text(encoding="utf-8").strip():
            print(f"translation {locale}: hook produced no output", file=sys.stderr)
            continue
        translations.append(
            {
                "locale": locale,
                "file": out.relative_to(root).as_posix(),
                "machine": True,
                "authoritative": False,
            }
        )
    if not translations:
        return []
    write_json(
        directory / "pr-body.manifest.json",
        {
            "source": source_relative(root, body_path),
            "source_sha256": digest,
            "source_locale": source_locale,
            "generated_at": utc_now(),
            "tool": "batch.py",
            "translations": translations,
        },
    )
    print(f"translations: {', '.join(item['locale'] for item in translations)}")
    return [item["locale"] for item in translations]


def pr_skills(root: Path, batch_id: str) -> str:
    """Render the skill usage report as a local review supplement."""
    card = read_card(root, batch_id)
    state = read_state(root, batch_id)
    records = state.get("skill_evidence", {})
    lines = [
        "# Skills",
        "",
        "Local review supplement. Not part of the PR body; never committed.",
        "",
        "| Skill | Plan | Actual | What changed | Proof |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in card.get("skills", []):
        skill_id = str(item.get("id", ""))
        record = records.get(skill_id, {})
        plan = "required" if item.get("required") else "optional"
        actual = str(record.get("status") or "missing")
        changed = str(record.get("changed") or "-").replace("|", "\\|")
        proof = str(record.get("proof") or "-").replace("|", "\\|")
        lines.append(f"| `{skill_id}` | {plan} | {actual} | {changed} | {proof} |")
    return "\n".join(lines) + "\n"


def cmd_pr(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    batch_id = resolve_id(root, args.id)
    state = read_state(root, batch_id)
    mismatch = batch_branch_mismatch(root, state, batch_id)
    if mismatch:
        print(mismatch, file=sys.stderr)
        return 1
    if state.get("status") not in {"checked", "pr_ready"}:
        print("run 'check' successfully before preparing a PR", file=sys.stderr)
        return 1
    card = read_card(root, batch_id)
    if card.get("legacy"):
        print("legacy cards have no PR flow", file=sys.stderr)
        return 1
    config = load_config(root)
    rule = commit_rule(root, config)
    subject = str(card.get("pr_title") or card.get("goal", batch_id)).strip()
    title = subject
    if rule["enabled"]:
        kind = str(card.get("type", ""))
        if rule["types"] and kind not in rule["types"]:
            print(
                f"card type '{kind}' is not a commit type; use one of: "
                f"{', '.join(rule['types'])}",
                file=sys.stderr,
            )
            return 1
        scope = str(card.get("git_scope") or "").strip()
        if rule["scopes"] and not scope:
            print(
                "card.git_scope is required when git scopes are configured; "
                f"choose one of: {', '.join(rule['scopes'])}",
                file=sys.stderr,
            )
            return 1
        if scope and rule["scopes"] and scope not in rule["scopes"]:
            print(
                f"card.git_scope '{scope}' is not one of: "
                f"{', '.join(rule['scopes'])}",
                file=sys.stderr,
            )
            return 1
        if scope:
            title = f"{kind}({scope}): {subject}"
        else:
            title = f"{kind}: {subject}"
    approval = load_json(batch_dir(root, batch_id) / "approval.json")
    if approval is None or approval.get("card_hash") != card_hash(card):
        print("card is not approved (or approval is stale)", file=sys.stderr)
        return 1
    current, message = source_is_current(root, card)
    if not current:
        print(message, file=sys.stderr)
        return 1
    source: Path | None = None
    if args.body_from:
        source = Path(args.body_from)
        source = source if source.is_absolute() else root / source
        if not source.is_file():
            print(f"body source not found: {source}", file=sys.stderr)
            return 2
        payload = source.read_text(encoding="utf-8")
    else:
        payload = pr_body(root, batch_id) + "\n"
    body_path = Path(args.body_file) if args.body_file else (batch_dir(root, batch_id) / "pr-body.md")
    body_path = body_path if body_path.is_absolute() else root / body_path
    if not inside_project(root, body_path):
        print(f"body output must stay inside the project: {body_path}", file=sys.stderr)
        return 2
    if source is not None and body_path.resolve() == source.resolve():
        print("--body-from and --body-out point at the same file", file=sys.stderr)
        return 2
    write_text(body_path, payload)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    shown = source_relative(root, body_path)
    print(f"prepared {shown}")
    print(f"body hash: {digest[:8]}")
    state["status"] = "pr_ready"
    state["pr_body"] = shown
    state["pr_body_sha256"] = digest
    state["pr_title"] = title
    state["pr_translations"] = pr_translations(
        root, batch_id, body_path, digest, config, state
    )
    if card.get("skills"):
        skills_path = batch_dir(root, batch_id) / "pr-skills.md"
        write_text(skills_path, pr_skills(root, batch_id))
        state["pr_skills"] = skills_path.relative_to(root).as_posix()
        print(f"skills report: {state['pr_skills']}")
    write_json(batch_dir(root, batch_id) / "state.json", state)

    if not args.create:
        return 0
    if args.confirm != digest[:8]:
        print(f"confirm mismatch: expected {digest[:8]}", file=sys.stderr)
        return 1
    command = config.get("pr_create")
    if not command:
        print("config.pr_create is empty; use --prepare only", file=sys.stderr)
        return 2
    code, out, err = run_hook(
        root,
        command,
        {
            "id": batch_id,
            "title": title,
            "body": str(body_path),
            "branch": str(state.get("branch", "")),
            "root": str(root),
        },
    )
    if out:
        print(out)
    if err:
        print(err, file=sys.stderr)
    if code != 0:
        return 1
    state["status"] = "pr_created"
    state["pr_output"] = out
    write_json(batch_dir(root, batch_id) / "state.json", state)
    print(f"created PR for {batch_id}")
    return 0


def exit_record_draft(
    card: dict[str, Any], state: dict[str, Any], batch_id: str
) -> str:
    """Build an exit record skeleton from the card and the batch state."""
    scope = state.get("scope") or {}
    budget = int(scope.get("budget") or card.get("size_budget") or 0)
    changed = int(scope.get("changed") or 0)
    lines_changed = int(scope.get("added") or 0) + int(scope.get("deleted") or 0)
    forced = "yes" if state.get("check_override") else "no"
    today = str(state.get("merged_at") or utc_now())[:10]
    rows = [
        f"# {batch_id} — Exit record",
        "",
        "## Result",
        "",
        "pass" if state.get("status") == "merged" else "fail",
        "",
        "## Delivery",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| PR | {state.get('pr') or '#fill'} |",
        "| Commit | `fill` |",
        f"| Merged at | {today} |",
        "| By | @fill |",
        f"| Merge | {state.get('merge_mode') or 'squash'} |",
        f"| Forced | {forced} |",
    ]
    if forced == "yes":
        reason = str((state.get("check_override") or {}).get("reason", ""))
        rows.append(f"| Force reason | {reason or 'fill'} |")
    rows += [
        "",
        "## Traceability",
        "",
        "- `REQ-fill`",
        "- `TC-fill`",
        "",
        "## Acceptance",
        "",
        "| # | Criterion | Evidence | Result |",
        "|---|---|---|---|",
    ]
    criteria = card.get("acceptance") or []
    for index, item in enumerate(criteria, 1):
        rows.append(f"| {index} | {item} | fill | fill |")
    if not criteria:
        rows.append("| 1 | fill | fill | fill |")
    rows += ["", "## Skills", "", "| Skill | Plan | Actual | Evidence |", "|---|---|---|---|"]
    records = state.get("skill_evidence") or {}
    for item in card.get("skills") or []:
        skill_id = str(item.get("id", ""))
        record = records.get(skill_id) or {}
        plan = "required" if item.get("required") else "optional"
        actual = record.get("status") or "fill"
        proof = record.get("proof") or "fill"
        rows.append(f"| {skill_id} | {plan} | {actual} | {proof} |")
    if not card.get("skills"):
        rows.append("| fill | fill | fill | fill |")
    rows += ["", "## Changelog", ""]
    fragments = card.get("changelog") or []
    rows += [f"- `{item}` — fill" for item in fragments] or ["- fill"]
    rows += [
        "",
        "## Scope",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Budget | {budget} |",
        f"| Changed | {lines_changed} |",
        f"| Result | {'pass' if scope.get('result') == 'pass' else 'fail'} |",
        "",
        "## Deviations",
        "",
    ]
    override = state.get("budget_override") or None
    if override:
        rows.append(
            f"- budget override: {override.get('lines')} lines over "
            f"{override.get('budget')} — {override.get('reason')}"
        )
    else:
        rows.append("- none")
    rows += ["", "## Follow-ups", "", "- none", ""]
    return "\n".join(rows)


def cmd_exit(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    batch_id = resolve_id(root, args.id)
    card = read_card(root, batch_id)
    state = read_state(root, batch_id)
    target = Path(args.out) if args.out else None
    if target is None:
        config = load_config(root)
        docs_root = configured_docs_root(root, config)
        if docs_root is None:
            source = card_source_path(root, card)
            docs_root = docs_root_from_card(source) if source else None
        if docs_root is None:
            print("docs repo not found; pass --out <path>", file=sys.stderr)
            return 2
        target = docs_root / DOCS_RECORDS / "live" / f"{batch_id}-exit.md"
    if target.exists() and not args.force:
        print(f"{target} exists; pass --force to overwrite", file=sys.stderr)
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(exit_record_draft(card, state, batch_id) + "\n", encoding="utf-8")
    print(f"drafted {target}")
    print("fill the remaining fields, then run check_records.py")
    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    batch_id = resolve_id(root, args.id)
    state = read_state(root, batch_id)
    if not args.yes:
        print("merge requires --yes", file=sys.stderr)
        return 2
    status = state.get("status")
    if args.force and not args.external:
        print("--force is only valid with --external", file=sys.stderr)
        return 2
    if status not in {"checked", "pr_ready", "pr_created"}:
        if not (args.external and status == "check_failed" and args.force):
            if args.external and status == "check_failed":
                print(
                    "batch check failed; an external merge needs "
                    "--force --reason <why the failure is accepted>",
                    file=sys.stderr,
                )
            else:
                print("batch is not checked or PR-ready", file=sys.stderr)
            return 1
        if not args.reason.strip():
            print("--force requires --reason", file=sys.stderr)
            return 2
    config = load_config(root)
    command = config.get("merge")
    if not command:
        if not args.external:
            print(
                "config.merge is empty; merge the PR externally, then rerun "
                "'merge --external --pr <number> --yes'",
                file=sys.stderr,
            )
            return 2
        override = None
        if status == "check_failed":
            override = {
                "from": status,
                "reason": args.reason.strip(),
                "at": utc_now(),
            }
        state["status"] = "merged"
        state["merged_at"] = utc_now()
        state["merge_mode"] = "external"
        state["pr"] = args.pr
        if override is not None:
            state["check_override"] = override
        write_json(batch_dir(root, batch_id) / "state.json", state)
        clear_active(root)
        suffix = " after a forced check failure" if override is not None else ""
        print(f"merged {batch_id} externally (PR {args.pr}){suffix}")
        return 0
    if args.external:
        print(
            "--external is only valid when config.merge is empty",
            file=sys.stderr,
        )
        return 2
    if status != "pr_created":
        print("batch has no created PR", file=sys.stderr)
        return 1
    code, out, err = run_hook(
        root,
        command,
        {
            "id": batch_id,
            "title": batch_id,
            "body": "",
            "branch": str(state.get("branch", "")),
            "root": str(root),
            "pr": args.pr,
        },
    )
    if out:
        print(out)
    if err:
        print(err, file=sys.stderr)
    if code != 0:
        return 1
    merged_problems = check_merged_commit(root, config)
    for item in merged_problems:
        print(f"warning: merged commit: {item}", file=sys.stderr)
    state["status"] = "merged"
    state["merged_at"] = utc_now()
    write_json(batch_dir(root, batch_id) / "state.json", state)
    clear_active(root)
    print(f"merged {batch_id}")
    return 0


def cmd_abort(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    batch_id = resolve_id(root, args.id)
    state = read_state(root, batch_id)
    if state.get("status") == "merged":
        print("cannot abort a merged batch", file=sys.stderr)
        return 1
    branch = str(state.get("branch") or "")
    base_ref = str(state.get("base_ref") or "")
    switched_to = ""
    if branch and state.get("branch_created") is True and current_branch(root) == branch:
        code, status_out, _ = run_git(
            root, ["status", "--porcelain", "--", ".", f":(exclude){STATE_DIR}"]
        )
        if code == 0 and not status_out:
            target = base_ref or str(state.get("base") or "")
            if target:
                switch_code, _, switch_err = run_git(root, ["switch", target])
                if switch_code == 0:
                    switched_to = target
                else:
                    print(
                        f"could not switch back to {target}: {switch_err} "
                        f"(the branch {branch} is kept)",
                        file=sys.stderr,
                    )
        else:
            print(
                f"working tree has changes; still on {branch}. "
                "Commit or stash them, then run: git switch "
                f"{base_ref or '<base>'}",
                file=sys.stderr,
            )
    state["status"] = "aborted"
    state["aborted_at"] = utc_now()
    write_json(batch_dir(root, batch_id) / "state.json", state)
    if active_id(root) == batch_id:
        clear_active(root)
    print(f"aborted {batch_id}")
    if switched_to:
        print(f"switched back to {switched_to}")
    if branch:
        print(f"branch kept: {branch}")
    return 0


def cmd_pause(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    batch_id = resolve_id(root, args.id)
    state = read_state(root, batch_id)
    status = str(state.get("status") or "")
    if status == "paused":
        print(f"{batch_id} is already paused")
        return 0
    if status not in PAUSABLE_STATUSES:
        print(f"cannot pause a {status} batch", file=sys.stderr)
        return 1
    state["paused_from"] = status
    state["status"] = "paused"
    state["paused_at"] = utc_now()
    write_json(batch_dir(root, batch_id) / "state.json", state)
    if active_id(root) == batch_id:
        clear_active(root)
    branch = str(state.get("branch") or "")
    print(f"paused {batch_id} ({status})")
    if branch:
        print(f"branch: {branch}")
    print("work stays where it is; park it with 'git commit' or 'git stash'")
    print(f"resume with: batch.py resume {batch_id}")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    git_required(root)
    batch_id = resolve_id(root, args.id)
    state = read_state(root, batch_id)
    status = str(state.get("status") or "")
    if status != "paused":
        print(f"batch is not paused: {status}", file=sys.stderr)
        return 1
    branch = str(state.get("branch") or "")
    if not branch:
        print("state has no branch; cannot resume", file=sys.stderr)
        return 1
    if not branch_exists(root, branch):
        print(
            f"branch is gone: {branch}; abort the batch and plan it again",
            file=sys.stderr,
        )
        return 1
    other = active_id(root)
    if other and other != batch_id:
        print(f"another batch is active: {other}", file=sys.stderr)
        return 1
    card = read_card(root, batch_id)
    if card_hash(card) != state.get("card_hash"):
        print("card changed since start; re-approve it before resuming", file=sys.stderr)
        return 1
    current, message = source_is_current(root, card)
    if not current:
        print(message, file=sys.stderr)
        return 1
    code, _, err = run_git(root, ["switch", branch])
    if code != 0:
        print(f"could not switch to {branch}: {err}", file=sys.stderr)
        return 1
    state["status"] = str(state.get("paused_from") or "started")
    state["resumed_at"] = utc_now()
    write_json(batch_dir(root, batch_id) / "state.json", state)
    set_active(root, batch_id)
    print(f"resumed {batch_id} on {branch} ({state['status']})")
    return 0


def cmd_adopt(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    source = Path(args.source)
    source = source if source.is_absolute() else root / source
    source = source.resolve()
    if not source.is_file():
        print(f"card source not found: {source}", file=sys.stderr)
        return 2
    batch_id = args.id or source.stem
    if not CARD_ID_RE.fullmatch(batch_id):
        print("legacy id must be B followed by digits", file=sys.stderr)
        return 2
    target = batch_dir(root, batch_id)
    if target.exists() and not archive_aborted(root, batch_id):
        print(f"batch already exists: {batch_id}", file=sys.stderr)
        return 1
    snapshot = {
        "id": batch_id,
        "legacy": True,
        "source": source_relative(root, source),
        "source_sha256": file_sha256(source),
    }
    write_json(target / "card.json", snapshot)
    print(f"adopted {batch_id} as read-only legacy")
    print(f"source: {snapshot['source']}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    root_dir = state_root(root)
    if not root_dir.is_dir():
        print("no batches")
        return 0
    for path in sorted(root_dir.iterdir(), key=lambda item: batch_sort_key(item.name)):
        if not path.is_dir() or not ID_RE.fullmatch(path.name):
            continue
        state = load_json(path / "state.json") or {}
        card = load_json(path / "card.json") or {}
        status = state.get("status") or ("legacy" if card.get("legacy") else "planned")
        print(f"{path.name}\t{status}\t{card.get('goal', '')}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    try:
        batch_id = resolve_id(root, args.id)
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print_status(root, batch_id, args.json)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="project-local batch execution skeleton")
    parser.add_argument("--root", type=Path, default=ROOT)
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="create a batch card")
    plan.add_argument("id", nargs="?")
    plan.add_argument("--from", dest="source", help="plan from an external card")
    plan.add_argument("--goal")
    plan.add_argument("--allowed", action="append")
    plan.add_argument("--forbidden", action="append")
    plan.add_argument("--exit-criterion", action="append")
    plan.set_defaults(func=cmd_plan)

    adopt = sub.add_parser("adopt", help="adopt a legacy card as read-only")
    adopt.add_argument("id", nargs="?")
    adopt.add_argument("--from", dest="source", required=True)
    adopt.set_defaults(func=cmd_adopt)

    approve = sub.add_parser("approve", help="approve a card by hash")
    approve.add_argument("id", nargs="?")
    approve.add_argument("--confirm", required=True)
    approve.add_argument("--by", default="")
    approve.set_defaults(func=cmd_approve)

    start = sub.add_parser("start", help="start an approved batch")
    start.add_argument("id", nargs="?")
    start.add_argument("--base")
    start.add_argument("--branch")
    start.add_argument("--no-branch", action="store_true")
    start.set_defaults(func=cmd_start)

    check = sub.add_parser("check", help="check scope and configured commands")
    check.add_argument("id", nargs="?")
    check.add_argument(
        "--release",
        action="store_true",
        help="also run config.release_checks",
    )
    check.add_argument(
        "--allow-over-budget",
        metavar="REASON",
        help="record why this batch exceeds its size budget",
    )
    check.set_defaults(func=cmd_check)

    pr = sub.add_parser("pr", help="prepare or create a PR body")
    pr.add_argument("id", nargs="?")
    pr.add_argument("--prepare", action="store_true")
    pr.add_argument("--create", action="store_true")
    pr.add_argument(
        "--body-out",
        "--body-file",
        dest="body_file",
        help="where to write the body (default .batch/<id>/pr-body.md)",
    )
    pr.add_argument(
        "--body-from",
        help="read the body from this file instead of generating it",
    )
    pr.add_argument("--confirm")
    pr.set_defaults(func=cmd_pr)

    merge = sub.add_parser("merge", help="run the configured merge command")
    merge.add_argument("id", nargs="?")
    merge.add_argument("--pr", required=True)
    merge.add_argument("--yes", action="store_true")
    merge.add_argument(
        "--external",
        action="store_true",
        help="record a manually merged PR; only when config.merge is empty",
    )
    merge.add_argument(
        "--force",
        action="store_true",
        help="with --external, accept a check_failed batch; requires --reason",
    )
    merge.add_argument(
        "--reason",
        default="",
        help="why a check_failed batch is accepted (recorded in state.json)",
    )
    merge.set_defaults(func=cmd_merge)

    exit_parser = sub.add_parser(
        "exit", help="draft the exit record from the card and state"
    )
    exit_parser.add_argument("id", nargs="?")
    exit_parser.add_argument(
        "--out",
        help="write here instead of <docs>/records/live/<id>-exit.md",
    )
    exit_parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing exit record",
    )
    exit_parser.set_defaults(func=cmd_exit)

    abort = sub.add_parser("abort", help="abort an unmerged batch")
    abort.add_argument("id", nargs="?")
    abort.set_defaults(func=cmd_abort)

    pause = sub.add_parser("pause", help="park a batch and keep its branch")
    pause.add_argument("id", nargs="?")
    pause.set_defaults(func=cmd_pause)

    resume = sub.add_parser("resume", help="return to a paused batch")
    resume.add_argument("id", nargs="?")
    resume.set_defaults(func=cmd_resume)

    listing = sub.add_parser("list", help="list batches")
    listing.set_defaults(func=cmd_list)

    status = sub.add_parser("status", help="show one batch")
    status.add_argument("id", nargs="?")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_status)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
