# Immutable committed-snapshot hydrator

`context-git-hydrator` is a read-only go-git adapter for Issues #68 and #70. It resolves one revision to an exact commit and emits a deterministic structural observation of that commit's root tree.

## Contract

```text
repository + revision request
          ↓ go-git
exact commit resolution
          ↓ canonical observation
closed committed-tree observation
          ↓ CUE
candidate repository-context graph snapshot
```

The adapter does not inspect the index or worktree, fetch network data, follow symlinks, recurse into gitlinks, embed blob contents, infer language semantics, or promote evidence authority.

## CLI

```bash
context-git-hydrator committed --request request.json
```

Example request:

```json
{"schema":"kernel.git-committed-snapshot-request.v0","repositoryID":"repo.dotfiles","path":".","revision":"HEAD"}
```

`repositoryID` is explicit. Branch, tag, symbolic, and exact-hash selectors are resolved before observation. The emitted `requestedRevision` field is the canonical exact commit hex binding, so equivalent selectors produce byte-identical normalized output.

The observation contains no checkout path, timestamp, remote URL, random identifier, or host-environment field.

## Build provenance

Release builds must inject the source-bound hydrator digest:

```bash
go build -trimpath \
  -ldflags "-X github.com/fatb4f/dotfiles/.codex/context-hydrators/git/internal/hydrator.BuildHydratorDigest=sha256:<digest>" \
  ./cmd/context-git-hydrator
```

An unbound build fails closed when hydration is attempted. The repository qualification script deterministically hashes the Go source, `go.mod`, and `go.sum`, injects that digest, and verifies that the emitted provenance matches it.

## Identity

- `contentIdentity`: Git object format and object ID.
- `occurrenceIdentity`: repository plus normalized path; stable while that repository path is preserved across revisions.
- `snapshotOccurrenceIdentity`: repository plus resolved revision plus normalized path; bound to one exact committed snapshot.

A rename preserves content identity while changing both occurrence identities. A content edit, unrelated addition, or mode-only change preserves the stable occurrence identity for unaffected paths while changing the revision-bound snapshot occurrence identity. Graph member keys and containment endpoints use stable occurrence identity; source and provenance fields retain the exact resolved revision.

## Qualification

From this module:

```bash
go test ./...
```

To preserve the executable property report as a CI artifact:

```bash
CONTEXT_GIT_HYDRATOR_PROPERTY_REPORT="$PWD/property-report.json" \
  go test -count=1 -json ./... >go-test.jsonl
```

The repository qualification writes stable `property-report.json` and
`qualification-report.json` files under
`${CONTEXT_GIT_QUALIFICATION_DIR:-${TMPDIR:-/tmp}/context-git-hydrator-qualification}`.

From the repository root:

```bash
bash .github/scripts/context-git-hydrator-test.sh
```

The qualification script:

- creates hermetic deterministic commits A-F with an explicit object format;
- injects and verifies build-bound hydrator provenance;
- proves equivalent selectors emit identical observations;
- validates observations and projections with CUE;
- executes structural, authority, and opaque-entry rejection mutations;
- derives declared, generated, executed, and reported property sets independently;
- rejects failed property results and validates the closed qualification report.

Hypothesis strategies cover every cataloged invariant across positive,
negative, boundary, metamorphic, and controlled-environment cases. Differential
checks compare CUE, the typed Go adapter, hydrator execution, projection
references, and normalized serialization where applicable. If an invalid
mutation is unexpectedly accepted, the reverse oracle preserves the original
and minimized fixtures in a non-authoritative, review-pending regression queue;
it never promotes the candidate into the property catalog.
