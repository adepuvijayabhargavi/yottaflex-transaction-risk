# Explainable Risk Scoring Engine and Detection Rules

Phase 5 implements the explainable transaction risk-scoring engine, rule evaluators, risk level classifications, and alert generation workflows.

## 1. Approved Active Risk Rules

The risk engine loads its active configuration dynamically from the `yottaflex.risk_rules` database table using `YTF_RISK_DATABASE_URL`. The six approved risk rules are:

| Code | Runtime Weight | Severity | Time Window | Detection Condition & Parameters |
|---|:---:|:---:|---|---|
| `HIGH_TRANSACTION_VELOCITY` | **20** | `HIGH` | 60 min | Debit account has &ge; 4 outgoing transactions within a 60-minute window cluster (`transaction_count: 4`, `window_minutes: 60`). |
| `NEW_DEVICE_ACTIVITY` | **18** | `HIGH` | 24 hrs | Transaction device is untrusted (`is_trusted is False`) and was first registered less than 24 hours prior (`device_age_hours: 24`, `require_untrusted: true`). |
| `CIRCULAR_FUND_TRANSFER` | **30** | `CRITICAL` | 24 hrs | Internal transfer participating in a closed loop of transfer legs ($A \to B \to C \to A$) within 24 hours and cycle length &le; 4 (`window_hours: 24`, `max_cycle_length: 4`). |
| `DORMANT_ACCOUNT_REACTIVATION` | **22** | `HIGH` | 90 days | Debit account was in status `DORMANT` at transaction time or had no outgoing transactions for &ge; 90 days (`dormant_days: 90`). |
| `HIGH_VALUE_TRANSACTION` | **20** | `HIGH` | — | Transaction amount &ge; $50,000.00 USD (`amount_threshold: 50000`, `currency: "USD"`). |
| `REPEATED_TRANSACTIONS` | **15** | `MEDIUM` | 30 min | Same debit account, merchant, and amount repeating &ge; 3 times within 30 minutes (`repeat_count: 3`, `window_minutes: 30`). |

> [!NOTE]
> **Authoritative Weights Clarification**:
> The active database weights total 125 across the 6 approved rules. These weights are calibrated in the live MySQL schema to prevent score saturation at the 100-cap and preserve the verified baseline checksums. Database rows 7–12 (`RAPID_PASS_THROUGH`, etc.) are unutilized placeholders from the initial seed and are excluded from the active evaluation scope.

---

## 2. Score Calculation & Risk Levels

### Composite Scoring
When a transaction is evaluated against all active rules:
* Each matching rule produces a `RiskFinding` containing rule code, weight score, severity, explanation, and structured evidence.
* The composite transaction score is the sum of all matching finding scores, capped at 100:
  $$\text{score} = \min\left(\sum_{f \in \text{findings}} f.\text{score}, 100\right)$$
* If no rules trigger, the transaction receives a score of 0.

### Risk Level Tiers

| Score Range | Risk Level | Alerting Status | Description |
|:---:|:---:|:---:|---|
| **0 – 39** | `RiskLevel.LOW` | Non-Alerting | Standard, low-risk transaction below the production alert threshold. |
| **40 – 59** | `RiskLevel.MEDIUM` | **Alerting** | Meets or exceeds the production threshold (40). Triggers an alert with `AlertPriority.MEDIUM`. |
| **60 – 79** | `RiskLevel.HIGH` | **Alerting** | Significant suspicious signals. Triggers an alert with `AlertPriority.HIGH`. |
| **80 – 100** | `RiskLevel.CRITICAL` | **Alerting** | Severe risk. Triggers an alert with `AlertPriority.CRITICAL`. |

> [!IMPORTANT]
> **Critical Finding Elevation**:
> If any triggered finding has `severity == RiskSeverity.CRITICAL` (e.g. `CIRCULAR_FUND_TRANSFER`), the transaction assessment is automatically elevated to `RiskLevel.CRITICAL` regardless of whether its numeric score reached 80, and an alert is generated with `AlertPriority.CRITICAL`.

---

## 3. Alert Generation Logic

An `Alert` is generated for a transaction if and only if:
$$\text{composite\_score} \ge \text{threshold} \quad \lor \quad \exists f \in \text{findings} \text{ such that } f.\text{severity} == \text{RiskSeverity.CRITICAL}$$

* **Production Threshold**: `YTF_ALERT_THRESHOLD = 40` (configured via `.env` and `config.py`).
* **1-to-1 Finding Linkage**: Each alert is linked to the primary triggering finding (highest severity, then highest score). The unique constraint `uq_alerts_finding_id` is enforced.
* **Alert Priority Mapping (`v1.0.1`)**: Mapped directly from the assessment's risk level (`AlertPriority(assessment.risk_level.value)`), aligning alert triage urgency with the composite score tier:
  - `RiskLevel.MEDIUM` (Score 40–59) $\to$ `AlertPriority.MEDIUM`
  - `RiskLevel.HIGH` (Score 60–79) $\to$ `AlertPriority.HIGH`
  - `RiskLevel.CRITICAL` (Score 80–100 or critical finding elevation) $\to$ `AlertPriority.CRITICAL`
* **Historical Model Versioning (`v1.0.0`)**: In `v1.0.0`, alert priority was mapped from the finding's configured severity (`primary.severity.value`), assigning `AlertPriority.HIGH` to medium-scoring transactions. Because `ytf_risk` is an immutable, append-only database role (`SELECT, INSERT` only per `docs/architecture.md`), `v1.0.0` records are preserved as immutable historical audit data, and `v1.0.1` represents the current production baseline.
* **Experimental CLI Override**: Supports `--threshold <int>` (e.g. `--threshold 15`) for pilot sensitivity analysis. Lowering the threshold increases sensitivity to low-weight individual patterns but may increase false positives, and is explicitly reserved for experimental benchmarking.

---

## 4. Idempotency and Rerun Safety

* **Unique Assessment Constraint**: `risk_assessments(transaction_id, model_version)` ensures one assessment per transaction per model version.
* **Unique Finding Constraint**: `risk_findings(assessment_id, rule_id)` prevents duplicate findings inside an assessment.
* **Unique Alert Constraint**: `alerts(finding_id)` prevents duplicate alerts for the same finding.
* **Safe Rerun Behavior**: The batch evaluator queries existing assessments before inserting. If an assessment exists for `(transaction_id, model_version)`, it is skipped without error. Duplicate key collisions are handled gracefully.

---

## 5. CLI Commands

### 1. Batch Evaluation
```powershell
# Evaluate transactions with production default threshold (40)
.\.venv\Scripts\flask.exe risk evaluate --model-version v1.0.1

# Evaluate with an experimental threshold override for pilot benchmarking
.\.venv\Scripts\flask.exe risk evaluate --model-version v1.0.0-threshold15 --threshold 15
```

### 2. Status Inspection
```powershell
.\.venv\Scripts\flask.exe risk status --model-version v1.0.1
```
Displays count of assessed transactions, total findings, total alerts, and breakdown by risk levels and alert priorities.

### 3. Isolated Performance Metrics (Evaluation Workflow)
```powershell
.\.venv\Scripts\flask.exe risk evaluate-metrics --model-version v1.0.1
```
Reads ground truth via `YTF_EVAL_DATABASE_URL` and core alerts via `YTF_EVAL_CORE_DATABASE_URL`. Computes and reports:
* Total alerts generated
* True Positives (TP)
* False Positives (FP)
* False Negatives (FN)
* True Negatives (TN)
* Precision, Recall, and F1 score
