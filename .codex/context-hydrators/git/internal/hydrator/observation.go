package hydrator

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"sort"
	"strings"

	"github.com/fatb4f/dotfiles/.codex/context-hydrators/git/internal/identity"
)

func DecodeObservation(reader io.Reader) (Observation, error) {
	decoder := json.NewDecoder(reader)
	decoder.DisallowUnknownFields()
	var observation Observation
	if err := decoder.Decode(&observation); err != nil {
		return Observation{}, fmt.Errorf("decode committed snapshot observation: %w", err)
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		if err == nil {
			return Observation{}, errors.New("decode committed snapshot observation: multiple JSON values")
		}
		return Observation{}, fmt.Errorf("decode committed snapshot observation trailer: %w", err)
	}
	if err := ValidateObservation(observation); err != nil {
		return Observation{}, err
	}
	return observation, nil
}

func ValidateObservation(observation Observation) error {
	if observation.Schema != ObservationSchema {
		return fmt.Errorf("schema must be %q", ObservationSchema)
	}
	if !graphIDPattern.MatchString(observation.RepositoryID) {
		return errors.New("repositoryID must be a graph identifier")
	}
	if err := validateObjectID("resolvedRevision", observation.ResolvedRevision); err != nil {
		return err
	}
	if observation.RequestedRevision != observation.ResolvedRevision.Hex {
		return errors.New("requestedRevision must equal resolvedRevision.hex")
	}
	if err := validateObjectID("rootTree", observation.RootTree); err != nil {
		return err
	}
	if !graphIDPattern.MatchString(observation.Hydrator.Identity) {
		return errors.New("hydrator.identity must be a graph identifier")
	}
	if !isSHA256Digest(observation.Hydrator.Digest) {
		return errors.New("hydrator.digest must be a sha256 digest")
	}

	paths := make([]string, 0, len(observation.Occurrences))
	for index, occurrence := range observation.Occurrences {
		normalized, err := normalizeOccurrencePath(occurrence.Path)
		if err != nil || normalized != occurrence.Path {
			return fmt.Errorf("occurrence %d path is not normalized", index)
		}
		expectedKind, ok := map[string]string{
			"040000": "tree", "100644": "blob", "100664": "blob",
			"100755": "blob", "120000": "symlink", "160000": "submodule",
		}[occurrence.Mode]
		if !ok || occurrence.Kind != expectedKind {
			return fmt.Errorf("occurrence %q has incompatible mode and kind", occurrence.Path)
		}
		if err := validateObjectID("occurrence.objectID", occurrence.ObjectID); err != nil {
			return err
		}
		if occurrence.Size != nil && *occurrence.Size < 0 {
			return fmt.Errorf("occurrence %q has negative size", occurrence.Path)
		}
		paths = append(paths, occurrence.Path)
	}
	if !sort.StringsAreSorted(paths) {
		return errors.New("occurrence paths must be sorted")
	}
	for index := 1; index < len(paths); index++ {
		if paths[index] == paths[index-1] {
			return fmt.Errorf("duplicate occurrence path %q", paths[index])
		}
	}
	for _, opaque := range observation.Occurrences {
		if opaque.Kind != "symlink" && opaque.Kind != "submodule" {
			continue
		}
		for _, candidate := range observation.Occurrences {
			if strings.HasPrefix(candidate.Path, opaque.Path+"/") {
				return fmt.Errorf("opaque occurrence %q has descendant %q", opaque.Path, candidate.Path)
			}
		}
	}
	return nil
}

func ValidateCollectionAuthority(authority string) error {
	if authority != "none" && authority != "candidate" {
		return fmt.Errorf("collection authority %q requires an admission transition", authority)
	}
	return nil
}

func validateObjectID(name string, objectID identity.ObjectID) error {
	if !graphIDPattern.MatchString(objectID.Format) {
		return fmt.Errorf("%s.format must be a graph identifier", name)
	}
	if objectID.Hex == "" {
		return fmt.Errorf("%s.hex must not be empty", name)
	}
	for _, character := range objectID.Hex {
		if !strings.ContainsRune("0123456789abcdef", character) {
			return fmt.Errorf("%s.hex must be lowercase hexadecimal", name)
		}
	}
	return nil
}
