package hydrator

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"testing"

	"github.com/fatb4f/dotfiles/.codex/context-hydrators/git/internal/identity"
	"github.com/fatb4f/dotfiles/.codex/context-hydrators/git/internal/testfixture"
)

func TestDeclaredPropertyManifestLoads(t *testing.T) {
	assertStringSetEqual(t, "declared/generated", loadDeclaredPropertyIDs(t), GeneratedPropertyIDs())
}

func TestDeclaredGeneratedExecutedReportedPropertySetEquality(t *testing.T) {
	fixture := newFixtureRepository(t)
	declared := loadDeclaredPropertyIDs(t)
	generated := loadGeneratedPropertyIDs(t, fixture)
	executed := make([]string, 0, len(generated))
	results := make([]PropertyResult, 0, len(generated))

	for _, property := range executablePropertyCases() {
		property := property
		passed := t.Run("execute/"+property.ID, func(t *testing.T) {
			property.Run(t, fixture)
		})
		executed = append(executed, property.ID)
		status := PropertyStatusFailed
		if passed {
			status = PropertyStatusPassed
		}
		results = append(results, PropertyResult{
			PropertyID: property.ID,
			Status:     status,
		})
	}

	reportPath := propertyReportPath(t)
	if err := WritePropertyReport(reportPath, PropertyReport{
		Schema:  PropertyReportSchema,
		Results: results,
	}); err != nil {
		t.Fatalf("persist property report: %v", err)
	}
	persistedReport, err := ReadPropertyReport(reportPath)
	if err != nil {
		t.Fatalf("reload property report: %v", err)
	}
	reported, err := ReportedPropertyIDs(persistedReport)
	if err != nil {
		t.Fatalf("derive reported property set: %v", err)
	}

	assertStringSetEqual(t, "declared/generated", declared, generated)
	assertStringSetEqual(t, "declared/executed", declared, executed)
	assertStringSetEqual(t, "declared/reported", declared, reported)
}

func TestPropertyReportIsClosedAndRejectsDuplicateResults(t *testing.T) {
	valid := []string{
		`{"schema":"kernel.git-committed-snapshot-property-report.v0","results":[{"propertyID":"determinism","status":"passed"}]}`,
		`{"schema":"kernel.git-committed-snapshot-property-report.v0","results":[{"propertyID":"determinism","status":"failed"}]}`,
	}
	for _, document := range valid {
		if _, err := DecodePropertyReport(strings.NewReader(document)); err != nil {
			t.Fatalf("decode valid property report: %v", err)
		}
	}

	invalid := []string{
		`{"schema":"kernel.git-committed-snapshot-property-report.v0","results":[],"extra":true}`,
		valid[0] + ` {}`,
		`{"schema":"wrong","results":[]}`,
		`{"schema":"kernel.git-committed-snapshot-property-report.v0","results":[{"propertyID":"determinism","status":"unknown"}]}`,
		`{"schema":"kernel.git-committed-snapshot-property-report.v0","results":[{"propertyID":"determinism","status":"passed"},{"propertyID":"determinism","status":"passed"}]}`,
	}
	for _, document := range invalid {
		if _, err := DecodePropertyReport(strings.NewReader(document)); err == nil {
			t.Fatalf("invalid property report accepted: %s", document)
		}
	}
}

type executableProperty struct {
	ID  string
	Run func(*testing.T, testfixture.Repository)
}

