package hydrator

import (
	"errors"
	"fmt"
	"io"
	"os"
	"path"
	"sort"
	"strings"

	"github.com/go-git/go-billy/v5"
	git "github.com/go-git/go-git/v5"
	"github.com/go-git/go-git/v5/plumbing"
	"github.com/go-git/go-git/v5/plumbing/filemode"
	"github.com/go-git/go-git/v5/plumbing/format/gitignore"
	gitindex "github.com/go-git/go-git/v5/plumbing/format/index"
	"github.com/go-git/go-git/v5/plumbing/object"

	"github.com/fatb4f/dotfiles/.codex/context-hydrators/git/internal/identity"
)

type overlayEntry struct {
	mode     filemode.FileMode
	kind     string
	objectID identity.ObjectID
	size     *int64
}

func HydrateOverlay(request OverlayRequest, config Config) (OverlayObservation, error) {
	if err := ValidateOverlayRequest(request); err != nil {
		return OverlayObservation{}, err
	}
	if !graphIDPattern.MatchString(config.Identity) {
		return OverlayObservation{}, errors.New("hydrator identity must be a graph identifier")
	}
	if !isSHA256Digest(config.Digest) {
		return OverlayObservation{}, errors.New("hydrator digest must be a sha256 digest")
	}
	if config.Digest == UnboundHydratorDigest {
		return OverlayObservation{}, errors.New("hydrator digest is unbound; inject release provenance at build time")
	}
	if request.BaseRevision.Format != "sha1" {
		return OverlayObservation{}, fmt.Errorf("unsupported baseRevision object format %q", request.BaseRevision.Format)
	}

	repository, err := git.PlainOpenWithOptions(request.Path, &git.PlainOpenOptions{DetectDotGit: true})
	if err != nil {
		return OverlayObservation{}, fmt.Errorf("open repository: %w", err)
	}
	commit, err := repository.CommitObject(plumbing.NewHash(request.BaseRevision.Hex))
	if err != nil {
		return OverlayObservation{}, fmt.Errorf("load exact base revision %s: %w", request.BaseRevision.Hex, err)
	}
	resolvedBase := objectID(commit.Hash)
	if resolvedBase != request.BaseRevision {
		return OverlayObservation{}, errors.New("baseRevision does not identify the resolved commit exactly")
	}
	head, err := repository.Head()
	if err != nil {
		return OverlayObservation{}, fmt.Errorf("resolve repository HEAD for overlay binding: %w", err)
	}
	if head.Hash() != commit.Hash {
		return OverlayObservation{}, fmt.Errorf("overlay base %s does not match repository HEAD %s", commit.Hash, head.Hash())
	}
	baseTree, err := commit.Tree()
	if err != nil {
		return OverlayObservation{}, fmt.Errorf("load base tree: %w", err)
	}

	baseEntries, err := collectBaseEntries(repository, baseTree)
	if err != nil {
		return OverlayObservation{}, err
	}
	indexState, err := collectIndexEntries(repository)
	if err != nil {
		return OverlayObservation{}, err
	}
	indexOccurrences, err := compareBaseToIndex(baseEntries, indexState)
	if err != nil {
		return OverlayObservation{}, err
	}

	worktree, err := repository.Worktree()
	if err != nil {
		return OverlayObservation{}, fmt.Errorf("open worktree: %w", err)
	}
	worktreeState, err := collectWorktreeEntries(worktree.Filesystem, indexState)
	if err != nil {
		return OverlayObservation{}, err
	}
	worktreeOccurrences := compareIndexToWorktree(indexState, worktreeState)

	observation := OverlayObservation{
		Schema:       OverlayObservationSchema,
		RepositoryID: request.RepositoryID,
		BaseRevision: resolvedBase,
		BaseTree:     objectID(baseTree.Hash),
		Index: IndexOverlay{
			Schema:       IndexOverlaySchema,
			RepositoryID: request.RepositoryID,
			BaseRevision: resolvedBase,
			Occurrences:  indexOccurrences,
		},
		Worktree: WorktreeOverlay{
			Schema:       WorktreeOverlaySchema,
			RepositoryID: request.RepositoryID,
			BaseRevision: resolvedBase,
			Occurrences:  worktreeOccurrences,
		},
		Hydrator: HydratorIdentity{Identity: config.Identity, Digest: config.Digest},
	}
	if err := ValidateOverlayObservation(observation); err != nil {
		return OverlayObservation{}, fmt.Errorf("validate collected overlay: %w", err)
	}
	return observation, nil
}

