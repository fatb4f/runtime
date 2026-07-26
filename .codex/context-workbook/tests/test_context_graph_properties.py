from __future__ import annotations

import os
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from context_workbook.context_graph_property_extensions import register_additional_mutators
from context_workbook.context_graph_properties import (
    ContextGraphResolution,
    assert_expected,
    cue_vet,
    export_json_schema,
    load_property_catalog,
    mutate_for_property,
    pydantic_accepts,
    validate_property_coverage,
)


def _digest(byte: int) -> str:
    return "sha256:" + (bytes([byte % 256]) * 32).hex()


@st.composite
def context_graph_resolutions(
    draw: st.DrawFn,
    *,
    min_modules: int,
    max_modules: int,
    min_members: int,
    max_members: int,
) -> dict[str, Any]:
    module_count = draw(st.integers(min_value=min_modules, max_value=max_modules))
    member_count = draw(st.integers(min_value=min_members, max_value=max_members))
    snapshot_byte = draw(st.integers(min_value=4, max_value=250))
    observation_authority = draw(st.sampled_from(["none", "candidate"]))

    modules: dict[str, Any] = {}
    namespaces: dict[str, Any] = {}
    module_namespace_ids: dict[str, list[str]] = {}

    module_kinds = ["repository", "project", "workspace", "application"]
    namespace_kinds = ["repository-root", "package", "source", "application"]

    for index in range(module_count):
        module_id = f"module.generated-{index}"
        root_namespace_id = f"namespace.generated-{index}.root"
        child_namespace_id = f"namespace.generated-{index}.child"
        modules[module_id] = {
            "kind": module_kinds[index % len(module_kinds)],
            "name": f"generated-{index}",
            "rootNamespaceID": root_namespace_id,
            "source": {
                "kind": "hypothesis",
                "revision": "generated",
                "contentDigest": _digest(10 + index),
            },
        }
        namespaces[root_namespace_id] = {
            "moduleID": module_id,
            "parentNamespaceID": None,
            "name": f"generated-{index}",
            "kind": namespace_kinds[index % len(namespace_kinds)],
            "rootPath": "." if index == 0 else f"module-{index}",
        }
        namespaces[child_namespace_id] = {
            "moduleID": module_id,
            "parentNamespaceID": root_namespace_id,
            "name": f"generated-{index}.child",
            "kind": "source",
            "rootPath": f"module-{index}/src",
        }
        module_namespace_ids[module_id] = [root_namespace_id, child_namespace_id]

    module_ids = sorted(modules)
    members: dict[str, Any] = {}
    for index in range(member_count):
        module_id = module_ids[index % module_count]
        namespace_id = module_namespace_ids[module_id][1]
        member_id = f"member.generated-{index}"
        members[member_id] = {
            "moduleID": module_id,
            "namespaceID": namespace_id,
            "name": f"generated.module-{index}",
            "kind": "module",
            "path": f"module-{index % module_count}/src/member-{index}.py",
            "source": {
                "kind": "hypothesis",
                "path": f"module-{index % module_count}/src/member-{index}.py",
                "contentDigest": _digest(40 + index),
            },
        }

    member_ids = sorted(members)
    evidence_id = "evidence.generated"
    evidence = {
        evidence_id: {
            "kind": "observation",
            "subject": {"kind": "member", "id": member_ids[0]},
            "producer": None,
            "source": {
                "kind": "hypothesis",
                "path": members[member_ids[0]]["path"],
                "contentDigest": _digest(90),
            },
            "authority": observation_authority,
            "diagnostics": [],
        }
    }

    relationship_id = "relationship.generated"
    relationships = {
        relationship_id: {
            "subject": {"kind": "member", "id": member_ids[0]},
            "predicate": "depends_on",
            "object": {"kind": "member", "id": member_ids[1] if len(member_ids) > 1 else member_ids[0]},
            "evidenceIDs": [evidence_id],
        }
    }

    max_selected = min(4, len(member_ids))
    selected_member_ids = draw(
        st.lists(
            st.sampled_from(member_ids),
            min_size=1,
            max_size=max_selected,
            unique=True,
        )
    )
    selected = [{"kind": "member", "id": member_id} for member_id in selected_member_ids]
    snapshot_id = _digest(snapshot_byte)

    snapshot = {
        "schema": "kernel.context-graph.v0",
        "snapshotID": snapshot_id,
        "modules": modules,
        "namespaces": namespaces,
        "members": members,
        "relationships": relationships,
        "evidence": evidence,
        "provenance": {
            "authorityDigest": _digest(1),
            "schemaDigest": _digest(2),
            "hydratorDigest": _digest(3),
            "baseRevision": "generated",
        },
    }
    selection = {
        "schema": "kernel.context-selection.v0",
        "requestID": "request.generated",
        "snapshotID": snapshot_id,
        "seedEntities": [selected[0]],
        "selected": selected,
        "relationshipIDs": [relationship_id],
        "evidenceIDs": [evidence_id],
        "gaps": {},
        "conflicts": {},
        "sufficiency": "sufficient",
    }
    return {
        "schema": "kernel.context-resolution.v0",
        "snapshot": snapshot,
        "selection": selection,
    }


register_additional_mutators()
CATALOG = load_property_catalog()
PROPERTY_IDS = sorted(CATALOG.properties)
PROPERTY_EXAMPLES = int(os.environ.get("CONTEXT_GRAPH_PROPERTY_EXAMPLES", "3"))


def test_property_catalog_is_fully_executable() -> None:
    validate_property_coverage(CATALOG)
    assert set(PROPERTY_IDS) == set(CATALOG.properties)


@pytest.mark.parametrize("definition", ["#ContextGraphSnapshot", "#ContextGraphResolution"])
def test_cue_exports_draft_2020_12_json_schema(definition: str) -> None:
    schema = export_json_schema(definition)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["type"] == "object"


@settings(
    max_examples=4,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(
    resolution=context_graph_resolutions(
        min_modules=2,
        max_modules=6,
        min_members=1,
        max_members=12,
    )
)
def test_generated_context_graphs_are_valid(resolution: dict[str, Any]) -> None:
    ContextGraphResolution.model_validate(resolution)
    result = cue_vet("#ContextGraphResolution", resolution)
    assert result.accepted, result.diagnostics


@pytest.mark.parametrize("property_id", PROPERTY_IDS)
@settings(
    max_examples=PROPERTY_EXAMPLES,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(data=st.data())
def test_declared_context_graph_property(
    property_id: str,
    data: Any,
) -> None:
    property_spec = CATALOG.properties[property_id]
    resolution = data.draw(
        context_graph_resolutions(
            min_modules=property_spec.generator.min_modules,
            max_modules=property_spec.generator.max_modules,
            min_members=property_spec.generator.min_members,
            max_members=property_spec.generator.max_members,
        ),
        label=property_id,
    )

    ContextGraphResolution.model_validate(resolution)
    mutated = mutate_for_property(resolution, property_spec)
    cue_result = cue_vet(property_spec.target_definition, mutated)
    pydantic_result = pydantic_accepts(property_spec.target_definition, mutated)

    assert_expected(
        cue_result.accepted,
        property_spec.expected.cue,
        oracle="cue",
        property_id=property_id,
    )
    assert_expected(
        pydantic_result,
        property_spec.expected.pydantic,
        oracle="pydantic",
        property_id=property_id,
    )
