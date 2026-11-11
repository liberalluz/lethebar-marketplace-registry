# ADR-0001 · The index is the product; the files stay with the author

## Context

The registry is the place a player's engine asks "what can I install?". It is
not a download host. A package is a zip the author builds and publishes on
their own repository; the registry records which zip a name and a version mean.

Two facts force the shape:

- The engine only accepts a package whose id matches `^[a-z0-9-]+$`. A
  namespaced id such as `liberalluz.sanguo` cannot be a package id.
- GitHub release assets are served without CORS, so a browser cannot install
  straight from a link. The engine takes a file the player picked.

## Decision

- **Index only.** The registry stores JSON records and review notes. It never
  stores, mirrors or proxies a zip. `sha256` is how a record names a zip.
- **Identity is `(namespace, id, version)`.** `namespace` is the author's
  handle; `id` is the package's own id and stays flat. The same `id` may exist
  under two namespaces; the engine only ever sees `id`.
- **Versions are immutable.** A published `(namespace, id, version)` is never
  edited. A withdrawal sets `status: withdrawn` and keeps the record.
- **Review is layered by kind.** A bundle is checked as a game; a layer as a
  patch; genre material is not installable at all.
- **No accounts, no upload, no submission endpoint.** A listing is a pull
  request that appends one record.
- **The site is built from a pinned registry commit.** It renders what the
  index says and links to the author's release page.

## Consequences

- A player installs by downloading the zip from the author's release and
  picking it in the engine. A broken link is the author's, not ours.
- The index can be reviewed as a diff: one record per line of JSON.
- Deleting an author's release leaves a dead record; that is visible and
  fixable, which is better than a silent 404 inside our storage.

## Alternatives

- **Host the zips.** Rejected: storage, takedown and licence obligations for
  files we did not build.
- **Namespaced package ids.** Rejected: it breaks the engine's id rule and
  every save key.
- **One repository for index and site.** Rejected: the site changes far more
  often than the index, and a site deploy must not be able to edit records.
