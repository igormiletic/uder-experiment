import copy

from uder_experiment.metrics.calibration import brier_score, expected_calibration_error, confidence_correctness_correlation
from uder_experiment.metrics.consistency import check_invoice_consistency
from uder_experiment.metrics.preservation import evaluate_preservation
from conftest import make_scenario, render_all


def _gt():
    scenario = make_scenario("medium", index=11)
    return render_all(scenario)["ground_truth"]


def test_perfect_transformation_gives_preservation_1_and_loss_0():
    gt = _gt()
    pr = evaluate_preservation(gt, copy.deepcopy(gt))
    assert pr.preservation == 1.0
    assert pr.information_loss == 0.0
    assert pr.precision == 1.0
    assert pr.f1 == 1.0


def test_empty_transformation_gives_high_information_loss():
    gt = _gt()
    pr = evaluate_preservation(gt, {})
    assert pr.preservation == 0.0
    assert pr.information_loss == 1.0


def test_incorrect_required_field_has_greater_weighted_impact_than_optional():
    gt = _gt()
    corrupt_required = copy.deepcopy(gt)
    corrupt_required["invoice"]["financialSummary"]["netAmount"] += 500.0

    corrupt_optional = copy.deepcopy(gt)
    corrupt_optional["invoice"]["payment"]["reference"] = "SOMETHING-ELSE"

    pr_required = evaluate_preservation(gt, corrupt_required)
    pr_optional = evaluate_preservation(gt, corrupt_optional)
    assert pr_required.information_loss > pr_optional.information_loss


def test_hallucinated_field_reduces_precision():
    gt = _gt()
    hallucinated = copy.deepcopy(gt)
    hallucinated["invoice"]["commercialContext"]["contractReference"] = "FABRICATED-XYZ"
    pr = evaluate_preservation(gt, hallucinated, source_entity_properties=[])
    assert pr.precision < 1.0


def test_brier_score_zero_for_perfect_confidence():
    assert brier_score([1.0, 1.0, 0.0, 0.0], [1, 1, 0, 0]) == 0.0


def test_brier_score_positive_for_overconfident_wrong_prediction():
    assert brier_score([0.99], [0]) > 0.9


def test_ece_zero_for_perfectly_calibrated_synthetic_predictions():
    # 10 predictions at confidence 0.7, 7 correct -> perfectly calibrated in that bin
    confidences = [0.7] * 10
    correctness = [1] * 7 + [0] * 3
    result = expected_calibration_error(confidences, correctness, n_bins=10)
    assert abs(result.ece) < 1e-9


def test_ece_positive_for_miscalibrated_predictions():
    confidences = [0.99] * 10
    correctness = [1] * 3 + [0] * 7
    result = expected_calibration_error(confidences, correctness, n_bins=10)
    assert result.ece > 0.5


def test_confidence_correctness_correlation_positive_when_aligned():
    confidences = [0.1, 0.3, 0.5, 0.7, 0.9, 0.95]
    correctness = [0, 0, 0, 1, 1, 1]
    result = confidence_correctness_correlation(confidences, correctness)
    assert result.pearson > 0.5
    assert result.spearman > 0.5


def test_arithmetic_consistency_perfect_invoice_passes_all_checks():
    gt = _gt()
    report = check_invoice_consistency(gt)
    assert report.all_passed
    assert report.score == 1.0


def test_arithmetic_consistency_detects_broken_totals():
    gt = _gt()
    broken = copy.deepcopy(gt)
    broken["invoice"]["financialSummary"]["grossAmount"] += 1000.0
    report = check_invoice_consistency(broken)
    assert not report.all_passed
    assert report.score < 1.0
