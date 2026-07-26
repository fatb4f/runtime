package identity

import (
	"crypto/sha256"
	"encoding/hex"
)

// ObjectID is the transport-neutral identity of one Git object.
type ObjectID struct {
	Format string `json:"format"`
	Hex    string `json:"hex"`
}

// ContentID preserves immutable Git object identity independently of where the
// object occurs in a repository tree.
func ContentID(object ObjectID) string {
	return "git-object:" + object.Format + ":" + object.Hex
}

// OccurrenceID identifies one normalized path occurrence in one repository.
// It remains stable across committed revisions while that path is preserved.
func OccurrenceID(repositoryID, path string) string {
	return digest(repositoryID + "\x00" + path)
}

// SnapshotOccurrenceID binds one path occurrence to one exact committed
// revision. It is provenance identity, not the stable graph-member identity.
func SnapshotOccurrenceID(repositoryID string, revision ObjectID, path string) string {
	return digest(repositoryID + "\x00" + revision.Format + "\x00" + revision.Hex + "\x00" + path)
}

// LayerOccurrenceID keeps mutable index and worktree occurrences distinct
// while binding both to the exact immutable commit from which they were
// collected. It is separate from path occurrence and content identity.
func LayerOccurrenceID(repositoryID string, revision ObjectID, layer, path string) string {
	return digest(repositoryID + "\x00" + revision.Format + "\x00" + revision.Hex + "\x00" + layer + "\x00" + path)
}

// ProjectionID binds a normalized observation to the schema and authority
// policy identities used to project it into the context graph.
func ProjectionID(observationDigest, schemaDigest, policyDigest string) string {
	return digest(observationDigest + "\x00" + schemaDigest + "\x00" + policyDigest)
}

func digest(value string) string {
	sum := sha256.Sum256([]byte(value))
	return "sha256:" + hex.EncodeToString(sum[:])
}