func executablePropertyCases() []executableProperty {
	return []executableProperty{
		{ID: "determinism", Run: assertDeterminismProperty},
		{ID: "rename-content-preserved", Run: assertRenameContentPreservedProperty},
		{ID: "content-edit-content-changed", Run: assertContentEditContentChangedProperty},
		{ID: "unrelated-entry-preserved", Run: assertUnrelatedEntryPreservedProperty},
		{ID: "mode-change-content-preserved", Run: assertModeChangeContentPreservedProperty},
		{ID: "symlink-not-traversed", Run: assertSymlinkNotTraversedProperty},
		{ID: "submodule-not-traversed", Run: assertSubmoduleNotTraversedProperty},
		{ID: "revision-bound", Run: assertRevisionBoundProperty},
		{ID: "unknown-field-rejected", Run: assertUnknownFieldRejectedProperty},
		{ID: "duplicate-path-rejected", Run: assertDuplicatePathRejectedProperty},
		{ID: "unsorted-path-rejected", Run: assertUnsortedPathRejectedProperty},
		{ID: "incompatible-mode-rejected", Run: assertIncompatibleModeRejectedProperty},
		{ID: "non-normalized-path-rejected", Run: assertNonNormalizedPathRejectedProperty},
		{ID: "noncanonical-revision-rejected", Run: assertNoncanonicalRevisionRejectedProperty},
		{ID: "malformed-object-id-rejected", Run: assertMalformedObjectIDRejectedProperty},
		{ID: "malformed-digest-rejected", Run: assertMalformedDigestRejectedProperty},
		{ID: "opaque-symlink-descendant-rejected", Run: assertOpaqueSymlinkDescendantRejectedProperty},
		{ID: "opaque-submodule-descendant-rejected", Run: assertOpaqueSubmoduleDescendantRejectedProperty},
		{ID: "elevated-authority-rejected", Run: assertElevatedAuthorityRejectedProperty},
	}
}

func assertDeterminismProperty(t *testing.T, fixture testfixture.Repository) {
	t.Helper()
	request := fixtureRequest(fixture, fixture.Commits["F"])

	first, err := HydrateCommitted(request, DefaultConfig())
	if err != nil {
		t.Fatalf("first hydration: %v", err)
	}
	firstJSON, err := MarshalCanonical(first)
	if err != nil {
		t.Fatalf("marshal first hydration: %v", err)
	}

	t.Setenv("TZ", "Pacific/Kiritimati")
	t.Setenv("LC_ALL", "C")
	t.Setenv("LANG", "C")
	second, err := HydrateCommitted(request, DefaultConfig())
	if err != nil {
		t.Fatalf("second hydration: %v", err)
	}
	secondJSON, err := MarshalCanonical(second)
	if err != nil {
		t.Fatalf("marshal second hydration: %v", err)
	}
	if !bytes.Equal(firstJSON, secondJSON) {
		t.Fatalf("normalized output changed:\nfirst:  %s\nsecond: %s", firstJSON, secondJSON)
	}
	if bytes.Contains(firstJSON, []byte(fixture.Path)) {
		t.Fatal("normalized output leaked a host path")
	}
}

func assertRenameContentPreservedProperty(t *testing.T, fixture testfixture.Repository) {
	t.Helper()
	aObservation := hydrateFixture(t, fixture, fixture.Commits["A"])
	bObservation := hydrateFixture(t, fixture, fixture.Commits["B"])
	aReadme := occurrenceMap(aObservation)["docs/readme.txt"]
	bGuide := occurrenceMap(bObservation)["docs/guide.txt"]
	if identity.ContentID(aReadme.ObjectID) != identity.ContentID(bGuide.ObjectID) {
		t.Fatal("rename-only mutation changed content identity")
	}
	if identity.OccurrenceID("repo.fixture", aReadme.Path) == identity.OccurrenceID("repo.fixture", bGuide.Path) {
		t.Fatal("rename-only mutation preserved occurrence identity")
	}
	if identity.SnapshotOccurrenceID("repo.fixture", aObservation.ResolvedRevision, aReadme.Path) == identity.SnapshotOccurrenceID("repo.fixture", bObservation.ResolvedRevision, bGuide.Path) {
		t.Fatal("rename-only mutation preserved snapshot occurrence identity")
	}
}

