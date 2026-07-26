package testfixture

import (
	"os"
	"path/filepath"
	"testing"
)

func TestCreateIsHermeticAcrossHostGitConfiguration(t *testing.T) {
	root := t.TempDir()
	first, err := Create(filepath.Join(root, "fixture-one"))
	if err != nil {
		t.Fatalf("create baseline fixture: %v", err)
	}

	globalConfig := filepath.Join(root, "hostile-gitconfig")
	if err := os.WriteFile(globalConfig, []byte("[init]\n\tdefaultObjectFormat = sha256\n[core]\n\thooksPath = /nonexistent/hostile-hooks\n"), 0o644); err != nil {
		t.Fatalf("write hostile Git configuration: %v", err)
	}
	t.Setenv("GIT_DEFAULT_HASH", "sha256")
	t.Setenv("GIT_CONFIG_GLOBAL", globalConfig)
	t.Setenv("GIT_CONFIG_SYSTEM", globalConfig)
	t.Setenv("GIT_TEMPLATE_DIR", filepath.Join(root, "hostile-template"))
	t.Setenv("HOME", filepath.Join(root, "hostile-home"))
	t.Setenv("XDG_CONFIG_HOME", filepath.Join(root, "hostile-xdg"))

	second, err := Create(filepath.Join(root, "fixture-two"))
	if err != nil {
		t.Fatalf("create fixture under hostile environment: %v", err)
	}
	for _, commitID := range []string{"A", "B", "C", "D", "E", "F"} {
		if first.Commits[commitID] != second.Commits[commitID] {
			t.Fatalf("fixture commit %s changed: %s != %s", commitID, first.Commits[commitID], second.Commits[commitID])
		}
		if len(second.Commits[commitID]) != 40 {
			t.Fatalf("fixture commit %s is not SHA-1: %s", commitID, second.Commits[commitID])
		}
	}
}
