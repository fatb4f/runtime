package testfixture

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

type Repository struct {
	Path    string            `json:"path"`
	Commits map[string]string `json:"commits"`
}

func Create(path string) (Repository, error) {
	root := filepath.Clean(path)
	if err := os.MkdirAll(root, 0o755); err != nil {
		return Repository{}, fmt.Errorf("create fixture repository root: %w", err)
	}
	if err := prepareGitEnvironment(root); err != nil {
		return Repository{}, err
	}
	if _, err := runGit(root, nil, "init", "--object-format=sha1", "--initial-branch=main"); err != nil {
		return Repository{}, err
	}
	for _, setting := range [][2]string{
		{"user.name", "Context Fixture"},
		{"user.email", "fixture@example.invalid"},
		{"core.autocrlf", "false"},
		{"core.filemode", "true"},
	} {
		if _, err := runGit(root, nil, "config", setting[0], setting[1]); err != nil {
			return Repository{}, err
		}
	}

	if err := writeFile(root, "docs/readme.txt", "immutable fixture\n", 0o644); err != nil {
		return Repository{}, err
	}
	if err := writeFile(root, "src/main.sh", "#!/bin/sh\nprintf 'fixture\\n'\n", 0o644); err != nil {
		return Repository{}, err
	}
	if _, err := runGit(root, nil, "add", "--all"); err != nil {
		return Repository{}, err
	}
	commitA, err := commit(root, 1, "fixture A: initial tree")
	if err != nil {
		return Repository{}, err
	}
	if _, err := runGit(root, nil, "tag", "fixture-a", commitA); err != nil {
		return Repository{}, err
	}

	if err := os.Rename(filepath.Join(root, "docs/readme.txt"), filepath.Join(root, "docs/guide.txt")); err != nil {
		return Repository{}, fmt.Errorf("rename fixture file: %w", err)
	}
	if _, err := runGit(root, nil, "add", "--all"); err != nil {
		return Repository{}, err
	}
	commitB, err := commit(root, 2, "fixture B: rename")
	if err != nil {
		return Repository{}, err
	}

	if err := writeFile(root, "docs/guide.txt", "modified fixture\n", 0o644); err != nil {
		return Repository{}, err
	}
	if _, err := runGit(root, nil, "add", "--all"); err != nil {
		return Repository{}, err
	}
	commitC, err := commit(root, 3, "fixture C: content edit")
	if err != nil {
		return Repository{}, err
	}

	if err := writeFile(root, "unrelated.txt", "unrelated\n", 0o644); err != nil {
		return Repository{}, err
	}
	if _, err := runGit(root, nil, "add", "--all"); err != nil {
		return Repository{}, err
	}
	commitD, err := commit(root, 4, "fixture D: unrelated addition")
	if err != nil {
		return Repository{}, err
	}

	if err := os.Chmod(filepath.Join(root, "src/main.sh"), 0o755); err != nil {
		return Repository{}, fmt.Errorf("make fixture executable: %w", err)
	}
	if _, err := runGit(root, nil, "add", "--all"); err != nil {
		return Repository{}, err
	}
	commitE, err := commit(root, 5, "fixture E: mode change")
	if err != nil {
		return Repository{}, err
	}

	if err := os.Symlink("docs/guide.txt", filepath.Join(root, "guide-link")); err != nil {
		return Repository{}, fmt.Errorf("create fixture symlink: %w", err)
	}
	if _, err := runGit(root, nil, "add", "guide-link"); err != nil {
		return Repository{}, err
	}
	emptyTreeOutput, err := runGitInput(root, "", nil, "mktree")
	if err != nil {
		return Repository{}, err
	}
	emptyTree := strings.TrimSpace(emptyTreeOutput)
	gitlinkOutput, err := runGitInput(root, "", gitEnvironment(9), "commit-tree", emptyTree, "-m", "gitlink target")
	if err != nil {
		return Repository{}, err
	}
	gitlinkTarget := strings.TrimSpace(gitlinkOutput)
	if _, err := runGit(root, nil, "update-index", "--add", "--cacheinfo", "160000,"+gitlinkTarget+",vendor/dependency"); err != nil {
		return Repository{}, err
	}
	commitF, err := commit(root, 6, "fixture F: symlink and gitlink")
	if err != nil {
		return Repository{}, err
	}
	if _, err := runGit(root, nil, "tag", "fixture-f", commitF); err != nil {
		return Repository{}, err
	}
	// Materialize only the gitlink mount point. Overlay tests use this empty
	// directory to prove that the collector treats submodules as opaque without
	// storing or traversing a nested .git fixture.
	if err := os.MkdirAll(filepath.Join(root, "vendor/dependency"), 0o755); err != nil {
		return Repository{}, fmt.Errorf("materialize opaque gitlink mount point: %w", err)
	}

	return Repository{
		Path: root,
		Commits: map[string]string{
			"A": commitA,
			"B": commitB,
			"C": commitC,
			"D": commitD,
			"E": commitE,
			"F": commitF,
		},
	}, nil
}

// RunGit executes Git inside the isolated, deterministic fixture environment.
func RunGit(repository Repository, arguments ...string) (string, error) {
	return runGit(repository.Path, nil, arguments...)
}

