"""Deterministic, validation-only diagnosis for optimization candidates."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

DIAGNOSIS_POLICY_VERSION = "validation_diagnosis_v1"


class DiagnosisCode(StrEnum):
    UNSTABLE_MODEL = "UNSTABLE_MODEL"
    FREE_RUN_UNDEFINED = "FREE_RUN_UNDEFINED"
    INSUFFICIENT_EXCITATION = "INSUFFICIENT_EXCITATION"


@dataclass(frozen=True)
class CandidateRejectionEvidence:
    """Compact evidence for one structure rejected by an existing hard gate."""

    code: DiagnosisCode
    structure: dict[str, Any]
    stable: bool | None = None
    max_pole_modulus: float | None = None
    free_run_metric_finite: bool | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "structure": dict(self.structure),
            "stable": self.stable,
            "max_pole_modulus": self.max_pole_modulus,
            "free_run_metric_finite": self.free_run_metric_finite,
        }


@dataclass(frozen=True)
class ValidationDiagnosis:
    policy_version: str
    codes: tuple[DiagnosisCode, ...]
    evidence: dict[str, Any]

    def to_metrics(self) -> dict[str, Any]:
        return {
            "diagnosis_policy_version": self.policy_version,
            "diagnosis_codes": [code.value for code in self.codes],
            "diagnosis_evidence": dict(self.evidence),
        }

    def to_payload(self) -> dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "codes": [code.value for code in self.codes],
            "evidence": dict(self.evidence),
        }


def rejection_from_objective(
    *,
    reason: object,
    structure: Mapping[str, Any],
    stable: bool,
    max_pole_modulus: float | None,
    free_run_fit: float | None,
) -> CandidateRejectionEvidence | None:
    """Translate only the two existing objective hard gates into stable evidence."""

    if reason == "unstable":
        code = DiagnosisCode.UNSTABLE_MODEL
    elif reason == "free_run_undefined":
        code = DiagnosisCode.FREE_RUN_UNDEFINED
    else:
        return None
    return CandidateRejectionEvidence(
        code=code,
        structure=dict(structure),
        stable=False if code is DiagnosisCode.UNSTABLE_MODEL else stable,
        max_pole_modulus=_finite_or_none(max_pole_modulus),
        free_run_metric_finite=(
            False if code is DiagnosisCode.FREE_RUN_UNDEFINED else _is_finite(free_run_fit)
        ),
    )


def rejection_provenance(
    rejections: Sequence[CandidateRejectionEvidence],
) -> dict[str, Any] | None:
    """Aggregate structure rejections without storing repetitive per-fit payloads."""

    if not rejections:
        return None
    counts = Counter(item.code.value for item in rejections)
    examples: dict[str, dict[str, Any]] = {}
    for item in rejections:
        examples.setdefault(item.code.value, item.to_payload())
    return {
        "rejected_structure_count": len(rejections),
        "reason_counts": dict(counts),
        "examples": list(examples.values()),
    }


def diagnose_validation_candidate(
    *,
    validation_feedback: Mapping[str, Any] | None,
    selection_provenance: Mapping[str, Any] | None,
    objective_components: Mapping[str, Any] | None,
    candidate_rejections: Sequence[CandidateRejectionEvidence] = (),
) -> ValidationDiagnosis:
    """Return stable codes from validation evidence; Test data is not an accepted input."""

    codes: set[DiagnosisCode] = {item.code for item in candidate_rejections}
    evidence: dict[str, Any] = {}
    summary = _mapping(validation_feedback, "summary")
    free_run = _mapping(validation_feedback, "free_run")

    stable = summary.get("stable")
    stability_gate = (objective_components or {}).get("stability_gate")
    if stable is False or stability_gate is False or DiagnosisCode.UNSTABLE_MODEL in codes:
        codes.add(DiagnosisCode.UNSTABLE_MODEL)
        evidence[DiagnosisCode.UNSTABLE_MODEL.value] = {
            "stable": False,
            "max_pole_modulus": _finite_or_none(summary.get("max_pole_modulus")),
            "rejected_structure_count": sum(
                item.code is DiagnosisCode.UNSTABLE_MODEL for item in candidate_rejections
            ),
        }

    if "fit" in free_run and not _is_finite(free_run.get("fit")):
        codes.add(DiagnosisCode.FREE_RUN_UNDEFINED)
    if DiagnosisCode.FREE_RUN_UNDEFINED in codes:
        evidence[DiagnosisCode.FREE_RUN_UNDEFINED.value] = {
            "free_run_metric_finite": False,
            "rejected_structure_count": sum(
                item.code is DiagnosisCode.FREE_RUN_UNDEFINED for item in candidate_rejections
            ),
        }

    shortfall = summary.get("excitation_shortfall")
    excitation_satisfied = (selection_provenance or {}).get("excitation_satisfied")
    if excitation_satisfied is False or (
        isinstance(shortfall, Mapping) and bool(shortfall)
    ):
        codes.add(DiagnosisCode.INSUFFICIENT_EXCITATION)
        evidence[DiagnosisCode.INSUFFICIENT_EXCITATION.value] = {
            "excitation_satisfied": excitation_satisfied,
            "excitation_shortfall": dict(shortfall) if isinstance(shortfall, Mapping) else {},
            "persistent_excitation_order": dict(
                (selection_provenance or {}).get("persistent_excitation_order", {})
            ),
            "required_excitation_order": dict(
                (selection_provenance or {}).get("required_excitation_order", {})
            ),
        }

    ordered = tuple(code for code in DiagnosisCode if code in codes)
    return ValidationDiagnosis(
        policy_version=DIAGNOSIS_POLICY_VERSION,
        codes=ordered,
        evidence=evidence,
    )


def _mapping(parent: Mapping[str, Any] | None, key: str) -> Mapping[str, Any]:
    value = (parent or {}).get(key)
    return value if isinstance(value, Mapping) else {}


def _is_finite(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _finite_or_none(value: object) -> float | None:
    return float(value) if _is_finite(value) else None
