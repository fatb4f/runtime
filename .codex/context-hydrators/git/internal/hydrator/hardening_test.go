package hydrator

import (
	"bytes"
	"os"
	"strings"
	"testing"
)

const testHydratorDigest = "sha256:1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"

func TestMain(m *testing.M) {
	BuildHydratorDigest = testHydratorDigest
	os.Exit(m.Run())
}

func TestEquivalentRevisionSelectorsProduceIdenticalObservation(t *testing.T) {
	fixture := newFixtureRepository(t)
	selectors := []string{
		"HEAD",
		"main",
		"refs/heads/main",
		"fixture-f",
		"refs/tags/fixture-f",
		fixture.Commits["F"],
	}

	var baseline []byte
	for _, selector := range selectors {
		observation := hydrateFixture(t, fixture, selector)
		if observation.RequestedRevision != fixture.Commits["F"] {
			t.Fatalf("selector %q emitted requestedRevision %q, want exact commit %q", selector, observation.RequestedRevision, fixture.Commits["F"])
		}
		payload, err := MarshalCanonical(observation)
		if err != nil {
			t.Fatalf("marshal selector %q: %v", selector, err)
		}
		if baseline == nil {
			baseline = payload
			continue
		}
		if !bytes.Equal(baseline, payload) {
			t.Fatalf("equivalent selector %q changed normalized observation", selector)
		}
	}
}

func TestCommittedObservationUsesSizeWireField(t *testing.T) {
	fixture := newFixtureRepository(t)
	payload, err := MarshalCanonical(hydrateFixture(t, fixture, fixture.Commits["F"]))
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(payload, []byte(`"size":`)) {
		t.Fatal("committed observation omitted size wire field")
	}
	if bytes.Contains(payload, []byte(`"gitSizeBytes":`)) {
		t.Fatal("committed observation leaked projection-only gitSizeBytes field")
	}
}

func TestDefaultConfigRejectsUnboundBuildDigest(t *testing.T) {
	previous := BuildHydratorDigest
	BuildHydratorDigest = UnboundHydratorDigest
	t.Cleanup(func() { BuildHydratorDigest = previous })

	_, err := HydrateCommitted(Request{
		Schema:       RequestSchema,
		RepositoryID: "repo.fixture",
		Path:         ".",
		Revision:     "HEAD",
	}, DefaultConfig())
	if err == nil || !strings.Contains(err.Error(), "unbound") {
		t.Fatalf("unbound build digest error = %v", err)
	}
}

func TestInjectedBuildDigestChangesObservationProvenance(t *testing.T) {
	fixture := newFixtureRepository(t)
	request := fixtureRequest(fixture, fixture.Commits["F"])

	first, err := HydrateCommitted(request, Config{Identity: DefaultHydratorIdentity, Digest: testHydratorDigest})
	if err != nil {
		t.Fatalf("hydrate first bound build: %v", err)
	}
	second, err := HydrateCommitted(request, Config{Identity: DefaultHydratorIdentity, Digest: "sha256:fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"})
	if err != nil {
		t.Fatalf("hydrate second bound build: %v", err)
	}
	if first.Hydrator.Digest == second.Hydrator.Digest {
		t.Fatal("different bound builds emitted identical hydrator provenance")
	}
}

func TestReportedPropertyIDsRejectFailedResults(t *testing.T) {
	_, err := ReportedPropertyIDs(PropertyReport{
		Schema: PropertyReportSchema,
		Results: []PropertyResult{{
			PropertyID: "determinism",
			Status:     PropertyStatusFailed,
		}},
	})
	if err == nil {
		t.Fatal("failed property result was accepted as reported")
	}
}
