# Project-local batch execution

Optional, project-local execution layer for the implementation stage. It is not
a core Nebula skill and is only installed when bootstrap is called with
`--with-execution`.

The tool is stack-agnostic. It owns the state machine:

```text
plan -> approve -> start -> check -> pr -> merge
```

A stage skill or the project itself provides the checks and provider commands
through `infra/tool/batch/config.json`; `batch.py` only runs commands, reads exit
codes, and writes evidence.

## Files

```text
infra/tool/batch/
  batch.py       state machine
  config.json    project-owned commands and defaults
  README.md      this file
.batch/          local state and evidence; never commit
```

## Commands

```bash
python infra/tool/batch/batch.py plan --from ../<project>-docs/process/batches/B8.md
python infra/tool/batch/batch.py approve B8 --confirm <hash8>
python infra/tool/batch/batch.py start B8
python infra/tool/batch/batch.py check B8
python infra/tool/batch/batch.py pr B8 --prepare
python infra/tool/batch/batch.py pr B8 --create --confirm <body-hash8>
python infra/tool/batch/batch.py merge B8 --pr 123 --yes
python infra/tool/batch/batch.py merge B8 --pr 123 --yes --external
python infra/tool/batch/batch.py merge B8 --pr 123 --yes --external \
  --force --reason "budget accepted by the maintainer"
python infra/tool/batch/batch.py adopt B1 --from ../<project>-docs/process/batches/B1.md
python infra/tool/batch/batch.py pause B8
python infra/tool/batch/batch.py resume B8
python infra/tool/batch/batch.py abort B8
python infra/tool/batch/batch.py exit B8
python infra/tool/batch/batch.py status B8
```

`exit` drafts `records/live/<id>-exit.md` in the docs repo from the card and
state: delivery fields, acceptance rows, skill evidence, changelog, and the
measured budget are filled; `fill` marks what only a human can answer. Pass
`--out <path>` when the docs repo is unknown, and `--force` to overwrite.

`plan --from` reads the single external Markdown card and writes a snapshot to
`.batch/<id>/card.json`. The snapshot records the source path and a SHA-256 of
the Markdown with the `planned` marker line removed. Before writing, it checks
the docs repo: the id must appear in the SDP batch table (`process/sdp.md`), and
must not already be used by another card under `process/batches/` or by a record
under `records/`. The docs root is derived from the card path
(`<docs>/process/batches/B<n>.md`); `docs_root` in `config.json` overrides it.
`approve` binds both hashes; `start`, `check`, and `pr` re-read the source and
refuse a changed card. A card edit therefore requires a new approval.

`plan --from` also appends `<!-- planned: <id> <hash8> <date> -->` to the card.
Re-running it on a card that is only `planned` or `approved` refreshes the
snapshot in place: nothing changed prints `unchanged <id>`; a changed card is
updated, its approval is cleared, and the marker is rewritten. A started batch
is never refreshed (`abort` it or use a new id). The marker is how the docs repo
itself shows which cards are known to the execution tool; `check` warns when the
marker no longer matches the planned snapshot.

`plan --goal` is only for a dated ad-hoc investigation; it is not a planning
card and cannot become one later. `adopt` records an old B1–B7 card as a
read-only legacy snapshot; it never invents approval or scope.

A started batch can be paused. `pause` clears the active marker and leaves the
worktree and branch untouched, so another batch can start from the base branch.
`resume` checks that the branch still exists and the card has not changed, then
switches back and restores the status the batch had before the pause. Work that
must survive a pause is committed or stashed on the branch; the tool never
commits or discards it. `abort` ends the batch, switches back to the base branch
when the worktree is clean, and keeps the branch. Planning the same id again
first archives the aborted state to `.batch/archive/<id>-<timestamp>`, so an id
is never silently reused while the old tree is still around. `start` refuses to
create a batch branch from another batch branch; switch to the base branch first.

