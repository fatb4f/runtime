"""Additional assertion-defined graph mutations registered by the property catalog."""

from __future__ import annotations

from typing import Any

from context_workbook.context_graph_properties import MUTATORS, _first_key


def _unknown_namespace_module(value: dict[str, Any]) -> None:
    value["namespaces"][_first_key(value["namespaces"])]["moduleID"] = "module.missing"


def _unknown_member_module(value: dict[str, Any]) -> None:
    value["members"][_first_key(value["members"])]["moduleID"] = "module.missing"


def _unknown_evidence_subject(value: dict[str, Any]) -> None:
    item = value["evidence"][_first_key(value["evidence"])]
    item["subject"] = {"kind": "member", "id": "member.missing"}


def _unknown_evidence_producer(value: dict[str, Any]) -> None:
    item = value["evidence"][_first_key(value["evidence"])]
    item["producer"] = {"kind": "member", "id": "member.missing"}


def _unknown_selection_seed(value: dict[str, Any]) -> None:
    value["selection"]["seedEntities"][0] = {"kind": "member", "id": "member.missing"}


def _unknown_selection_relationship(value: dict[str, Any]) -> None:
    value["selection"]["relationshipIDs"] = ["relationship.missing"]


def _unknown_selection_evidence(value: dict[str, Any]) -> None:
    value["selection"]["evidenceIDs"] = ["evidence.missing"]


def register_additional_mutators() -> None:
    MUTATORS.update(
        {
            "unknown-namespace-module": _unknown_namespace_module,
            "unknown-member-module": _unknown_member_module,
            "unknown-evidence-subject": _unknown_evidence_subject,
            "unknown-evidence-producer": _unknown_evidence_producer,
            "unknown-selection-seed": _unknown_selection_seed,
            "unknown-selection-relationship": _unknown_selection_relationship,
            "unknown-selection-evidence": _unknown_selection_evidence,
        }
    )