func assertContentEditContentChangedProperty(t *testing.T, fixture testfixture.Repository) {
	t.Helper()
	bObservation := hydrateFixture(t, fixture, fixture.Commits["B"])
	cObservation := hydrateFixture(t, fixture, fixture.Commits["C"])
	bGuide := occurrenceMap(bObservation)["docs/guide.txt"]
	cGuide := occurrenceMap(cObservation)["docs/guide.txt"]
	if identity.ContentID(bGuide.ObjectID) == identity.ContentID(cGuide.ObjectID) {
		t.Fatal("content edit preserved blob identity")
	}
	if identity.OccurrenceID("repo.fixture", bGuide.Path) != identity.OccurrenceID("repo.fixture", cGuide.Path) {
		t.Fatal("content edit changed occurrence identity")
	}
	if identity.SnapshotOccurrenceID("repo.fixture", bObservation.ResolvedRevision, bGuide.Path) == identity.SnapshotOccurrenceID("repo.fixture", cObservation.ResolvedRevision, cGuide.Path) {
		t.Fatal("content edit preserved snapshot occurrence identity")
	}
}

func assertUnrelatedEntryPreservedProperty(t *testing.T, fixture testfixture.Repository) {
	t.Helper()
	cObservation := hydrateFixture(t, fixture, fixture.Commits["C"])
	dObservation := hydrateFixture(t, fixture, fixture.Commits["D"])
	cMain := occurrenceMap(cObservation)["src/main.sh"]
	dMain := occurrenceMap(dObservation)["src/main.sh"]
	if identity.ContentID(cMain.ObjectID) != identity.ContentID(dMain.ObjectID) {
		t.Fatal("unrelated addition changed unaffected content identity")
	}
	if identity.OccurrenceID("repo.fixture", cMain.Path) != identity.OccurrenceID("repo.fixture", dMain.Path) {
		t.Fatal("unrelated addition changed unaffected occurrence identity")
	}
	if identity.SnapshotOccurrenceID("repo.fixture", cObservation.ResolvedRevision, cMain.Path) == identity.SnapshotOccurrenceID("repo.fixture", dObservation.ResolvedRevision, dMain.Path) {
		t.Fatal("unrelated addition preserved snapshot occurrence identity across revisions")
	}
}

func assertModeChangeContentPreservedProperty(t *testing.T, fixture testfixture.Repository) {
	t.Helper()
	dObservation := hydrateFixture(t, fixture, fixture.Commits["D"])
	eObservation := hydrateFixture(t, fixture, fixture.Commits["E"])
	dMain := occurrenceMap(dObservation)["src/main.sh"]
	eMain := occurrenceMap(eObservation)["src/main.sh"]
	if identity.ContentID(dMain.ObjectID) != identity.ContentID(eMain.ObjectID) {
		t.Fatal("mode-only change changed blob identity")
	}
	if dMain.Mode == eMain.Mode {
		t.Fatal("mode-only change did not change occurrence metadata")
	}
	if identity.OccurrenceID("repo.fixture", dMain.Path) != identity.OccurrenceID("repo.fixture", eMain.Path) {
		t.Fatal("mode-only change changed occurrence identity")
	}
	if identity.SnapshotOccurrenceID("repo.fixture", dObservation.ResolvedRevision, dMain.Path) == identity.SnapshotOccurrenceID("repo.fixture", eObservation.ResolvedRevision, eMain.Path) {
		t.Fatal("snapshot occurrence identity did not bind resolved revision")
	}
}

func assertSymlinkNotTraversedProperty(t *testing.T, fixture testfixture.Repository) {
	t.Helper()
	occurrences := occurrenceMap(hydrateFixture(t, fixture, fixture.Commits["F"]))
	assertOccurrence(t, occurrences, "guide-link", "120000", "symlink")
	if occurrences["guide-link"].Size == nil || *occurrences["guide-link"].Size != int64(len("docs/guide.txt")) {
		t.Fatalf("symlink payload size = %v, want %d", occurrences["guide-link"].Size, len("docs/guide.txt"))
	}
	for path := range occurrences {
		if strings.HasPrefix(path, "guide-link/") {
			t.Fatalf("hydrator traversed symlink occurrence: %s", path)
		}
	}
}

func assertSubmoduleNotTraversedProperty(t *testing.T, fixture testfixture.Repository) {
	t.Helper()
	occurrences := occurrenceMap(hydrateFixture(t, fixture, fixture.Commits["F"]))
	assertOccurrence(t, occurrences, "vendor/dependency", "160000", "submodule")
	if occurrences["vendor/dependency"].Size != nil {
		t.Fatal("submodule occurrence must not carry blob size")
	}
	for path := range occurrences {
		if strings.HasPrefix(path, "vendor/dependency/") {
			t.Fatalf("hydrator traversed submodule occurrence: %s", path)
		}
	}
}

