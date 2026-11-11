# Review notes

One note per record: `reviews/<namespace>/<id>/<version>.md`. A note is written
when the record is added, and edited only to append a withdrawal.

## What a note says

- `reviewed`: the date the bytes were checked.
- `by`: the GitHub login that checked them.
- `sha256`: the hash that was checked, copied from the record.
- `verdict`: `accepted` or `rejected`, plus what was and was not covered.

A note that says `accepted` means: the zip at that hash matches the record's
`kind`, `specVersion`, `engine`, `collection` and `capabilities`; the envelope
passed; and the engine imported it. It does not mean the story is good.

## Withdrawal

A version is never deleted from `index.json`. To withdraw one:

1. Run `python tools/review.py --withdraw <namespace>/<id>@<version> --reason "<why>" --date <YYYY-MM-DD> --apply`.
   That flips `status` to `withdrawn` and appends a `## Withdrawal` section to
   the record's note.
2. Run `python tools/validate.py index.json`; a withdrawn record still validates.
3. Put the reason in the pull request; the site and any consumer keep showing
   the version as withdrawn, not as missing.

`python tools/review.py --self-test` proves the rule without touching the index:
it withdraws a copy, checks that the record is still there, and checks that the
validator still passes.

## Liveness

Records point at GitHub release assets; the registry does not host bytes.

- Weekly, or when a download fails, check the asset named by the record:
  `https://github.com/<homepage>/releases/download/pack/<id>/v<version>/<id>.zip`
  must answer `200` and its bytes must still hash to the record's `sha256`.
- If the asset is gone: open a note on the version with the date and the
  failure, then withdraw it. Do not delete the record; a save may still name it.
- A version that was withdrawn and later republished gets a new record; the
  withdrawn one stays.

This is a documented procedure, not a scheduled job yet.