`pr --prepare` writes `.batch/<id>/pr-body.md` in the shape of the repository PR
template (`Summary`, `Impact`, `Verification`, `Risks`, `Self-check`). Pass
`--body-from <file>` to publish a hand-written body instead: the file is copied
verbatim and is not overwritten. `--body-out <file>` (old name: `--body-file`)
moves where the body is written; the path must stay inside the project.
`state.pr_body_sha256` always hashes the bytes that were written, so a checker
that hashes the file gets the same digest. When `config.translate` is set and the
scaffold supports more than one language, it also writes one translation per
supported language other than the body language (`pr-body.<locale>.md`) plus
`pr-body.manifest.json` (source hash, timestamp, and each translation). The
source body stays authoritative; translations are local, best effort, and never
block: an empty hook skips them, and a failing locale is a warning. `state.json`
records `pr_body_sha256` and `pr_translations`. `.batch/` is never committed, and
`pr --create --confirm <body-hash8>` still confirms the source body hash. When
the card declares skills, `pr --prepare` also writes `.batch/<id>/pr-skills.md`
(see below); it is not part of the PR body.

## Skills

`start` prints the declared skills with their `SKILL.md` paths and refuses to
start when one is not installed. Before `check`, record what each skill changed
in `.batch/<id>/evidence/skills/<id>.md`:

```text
status: applied
changed: wrote the failing test first, then the implementation
proof: tests/test_login.py
```

`status` is `applied`, `partial`, or `skipped`. `check` fails when a `required`
skill has no evidence file, when `changed` repeats the status instead of naming
a change, when `proof` is empty, or when `proof` looks like a path that does not
exist. `pr --prepare` renders the same records as
`.batch/<id>/pr-skills.md` — a local review supplement to send by hand; it is
never pushed and never committed.

## Gates

`check` runs six gates before the configured commands:

- **id**: the batch id must not be claimed by another card under
  `process/batches/` or by a record under `records/` in the docs repo; skipped
  when the docs root cannot be derived (ad-hoc batches).
- **scope**: every changed path must match `allowed` and none may match
  `forbidden`.
- **budget**: added plus deleted lines, measured against the merge base with the
  current base branch (falling back to the recorded card base), must not exceed
  `size_budget`. Work merged into the base branch by other batches is not counted
  twice. Untracked files count by line; binary files are reported but not
  counted. A card may omit `size_budget`: `docs` defaults to 150, `fix` and
  `process` to 200, `feat` to 400, and anything else to 400. When over budget,
  `check` fails and prints the escape hatch; rerun with
  `--allow-over-budget "<why>"` to record the reason in
  `state.budget_override`, the evidence log, and the PR `Risks` section.
- **changelog**: every declared fragment must exist under `changelog.d/`, be
  changed by this batch, and be non-empty. `feat`/`fix` must declare one when
  the project has `changelog.d/`.
- **skills**: every declared non-stage skill must be installed under
  `.agents/skills`, `.claude/skills`, `.codex/skills`, `.codebuddy/skills`, or
  `.workbuddy/skills`. Stage skills are rejected when the card is registered.
  Every `required` skill must have an evidence file under
  `.batch/<id>/evidence/skills/` (see Skills above).
- **commit titles**: when a git rule is configured (the `git` preset in
  `.nebula-scaffold.json`, or `commit.types`/`scopes`/`body` in `config.json`),
  every commit the branch adds must read `type(scope): subject`, with `type`
  from `commit.types`; when `commit.scopes` is non-empty the scope is required
  and must come from that list; every token in `commit.body` (for example
  `Why:` and `Batch:`) must appear in the commit body. Write `Batch: none`
  when there is no batch. Merge commits are skipped. With no rule configured
  the gate is skipped.

A failing gate stops the configured commands and leaves the batch in
`check_failed`. The exit record copies each skill's actual
`applied`/`partial`/`skipped` status and what changed from the evidence file.

## Release checks

`checks` run for every batch; `release_checks` run only for a release batch.
Mark a release batch in the card with `"release": true`, or pass `--release`
once to `check` without editing the card. Both lists run in order; the evidence
line reads `release: yes (N checks)` or `release: no (M checks)`. The card flag
is part of the snapshot, so the PR body and the exit record show which tier ran.
Use the release tier for suite-wide or packaging commands that would otherwise
make every small batch pay for them.