func assertRevisionBoundProperty(t *testing.T, fixture testfixture.Repository) {
	t.Helper()
	branch := hydrateFixture(t, fixture, "main")
	if branch.ResolvedRevision.Hex != fixture.Commits["F"] {
		t.Fatalf("branch resolved to %s, want %s", branch.ResolvedRevision.Hex, fixture.Commits["F"])
	}
	tag := hydrateFixture(t, fixture, "fixture-a")
	if tag.ResolvedRevision.Hex != fixture.Commits["A"] {
		t.Fatalf("tag resolved to %s, want %s", tag.ResolvedRevision.Hex, fixture.Commits["A"])
	}

	boundRequest := fixtureRequest(fixture, branch.ResolvedRevision.Hex)
	before, err := HydrateCommitted(boundRequest, DefaultConfig())
	if err != nil {
		t.Fatalf("hydrate bound commit before branch move: %v", err)
	}
	if err := testfixture.UpdateRef(fixture, "refs/heads/main", fixture.Commits["A"]); err != nil {
		t.Fatalf("move fixture branch: %v", err)
	}
	after, err := HydrateCommitted(boundRequest, DefaultConfig())
	if err != nil {
		t.Fatalf("hydrate bound commit after branch move: %v", err)
	}
	beforeJSON, err := MarshalCanonical(before)
	if err != nil {
		t.Fatalf("marshal bound observation before branch move: %v", err)
	}
	afterJSON, err := MarshalCanonical(after)
	if err != nil {
		t.Fatalf("marshal bound observation after branch move: %v", err)
	}
	if !bytes.Equal(beforeJSON, afterJSON) {
		t.Fatal("exact-commit hydration changed when branch moved")
	}
}

func assertUnknownFieldRejectedProperty(t *testing.T, fixture testfixture.Repository) {
	t.Helper()
	valid := hydrateFixture(t, fixture, fixture.Commits["F"])
	payload, err := json.Marshal(valid)
	if err != nil {
		t.Fatalf("marshal valid observation: %v", err)
	}
	var document map[string]any
	if err := json.Unmarshal(payload, &document); err != nil {
		t.Fatalf("decode valid observation map: %v", err)
	}
	document["unknown"] = true
	payload, err = json.Marshal(document)
	if err != nil {
		t.Fatalf("marshal unknown-field mutation: %v", err)
	}
	if _, err := DecodeObservation(bytes.NewReader(payload)); err == nil {
		t.Fatal("typed observation adapter accepted an unknown field")
	}
}

func assertDuplicatePathRejectedProperty(t *testing.T, fixture testfixture.Repository) {
	observation := hydrateFixture(t, fixture, fixture.Commits["F"])
	observation.Occurrences = append(observation.Occurrences, observation.Occurrences[0])
	sort.Slice(observation.Occurrences, func(i, j int) bool { return observation.Occurrences[i].Path < observation.Occurrences[j].Path })
	assertObservationRejected(t, observation)
}

func assertUnsortedPathRejectedProperty(t *testing.T, fixture testfixture.Repository) {
	observation := hydrateFixture(t, fixture, fixture.Commits["F"])
	for left, right := 0, len(observation.Occurrences)-1; left < right; left, right = left+1, right-1 {
		observation.Occurrences[left], observation.Occurrences[right] = observation.Occurrences[right], observation.Occurrences[left]
	}
	assertObservationRejected(t, observation)
}

func assertIncompatibleModeRejectedProperty(t *testing.T, fixture testfixture.Repository) {
	observation := hydrateFixture(t, fixture, fixture.Commits["F"])
	for index := range observation.Occurrences {
		if observation.Occurrences[index].Kind == "blob" {
			observation.Occurrences[index].Mode = "160000"
			break
		}
	}
	assertObservationRejected(t, observation)
}

