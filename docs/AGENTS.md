# docs — agent entry

- Read the root `AGENTS.md` first.
- Controlled docs are versioned at baselines, not per PR.
- Daily PRs do not bump controlled versions or add history rows.
- SDP belongs to the external process dir; it is plan-only.
- `changelog.d/` is a root release device, not a docs category.
- `language` lives in `.nebula-scaffold.json`; `primary` is authoritative.
- Controlled docs translations are same-dir `<name>.<locale>.md` files with
  `<!-- translation-of: <source> -->`; update existing translations with the source.
- Every multilingual document puts one language switch immediately below the first
  H1; the current language is plain text and the others are relative links.
- Records, changelog, AGENTS, and baselines stay single-language.