// WriteWorktreeFile changes a fixture worktree without staging it.
func WriteWorktreeFile(repository Repository, relative, content string, mode os.FileMode) error {
	return writeFile(repository.Path, relative, content, mode)
}

// RemoveWorktreePath removes one fixture path without touching the index.
func RemoveWorktreePath(repository Repository, relative string) error {
	if err := os.RemoveAll(filepath.Join(repository.Path, filepath.FromSlash(relative))); err != nil {
		return fmt.Errorf("remove fixture path %s: %w", relative, err)
	}
	return nil
}

// CreateWorktreeSymlink creates a structural symlink fixture.
func CreateWorktreeSymlink(repository Repository, target, relative string) error {
	absolute := filepath.Join(repository.Path, filepath.FromSlash(relative))
	if err := os.MkdirAll(filepath.Dir(absolute), 0o755); err != nil {
		return fmt.Errorf("create symlink fixture parent: %w", err)
	}
	if err := os.Symlink(target, absolute); err != nil {
		return fmt.Errorf("create fixture symlink %s: %w", relative, err)
	}
	return nil
}

func UpdateRef(repository Repository, refName, commit string) error {
	_, err := runGit(repository.Path, nil, "update-ref", refName, commit)
	return err
}

func WriteManifest(path string, repository Repository, properties []string) error {
	document := struct {
		Repository Repository `json:"repository"`
		Properties []string   `json:"properties"`
	}{Repository: repository, Properties: properties}
	payload, err := json.MarshalIndent(document, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal fixture manifest: %w", err)
	}
	payload = append(payload, '\n')
	if err := os.WriteFile(path, payload, 0o644); err != nil {
		return fmt.Errorf("write fixture manifest: %w", err)
	}
	return nil
}

func writeFile(root, relative, content string, mode os.FileMode) error {
	absolute := filepath.Join(root, filepath.FromSlash(relative))
	if err := os.MkdirAll(filepath.Dir(absolute), 0o755); err != nil {
		return fmt.Errorf("create fixture directory: %w", err)
	}
	if err := os.WriteFile(absolute, []byte(content), mode); err != nil {
		return fmt.Errorf("write fixture file %s: %w", relative, err)
	}
	if err := os.Chmod(absolute, mode); err != nil {
		return fmt.Errorf("chmod fixture file %s: %w", relative, err)
	}
	return nil
}

func commit(root string, sequence int, message string) (string, error) {
	if _, err := runGit(root, gitEnvironment(sequence), "commit", "--no-gpg-sign", "-m", message); err != nil {
		return "", err
	}
	output, err := runGit(root, nil, "rev-parse", "HEAD")
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(output), nil
}

func gitEnvironment(sequence int) []string {
	date := fmt.Sprintf("2001-01-%02dT00:00:00Z", sequence)
	return []string{
		"GIT_AUTHOR_NAME=Context Fixture",
		"GIT_AUTHOR_EMAIL=fixture@example.invalid",
		"GIT_AUTHOR_DATE=" + date,
		"GIT_COMMITTER_NAME=Context Fixture",
		"GIT_COMMITTER_EMAIL=fixture@example.invalid",
		"GIT_COMMITTER_DATE=" + date,
	}
}

func prepareGitEnvironment(root string) error {
	stateRoot := gitEnvironmentRoot(root)
	if err := os.RemoveAll(stateRoot); err != nil {
		return fmt.Errorf("reset fixture Git environment: %w", err)
	}
	for _, directory := range []string{
		filepath.Join(stateRoot, "home"),
		filepath.Join(stateRoot, "xdg"),
		filepath.Join(stateRoot, "templates"),
	} {
		if err := os.MkdirAll(directory, 0o755); err != nil {
			return fmt.Errorf("create fixture Git environment: %w", err)
		}
	}
	return nil
}

func gitEnvironmentRoot(root string) string {
	return filepath.Join(filepath.Dir(root), "."+filepath.Base(root)+"-git-environment")
}

func isolatedGitEnvironment(root string, environment []string) []string {
	stateRoot := gitEnvironmentRoot(root)
	result := []string{
		"PATH=" + os.Getenv("PATH"),
		"HOME=" + filepath.Join(stateRoot, "home"),
		"XDG_CONFIG_HOME=" + filepath.Join(stateRoot, "xdg"),
		"GIT_CONFIG_NOSYSTEM=1",
		"GIT_CONFIG_GLOBAL=" + os.DevNull,
		"GIT_ATTR_NOSYSTEM=1",
		"GIT_TEMPLATE_DIR=" + filepath.Join(stateRoot, "templates"),
		"GIT_TERMINAL_PROMPT=0",
		"LC_ALL=C",
		"LANG=C",
		"TZ=UTC",
	}
	if temporary := os.Getenv("TMPDIR"); temporary != "" {
		result = append(result, "TMPDIR="+temporary)
	}
	return append(result, environment...)
}

func runGit(root string, environment []string, arguments ...string) (string, error) {
	return runGitInput(root, "", environment, arguments...)
}

func runGitInput(root, input string, environment []string, arguments ...string) (string, error) {
	command := exec.Command("git", arguments...)
	command.Dir = root
	command.Env = isolatedGitEnvironment(root, environment)
	command.Stdin = strings.NewReader(input)
	output, err := command.CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("git %s: %w\n%s", strings.Join(arguments, " "), err, output)
	}
	return string(output), nil
}
