package hydrator

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
)

const OverlayPropertyReportSchema = "kernel.git-overlay-property-report.v0"

var overlayGeneratedPropertyIDs = []string{
	"overlay-determinism",
	"clean-overlay-preserves-base",
	"exact-base-bound",
	"index-worktree-distinct",
	"same-path-layers-coexist",
	"untracked-not-staged",
	"staged-addition-observed",
	"staged-modification-observed",
	"staged-deletion-explicit",
	"unstaged-modification-observed",
	"unstaged-deletion-explicit",
	"executable-mode-change-observed",
	"symlink-not-followed",
	"submodule-not-traversed",
	"deletion-content-absent",
	"unrelated-change-identity-preserved",
	"unknown-field-rejected",
	"duplicate-index-path-rejected",
	"duplicate-worktree-path-rejected",
	"unsorted-layer-path-rejected",
	"invalid-mode-kind-rejected",
	"non-normalized-path-rejected",
	"broken-base-binding-rejected",
	"elevated-authority-rejected",
}

func OverlayGeneratedPropertyIDs() []string {
	return append([]string(nil), overlayGeneratedPropertyIDs...)
}

type OverlayPropertyReport struct {
	Schema  string           `json:"schema"`
	Results []PropertyResult `json:"results"`
}

func ValidateOverlayPropertyReport(report OverlayPropertyReport) error {
	if report.Schema != OverlayPropertyReportSchema {
		return fmt.Errorf("overlay property report schema must be %q", OverlayPropertyReportSchema)
	}
	seen := make(map[string]struct{}, len(report.Results))
	for index, result := range report.Results {
		if result.PropertyID == "" {
			return fmt.Errorf("overlay property report result %d has an empty propertyID", index)
		}
		if result.Status != PropertyStatusPassed && result.Status != PropertyStatusFailed {
			return fmt.Errorf("overlay property %q has unsupported status %q", result.PropertyID, result.Status)
		}
		if _, duplicate := seen[result.PropertyID]; duplicate {
			return fmt.Errorf("overlay property report contains duplicate propertyID %q", result.PropertyID)
		}
		seen[result.PropertyID] = struct{}{}
	}
	return nil
}

func WriteOverlayPropertyReport(path string, report OverlayPropertyReport) error {
	if err := ValidateOverlayPropertyReport(report); err != nil {
		return err
	}
	payload, err := json.MarshalIndent(report, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal overlay property report: %w", err)
	}
	payload = append(payload, '\n')
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return fmt.Errorf("create overlay property report directory: %w", err)
	}
	if err := os.WriteFile(path, payload, 0o644); err != nil {
		return fmt.Errorf("write overlay property report: %w", err)
	}
	return nil
}

func ReadOverlayPropertyReport(path string) (OverlayPropertyReport, error) {
	file, err := os.Open(path)
	if err != nil {
		return OverlayPropertyReport{}, fmt.Errorf("open overlay property report: %w", err)
	}
	defer file.Close()
	decoder := json.NewDecoder(file)
	decoder.DisallowUnknownFields()
	var report OverlayPropertyReport
	if err := decoder.Decode(&report); err != nil {
		return OverlayPropertyReport{}, fmt.Errorf("decode overlay property report: %w", err)
	}
	var trailing any
	if err := decoder.Decode(&trailing); !errors.Is(err, io.EOF) {
		if err == nil {
			return OverlayPropertyReport{}, errors.New("decode overlay property report: multiple JSON values")
		}
		return OverlayPropertyReport{}, fmt.Errorf("decode overlay property report trailer: %w", err)
	}
	if err := ValidateOverlayPropertyReport(report); err != nil {
		return OverlayPropertyReport{}, err
	}
	return report, nil
}

func OverlayReportedPropertyIDs(report OverlayPropertyReport) ([]string, error) {
	if err := ValidateOverlayPropertyReport(report); err != nil {
		return nil, err
	}
	ids := make([]string, 0, len(report.Results))
	for _, result := range report.Results {
		if result.Status != PropertyStatusPassed {
			return nil, fmt.Errorf("overlay property %q was reported with status %q", result.PropertyID, result.Status)
		}
		ids = append(ids, result.PropertyID)
	}
	return ids, nil
}
