package hydrator

import (
	"bufio"
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"testing"

	"github.com/fatb4f/dotfiles/.codex/context-hydrators/git/internal/identity"
)

type overlayPropertyCase struct {
	ID  string
	Run func(*testing.T, overlayFixture)
}

func TestOverlayDeclaredPropertyManifestLoads(t *testing.T) {
	assertStringSetEqual(t, "overlay declared/generated", loadOverlayDeclaredPropertyIDs(t), OverlayGeneratedPropertyIDs())
}

func TestOverlayDeclaredGeneratedExecutedReportedPropertySetEquality(t *testing.T) {
	fixture := newOverlayFixture(t)
	declared := loadOverlayDeclaredPropertyIDs(t)
	generated := loadOverlayGeneratedPropertyIDs(t, fixture)
	executed := make([]string, 0, len(generated))
	results := make([]PropertyResult, 0, len(generated))
	for _, property := range executableOverlayPropertyCases() {
		property := property
		passed := t.Run("execute/"+property.ID, func(t *testing.T) { property.Run(t, fixture) })
		executed = append(executed, property.ID)
		status := PropertyStatusFailed
		if passed {
			status = PropertyStatusPassed
		}
		results = append(results, PropertyResult{PropertyID: property.ID, Status: status})
	}
	reportPath := overlayPropertyReportPath(t)
	if err := WriteOverlayPropertyReport(reportPath, OverlayPropertyReport{Schema: OverlayPropertyReportSchema, Results: results}); err != nil {
		t.Fatalf("persist overlay property report: %v", err)
	}
	report, err := ReadOverlayPropertyReport(reportPath)
	if err != nil {
		t.Fatalf("reload overlay property report: %v", err)
	}
	reported, err := OverlayReportedPropertyIDs(report)
	if err != nil {
		t.Fatalf("derive reported overlay properties: %v", err)
	}
	assertStringSetEqual(t, "overlay declared/generated", declared, generated)
	assertStringSetEqual(t, "overlay declared/executed", declared, executed)
	assertStringSetEqual(t, "overlay declared/reported", declared, reported)
}

func TestOverlayPropertyReportIsClosedAndUnique(t *testing.T) {
	valid := OverlayPropertyReport{Schema: OverlayPropertyReportSchema, Results: []PropertyResult{{PropertyID: "overlay-determinism", Status: "passed"}}}
	path := filepath.Join(t.TempDir(), "report.json")
	if err := WriteOverlayPropertyReport(path, valid); err != nil {
		t.Fatal(err)
	}
	for _, report := range []OverlayPropertyReport{
		{Schema: "wrong", Results: valid.Results},
		{Schema: OverlayPropertyReportSchema, Results: append(valid.Results, valid.Results[0])},
	} {
		if err := ValidateOverlayPropertyReport(report); err == nil {
			t.Fatalf("invalid overlay report accepted: %#v", report)
		}
	}
}

func executableOverlayPropertyCases() []overlayPropertyCase {
	return []overlayPropertyCase{
		{"overlay-determinism", assertOverlayDeterminism},
		{"clean-overlay-preserves-base", assertCleanOverlayPreservesBase},
		{"exact-base-bound", assertExactOverlayBaseBound},
		{"index-worktree-distinct", assertOverlayLayersDistinct},
		{"same-path-layers-coexist", assertSamePathLayersCoexist},
		{"untracked-not-staged", assertUntrackedNotStaged},
		{"staged-addition-observed", assertStagedAdditionObserved},
		{"staged-modification-observed", assertStagedModificationObserved},
		{"staged-deletion-explicit", assertStagedDeletionExplicit},
		{"unstaged-modification-observed", assertUnstagedModificationObserved},
		{"unstaged-deletion-explicit", assertUnstagedDeletionExplicit},
		{"executable-mode-change-observed", assertExecutableModeChangeObserved},
		{"symlink-not-followed", assertOverlaySymlinkNotFollowed},
		{"submodule-not-traversed", assertOverlaySubmoduleNotTraversed},
		{"deletion-content-absent", assertDeletionContentAbsent},
		{"unrelated-change-identity-preserved", assertOverlayUnrelatedIdentityPreserved},
		{"unknown-field-rejected", assertOverlayUnknownFieldRejected},
		{"duplicate-index-path-rejected", assertDuplicateIndexPathRejected},
		{"duplicate-worktree-path-rejected", assertDuplicateWorktreePathRejected},
		{"unsorted-layer-path-rejected", assertUnsortedOverlayPathRejected},
		{"invalid-mode-kind-rejected", assertInvalidOverlayModeKindRejected},
		{"non-normalized-path-rejected", assertNonNormalizedOverlayPathRejected},
		{"broken-base-binding-rejected", assertBrokenOverlayBaseBindingRejected},
		{"elevated-authority-rejected", assertOverlayElevatedAuthorityRejected},
	}
}

