package hydrator

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/fatb4f/dotfiles/.codex/context-hydrators/git/internal/identity"
	"github.com/fatb4f/dotfiles/.codex/context-hydrators/git/internal/testfixture"
)

type overlayFixture struct {
	Repository testfixture.Repository
	Clean      OverlayObservation
	Dirty      OverlayObservation
}

func TestHydrateOverlayRepresentsIndexAndWorktreeSeparately(t *testing.T) {
	fixture := newOverlayFixture(t)
	index := overlayOccurrenceMap(fixture.Dirty.Index.Occurrences)
	worktree := overlayOccurrenceMap(fixture.Dirty.Worktree.Occurrences)

	assertOverlayOccurrence(t, index, "docs/guide.txt", "index", "modified", "blob")
	assertOverlayOccurrence(t, worktree, "docs/guide.txt", "worktree", "modified", "blob")
	assertOverlayOccurrence(t, index, "staged-add.txt", "index", "added", "blob")
	assertOverlayOccurrence(t, index, "unrelated.txt", "index", "deleted", "")
	assertOverlayOccurrence(t, worktree, "guide-link", "worktree", "deleted", "")
	assertOverlayOccurrence(t, worktree, "untracked.txt", "worktree", "untracked", "blob")
	assertOverlayOccurrence(t, index, "overlay-link", "index", "added", "symlink")
	assertOverlayOccurrence(t, index, "vendor/overlay", "index", "added", "submodule")

	modeChange := index["src/main.sh"]
	if modeChange.Status != "modified" || !modeChange.ModeChanged || modeChange.Mode != "100644" {
		t.Fatalf("executable mode change = %#v", modeChange)
	}
	for _, deleted := range []OverlayOccurrence{index["unrelated.txt"], worktree["guide-link"]} {
		if deleted.ObjectID != nil || deleted.Mode != "" || deleted.Kind != "" || deleted.Size != nil {
			t.Fatalf("deletion fabricated content fields: %#v", deleted)
		}
	}
}

func TestOverlayObservationUsesSizeWireField(t *testing.T) {
	fixture := newOverlayFixture(t)
	payload, err := MarshalOverlayCanonical(fixture.Dirty)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(payload, []byte(`"size":`)) {
		t.Fatal("overlay observation omitted size wire field")
	}
	if bytes.Contains(payload, []byte(`"gitSizeBytes":`)) {
		t.Fatal("overlay observation leaked projection-only gitSizeBytes field")
	}
}

func TestCleanOverlayIsEmpty(t *testing.T) {
	fixture := newFixtureRepository(t)
	observation := hydrateOverlayFixture(t, fixture)
	if len(observation.Index.Occurrences) != 0 || len(observation.Worktree.Occurrences) != 0 {
		t.Fatalf("clean overlay is not empty: index=%#v worktree=%#v", observation.Index.Occurrences, observation.Worktree.Occurrences)
	}
}

func TestDecodeOverlayRequestAndObservationAreClosed(t *testing.T) {
	base := "1111111111111111111111111111111111111111"
	valid := `{"schema":"kernel.git-overlay-request.v0","repositoryID":"repo.fixture","path":".","baseRevision":{"format":"sha1","hex":"` + base + `"}}`
	if _, err := DecodeOverlayRequest(strings.NewReader(valid)); err != nil {
		t.Fatalf("decode valid overlay request: %v", err)
	}
	for _, document := range []string{
		strings.TrimSuffix(valid, "}") + `,"unknown":true}`,
		valid + ` {}`,
		strings.Replace(valid, `"sha1"`, `"INVALID"`, 1),
		strings.Replace(valid, `"path":"."`, `"path":"../escape"`, 1),
	} {
		if _, err := DecodeOverlayRequest(strings.NewReader(document)); err == nil {
			t.Fatalf("invalid overlay request accepted: %s", document)
		}
	}

	fixture := newOverlayFixture(t)
	payload, err := MarshalOverlayCanonical(fixture.Dirty)
	if err != nil {
		t.Fatalf("marshal overlay observation: %v", err)
	}
	if _, err := DecodeOverlayObservation(bytes.NewReader(payload)); err != nil {
		t.Fatalf("decode canonical overlay observation: %v", err)
	}
	var document map[string]any
	if err := json.Unmarshal(payload, &document); err != nil {
		t.Fatal(err)
	}
	document["unknown"] = true
	mutated, _ := json.Marshal(document)
	if _, err := DecodeOverlayObservation(bytes.NewReader(mutated)); err == nil {
		t.Fatal("typed overlay observation accepted unknown field")
	}
}