func assertNonNormalizedPathRejectedProperty(t *testing.T, fixture testfixture.Repository) {
	observation := hydrateFixture(t, fixture, fixture.Commits["F"])
	observation.Occurrences[0].Path = "docs/../escape"
	assertObservationRejected(t, observation)
}

func assertNoncanonicalRevisionRejectedProperty(t *testing.T, fixture testfixture.Repository) {
	observation := hydrateFixture(t, fixture, fixture.Commits["F"])
	observation.RequestedRevision = "main"
	assertObservationRejected(t, observation)
}

func assertMalformedObjectIDRejectedProperty(t *testing.T, fixture testfixture.Repository) {
	observation := hydrateFixture(t, fixture, fixture.Commits["F"])
	observation.Occurrences[0].ObjectID.Hex = "not-hex"
	assertObservationRejected(t, observation)
}

func assertMalformedDigestRejectedProperty(t *testing.T, fixture testfixture.Repository) {
	observation := hydrateFixture(t, fixture, fixture.Commits["F"])
	observation.Hydrator.Digest = "sha256:short"
	assertObservationRejected(t, observation)
}

func assertOpaqueSymlinkDescendantRejectedProperty(t *testing.T, fixture testfixture.Repository) {
	observation := hydrateFixture(t, fixture, fixture.Commits["F"])
	child := observation.Occurrences[0]
	child.Path = "guide-link/child"
	observation.Occurrences = append(observation.Occurrences, child)
	sort.Slice(observation.Occurrences, func(i, j int) bool { return observation.Occurrences[i].Path < observation.Occurrences[j].Path })
	assertObservationRejected(t, observation)
}

func assertOpaqueSubmoduleDescendantRejectedProperty(t *testing.T, fixture testfixture.Repository) {
	observation := hydrateFixture(t, fixture, fixture.Commits["F"])
	child := observation.Occurrences[0]
	child.Path = "vendor/dependency/child"
	observation.Occurrences = append(observation.Occurrences, child)
	sort.Slice(observation.Occurrences, func(i, j int) bool { return observation.Occurrences[i].Path < observation.Occurrences[j].Path })
	assertObservationRejected(t, observation)
}

func assertElevatedAuthorityRejectedProperty(t *testing.T, _ testfixture.Repository) {
	if err := ValidateCollectionAuthority("candidate"); err != nil {
		t.Fatalf("candidate collection authority rejected: %v", err)
	}
	if err := ValidateCollectionAuthority("controller"); err == nil {
		t.Fatal("collection adapter accepted controller authority without admission")
	}
}

func assertObservationRejected(t *testing.T, observation Observation) {
	t.Helper()
	if err := ValidateObservation(observation); err == nil {
		t.Fatal("typed observation adapter accepted an invariant mutation")
	}
}

func loadGeneratedPropertyIDs(t *testing.T, fixture testfixture.Repository) []string {
	t.Helper()
	manifestPath := filepath.Join(t.TempDir(), "fixture-manifest.json")
	if err := testfixture.WriteManifest(manifestPath, fixture, GeneratedPropertyIDs()); err != nil {
		t.Fatalf("write generated fixture manifest: %v", err)
	}
	manifestFile, err := os.Open(manifestPath)
	if err != nil {
		t.Fatalf("open generated fixture manifest: %v", err)
	}
	defer manifestFile.Close()

	decoder := json.NewDecoder(manifestFile)
	decoder.DisallowUnknownFields()
	var manifest struct {
		Repository testfixture.Repository `json:"repository"`
		Properties []string               `json:"properties"`
	}
	if err := decoder.Decode(&manifest); err != nil {
		t.Fatalf("decode generated fixture manifest: %v", err)
	}
	if len(manifest.Properties) == 0 {
		t.Fatal("generated fixture property manifest is empty")
	}
	return manifest.Properties
}

