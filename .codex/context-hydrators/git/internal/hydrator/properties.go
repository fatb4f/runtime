package hydrator

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
)

const (
	PropertyReportSchema = "kernel.git-committed-snapshot-property-report.v0"
	PropertyStatusPassed = "passed"
	PropertyStatusFailed = "failed"
)

var generatedPropertyIDs = []string{
	"determinism",
	"rename-content-preserved",
	"content-edit-content-changed",
	"unrelated-entry-preserved",
	"mode-change-content-preserved",
	"symlink-not-traversed",
	"submodule-not-traversed",
	"revision-bound",
	"unknown-field-rejected",
	"duplicate-path-rejected",
	"unsorted-path-rejected",
	"incompatible-mode-rejected",
	"non-normalized-path-rejected",
	"noncanonical-revision-rejected",
	"malformed-object-id-rejected",
	"malformed-digest-rejected",
	"opaque-symlink-descendant-rejected",
	"opaque-submodule-descendant-rejected",
	"elevated-authority-rejected",
}

// GeneratedPropertyIDs returns the independently maintained property set emitted
// with generated qualification fixtures. The CUE declaration and executable
// property registry are checked against this set by the qualification gate.
func GeneratedPropertyIDs() []string {
	return append([]string(nil), generatedPropertyIDs...)
}

type PropertyResult struct {
	PropertyID string `json:"propertyID"`
	Status     string `json:"status"`
}

type PropertyReport struct {
	Schema  string           `json:"schema"`
	Results []PropertyResult `json:"results"`
}

func MarshalPropertyReport(report PropertyReport) ([]byte, error) {
	if err := ValidatePropertyReport(report); err != nil {
		return nil, err
	}
	payload, err := json.MarshalIndent(report, "", "  ")
	if err != nil {
		return nil, fmt.Errorf("marshal committed snapshot property report: %w", err)
	}
	return append(payload, '\n'), nil
}

func DecodePropertyReport(reader io.Reader) (PropertyReport, error) {
	decoder := json.NewDecoder(reader)
	decoder.DisallowUnknownFields()

	var report PropertyReport
	if err := decoder.Decode(&report); err != nil {
		return PropertyReport{}, fmt.Errorf("decode committed snapshot property report: %w", err)
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		if err == nil {
			return PropertyReport{}, errors.New("decode committed snapshot property report: multiple JSON values")
		}
		return PropertyReport{}, fmt.Errorf("decode committed snapshot property report trailer: %w", err)
	}
	if err := ValidatePropertyReport(report); err != nil {
		return PropertyReport{}, err
	}
	return report, nil
}

func ValidatePropertyReport(report PropertyReport) error {
	if report.Schema != PropertyReportSchema {
		return fmt.Errorf("property report schema must be %q", PropertyReportSchema)
	}
	seen := make(map[string]struct{}, len(report.Results))
	for index, result := range report.Results {
		if result.PropertyID == "" {
			return fmt.Errorf("property report result %d has an empty propertyID", index)
		}
		if result.Status != PropertyStatusPassed && result.Status != PropertyStatusFailed {
			return fmt.Errorf("property report result %q has unsupported status %q", result.PropertyID, result.Status)
		}
		if _, duplicate := seen[result.PropertyID]; duplicate {
			return fmt.Errorf("property report contains duplicate propertyID %q", result.PropertyID)
		}
		seen[result.PropertyID] = struct{}{}
	}
	return nil
}

func ReportedPropertyIDs(report PropertyReport) ([]string, error) {
	if err := ValidatePropertyReport(report); err != nil {
		return nil, err
	}
	propertyIDs := make([]string, 0, len(report.Results))
	for _, result := range report.Results {
		if result.Status != PropertyStatusPassed {
			return nil, fmt.Errorf("property %q was reported with status %q", result.PropertyID, result.Status)
		}
		propertyIDs = append(propertyIDs, result.PropertyID)
	}
	return propertyIDs, nil
}

func WritePropertyReport(path string, report PropertyReport) error {
	payload, err := MarshalPropertyReport(report)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return fmt.Errorf("create property report directory: %w", err)
	}
	if err := os.WriteFile(path, payload, 0o644); err != nil {
		return fmt.Errorf("write committed snapshot property report: %w", err)
	}
	return nil
}

func ReadPropertyReport(path string) (PropertyReport, error) {
	file, err := os.Open(path)
	if err != nil {
		return PropertyReport{}, fmt.Errorf("open committed snapshot property report: %w", err)
	}
	defer file.Close()
	return DecodePropertyReport(file)
}