func collectBaseEntries(repository *git.Repository, tree *object.Tree) (map[string]overlayEntry, error) {
	occurrences := make([]Occurrence, 0, len(tree.Entries))
	if err := walkTree(repository, tree, "", &occurrences, make(map[string]struct{})); err != nil {
		return nil, fmt.Errorf("walk exact base tree: %w", err)
	}
	entries := make(map[string]overlayEntry)
	for _, occurrence := range occurrences {
		if occurrence.Kind == "tree" {
			continue
		}
		mode, err := filemode.New(occurrence.Mode)
		if err != nil {
			return nil, fmt.Errorf("decode base mode for %q: %w", occurrence.Path, err)
		}
		entries[occurrence.Path] = overlayEntry{mode: mode, kind: occurrence.Kind, objectID: occurrence.ObjectID, size: occurrence.Size}
	}
	return entries, nil
}

func collectIndexEntries(repository *git.Repository) (map[string]overlayEntry, error) {
	index, err := repository.Storer.Index()
	if err != nil {
		return nil, fmt.Errorf("read Git index: %w", err)
	}
	entries := make(map[string]overlayEntry, len(index.Entries))
	for _, entry := range index.Entries {
		normalized, err := normalizeOccurrencePath(entry.Name)
		if err != nil || normalized != entry.Name {
			return nil, fmt.Errorf("index path %q is not normalized", entry.Name)
		}
		if entry.Stage != gitindex.Stage(0) {
			return nil, fmt.Errorf("index path %q has unresolved merge stage %d", entry.Name, entry.Stage)
		}
		if entry.IntentToAdd || entry.Hash.IsZero() {
			return nil, fmt.Errorf("index path %q has no content identity", entry.Name)
		}
		if _, duplicate := entries[normalized]; duplicate {
			return nil, fmt.Errorf("duplicate index path %q", normalized)
		}
		kind, err := kindForMode(entry.Mode)
		if err != nil || kind == "tree" {
			return nil, fmt.Errorf("index path %q has unsupported mode %06o", normalized, uint32(entry.Mode))
		}
		value := overlayEntry{mode: entry.Mode, kind: kind, objectID: objectID(entry.Hash)}
		if kind != "submodule" {
			blob, err := repository.BlobObject(entry.Hash)
			if err != nil {
				return nil, fmt.Errorf("load indexed blob %q: %w", normalized, err)
			}
			size := blob.Size
			value.size = &size
		}
		entries[normalized] = value
	}
	return entries, nil
}

func compareBaseToIndex(base, index map[string]overlayEntry) ([]OverlayOccurrence, error) {
	paths := unionPaths(base, index)
	occurrences := make([]OverlayOccurrence, 0)
	for _, currentPath := range paths {
		baseEntry, inBase := base[currentPath]
		indexEntry, inIndex := index[currentPath]
		switch {
		case inBase && !inIndex:
			occurrences = append(occurrences, deletedOverlayOccurrence("index", currentPath))
		case !inBase && inIndex:
			occurrences = append(occurrences, presentOverlayOccurrence("index", "added", currentPath, indexEntry, false))
		case inBase && inIndex && (baseEntry.objectID != indexEntry.objectID || baseEntry.mode != indexEntry.mode):
			occurrences = append(occurrences, presentOverlayOccurrence("index", "modified", currentPath, indexEntry, baseEntry.mode != indexEntry.mode))
		}
	}
	return occurrences, nil
}

func collectWorktreeEntries(filesystem billy.Filesystem, index map[string]overlayEntry) (map[string]overlayEntry, error) {
	patterns, err := gitignore.ReadPatterns(filesystem, nil)
	if err != nil {
		return nil, fmt.Errorf("read Git ignore patterns: %w", err)
	}
	matcher := gitignore.NewMatcher(patterns)
	entries := make(map[string]overlayEntry)
	var walk func(string) error
	walk = func(directory string) error {
		children, err := filesystem.ReadDir(directory)
		if err != nil {
			return fmt.Errorf("read worktree directory %q: %w", directory, err)
		}
		for _, child := range children {
			currentPath := child.Name()
			if directory != "." {
				currentPath = path.Join(directory, child.Name())
			}
			if currentPath == ".git" {
				continue
			}
			normalized, err := normalizeOccurrencePath(currentPath)
			if err != nil {
				return fmt.Errorf("worktree path %q: %w", currentPath, err)
			}
			info, err := filesystem.Lstat(normalized)
			if err != nil {
				return fmt.Errorf("inspect worktree path %q: %w", normalized, err)
			}

			if indexed, ok := index[normalized]; ok && indexed.kind == "submodule" && info.IsDir() {
				// A present gitlink is observable from the index. Treat its working
				// directory as opaque and never open or enumerate it.
				entries[normalized] = indexed
				continue
			}
			if info.IsDir() {
				if _, tracked := index[normalized]; !tracked {
					if _, err := filesystem.Lstat(path.Join(normalized, ".git")); err == nil {
						// An untracked nested repository has no trustworthy gitlink
						// object identity. Keep it opaque rather than inventing one.
						continue
					} else if !errors.Is(err, os.ErrNotExist) {
						return fmt.Errorf("inspect nested repository marker %q: %w", normalized, err)
					}
				}
				if err := walk(normalized); err != nil {
					return err
				}
				continue
			}
			if _, tracked := index[normalized]; !tracked && matcher.Match(strings.Split(normalized, "/"), false) {
				continue
			}
			entry, err := readWorktreeEntry(filesystem, normalized, info)
			if err != nil {
				return err
			}
			entries[normalized] = entry
		}
		return nil
	}
	if err := walk("."); err != nil {
		return nil, err
	}
	return entries, nil
}

