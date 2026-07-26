package hydrator

import "github.com/fatb4f/dotfiles/.codex/context-hydrators/git/internal/identity"

const (
	OverlayRequestSchema     = "kernel.git-overlay-request.v0"
	OverlayObservationSchema = "kernel.git-overlay-observation.v0"
	IndexOverlaySchema       = "kernel.git-index-overlay.v0"
	WorktreeOverlaySchema    = "kernel.git-worktree-overlay.v0"
)

type OverlayRequest struct {
	Schema       string            `json:"schema"`
	RepositoryID string            `json:"repositoryID"`
	Path         string            `json:"path"`
	BaseRevision identity.ObjectID `json:"baseRevision"`
}

type OverlayOccurrence struct {
	Path        string             `json:"path"`
	Layer       string             `json:"layer"`
	Status      string             `json:"status"`
	ModeChanged bool               `json:"modeChanged"`
	Mode        string             `json:"mode,omitempty"`
	Kind        string             `json:"kind,omitempty"`
	ObjectID    *identity.ObjectID `json:"objectID,omitempty"`
	Size        *int64             `json:"size,omitempty"`
}

type IndexOverlay struct {
	Schema       string              `json:"schema"`
	RepositoryID string              `json:"repositoryID"`
	BaseRevision identity.ObjectID   `json:"baseRevision"`
	Occurrences  []OverlayOccurrence `json:"occurrences"`
}

type WorktreeOverlay struct {
	Schema       string              `json:"schema"`
	RepositoryID string              `json:"repositoryID"`
	BaseRevision identity.ObjectID   `json:"baseRevision"`
	Occurrences  []OverlayOccurrence `json:"occurrences"`
}

type OverlayObservation struct {
	Schema       string            `json:"schema"`
	RepositoryID string            `json:"repositoryID"`
	BaseRevision identity.ObjectID `json:"baseRevision"`
	BaseTree     identity.ObjectID `json:"baseTree"`
	Index        IndexOverlay      `json:"index"`
	Worktree     WorktreeOverlay   `json:"worktree"`
	Hydrator     HydratorIdentity  `json:"hydrator"`
}