func assertOverlayDeterminism(t *testing.T, fixture overlayFixture) {
	first := hydrateOverlayFixture(t, fixture.Repository)
	firstJSON, err := MarshalOverlayCanonical(first)
	if err != nil {
		t.Fatal(err)
	}
	t.Setenv("TZ", "Pacific/Kiritimati")
	t.Setenv("LANG", "C")
	second := hydrateOverlayFixture(t, fixture.Repository)
	secondJSON, err := MarshalOverlayCanonical(second)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(firstJSON, secondJSON) {
		t.Fatal("environment perturbation changed canonical overlay bytes")
	}
	if bytes.Contains(firstJSON, []byte(fixture.Repository.Path)) {
		t.Fatal("overlay leaked absolute or fixture path")
	}
}

func assertCleanOverlayPreservesBase(t *testing.T, fixture overlayFixture) {
	if len(fixture.Clean.Index.Occurrences)+len(fixture.Clean.Worktree.Occurrences) != 0 {
		t.Fatal("clean overlay contains occurrences")
	}
}

func assertExactOverlayBaseBound(t *testing.T, fixture overlayFixture) {
	request := overlayFixtureRequest(fixture.Repository)
	request.BaseRevision = objectIDFromHex(fixture.Repository.Commits["A"])
	if _, err := HydrateOverlay(request, DefaultConfig()); err == nil {
		t.Fatal("collector accepted an exact base that does not match HEAD")
	}
}

func assertOverlayLayersDistinct(t *testing.T, fixture overlayFixture) {
	mutated := cloneOverlayObservation(t, fixture.Dirty)
	mutated.Worktree.Occurrences[0].Layer = "index"
	if err := ValidateOverlayObservation(mutated); err == nil {
		t.Fatal("typed adapter collapsed a worktree occurrence into index")
	}
}

func assertSamePathLayersCoexist(t *testing.T, fixture overlayFixture) {
	index := overlayOccurrenceMap(fixture.Dirty.Index.Occurrences)["docs/guide.txt"]
	worktree := overlayOccurrenceMap(fixture.Dirty.Worktree.Occurrences)["docs/guide.txt"]
	if index.Path == "" || worktree.Path == "" {
		t.Fatal("same-path staged and unstaged occurrences did not coexist")
	}
	base := fixture.Dirty.BaseRevision
	if identity.OccurrenceID("repo.fixture", index.Path) != identity.OccurrenceID("repo.fixture", worktree.Path) {
		t.Fatal("same path changed stable occurrence identity")
	}
	if identity.LayerOccurrenceID("repo.fixture", base, "index", index.Path) == identity.LayerOccurrenceID("repo.fixture", base, "worktree", worktree.Path) {
		t.Fatal("same path collapsed layer occurrence identity")
	}
}