func readWorktreeEntry(filesystem billy.Filesystem, currentPath string, info os.FileInfo) (overlayEntry, error) {
	mode, err := filemode.NewFromOSFileMode(info.Mode())
	if err != nil {
		return overlayEntry{}, fmt.Errorf("derive Git mode for %q: %w", currentPath, err)
	}
	kind, err := kindForMode(mode)
	if err != nil || kind == "tree" || kind == "submodule" {
		return overlayEntry{}, fmt.Errorf("unsupported worktree entry %q", currentPath)
	}
	var content []byte
	if kind == "symlink" {
		target, err := filesystem.Readlink(currentPath)
		if err != nil {
			return overlayEntry{}, fmt.Errorf("read symlink %q: %w", currentPath, err)
		}
		content = []byte(target)
	} else {
		file, err := filesystem.Open(currentPath)
		if err != nil {
			return overlayEntry{}, fmt.Errorf("open worktree file %q: %w", currentPath, err)
		}
		content, err = io.ReadAll(file)
		closeErr := file.Close()
		if err != nil {
			return overlayEntry{}, fmt.Errorf("read worktree file %q: %w", currentPath, err)
		}
		if closeErr != nil {
			return overlayEntry{}, fmt.Errorf("close worktree file %q: %w", currentPath, closeErr)
		}
	}
	hash := plumbing.ComputeHash(plumbing.BlobObject, content)
	size := int64(len(content))
	return overlayEntry{mode: mode, kind: kind, objectID: objectID(hash), size: &size}, nil
}

func compareIndexToWorktree(index, worktree map[string]overlayEntry) []OverlayOccurrence {
	paths := unionPaths(index, worktree)
	occurrences := make([]OverlayOccurrence, 0)
	for _, currentPath := range paths {
		indexEntry, inIndex := index[currentPath]
		worktreeEntry, inWorktree := worktree[currentPath]
		switch {
		case inIndex && !inWorktree:
			occurrences = append(occurrences, deletedOverlayOccurrence("worktree", currentPath))
		case !inIndex && inWorktree:
			occurrences = append(occurrences, presentOverlayOccurrence("worktree", "untracked", currentPath, worktreeEntry, false))
		case inIndex && inWorktree && (indexEntry.objectID != worktreeEntry.objectID || indexEntry.mode != worktreeEntry.mode):
			occurrences = append(occurrences, presentOverlayOccurrence("worktree", "modified", currentPath, worktreeEntry, indexEntry.mode != worktreeEntry.mode))
		}
	}
	return occurrences
}

func presentOverlayOccurrence(layer, status, currentPath string, entry overlayEntry, modeChanged bool) OverlayOccurrence {
	object := entry.objectID
	return OverlayOccurrence{
		Path: currentPath, Layer: layer, Status: status, ModeChanged: modeChanged,
		Mode: fmt.Sprintf("%06o", uint32(entry.mode)), Kind: entry.kind, ObjectID: &object, Size: entry.size,
	}
}

func deletedOverlayOccurrence(layer, currentPath string) OverlayOccurrence {
	return OverlayOccurrence{Path: currentPath, Layer: layer, Status: "deleted", ModeChanged: false}
}

func unionPaths(left, right map[string]overlayEntry) []string {
	set := make(map[string]struct{}, len(left)+len(right))
	for currentPath := range left {
		set[currentPath] = struct{}{}
	}
	for currentPath := range right {
		set[currentPath] = struct{}{}
	}
	paths := make([]string, 0, len(set))
	for currentPath := range set {
		paths = append(paths, currentPath)
	}
	sort.Strings(paths)
	return paths
}
