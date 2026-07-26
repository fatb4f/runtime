package hydrator

import (
	"errors"
	"fmt"
	"path"
	"sort"
	"strings"
	"unicode/utf8"

	git "github.com/go-git/go-git/v5"
	"github.com/go-git/go-git/v5/plumbing"
	"github.com/go-git/go-git/v5/plumbing/filemode"
	"github.com/go-git/go-git/v5/plumbing/object"

	"github.com/fatb4f/dotfiles/.codex/context-hydrators/git/internal/identity"
)

type Config struct {
	Identity string
	Digest   string
}

func DefaultConfig() Config {
	return Config{Identity: DefaultHydratorIdentity, Digest: BuildHydratorDigest}
}

func HydrateCommitted(request Request, config Config) (Observation, error) {
	if err := ValidateRequest(request); err != nil {
		return Observation{}, err
	}
	if !graphIDPattern.MatchString(config.Identity) {
		return Observation{}, errors.New("hydrator identity must be a graph identifier")
	}
	if !isSHA256Digest(config.Digest) {
		return Observation{}, errors.New("hydrator digest must be a sha256 digest")
	}
	if config.Digest == UnboundHydratorDigest {
		return Observation{}, errors.New("hydrator digest is unbound; inject release provenance at build time")
	}

	repository, err := git.PlainOpenWithOptions(request.Path, &git.PlainOpenOptions{DetectDotGit: true})
	if err != nil {
		return Observation{}, fmt.Errorf("open repository: %w", err)
	}

	hash, err := repository.ResolveRevision(plumbing.Revision(request.Revision))
	if err != nil {
		return Observation{}, fmt.Errorf("resolve revision %q: %w", request.Revision, err)
	}
	commit, err := repository.CommitObject(*hash)
	if err != nil {
		return Observation{}, fmt.Errorf("resolved object %s is not a commit: %w", hash.String(), err)
	}
	tree, err := commit.Tree()
	if err != nil {
		return Observation{}, fmt.Errorf("load root tree: %w", err)
	}

	occurrences := make([]Occurrence, 0, len(tree.Entries))
	seen := make(map[string]struct{})
	if err := walkTree(repository, tree, "", &occurrences, seen); err != nil {
		return Observation{}, err
	}
	sort.Slice(occurrences, func(i, j int) bool {
		return occurrences[i].Path < occurrences[j].Path
	})

	resolvedRevision := objectID(commit.Hash)
	canonicalRevision := resolvedRevision.Hex

	return Observation{
		Schema:            ObservationSchema,
		RepositoryID:      request.RepositoryID,
		RequestedRevision: canonicalRevision,
		ResolvedRevision:  resolvedRevision,
		RootTree:          objectID(tree.Hash),
		Occurrences:       occurrences,
		Hydrator: HydratorIdentity{
			Identity: config.Identity,
			Digest:   config.Digest,
		},
	}, nil
}

func walkTree(repository *git.Repository, tree *object.Tree, prefix string, occurrences *[]Occurrence, seen map[string]struct{}) error {
	entries := append([]object.TreeEntry(nil), tree.Entries...)
	sort.Slice(entries, func(i, j int) bool { return entries[i].Name < entries[j].Name })

	for _, entry := range entries {
		entryPath := entry.Name
		if prefix != "" {
			entryPath = prefix + "/" + entry.Name
		}
		normalized, err := normalizeOccurrencePath(entryPath)
		if err != nil {
			return fmt.Errorf("tree entry %q: %w", entryPath, err)
		}
		if _, exists := seen[normalized]; exists {
			return fmt.Errorf("duplicate committed path %q", normalized)
		}
		seen[normalized] = struct{}{}

		kind, err := kindForMode(entry.Mode)
		if err != nil {
			return fmt.Errorf("tree entry %q: %w", normalized, err)
		}
		occurrence := Occurrence{
			Path:     normalized,
			Mode:     fmt.Sprintf("%06o", uint32(entry.Mode)),
			Kind:     kind,
			ObjectID: objectID(entry.Hash),
		}

		switch kind {
		case "blob", "symlink":
			blob, err := repository.BlobObject(entry.Hash)
			if err != nil {
				return fmt.Errorf("load blob %q: %w", normalized, err)
			}
			size := blob.Size
			occurrence.Size = &size
		case "tree":
			// The tree is recorded before recursion so a directory remains a
			// first-class committed occurrence.
		case "submodule":
			// A gitlink names a commit in another repository. Never resolve or
			// recurse through it from this structural hydrator.
		default:
			return fmt.Errorf("unsupported occurrence kind %q", kind)
		}

		*occurrences = append(*occurrences, occurrence)
		if kind == "tree" {
			child, err := repository.TreeObject(entry.Hash)
			if err != nil {
				return fmt.Errorf("load tree %q: %w", normalized, err)
			}
			if err := walkTree(repository, child, normalized, occurrences, seen); err != nil {
				return err
			}
		}
	}
	return nil
}

func normalizeOccurrencePath(value string) (string, error) {
	if !utf8.ValidString(value) {
		return "", errors.New("path must be valid UTF-8")
	}
	if value == "" || value == "." || strings.HasPrefix(value, "/") {
		return "", errors.New("path must be non-empty and relative")
	}
	normalized := path.Clean(value)
	if normalized != value || normalized == ".." || strings.HasPrefix(normalized, "../") {
		return "", errors.New("path must already be normalized")
	}
	return normalized, nil
}

func kindForMode(mode filemode.FileMode) (string, error) {
	switch mode {
	case filemode.Dir:
		return "tree", nil
	case filemode.Submodule:
		return "submodule", nil
	case filemode.Symlink:
		return "symlink", nil
	case filemode.Regular, filemode.Executable, filemode.Deprecated:
		return "blob", nil
	default:
		return "", fmt.Errorf("unsupported git mode %06o", uint32(mode))
	}
}

func objectID(hash plumbing.Hash) identity.ObjectID {
	hexValue := hash.String()
	format := fmt.Sprintf("git-hash-%d", len(hexValue)*4)
	switch len(hexValue) {
	case 40:
		format = "sha1"
	case 64:
		format = "sha256"
	}
	return identity.ObjectID{Format: format, Hex: hexValue}
}

func isSHA256Digest(value string) bool {
	if len(value) != len("sha256:")+64 || !strings.HasPrefix(value, "sha256:") {
		return false
	}
	for _, character := range value[len("sha256:"):] {
		if !strings.ContainsRune("0123456789abcdef", character) {
			return false
		}
	}
	return true
}
