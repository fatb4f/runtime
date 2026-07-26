package hydrator

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"path"
	"regexp"
	"strings"
)

var graphIDPattern = regexp.MustCompile(`^[a-z0-9]+([._:/-][a-z0-9]+)*$`)

func DecodeRequest(reader io.Reader) (Request, error) {
	decoder := json.NewDecoder(reader)
	decoder.DisallowUnknownFields()

	var request Request
	if err := decoder.Decode(&request); err != nil {
		return Request{}, fmt.Errorf("decode committed snapshot request: %w", err)
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		if err == nil {
			return Request{}, errors.New("decode committed snapshot request: multiple JSON values")
		}
		return Request{}, fmt.Errorf("decode committed snapshot request trailer: %w", err)
	}
	if err := ValidateRequest(request); err != nil {
		return Request{}, err
	}
	return request, nil
}

func ValidateRequest(request Request) error {
	if request.Schema != RequestSchema {
		return fmt.Errorf("schema must be %q", RequestSchema)
	}
	if !graphIDPattern.MatchString(request.RepositoryID) {
		return errors.New("repositoryID must be a graph identifier")
	}
	if request.Revision == "" {
		return errors.New("revision must not be empty")
	}
	if request.Path == "" {
		return errors.New("path must not be empty")
	}
	if request.Path != "." {
		if strings.HasPrefix(request.Path, "/") || path.Clean(request.Path) != request.Path || request.Path == ".." || strings.HasPrefix(request.Path, "../") {
			return errors.New("path must be normalized and repository-relative")
		}
	}
	return nil
}
