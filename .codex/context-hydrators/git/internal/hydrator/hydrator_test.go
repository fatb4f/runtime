package hydrator

import (
	"os"
	"sort"
	"strings"
	"testing"

	"github.com/fatb4f/dotfiles/.codex/context-hydrators/git/internal/testfixture"
)

func TestHydrateCommittedRepresentsCommittedTreeWithoutTraversal(t *testing.T) {
	fixture := newFixtureRepository(t)
	observation := hydrateFixture(t, fixture, fixture.Commits["F"])

	if observation.ResolvedRevision.Hex != fixture.Commits["F"] {
		t.Fatalf("resolved revision = %s, want %s", observation.ResolvedRevision.Hex, fixture.Commits["F"])
	}
	if observation.RequestedRevision != fixture.Commits["F"] {
		t.Fatalf("requested revision was not preserved: %q", observation.RequestedRevision)
	}

	byPath := occurrenceMap(observation)
	assertOccurrence(t, byPath, "docs", "040000", "tree")
	assertOccurrence(t, byPath, "docs/guide.txt", "100644", "blob")
	assertOccurrence(t, byPath, "src", "040000", "tree")
	assertOccurrence(t, byPath, "src/main.sh", "100755", "blob")
	assertOccurrence(t, byPath, "guide-link", "120000", "symlink")
	assertOccurrence(t, byPath, "vendor/dependency", "160000", "submodule")

	if byPath["guide-link"].Size == nil || *byPath["guide-link"].Size != int64(len("docs/guide.txt")) {
		t.Fatalf("symlink payload size = %v, want %d", byPath["guide-link"].Size, len("docs/guide.txt"))
	}
	if byPath["vendor/dependency"].Size != nil {
		t.Fatal("submodule occurrence must not carry blob size")
	}
	for path := range byPath {
		if strings.HasPrefix(path, "vendor/dependency/") || strings.HasPrefix(path, "guide-link/") {
			t.Fatalf("hydrator traversed an opaque entry: %s", path)
		}
	}

	paths := make([]string, 0, len(observation.Occurrences))
	for _, occurrence := range observation.Occurrences {
		paths = append(paths, occurrence.Path)
	}
	if !sort.StringsAreSorted(paths) {
		t.Fatalf("occurrences are not canonically sorted: %v", paths)
	}
}

func TestHydrateCommittedIsByteDeterministic(t *testing.T) {
	assertDeterminismProperty(t, newFixtureRepository(t))
}

func TestRevisionSelectorsBindToExactCommit(t *testing.T) {
	assertRevisionBoundProperty(t, newFixtureRepository(t))
}

func TestContentAndPathIdentityProperties(t *testing.T) {
	fixture := newFixtureRepository(t)
	assertRenameContentPreservedProperty(t, fixture)
	assertContentEditContentChangedProperty(t, fixture)
	assertUnrelatedEntryPreservedProperty(t, fixture)
	assertModeChangeContentPreservedProperty(t, fixture)
}

func TestDecodeRequestIsClosed(t *testing.T) {
	valid := `{"schema":"kernel.git-committed-snapshot-request.v0","repositoryID":"repo.fixture","path":".","revision":"HEAD"}`
	request, err := DecodeRequest(strings.NewReader(valid))
	if err != nil {
		t.Fatalf("decode valid request: %v", err)
	}
	if request.RepositoryID != "repo.fixture" {
		t.Fatalf("repository ID = %q", request.RepositoryID)
	}

	invalid := []string{
		`{"schema":"kernel.git-committed-snapshot-request.v0","repositoryID":"repo.fixture","path":".","revision":"HEAD","extra":true}`,
		valid + ` {}`,
		`{"schema":"wrong","repositoryID":"repo.fixture","path":".","revision":"HEAD"}`,
		`{"schema":"kernel.git-committed-snapshot-request.v0","repositoryID":"INVALID","path":".","revision":"HEAD"}`,
		`{"schema":"kernel.git-committed-snapshot-request.v0","repositoryID":"repo.fixture","path":"../repo","revision":"HEAD"}`,
	}
	for _, document := range invalid {
		if _, err := DecodeRequest(strings.NewReader(document)); err == nil {
			t.Fatalf("invalid request accepted: %s", document)
		}
	}
}

func hydrateFixture(t *testing.T, fixture testfixture.Repository, revision string) Observation {
	t.Helper()
	observation, err := HydrateCommitted(fixtureRequest(fixture, revision), DefaultConfig())
	if err != nil {
		t.Fatalf("hydrate fixture revision %s: %v", revision, err)
	}
	return observation
}

func fixtureRequest(fixture testfixture.Repository, revision string) Request {
	return Request{
		Schema:       RequestSchema,
		RepositoryID: "repo.fixture",
		Path:         fixture.Path,
		Revision:     revision,
	}
}

func occurrenceMap(observation Observation) map[string]Occurrence {
	result := make(map[string]Occurrence, len(observation.Occurrences))
	for _, occurrence := range observation.Occurrences {
		result[occurrence.Path] = occurrence
	}
	return result
}

func assertOccurrence(t *testing.T, occurrences map[string]Occurrence, path, mode, kind string) {
	t.Helper()
	occurrence, ok := occurrences[path]
	if !ok {
		t.Fatalf("missing occurrence %q", path)
	}
	if occurrence.Mode != mode || occurrence.Kind != kind {
		t.Fatalf("occurrence %q = mode %s kind %s, want %s %s", path, occurrence.Mode, occurrence.Kind, mode, kind)
	}
}

func newFixtureRepository(t *testing.T) testfixture.Repository {
	t.Helper()
	root, err := os.MkdirTemp(".", "fixture-repository-")
	if err != nil {
		t.Fatalf("create fixture directory: %v", err)
	}
	t.Cleanup(func() { _ = os.RemoveAll(root) })
	repository, err := testfixture.Create(root)
	if err != nil {
		t.Fatalf("create fixture repository: %v", err)
	}
	return repository
}