func newOverlayFixture(t *testing.T) overlayFixture {
	t.Helper()
	repository := newFixtureRepository(t)
	clean := hydrateOverlayFixture(t, repository)

	mustWriteOverlayFile(t, repository, "docs/guide.txt", "staged guide\n", 0o644)
	mustRunFixtureGit(t, repository, "add", "docs/guide.txt")
	mustWriteOverlayFile(t, repository, "docs/guide.txt", "unstaged guide\n", 0o644)

	mustWriteOverlayFile(t, repository, "staged-add.txt", "staged addition\n", 0o644)
	mustRunFixtureGit(t, repository, "add", "staged-add.txt")
	mustRunFixtureGit(t, repository, "rm", "-f", "unrelated.txt")

	if err := os.Chmod(filepath.Join(repository.Path, "src/main.sh"), 0o644); err != nil {
		t.Fatalf("change executable mode: %v", err)
	}
	mustRunFixtureGit(t, repository, "add", "src/main.sh")

	if err := testfixture.RemoveWorktreePath(repository, "guide-link"); err != nil {
		t.Fatal(err)
	}
	mustWriteOverlayFile(t, repository, "untracked.txt", "untracked\n", 0o644)

	if err := testfixture.CreateWorktreeSymlink(repository, "untracked.txt", "overlay-link"); err != nil {
		t.Fatal(err)
	}
	mustRunFixtureGit(t, repository, "add", "overlay-link")

	if err := os.MkdirAll(filepath.Join(repository.Path, "vendor/overlay"), 0o755); err != nil {
		t.Fatalf("create opaque overlay gitlink mount: %v", err)
	}
	mustRunFixtureGit(t, repository, "update-index", "--add", "--cacheinfo", "160000,"+repository.Commits["A"]+",vendor/overlay")

	dirty := hydrateOverlayFixture(t, repository)
	return overlayFixture{Repository: repository, Clean: clean, Dirty: dirty}
}

func hydrateOverlayFixture(t *testing.T, fixture testfixture.Repository) OverlayObservation {
	t.Helper()
	observation, err := HydrateOverlay(overlayFixtureRequest(fixture), DefaultConfig())
	if err != nil {
		t.Fatalf("hydrate overlay: %v", err)
	}
	return observation
}

func overlayFixtureRequest(fixture testfixture.Repository) OverlayRequest {
	return OverlayRequest{
		Schema: OverlayRequestSchema, RepositoryID: "repo.fixture", Path: fixture.Path,
		BaseRevision: objectIDFromHex(fixture.Commits["F"]),
	}
}

func objectIDFromHex(hex string) identity.ObjectID {
	return identity.ObjectID{Format: "sha1", Hex: hex}
}

func mustWriteOverlayFile(t *testing.T, repository testfixture.Repository, path, content string, mode os.FileMode) {
	t.Helper()
	if err := testfixture.WriteWorktreeFile(repository, path, content, mode); err != nil {
		t.Fatal(err)
	}
}

func mustRunFixtureGit(t *testing.T, repository testfixture.Repository, arguments ...string) {
	t.Helper()
	if _, err := testfixture.RunGit(repository, arguments...); err != nil {
		t.Fatal(err)
	}
}

func overlayOccurrenceMap(occurrences []OverlayOccurrence) map[string]OverlayOccurrence {
	result := make(map[string]OverlayOccurrence, len(occurrences))
	for _, occurrence := range occurrences {
		result[occurrence.Path] = occurrence
	}
	return result
}

func assertOverlayOccurrence(t *testing.T, occurrences map[string]OverlayOccurrence, path, layer, status, kind string) {
	t.Helper()
	occurrence, ok := occurrences[path]
	if !ok {
		t.Fatalf("missing %s occurrence %q", layer, path)
	}
	if occurrence.Layer != layer || occurrence.Status != status || occurrence.Kind != kind {
		t.Fatalf("occurrence %q = %#v, want layer=%s status=%s kind=%s", path, occurrence, layer, status, kind)
	}
}
