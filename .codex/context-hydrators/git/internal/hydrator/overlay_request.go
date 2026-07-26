package hydrator

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"path"
	"strings"
)

func DecodeOverlayRequest(reader io.Reader) (OverlayRequest, error) {
	decoder := json.NewDecoder(reader)
	decoder.DisallowUnknownFields()
	var request OverlayRequest
	if err := decoder.Decode(&request); err != nil {
		return OverlayRequest{}, fmt.Errorf("decode overlay request: %w", err)
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		if err == nil {
			return OverlayRequest{}, errors.New("decode overlay request: multiple JSON values")
		}
		return OverlayRequest{}, fmt.Errorf("decode overlay request trailer: %w", err)
	}
	if err := ValidateOverlayRequest(request); err != nil {
		return OverlayRequest{}, err
	}
	return request, nil
}

func ValidateOverlayRequest(request OverlayRequest) error {
	if request.Schema != OverlayRequestSchema {
		return fmt.Errorf("schema must be %q", OverlayRequestSchema)
	}
	if !graphIDPattern.MatchString(request.RepositoryID) {
		return errors.New("repositoryID must be a graph identifier")
	}
	if request.Path == "" {
		return errors.New("path must not be empty")
	}
	if request.Path != "." && (strings.HasPrefix(request.Path, "/") || path.Clean(request.Path) != request.Path || request.Path == ".." || strings.HasPrefix(request.Path, "../")) {
		return errors.New("path must be normalized and repository-relative")
	}
	if err := validateObjectID("baseRevision", request.BaseRevision); err != nil {
		return err
	}
	return nil
}
