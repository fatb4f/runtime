package hydrator

import "github.com/fatb4f/dotfiles/.codex/context-hydrators/git/internal/identity"

const (
	RequestSchema     = "kernel.git-committed-snapshot-request.v0"
	ObservationSchema = "kernel.git-committed-snapshot-observation.v0"

	DefaultHydratorIdentity = "context-git-hydrator"
	UnboundHydratorDigest   = "sha256:0000000000000000000000000000000000000000000000000000000000000000"
)

// BuildHydratorDigest is injected by the reproducible build with -ldflags -X.
// The unbound default fails closed when the command is run without release
// provenance metadata.
var BuildHydratorDigest = UnboundHydratorDigest

type Request struct {
	Schema       string `json:"schema"`
	RepositoryID string `json:"repositoryID"`
	Path         string `json:"path"`
	Revision     string `json:"revision"`
}

type Occurrence struct {
	Path     string            `json:"path"`
	Mode     string            `json:"mode"`
	Kind     string            `json:"kind"`
	ObjectID identity.ObjectID `json:"objectID"`
	Size     *int64            `json:"size,omitempty"`
}

type HydratorIdentity struct {
	Identity string `json:"identity"`
	Digest   string `json:"digest"`
}

type Observation struct {
	Schema       string `json:"schema"`
	RepositoryID string `json:"repositoryID"`

	// RequestedRevision is the canonical exact-commit binding derived after
	// resolving the caller's selector. Raw branch, tag, or symbolic selectors
	// are request transport and do not enter normalized observation identity.
	RequestedRevision string            `json:"requestedRevision"`
	ResolvedRevision  identity.ObjectID `json:"resolvedRevision"`
	RootTree          identity.ObjectID `json:"rootTree"`
	Occurrences       []Occurrence      `json:"occurrences"`
	Hydrator          HydratorIdentity  `json:"hydrator"`
}
