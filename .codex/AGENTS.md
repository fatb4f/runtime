# `.codex` contract-extension workflow

## Scope

These instructions govern changes under `.codex/`. Nested `AGENTS.md` files may narrow subsystem details, but must preserve the dependency order, authority bounds, determinism requirements, and qualification gates below.

CUE definitions are the structural and logical authority. Implementations, fixtures, generated clients, test reports, and fuzz counterexamples are derived surfaces; they do not define the contract.

## Acyclic extension DAG

Every extension must move in this direction only:

```text
N0  Base schema and shared lattice definitions
    .codex/context-model/model.cue
    .codex/context-model/context_graph*.cue
                     |
                     v
N1  Domain schema extension
    closed request/input/output shapes
    bounded identifiers, references, unions, and authority
                     |
                     v
N2  Assertion invariants
    named properties with preconditions, mutation class,
    preserved terms, changed terms, and rejection outcomes
                     |
                     v
N3  Generator contract
    positive, negative, boundary, and metamorphic cases
    generated from the schema and assertion catalog
                     |
                     v
N4  Typed adapters
    Go/Python/Pydantic projections that cannot widen N1 or N2
                     |
                     v
N5  Executable property runners
    one property ID -> one concrete assertion runner
                     |
                     v
N6  Hypothesis schemas and mutation strategies
    invariant-directed generation and shrinking
                     |
                     v
N7  Forward fuzzing and differential oracles
    CUE vs typed adapter vs implementation
                     |
                     v
N8  Backward fuzz analysis
    minimized counterexample -> proposed assertion candidate
                     |
                     v
N9  Automated qualification and persisted report
    declared = generated = executed = reported
```

No node may infer authority from a downstream node. In particular:

- adapters must not define behavior absent from CUE;
- fixtures must not become the source of expected behavior;
- reports must not manufacture property membership;
- fuzz findings must not modify authoritative schemas during the same run.

A backward-fuzz finding enters the next DAG generation at N1 or N2 after review. This version boundary preserves acyclicity.

## Schema-extension protocol

For every new field, variant, relationship, projection, or adapter operation:

1. Extend the narrowest closed CUE schema.
2. Declare its invariants before implementing it.
3. Give every invariant a stable property ID.
4. State its preconditions and mutation class.
5. State which identity, authority, ordering, provenance, or structural terms must be preserved or changed.
6. Define malformed and boundary mutations that must bottom.
7. Generate typed adapters only after the schema and property catalog evaluate.
8. Add one executable assertion runner per property ID.
9. Add Hypothesis strategies derived from the same invariant vocabulary.
10. Run deterministic, metamorphic, differential, and rejection qualification.

Unknown fields must reject at closed boundaries. Collection adapters remain limited to `none | candidate` authority unless a separate admission transition is explicitly modeled.

## Assertion catalogs and equality gates

Property membership must have four independent sources:

```text
declared  <- CUE assertion/property catalog
generated <- generated fixture or mutation manifest
executed  <- IDs emitted by successful property runners
reported  <- persisted report reloaded from disk
```

Qualification requires exact set equality:

```text
declared = generated = executed = reported
```

Copying one set to construct another is prohibited. A generic execution path that records an ID without running its property-specific assertion is prohibited. Reports must be closed, reject duplicate property IDs, and distinguish passed from failed execution.

## Hypothesis requirements

Define Hypothesis schemas around every invariant, not only around example fixtures. Each invariant must have applicable strategies for:

- valid values near lower and upper bounds;
- unknown-field insertion;
- missing required fields;
- incompatible union or mode/kind combinations;
- duplicate identifiers and duplicate paths;
- ordering and normalization perturbations;
- broken references and containment edges;
- authority elevation without admission;
- identity-preserving mutations;
- identity-changing mutations;
- provenance and digest perturbations;
- environment changes relevant to determinism.

Metamorphic strategies must encode preservation/change matrices directly. For example, rename-only, content-edit, unrelated-addition, and mode-only mutations must each assert the correct behavior for content identity, stable occurrence identity, snapshot occurrence identity, and metadata.

Shrinking must retain the violated invariant and produce the smallest reproducible counterexample. A strategy that only produces accepted examples is incomplete.

## Fuzzing and backward assertion discovery

Forward fuzzing starts from an invariant and generates values or mutations expected to accept or reject. Compare at least these oracles where applicable:

```text
CUE validation/projection
<-> typed model validation
<-> adapter execution
<-> normalized serialized output
```

Any disagreement is a failure even when one surface accepts the value.

Backward fuzzing starts from an observed failure, unexpected acceptance, oracle disagreement, or metamorphic violation. It must:

1. preserve the original failing input and tool identities;
2. minimize the counterexample;
3. classify the missing constraint or assertion;
4. emit a closed assertion candidate containing:
   - proposed property ID;
   - target schema definition;
   - minimized fixture;
   - mutation class;
   - expected accept/reject result;
   - preserved and changed invariant terms;
   - affected oracle surfaces;
5. add the case to a non-authoritative regression queue;
6. require review before promotion into the CUE property catalog.

A fuzzer must never silently update the declared property set or mark its own discovered candidate as executed. Once promoted, regenerate N3-N6 and run the complete DAG again.

## Automated tests

At minimum, qualification must cover:

- CUE evaluation and scoped positive/negative vetting;
- typed-model validation;
- adapter unit and integration tests;
- deterministic byte output under controlled environment perturbations;
- metamorphic identity and provenance properties;
- structural rejection and authority-boundary tests;
- Hypothesis invariant mutation suites;
- forward fuzz differential checks;
- backward-fuzz regression candidates;
- persisted equality-gate reports.

Use the repository's pinned commands and workflows. A change is incomplete if any existing graph, admission, workbook, DSPy, or subsystem suite regresses.
