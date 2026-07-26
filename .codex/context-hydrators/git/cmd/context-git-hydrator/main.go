package main

import (
	"errors"
	"flag"
	"fmt"
	"io"
	"os"

	"github.com/fatb4f/dotfiles/.codex/context-hydrators/git/internal/hydrator"
)

func main() {
	if err := run(os.Args[1:], os.Stdout, os.Stderr); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func run(arguments []string, stdout, stderr io.Writer) error {
	if len(arguments) > 0 && arguments[0] == "validate-observation" {
		return validateObservation(arguments[1:], stdout, stderr)
	}
	if len(arguments) > 0 && arguments[0] == "validate-overlay-observation" {
		return validateOverlayObservation(arguments[1:], stdout, stderr)
	}
	if len(arguments) > 0 && arguments[0] == "overlay" {
		return hydrateOverlay(arguments[1:], stdout, stderr)
	}
	if len(arguments) == 0 || arguments[0] != "committed" {
		return errors.New("usage: context-git-hydrator committed --request request.json | overlay --request request.json | validate-observation --observation observation.json | validate-overlay-observation --observation observation.json")
	}

	flags := flag.NewFlagSet("committed", flag.ContinueOnError)
	flags.SetOutput(stderr)
	requestPath := flags.String("request", "", "path to a committed snapshot request JSON document")
	if err := flags.Parse(arguments[1:]); err != nil {
		return err
	}
	if flags.NArg() != 0 || *requestPath == "" {
		return errors.New("usage: context-git-hydrator committed --request request.json")
	}

	requestFile, err := os.Open(*requestPath)
	if err != nil {
		return fmt.Errorf("open request: %w", err)
	}
	defer requestFile.Close()

	request, err := hydrator.DecodeRequest(requestFile)
	if err != nil {
		return err
	}
	observation, err := hydrator.HydrateCommitted(request, hydrator.DefaultConfig())
	if err != nil {
		return err
	}
	payload, err := hydrator.MarshalCanonical(observation)
	if err != nil {
		return err
	}
	if _, err := stdout.Write(payload); err != nil {
		return fmt.Errorf("write observation: %w", err)
	}
	return nil
}

func hydrateOverlay(arguments []string, stdout, stderr io.Writer) error {
	flags := flag.NewFlagSet("overlay", flag.ContinueOnError)
	flags.SetOutput(stderr)
	requestPath := flags.String("request", "", "path to an overlay request JSON document")
	if err := flags.Parse(arguments); err != nil {
		return err
	}
	if flags.NArg() != 0 || *requestPath == "" {
		return errors.New("usage: context-git-hydrator overlay --request request.json")
	}
	requestFile, err := os.Open(*requestPath)
	if err != nil {
		return fmt.Errorf("open overlay request: %w", err)
	}
	defer requestFile.Close()
	request, err := hydrator.DecodeOverlayRequest(requestFile)
	if err != nil {
		return err
	}
	observation, err := hydrator.HydrateOverlay(request, hydrator.DefaultConfig())
	if err != nil {
		return err
	}
	payload, err := hydrator.MarshalOverlayCanonical(observation)
	if err != nil {
		return err
	}
	if _, err := stdout.Write(payload); err != nil {
		return fmt.Errorf("write overlay observation: %w", err)
	}
	return nil
}

func validateObservation(arguments []string, stdout, stderr io.Writer) error {
	flags := flag.NewFlagSet("validate-observation", flag.ContinueOnError)
	flags.SetOutput(stderr)
	observationPath := flags.String("observation", "", "path to a committed snapshot observation JSON document")
	if err := flags.Parse(arguments); err != nil {
		return err
	}
	if flags.NArg() != 0 || *observationPath == "" {
		return errors.New("usage: context-git-hydrator validate-observation --observation observation.json")
	}
	file, err := os.Open(*observationPath)
	if err != nil {
		return fmt.Errorf("open observation: %w", err)
	}
	defer file.Close()
	observation, err := hydrator.DecodeObservation(file)
	if err != nil {
		return err
	}
	payload, err := hydrator.MarshalCanonical(observation)
	if err != nil {
		return err
	}
	if _, err := stdout.Write(payload); err != nil {
		return fmt.Errorf("write observation: %w", err)
	}
	return nil
}

func validateOverlayObservation(arguments []string, stdout, stderr io.Writer) error {
	flags := flag.NewFlagSet("validate-overlay-observation", flag.ContinueOnError)
	flags.SetOutput(stderr)
	observationPath := flags.String("observation", "", "path to an overlay observation JSON document")
	if err := flags.Parse(arguments); err != nil {
		return err
	}
	if flags.NArg() != 0 || *observationPath == "" {
		return errors.New("usage: context-git-hydrator validate-overlay-observation --observation observation.json")
	}
	file, err := os.Open(*observationPath)
	if err != nil {
		return fmt.Errorf("open overlay observation: %w", err)
	}
	defer file.Close()
	observation, err := hydrator.DecodeOverlayObservation(file)
	if err != nil {
		return err
	}
	payload, err := hydrator.MarshalOverlayCanonical(observation)
	if err != nil {
		return err
	}
	if _, err := stdout.Write(payload); err != nil {
		return fmt.Errorf("write overlay observation: %w", err)
	}
	return nil
}