func assertUntrackedNotStaged(t *testing.T, fixture overlayFixture) {
	if _, ok := overlayOccurrenceMap(fixture.Dirty.Index.Occurrences)["untracked.txt"]; ok {
		t.Fatal("untracked worktree entry appeared staged")
	}
	assertOverlayOccurrence(t, overlayOccurrenceMap(fixture.Dirty.Worktree.Occurrences), "untracked.txt", "worktree", "untracked", "blob")
}

func assertStagedAdditionObserved(t *testing.T, fixture overlayFixture) {
	assertOverlayOccurrence(t, overlayOccurrenceMap(fixture.Dirty.Index.Occurrences), "staged-add.txt", "index", "added", "blob")
}

func assertStagedModificationObserved(t *testing.T, fixture overlayFixture) {
	assertOverlayOccurrence(t, overlayOccurrenceMap(fixture.Dirty.Index.Occurrences), "docs/guide.txt", "index", "modified", "blob")
}

func assertStagedDeletionExplicit(t *testing.T, fixture overlayFixture) {
	assertOverlayOccurrence(t, overlayOccurrenceMap(fixture.Dirty.Index.Occurrences), "unrelated.txt", "index", "deleted", "")
}

func assertUnstagedModificationObserved(t *testing.T, fixture overlayFixture) {
	assertOverlayOccurrence(t, overlayOccurrenceMap(fixture.Dirty.Worktree.Occurrences), "docs/guide.txt", "worktree", "modified", "blob")
}

func assertUnstagedDeletionExplicit(t *testing.T, fixture overlayFixture) {
	assertOverlayOccurrence(t, overlayOccurrenceMap(fixture.Dirty.Worktree.Occurrences), "guide-link", "worktree", "deleted", "")
}

func assertExecutableModeChangeObserved(t *testing.T, fixture overlayFixture) {
	occurrence := overlayOccurrenceMap(fixture.Dirty.Index.Occurrences)["src/main.sh"]
	if !occurrence.ModeChanged || occurrence.Mode != "100644" {
		t.Fatalf("mode-only change not represented: %#v", occurrence)
	}
	base := occurrenceMap(hydrateFixture(t, fixture.Repository, fixture.Repository.Commits["F"]))["src/main.sh"]
	if occurrence.ObjectID == nil || *occurrence.ObjectID != base.ObjectID {
		t.Fatal("mode-only change did not preserve content identity")
	}
}

func assertOverlaySymlinkNotFollowed(t *testing.T, fixture overlayFixture) {
	occurrence := overlayOccurrenceMap(fixture.Dirty.Index.Occurrences)["overlay-link"]
	if occurrence.Kind != "symlink" || occurrence.Size == nil || *occurrence.Size != int64(len("untracked.txt")) {
		t.Fatalf("symlink was not represented from link text: %#v", occurrence)
	}
}

func assertOverlaySubmoduleNotTraversed(t *testing.T, fixture overlayFixture) {
	occurrence := overlayOccurrenceMap(fixture.Dirty.Index.Occurrences)["vendor/overlay"]
	if occurrence.Kind != "submodule" || occurrence.Size != nil {
		t.Fatalf("gitlink was not opaque: %#v", occurrence)
	}
	for _, layer := range [][]OverlayOccurrence{fixture.Dirty.Index.Occurrences, fixture.Dirty.Worktree.Occurrences} {
		for _, candidate := range layer {
			if strings.HasPrefix(candidate.Path, "vendor/overlay/") {
				t.Fatalf("collector traversed gitlink: %s", candidate.Path)
			}
		}
	}
}

func assertDeletionContentAbsent(t *testing.T, fixture overlayFixture) {
	mutated := cloneOverlayObservation(t, fixture.Dirty)
	for index := range mutated.Index.Occurrences {
		if mutated.Index.Occurrences[index].Status == "deleted" {
			object := objectIDFromHex(strings.Repeat("a", 40))
			mutated.Index.Occurrences[index].ObjectID = &object
			if err := ValidateOverlayObservation(mutated); err == nil {
				t.Fatal("deletion accepted a fabricated content identity")
			}
			return
		}
	}
	t.Fatal("fixture has no staged deletion")
}

