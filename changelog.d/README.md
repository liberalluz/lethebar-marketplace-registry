# changelog.d

One fragment per `feat` / `fix` batch. Release consumes fragments; batches never edit `CHANGELOG.md`.

```markdown
### Added
- user-visible change

### Fixed
- bug fix
```

Only `### Added / Changed / Fixed / Removed`; no H1/H2 or front matter.
Run `python infra/tool/release/release.py --root . --check` before release.
