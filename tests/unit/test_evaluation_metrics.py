"""Unit tests for isolated evaluation metrics computation."""

from __future__ import annotations

from unittest.mock import MagicMock

from sqlalchemy.orm import Session

from app.evaluation.metrics import compute_evaluation_metrics


def test_compute_evaluation_metrics_math():
    # Mock ground truth query: 10 transactions (4 fraud, 6 non-fraud)
    mock_eval_session = MagicMock(spec=Session)
    mock_eval_session.execute.return_value = [
        ("TXN-001", True),  # TP
        ("TXN-002", True),  # TP
        ("TXN-003", True),  # TP
        ("TXN-004", True),  # FN
        ("TXN-005", False),  # FP
        ("TXN-006", False),  # TN
        ("TXN-007", False),  # TN
        ("TXN-008", False),  # TN
        ("TXN-009", False),  # TN
        ("TXN-010", False),  # TN
    ]

    # Mock core alerts query: TXN-001, TXN-002, TXN-003, TXN-005 have alerts
    mock_core_session = MagicMock(spec=Session)
    mock_core_session.scalars.return_value = [
        "TXN-001",
        "TXN-002",
        "TXN-003",
        "TXN-005",
    ]

    metrics = compute_evaluation_metrics(
        model_version="v1.0.0",
        eval_session=mock_eval_session,
        core_session=mock_core_session,
    )

    assert metrics.total_transactions == 10
    assert metrics.ground_truth_positives == 4
    assert metrics.ground_truth_negatives == 6
    assert metrics.total_alerts == 4
    assert metrics.true_positives == 3
    assert metrics.false_positives == 1
    assert metrics.false_negatives == 1
    assert metrics.true_negatives == 5

    # Precision = 3 / (3 + 1) = 0.75
    assert metrics.precision == 0.75

    # Recall = 3 / (3 + 1) = 0.75
    assert metrics.recall == 0.75

    # F1 = 2 * (0.75 * 0.75) / (0.75 + 0.75) = 0.75
    assert metrics.f1_score == 0.75

    as_dict = metrics.to_dict()
    assert as_dict["precision"] == 0.75
    assert as_dict["recall"] == 0.75
    assert as_dict["f1_score"] == 0.75