func assertOverlayUnrelatedIdentityPreserved(t *testing.T, fixture overlayFixture) {
	before := overlayOccurrenceMap(fixture.Dirty.Worktree.Occurrences)["docs/guide.txt"]
	mustWriteOverlayFile(t, fixture.Repository, "zz-unrelated.txt", "unrelated overlay\n", 0o644)
	afterObservation := hydrateOverlayFixture(t, fixture.Repository)
	after := overlayOccurrenceMap(afterObservation.Worktree.Occurrences)["docs/guide.txt"]
	if before.ObjectID == nil || after.ObjectID == nil || *before.ObjectID != *after.ObjectID {
		t.Fatal("unrelated change altered unaffected content identity")
	}
	if identity.LayerOccurrenceID("repo.fixture", fixture.Dirty.BaseRevision, "worktree", before.Path) != identity.LayerOccurrenceID("repo.fixture", afterObservation.BaseRevision, "worktree", after.Path) {
		t.Fatal("unrelated change altered unaffected layer identity")
	}
}

func assertOverlayUnknownFieldRejected(t *testing.T, fixture overlayFixture) {
	payload, _ := MarshalOverlayCanonical(fixture.Dirty)
	var document map[string]any
	_ = json.Unmarshal(payload, &document)
	document["unknown"] = true
	mutated, _ := json.Marshal(document)
	if _, err := DecodeOverlayObservation(bytes.NewReader(mutated)); err == nil {
		t.Fatal("unknown overlay observation field accepted")
	}
}

func assertDuplicateIndexPathRejected(t *testing.T, fixture overlayFixture) {
	mutated := cloneOverlayObservation(t, fixture.Dirty)
	mutated.Index.Occurrences = append(mutated.Index.Occurrences, mutated.Index.Occurrences[0])
	sort.Slice(mutated.Index.Occurrences, func(i, j int) bool { return mutated.Index.Occurrences[i].Path < mutated.Index.Occurrences[j].Path })
	if err := ValidateOverlayObservation(mutated); err == nil {
		t.Fatal("duplicate index path accepted")
	}
}

func assertDuplicateWorktreePathRejected(t *testing.T, fixture overlayFixture) {
	mutated := cloneOverlayObservation(t, fixture.Dirty)
	mutated.Worktree.Occurrences = append(mutated.Worktree.Occurrences, mutated.Worktree.Occurrences[0])
	sort.Slice(mutated.Worktree.Occurrences, func(i, j int) bool {
		return mutated.Worktree.Occurrences[i].Path < mutated.Worktree.Occurrences[j].Path
	})
	if err := ValidateOverlayObservation(mutated); err == nil {
		t.Fatal("duplicate worktree path accepted")
	}
}

func assertUnsortedOverlayPathRejected(t *testing.T, fixture overlayFixture) {
	mutated := cloneOverlayObservation(t, fixture.Dirty)
	mutated.Index.Occurrences[0], mutated.Index.Occurrences[len(mutated.Index.Occurrences)-1] = mutated.Index.Occurrences[len(mutated.Index.Occurrences)-1], mutated.Index.Occurrences[0]
	if err := ValidateOverlayObservation(mutated); err == nil {
		t.Fatal("unsorted overlay paths accepted")
	}
}

func assertInvalidOverlayModeKindRejected(t *testing.T, fixture overlayFixture) {
	mutated := cloneOverlayObservation(t, fixture.Dirty)
	for index := range mutated.Index.Occurrences {
		if mutated.Index.Occurrences[index].Status != "deleted" {
			mutated.Index.Occurrences[index].Mode = "160000"
			mutated.Index.Occurrences[index].Kind = "blob"
			if err := ValidateOverlayObservation(mutated); err == nil {
				t.Fatal("invalid overlay mode-kind accepted")
			}
			return
		}
	}
}

