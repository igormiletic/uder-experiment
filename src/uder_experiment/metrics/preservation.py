"""Semantic preservation / precision / F1 / weighted information loss (spec Section 13.1-13.4)."""
from __future__ import annotations

from dataclasses import dataclass, field

from uder_experiment.metrics.features import SemanticFeature, extract_features, source_support_values
from uder_experiment.metrics.value_accuracy import values_equal


@dataclass
class FieldEvaluation:
    path: str
    weight: float
    required: bool
    expected_value: object
    actual_value: object
    correct: bool
    present_in_expected: bool
    present_in_actual: bool
    supported: bool  # used for precision / hallucination detection


@dataclass
class PreservationResult:
    preservation: float
    information_loss: float
    precision: float
    f1: float
    value_accuracy: float  # accuracy over the intersection of required, exact-comparable fields
    field_evaluations: list[FieldEvaluation] = field(default_factory=list)


def _safe_div(num: float, den: float) -> float:
    return num / den if den else 0.0


def evaluate_preservation(
    expected_canonical: dict,
    actual_canonical: dict,
    source_entity_properties: list[dict] | None = None,
) -> PreservationResult:
    expected_features = extract_features(expected_canonical)
    actual_features = extract_features(actual_canonical) if actual_canonical else {}
    support = source_support_values(source_entity_properties) if source_entity_properties else set()

    evaluations: list[FieldEvaluation] = []

    preserved_weight = 0.0
    expected_weight = 0.0
    for path, exp_f in expected_features.items():
        expected_weight += exp_f.weight
        act_f = actual_features.get(path)
        act_value = act_f.value if act_f else None
        correct = act_f is not None and values_equal(exp_f.value, act_value, exp_f.value_type)
        if correct:
            preserved_weight += exp_f.weight
        evaluations.append(FieldEvaluation(
            path=path, weight=exp_f.weight, required=exp_f.required,
            expected_value=exp_f.value, actual_value=act_value, correct=correct,
            present_in_expected=_is_present(exp_f), present_in_actual=act_f is not None and _is_present(act_f),
            supported=True,
        ))
    preservation = _safe_div(preserved_weight, expected_weight)

    supported_weight = 0.0
    output_weight = 0.0
    for path, act_f in actual_features.items():
        if not _is_present(act_f):
            continue  # a null/empty output field makes no claim, so it cannot hallucinate
        output_weight += act_f.weight
        exp_f = expected_features.get(path)
        matches_ground_truth = exp_f is not None and values_equal(exp_f.value, act_f.value, act_f.value_type)
        supported = matches_ground_truth or _in_support_set(act_f.value, support)
        if supported:
            supported_weight += act_f.weight
        if exp_f is None:
            evaluations.append(FieldEvaluation(
                path=path, weight=act_f.weight, required=False,
                expected_value=None, actual_value=act_f.value, correct=False,
                present_in_expected=False, present_in_actual=True, supported=supported,
            ))
    precision = _safe_div(supported_weight, output_weight)

    f1 = _safe_div(2 * precision * preservation, precision + preservation) if (precision + preservation) else 0.0

    required_evals = [e for e in evaluations if e.required and e.present_in_expected]
    value_accuracy = _safe_div(sum(1 for e in required_evals if e.correct), len(required_evals)) if required_evals else 1.0

    return PreservationResult(
        preservation=preservation, information_loss=1.0 - preservation,
        precision=precision, f1=f1, value_accuracy=value_accuracy,
        field_evaluations=evaluations,
    )


def _is_present(feat: SemanticFeature) -> bool:
    if feat.value is None:
        return False
    if feat.value_type == "set" and len(feat.value) == 0:
        return False
    return True


def _in_support_set(value, support: set[str]) -> bool:
    if isinstance(value, (set, frozenset)):
        return all(f"{scheme}".lower() in support or f"{val}".lower() in support for scheme, val in value) if value else True
    return str(value).strip().lower() in support