`start` resolves the card base to a commit and stores that SHA in
`state.base`; the original branch or tag is kept in `state.base_ref`. `check`
resolves old state files that still contain a branch name and writes the SHA
back, so later runs still measure the original base after the branch merges.

## Configuration

`config.json`:

```json
{
  "base": "main",
  "branch_prefix": "batch/",
  "scope": {"ignore": [], "generated": []},
  "commit": {"types": [], "scopes": [], "body": []},
  "checks": [
    {
      "name": "test",
      "command": ["python", "-m", "pytest"],
      "cwd": ".",
      "timeout": 600
    }
  ],
  "release_checks": [],
  "pr_create": ["gh", "pr", "create", "--title", "{title}", "--body-file", "{body}"],
  "translate": ["python", "tool/translate.py", "--in", "{body}", "--locale", "{locale}", "--out", "{out}"],
  "merge": ["gh", "pr", "merge", "{pr}", "--merge"]
}
```

- `checks`: commands run by `check`; each writes `evidence/<name>.log`.
  `cwd` is relative to the project root.
- `release_checks`: extra commands run only when the card says `"release": true`
  or `check --release` is passed; same shape as `checks`.
- `docs_root`: docs repo root used by `plan --from` for the SDP and duplicate-id
  checks; empty derives it from the card path.
- `pr_create` / `merge`: optional provider hooks. Placeholders:
  `{id}`, `{title}`, `{body}`, `{branch}`, `{root}`, `{pr}`.
- `translate`: optional PR body translation hook. Placeholders: the same set plus
  `{locale}` and `{out}`. It runs once per supported language other than the
  body language; leave it empty to skip translations.
- `scope.ignore`: paths ignored by scope checks; `.batch/` is always ignored.
- `scope.generated`: generated paths ignored by scope checks, kept separate
  from hand-written ignores so a project can review the stack's output.
- `commit`: the optional git rule. `types` is the closed list of subject
  types; `scopes` is the closed list of scopes (empty means "do not require a
  scope"); `body` lists the tokens every commit body must contain, for example
  `["Why:", "Batch:"]`. All three empty means the rule is off. When the rule
  is on, `pr --prepare` also builds the PR title as `type(scope): goal` from
  the card's `type` and `git_scope` (and refuses cards without a scope when
  scopes are configured). The subject is the card's `pr_title` when present,
  otherwise `goal`; a long explanation can stay in `goal` while the title stays
  short. `merge` warns when the squash commit on the base branch does not match
  the rule. `bootstrap --git-convention team` writes the same rule to
  `.nebula-scaffold.json`; `config.commit` wins over it.
- Empty hooks mean the tool stops at `pr --prepare` or reports that merge must
  be done externally. After merging a PR manually, run
  `merge <id> --pr <number> --yes --external` to record the merge and release
  `.batch/active`. `--external` is rejected when `config.merge` is configured.
  A `check_failed` batch can only be recorded with `--external --force
  --reason <why>`; the override and reason are written to `state.json`.
- `start` clears an active marker whose batch is already `merged` or `aborted`;
  that is recovery for a stale `.batch/active`, not a way to run two batches.
- `branch_prefix`: `start` creates `<prefix><id>-<slug>`; the slug is the
  lowercased goal and is omitted when empty (for example a non-ASCII goal).
- Batch id resolution: an explicit id wins, then `.batch/active`, then the only
  local batch. With several batches and no active marker, commands error and
  list the candidates instead of guessing.
- `--with-execution` fills `checks`/`scope` from the selected stack's
  `execution.yaml`; it never overwrites an existing `config.json`.

## Boundaries

- It does not decide whether a change should be batched.
- It does not know Flutter, Swift, or any other stack.
- It does not replace review or human merge approval.
- It does not store records or release notes.
- The project owns `config.json`; bootstrap does not overwrite it on re-run.
