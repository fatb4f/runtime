package identity

import "testing"

func TestContentOccurrenceAndSnapshotOccurrenceIdentityAreDistinct(t *testing.T) {
	t.Parallel()

	blob := ObjectID{Format: "sha1", Hex: "1111111111111111111111111111111111111111"}
	revisionA := ObjectID{Format: "sha1", Hex: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
	revisionB := ObjectID{Format: "sha1", Hex: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}

	if ContentID(blob) != ContentID(blob) {
		t.Fatal("content identity must be stable")
	}
	if OccurrenceID("repo.fixture", "a.txt") == OccurrenceID("repo.fixture", "b.txt") {
		t.Fatal("rename must change occurrence identity")
	}
	if OccurrenceID("repo.fixture", "a.txt") != OccurrenceID("repo.fixture", "a.txt") {
		t.Fatal("unchanged path must preserve occurrence identity across revisions")
	}
	if SnapshotOccurrenceID("repo.fixture", revisionA, "a.txt") == SnapshotOccurrenceID("repo.fixture", revisionB, "a.txt") {
		t.Fatal("snapshot occurrence identity must bind the resolved revision")
	}
	if OccurrenceID("repo.fixture", "a.txt") == SnapshotOccurrenceID("repo.fixture", revisionA, "a.txt") {
		t.Fatal("stable occurrence identity and snapshot occurrence identity must remain distinct")
	}
}

func TestLayerOccurrenceIdentitySeparatesMutableLayers(t *testing.T) {
	revision := ObjectID{Format: "sha1", Hex: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
	index := LayerOccurrenceID("repo.fixture", revision, "index", "same.txt")
	worktree := LayerOccurrenceID("repo.fixture", revision, "worktree", "same.txt")
	if index == worktree {
		t.Fatal("index and worktree layer identities collapsed")
	}
	if index != LayerOccurrenceID("repo.fixture", revision, "index", "same.txt") {
		t.Fatal("layer occurrence identity is not deterministic")
	}
}
