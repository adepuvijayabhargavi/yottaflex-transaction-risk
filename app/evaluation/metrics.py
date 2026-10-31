"""Isolated evaluation metric computation using separate eval connections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import DatabaseRole, database_url_for_role
from app.evaluation.ground_truth import GroundTruth
from app.models import Alert, RiskAssessment, Transaction


@dataclass(frozen=True, slots=True)
class EvaluationMetrics:
    """Evaluation metrics comparing core alerts against isolated ground truth."""

    model_version: str
    total_transactions: int
    ground_truth_positives: int
    ground_truth_negatives: int
    total_alerts: int
    true_positives: int
    false_positives: int
    false_negatives: int
    true_negatives: int
    precision: float
    recall: float
    f1_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_version": self.model_version,
            "total_transactions": self.total_transactions,
            "ground_truth_positives": self.ground_truth_positives,
            "ground_truth_negatives": self.ground_truth_negatives,
            "total_alerts": self.total_alerts,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "true_negatives": self.true_negatives,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1_score": round(self.f1_score, 4),
        }


def compute_evaluation_metrics(
    model_version: str = "v1.0.0",
    *,
    eval_session: Session | None = None,
    core_session: Session | None = None,
) -> EvaluationMetrics:
    """Compute precision, recall, and F1 by joining isolated result sets in Python."""
    # 1. Read ground truth from yottaflex_eval (using eval_session or YTF_EVAL_DATABASE_URL)
    gt_map: dict[str, bool] = {}

    if eval_session is not None:
        stmt_gt = select(GroundTruth.transaction_reference, GroundTruth.is_fraud)
        for ref, is_fraud in eval_session.execute(stmt_gt):
            gt_map[ref] = bool(is_fraud)
    else:
        eval_url = database_url_for_role(DatabaseRole.EVAL)
        assert eval_url is not None
        eval_engine = create_engine(eval_url, pool_pre_ping=True)
        with Session(eval_engine) as sess:
            stmt_gt = select(GroundTruth.transaction_reference, GroundTruth.is_fraud)
            for ref, is_fraud in sess.execute(stmt_gt):
                gt_map[ref] = bool(is_fraud)
        eval_engine.dispose()

    # 2. Read alerts for model_version from core schema (using core_session or YTF_EVAL_CORE_DATABASE_URL)
    alerted_refs: set[str] = set()

    if core_session is not None:
        stmt_alerts = (
            select(Transaction.transaction_reference)
            .join(Alert, Alert.transaction_id == Transaction.id)
            .join(RiskAssessment, Alert.assessment_id == RiskAssessment.id)
            .where(RiskAssessment.model_version == model_version)
        )
        alerted_refs = set(core_session.scalars(stmt_alerts))
    else:
        core_url = database_url_for_role(DatabaseRole.EVAL_CORE)
        assert core_url is not None
        core_engine = create_engine(core_url, pool_pre_ping=True)
        with Session(core_engine) as sess:
            stmt_alerts = (
                select(Transaction.transaction_reference)
                .join(Alert, Alert.transaction_id == Transaction.id)
                .join(RiskAssessment, Alert.assessment_id == RiskAssessment.id)
                .where(RiskAssessment.model_version == model_version)
            )
            alerted_refs = set(sess.scalars(stmt_alerts))
        core_engine.dispose()

    # 3. Join in Python and calculate metrics
    total_tx = len(gt_map)
    gt_pos = sum(1 for is_fraud in gt_map.values() if is_fraud)
    gt_neg = total_tx - gt_pos

    tp = sum(1 for ref, is_fraud in gt_map.items() if is_fraud and ref in alerted_refs)
    fp = sum(
        1 for ref, is_fraud in gt_map.items() if not is_fraud and ref in alerted_refs
    )
    fn = sum(
        1 for ref, is_fraud in gt_map.items() if is_fraud and ref not in alerted_refs
    )
    tn = sum(
        1
        for ref, is_fraud in gt_map.items()
        if not is_fraud and ref not in alerted_refs
    )

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (
        (2 * precision * recall) / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    return EvaluationMetrics(
        model_version=model_version,
        total_transactions=total_tx,
        ground_truth_positives=gt_pos,
        ground_truth_negatives=gt_neg,
        total_alerts=len(alerted_refs),
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        true_negatives=tn,
        precision=precision,
        recall=recall,
        f1_score=f1,
    )