func assertNonNormalizedOverlayPathRejected(t *testing.T, fixture overlayFixture) {
	mutated := cloneOverlayObservation(t, fixture.Dirty)
	mutated.Index.Occurrences[0].Path = "docs/../escape"
	if err := ValidateOverlayObservation(mutated); err == nil {
		t.Fatal("non-normalized overlay path accepted")
	}
}

func assertBrokenOverlayBaseBindingRejected(t *testing.T, fixture overlayFixture) {
	mutated := cloneOverlayObservation(t, fixture.Dirty)
	mutated.Worktree.BaseRevision = objectIDFromHex(fixture.Repository.Commits["A"])
	if err := ValidateOverlayObservation(mutated); err == nil {
		t.Fatal("broken layer base binding accepted")
	}
}

func assertOverlayElevatedAuthorityRejected(t *testing.T, _ overlayFixture) {
	if err := ValidateCollectionAuthority("candidate"); err != nil {
		t.Fatal(err)
	}
	if err := ValidateCollectionAuthority("controller"); err == nil {
		t.Fatal("overlay collector accepted elevated authority")
	}
}

func cloneOverlayObservation(t *testing.T, observation OverlayObservation) OverlayObservation {
	t.Helper()
	payload, err := json.Marshal(observation)
	if err != nil {
		t.Fatal(err)
	}
	var cloned OverlayObservation
	if err := json.Unmarshal(payload, &cloned); err != nil {
		t.Fatal(err)
	}
	return cloned
}

func loadOverlayGeneratedPropertyIDs(t *testing.T, fixture overlayFixture) []string {
	t.Helper()
	manifest := struct {
		BaseRevision identity.ObjectID `json:"baseRevision"`
		Properties   []string          `json:"properties"`
	}{BaseRevision: fixture.Dirty.BaseRevision, Properties: OverlayGeneratedPropertyIDs()}
	payload, err := json.Marshal(manifest)
	if err != nil {
		t.Fatal(err)
	}
	var generated struct {
		BaseRevision identity.ObjectID `json:"baseRevision"`
		Properties   []string          `json:"properties"`
	}
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&generated); err != nil {
		t.Fatal(err)
	}
	return generated.Properties
}

func loadOverlayDeclaredPropertyIDs(t *testing.T) []string {
	t.Helper()
	_, sourceFile, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("locate overlay property source")
	}
	cuePath := filepath.Clean(filepath.Join(filepath.Dir(sourceFile), "../../../../context-model/git_overlay_properties.cue"))
	source, err := os.ReadFile(cuePath)
	if err != nil {
		t.Fatal(err)
	}
	body, err := cueClosedStructBody(source, "gitOverlayProperties")
	if err != nil {
		t.Fatal(err)
	}
	fieldPattern := regexp.MustCompile(`^("(?:\\.|[^"\\])*")[ \t]*:[ \t]*true[ \t]*(?://.*)?$`)
	ids := make([]string, 0)
	seen := make(map[string]struct{})
	scanner := bufio.NewScanner(bytes.NewReader(body))
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "//") {
			continue
		}
		match := fieldPattern.FindStringSubmatch(line)
		if match == nil {
			t.Fatalf("unsupported overlay property manifest line: %q", line)
		}
		id, err := strconv.Unquote(match[1])
		if err != nil {
			t.Fatal(err)
		}
		if _, duplicate := seen[id]; duplicate {
			t.Fatalf("duplicate overlay property %q", id)
		}
		seen[id] = struct{}{}
		ids = append(ids, id)
	}
	if err := scanner.Err(); err != nil {
		t.Fatal(err)
	}
	return ids
}

func overlayPropertyReportPath(t *testing.T) string {
	if configured := os.Getenv("CONTEXT_GIT_OVERLAY_PROPERTY_REPORT"); configured != "" {
		return configured
	}
	return filepath.Join(t.TempDir(), "git-overlay-property-report.json")
}