func loadDeclaredPropertyIDs(t *testing.T) []string {
	t.Helper()
	_, sourceFile, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("locate property gate source file")
	}
	cuePath := filepath.Clean(filepath.Join(filepath.Dir(sourceFile), "../../../../context-model/git_committed_snapshot.cue"))
	source, err := os.ReadFile(cuePath)
	if err != nil {
		t.Fatalf("read CUE property manifest %s: %v", cuePath, err)
	}
	body, err := cueClosedStructBody(source, "gitCommittedSnapshotProperties")
	if err != nil {
		t.Fatalf("read CUE property manifest: %v", err)
	}

	fieldPattern := regexp.MustCompile(`^("(?:\\.|[^"\\])*")[ \t]*:[ \t]*true[ \t]*(?://.*)?$`)
	propertyIDs := make([]string, 0)
	seen := make(map[string]struct{})
	scanner := bufio.NewScanner(bytes.NewReader(body))
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "//") {
			continue
		}
		match := fieldPattern.FindStringSubmatch(line)
		if match == nil {
			t.Fatalf("CUE property manifest contains unsupported field syntax: %q", line)
		}
		propertyID, err := strconv.Unquote(match[1])
		if err != nil {
			t.Fatalf("decode CUE property manifest label %q: %v", match[1], err)
		}
		if _, duplicate := seen[propertyID]; duplicate {
			t.Fatalf("CUE property manifest contains duplicate property %q", propertyID)
		}
		seen[propertyID] = struct{}{}
		propertyIDs = append(propertyIDs, propertyID)
	}
	if err := scanner.Err(); err != nil {
		t.Fatalf("scan CUE property manifest: %v", err)
	}
	if len(propertyIDs) == 0 {
		t.Fatal("CUE property manifest is empty")
	}
	return propertyIDs
}

func cueClosedStructBody(source []byte, fieldName string) ([]byte, error) {
	marker := regexp.MustCompile(`(?m)^[ \t]*` + regexp.QuoteMeta(fieldName) + `[ \t]*:[ \t]*close[ \t]*\([ \t]*\{`)
	location := marker.FindIndex(source)
	if location == nil {
		return nil, fmt.Errorf("field %q is not a closed struct manifest", fieldName)
	}
	openingOffset := bytes.LastIndexByte(source[location[0]:location[1]], '{')
	if openingOffset < 0 {
		return nil, fmt.Errorf("field %q has no opening struct delimiter", fieldName)
	}
	opening := location[0] + openingOffset

	depth := 0
	inString := false
	escaped := false
	lineComment := false
	blockComment := false
	for index := opening; index < len(source); index++ {
		current := source[index]
		var next byte
		if index+1 < len(source) {
			next = source[index+1]
		}

		if lineComment {
			if current == '\n' {
				lineComment = false
			}
			continue
		}
		if blockComment {
			if current == '*' && next == '/' {
				blockComment = false
				index++
			}
			continue
		}
		if inString {
			if escaped {
				escaped = false
				continue
			}
			if current == '\\' {
				escaped = true
				continue
			}
			if current == '"' {
				inString = false
			}
			continue
		}
		if current == '/' && next == '/' {
			lineComment = true
			index++
			continue
		}
		if current == '/' && next == '*' {
			blockComment = true
			index++
			continue
		}
		if current == '"' {
			inString = true
			continue
		}

		switch current {
		case '{':
			depth++
		case '}':
			depth--
			if depth == 0 {
				return source[opening+1 : index], nil
			}
		}
	}
	return nil, fmt.Errorf("field %q has no closing struct delimiter", fieldName)
}

func propertyReportPath(t *testing.T) string {
	t.Helper()
	if configured := os.Getenv("CONTEXT_GIT_HYDRATOR_PROPERTY_REPORT"); configured != "" {
		return configured
	}
	return filepath.Join(t.TempDir(), "git-committed-snapshot-property-report.json")
}

func assertStringSetEqual(t *testing.T, name string, left, right []string) {
	t.Helper()
	leftCopy := append([]string(nil), left...)
	rightCopy := append([]string(nil), right...)
	sort.Strings(leftCopy)
	sort.Strings(rightCopy)
	if strings.Join(leftCopy, "\x00") != strings.Join(rightCopy, "\x00") {
		t.Fatalf("%s mismatch: %v != %v", name, leftCopy, rightCopy)
	}
}
