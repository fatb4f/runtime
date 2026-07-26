package main

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"

	"github.com/fatb4f/dotfiles/.codex/context-hydrators/git/internal/hydrator"
	"github.com/fatb4f/dotfiles/.codex/context-hydrators/git/internal/testfixture"
)

func main() {
	output := flag.String("output", "", "directory in which to create the qualification fixture")
	flag.Parse()
	if *output == "" || flag.NArg() != 0 {
		fmt.Fprintln(os.Stderr, "usage: context-git-fixture --output directory")
		os.Exit(2)
	}
	if err := os.MkdirAll(*output, 0o755); err != nil {
		fmt.Fprintf(os.Stderr, "create output directory: %v\n", err)
		os.Exit(1)
	}
	repository, err := testfixture.Create(filepath.Join(*output, "repository"))
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	if err := testfixture.WriteManifest(filepath.Join(*output, "manifest.json"), repository, hydrator.GeneratedPropertyIDs()); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	if err := testfixture.WriteManifest(filepath.Join(*output, "overlay-manifest.json"), repository, hydrator.OverlayGeneratedPropertyIDs()); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
