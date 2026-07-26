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

func DecodeOverlayObservation(reader io.Reader) (OverlayObservation, error) {
	decoder := json.NewDecoder(reader)
	decoder.DisallowUnknownFields()
	var observation OverlayObservation
	if err := decoder.Decode(&observation); err != nil {
		return OverlayObservation{}, fmt.Errorf("decode overlay observation: %w", err)
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		if err == nil {
			return OverlayObservation{}, errors.New("decode overlay observation: multiple JSON values")
		}
		return OverlayObservation{}, fmt.Errorf("decode overlay observation trailer: %w", err)
	}
	if err := ValidateOverlayObservation(observation); err != nil {
		return OverlayObservation{}, err
	}
	return observation, nil
}

func ValidateOverlayObservation(observation OverlayObservation) error {
	if observation.Schema != OverlayObservationSchema {
		return fmt.Errorf("schema must be %q", OverlayObservationSchema)
	}
	if !graphIDPattern.MatchString(observation.RepositoryID) {
		return errors.New("repositoryID must be a graph identifier")
	}
	if err := validateObjectID("baseRevision", observation.BaseRevision); err != nil {
		return err
	}
	if err := validateObjectID("baseTree", observation.BaseTree); err != nil {
		return err
	}
	if !graphIDPattern.MatchString(observation.Hydrator.Identity) {
		return errors.New("hydrator.identity must be a graph identifier")
	}
	if !isSHA256Digest(observation.Hydrator.Digest) {
		return errors.New("hydrator.digest must be a sha256 digest")
	}
	if observation.Index.Schema != IndexOverlaySchema || observation.Worktree.Schema != WorktreeOverlaySchema {
		return errors.New("overlay layer schema is invalid")
	}
	for name, repositoryID := range map[string]string{"index": observation.Index.RepositoryID, "worktree": observation.Worktree.RepositoryID} {
		if repositoryID != observation.RepositoryID {
			return fmt.Errorf("%s repositoryID does not match observation", name)
		}
	}
	for name, revision := range map[string]identity.ObjectID{"index": observation.Index.BaseRevision, "worktree": observation.Worktree.BaseRevision} {
		if revision != observation.BaseRevision {
			return fmt.Errorf("%s baseRevision does not match observation", name)
		}
	}
	if err := validateOverlayLayer("index", observation.Index.Occurrences); err != nil {
		return err
	}
	if err := validateOverlayLayer("worktree", observation.Worktree.Occurrences); err != nil {
		return err
	}
	return nil
}

func validateOverlayLayer(layer string, occurrences []OverlayOccurrence) error {
	paths := make([]string, 0, len(occurrences))
	for index, occurrence := range occurrences {
		normalized, err := normalizeOccurrencePath(occurrence.Path)
		if err != nil || normalized != occurrence.Path {
			return fmt.Errorf("%s occurrence %d path is not normalized", layer, index)
		}
		if occurrence.Layer != layer {
			return fmt.Errorf("%s occurrence %q claims layer %q", layer, occurrence.Path, occurrence.Layer)
		}
		if err := validateOverlayOccurrence(occurrence); err != nil {
			return fmt.Errorf("%s occurrence %q: %w", layer, occurrence.Path, err)
		}
		paths = append(paths, occurrence.Path)
	}
	if !sort.StringsAreSorted(paths) {
		return fmt.Errorf("%s occurrence paths must be sorted", layer)
	}
	for index := 1; index < len(paths); index++ {
		if paths[index] == paths[index-1] {
			return fmt.Errorf("duplicate %s occurrence path %q", layer, paths[index])
		}
	}
	for _, opaque := range occurrences {
		if opaque.Status == "deleted" || (opaque.Kind != "symlink" && opaque.Kind != "submodule") {
			continue
		}
		for _, candidate := range occurrences {
			if strings.HasPrefix(candidate.Path, opaque.Path+"/") {
				return fmt.Errorf("opaque %s occurrence %q has descendant %q", layer, opaque.Path, candidate.Path)
			}
		}
	}
	return nil
}

func validateOverlayOccurrence(occurrence OverlayOccurrence) error {
	allowed := map[string]map[string]bool{
		"index":    {"added": true, "modified": true, "deleted": true},
		"worktree": {"modified": true, "deleted": true, "untracked": true},
	}
	if !allowed[occurrence.Layer][occurrence.Status] {
		return fmt.Errorf("status %q is invalid for layer %q", occurrence.Status, occurrence.Layer)
	}
	if occurrence.Status == "deleted" {
		if occurrence.ModeChanged || occurrence.Mode != "" || occurrence.Kind != "" || occurrence.ObjectID != nil || occurrence.Size != nil {
			return errors.New("deletion must not carry content or mode fields")
		}
		return nil
	}
	if occurrence.Status != "modified" && occurrence.ModeChanged {
		return errors.New("only modified occurrences may set modeChanged")
	}
	expectedKind, ok := map[string]string{
		"100644": "blob", "100664": "blob", "100755": "blob",
		"120000": "symlink", "160000": "submodule",
	}[occurrence.Mode]
	if !ok || occurrence.Kind != expectedKind {
		return errors.New("mode and kind are incompatible")
	}
	if occurrence.ObjectID == nil {
		return errors.New("present occurrence requires objectID")
	}
	if err := validateObjectID("objectID", *occurrence.ObjectID); err != nil {
		return err
	}
	if occurrence.Kind == "submodule" && occurrence.Size != nil {
		return errors.New("submodule occurrence must not carry size")
	}
	if occurrence.Size != nil && *occurrence.Size < 0 {
		return errors.New("size must not be negative")
	}
	return nil
}

func MarshalOverlayCanonical(observation OverlayObservation) ([]byte, error) {
	if err := ValidateOverlayObservation(observation); err != nil {
		return nil, err
	}
	payload, err := json.Marshal(observation)
	if err != nil {
		return nil, fmt.Errorf("marshal overlay observation: %w", err)
	}
	return append(payload, '\n'), nil
}
