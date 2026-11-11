# Git conventions

One-page defaults. Change this file when the team changes the rule.

Whether the toolchain enforces these rules depends on configuration: run
`bootstrap --git-convention team` to write the `git` preset into
`.nebula-scaffold.json`, or write the `commit` block in
`infra/tool/batch/config.json`. With neither, nothing checks commit titles.

## 1. Branches

```text
main                 long-lived, protected
feat/<topic>         user-visible feature
fix/<topic>          bug fix
process/<topic>      process/tooling only
```

- One branch = one change.
- Delete the branch after merge.

## 2. Commits

```text
<type>(<scope>): <subject>
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `ci`.
Scopes: the module or area.

- Subject is imperative and short.
- Body explains why, not what. With the `team` preset the body must contain
  `Why:` and `Batch:` (write `Batch: none` when there is no batch).
- No secrets, no generated build output.

## 3. Pull requests

- One PR = one behavior.
- Fill the PR template.
- Link the issue or record if one exists.
- Required checks must be green.
- Do not rewrite history after review unless asked.

## 4. Merge

- Squash merge by default.
- The author does not self-approve.
- No direct push to `main`.
- A failed check is fixed, not bypassed.

## 5. Release

- Version lives in the declared manifest.
- Tag: `vX.Y.Z`.
- `CHANGELOG.md` must have the matching version before tagging.
- Content packs use `pack/<space>/vX.Y.Z` when tagged.
