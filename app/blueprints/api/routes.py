"""Versioned JSON API for alert review, investigation, and case management."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from functools import wraps
from typing import Any, TypeVar

from flask import Blueprint, jsonify, make_response, request
from flask_login import current_user
from flask_wtf.csrf import CSRFError, generate_csrf
from marshmallow import Schema
from marshmallow import ValidationError as SchemaValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.exceptions import BadRequest

from app.extensions import db
from app.models.enums import (
    AlertPriority,
    AlertStatus,
    CaseDecisionType,
    CaseNoteType,
    CasePriority,
    CaseStatus,
    RiskLevel,
    UserRole,
)
from app.schemas.api import (
    AlertAssignmentSchema,
    AlertLinkSchema,
    AlertListQuerySchema,
    CaseAssignmentSchema,
    CaseCreateSchema,
    CaseDecisionSchema,
    CaseListQuerySchema,
    CaseNoteSchema,
    CasePrioritySchema,
    CaseStatusSchema,
    EmptyBodySchema,
    ReasonSchema,
    TransactionHistoryQuerySchema,
    TransactionLookupQuerySchema,
)
from app.services.alerts import (
    acknowledge_alert,
    assign_alert,
    close_alert,
    dismiss_alert,
    get_alert_detail,
    list_alerts,
)
from app.services.cases import (
    REVIEW_ROLES,
    add_case_decision,
    add_case_note,
    assign_case,
    claim_case,
    create_case,
    get_case_detail,
    link_alert_to_case,
    list_cases,
    set_case_priority,
    transition_case,
    unlink_alert_from_case,
)
from app.services.transactions import (
    find_transaction_id,
    get_account_transaction_history,
    get_transaction_investigation,
)
from app.services.validation import ValidationError as WorkflowValidationError

from ..auth.security import role_required

api_bp = Blueprint("api", __name__, url_prefix="/api/v1")
T = TypeVar("T")

_CASE_FIELDS = (
    "id",
    "reference",
    "title",
    "description",
    "status",
    "priority",
    "assigned_to",
    "assigned_to_user_id",
    "opened_by",
    "opened_at",
    "closed_by",
    "closed_at",
    "is_closed",
)
_TRANSACTION_FIELDS = (
    "id",
    "reference",
    "type",
    "status",
    "amount",
    "formatted_amount",
    "currency",
    "occurred_at",
    "created_at",
    "description",
    "direction",
    "transfer_group_id",
)
_ACCOUNT_FIELDS = ("id", "type", "status", "currency")
_CUSTOMER_FIELDS = ("id", "reference", "name", "country_code", "risk_segment")
_EVIDENCE_FIELDS = {
    "amount",
    "threshold",
    "currency",
    "debit_account_id",
    "transaction_count",
    "window_minutes",
    "cluster_transaction_references",
    "device_id",
    "device_age_hours",
    "threshold_hours",
    "is_trusted",
    "first_seen_at",
    "transfer_group_id",
    "cycle_accounts",
    "cycle_length",
    "max_cycle_length",
    "duration_hours",
    "window_hours",
    "cycle_transaction_references",
    "merchant_id",
    "repeat_count",
    "snapshot_status",
    "dormant_days_threshold",
    "days_inactive",
    "is_dormant_snapshot",
    "is_inactive_prolonged",
}
_AUDIT_DETAIL_FIELDS = {
    "alert_ids",
    "alert_id",
    "alert_reference",
    "assignee_user_id",
    "previous_assignee_user_id",
    "priority",
    "previous_priority",
    "status",
    "previous_status",
    "reason",
    "note_type",
    "decision",
    "link_id",
}
_NOT_FOUND_CODES = {
    "CASE_ALERT_NOT_FOUND",
}
_HIDDEN_CASE_CODES = {
    "CASE_ALREADY_ASSIGNED",
    "CASE_ASSIGNMENT_REQUIRED",
    "CASE_MANAGER_REQUIRED",
}
_FORBIDDEN_CODES = {
    "CASE_MANAGER_REQUIRED",
    "CASE_PERMISSION_DENIED",
}
_CONFLICT_CODES = {
    "ALERT_ASSIGNMENT_TERMINAL",
    "ALERT_ASSIGNMENT_UNCHANGED",
    "ALERT_TRANSITION_INVALID",
    "CASE_ALERT_ALREADY_LINKED",
    "CASE_ALERT_STATUS_INVALID",
    "CASE_CLOSED",
    "CASE_REQUIRES_ACTIVE_ALERT",
    "CASE_TRANSITION_INVALID",
}


def _error(
    code: str,
    message: str,
    status: int,
    *,
    details: Any = None,
):
    payload: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        payload["details"] = details
    return jsonify({"error": payload}), status


def _api_role_required(*roles: UserRole):
    """Use the shared session authorization while normalizing API errors."""

    def decorator(view):
        guarded_view = role_required(*roles)(view)

        @wraps(view)
        def wrapped(*args, **kwargs):
            response = guarded_view(*args, **kwargs)
            if (
                isinstance(response, tuple)
                and len(response) == 2
                and response[1] in (401, 403)
            ):
                body = response[0].get_json(silent=True)
                if isinstance(body, dict):
                    code = body.get("error", "forbidden")
                    message = body.get("message", "Access denied.")
                    return _error(code, message, response[1])
            return response

        return wrapped

    return decorator


def _load_body(schema: Schema) -> tuple[dict[str, Any] | None, Any | None]:
    if not request.is_json:
        return None, _error(
            "unsupported_media_type",
            "Send a JSON request body with Content-Type: application/json.",
            415,
        )
    try:
        body = request.get_json()
    except BadRequest:
        return None, _error("invalid_json", "The JSON request body is malformed.", 400)
    if not isinstance(body, dict):
        return None, _error(
            "invalid_json", "The JSON request body must be an object.", 400
        )
    try:
        return schema.load(body), None
    except SchemaValidationError as exc:
        return None, _error(
            "validation_error",
            "The request contains invalid fields.",
            422,
            details=exc.messages,
        )


def _load_query(schema: Schema) -> tuple[dict[str, Any] | None, Any | None]:
    duplicate_keys = sorted(
        key for key in request.args if len(request.args.getlist(key)) > 1
    )
    if duplicate_keys:
        return None, _error(
            "validation_error",
            "Query parameters must not be repeated.",
            422,
            details={key: ["Parameter was repeated."] for key in duplicate_keys},
        )
    try:
        return schema.load(request.args.to_dict(flat=True)), None
    except SchemaValidationError as exc:
        return None, _error(
            "validation_error",
            "The query contains invalid fields.",
            422,
            details=exc.messages,
        )


def _pick(value: Any, fields: tuple[str, ...] | set[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {key: value[key] for key in fields if key in value}


def _safe_customer(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    return _pick(value, _CUSTOMER_FIELDS)


def _safe_account(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    account = _pick(value, _ACCOUNT_FIELDS)
    customer = _safe_customer(value.get("customer"))
    if customer is not None:
        account["customer"] = customer
    return account


def _safe_transaction(value: Any) -> dict[str, Any]:
    transaction = _pick(value, _TRANSACTION_FIELDS)
    for key in ("debit_account", "credit_account", "counterparty"):
        if key in value and value[key] is not None:
            transaction[key] = _safe_account(value[key])
    return transaction


def _safe_evidence(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    evidence: dict[str, Any] = {}
    for key in _EVIDENCE_FIELDS:
        item = value.get(key)
        if isinstance(item, list):
            scalars = [
                entry
                for entry in item[:100]
                if isinstance(entry, (str, int, float, bool))
            ]
            evidence[key] = scalars
        elif isinstance(item, (str, int, float, bool)):
            evidence[key] = item
    return evidence


def _safe_finding(value: Any) -> dict[str, Any]:
    finding = _pick(
        value,
        (
            "id",
            "rule_id",
            "rule_code",
            "rule_name",
            "score",
            "severity",
            "explanation",
            "created_at",
        ),
    )
    evidence = _safe_evidence(value.get("evidence"))
    if evidence:
        finding["evidence"] = evidence
    return finding


def _safe_assessment(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    assessment = _pick(
        value,
        ("id", "model_version", "score", "risk_level", "status", "assessed_at"),
    )
    explanation = value.get("explanation")
    if isinstance(explanation, str):
        assessment["explanation"] = explanation
    elif isinstance(explanation, Mapping) and isinstance(
        explanation.get("summary"), str
    ):
        assessment["explanation"] = {"summary": explanation["summary"]}
    if isinstance(value.get("findings"), list):
        assessment["findings"] = [
            _safe_finding(finding) for finding in value["findings"]
        ]
    return assessment


def _safe_alert(value: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    alert_source = value.get("alert")
    alert = _pick(
        alert_source,
        (
            "id",
            "reference",
            "status",
            "priority",
            "score",
            "summary",
            "created_at",
            "acknowledged_at",
            "closed_at",
            "assigned_to",
            "assigned_to_user_id",
        ),
    )
    if alert:
        details = (
            alert_source.get("details") if isinstance(alert_source, Mapping) else None
        )
        if isinstance(details, Mapping):
            safe_details = _pick(
                details,
                ("triggering_rule_code", "findings_count", "effective_threshold"),
            )
            evidence = _safe_evidence(details.get("evidence"))
            if evidence:
                safe_details["evidence"] = evidence
            if safe_details:
                alert["details"] = safe_details
        result["alert"] = alert
    if "transaction" in value:
        result["transaction"] = _safe_transaction(value["transaction"])
    if "customer" in value:
        result["customer"] = _safe_customer(value["customer"])
    if "assessment" in value:
        result["assessment"] = _safe_assessment(value["assessment"])
    if "triggering_rule" in value:
        result["triggering_rule"] = _pick(
            value["triggering_rule"],
            ("id", "code", "version", "name", "category", "severity"),
        )
    if "triggering_finding" in value and value["triggering_finding"] is not None:
        result["triggering_finding"] = _safe_finding(value["triggering_finding"])
        result["triggering_finding_id"] = value.get("triggering_finding_id")
    return result


def _safe_timeline_event(value: Any) -> dict[str, Any]:
    return _pick(value, ("occurred_at", "title", "summary", "source"))


def _safe_investigation(value: Mapping[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {
        "transaction": _safe_transaction(value["transaction"]),
        "merchant": (
            _pick(
                value.get("merchant"),
                ("name", "reference", "category", "country_code", "risk_level"),
            )
            if value.get("merchant") is not None
            else None
        ),
        "device": (
            _pick(
                value.get("device"),
                ("type", "first_seen_at", "last_seen_at", "trusted"),
            )
            if value.get("device") is not None
            else None
        ),
        "transfer_group": (
            _pick(
                value.get("transfer_group"),
                (
                    "id",
                    "reference",
                    "status",
                    "currency",
                    "expected_total",
                    "actual_total",
                    "reconciled_at",
                ),
            )
            if value.get("transfer_group") is not None
            else None
        ),
        "transfer_legs": [
            _safe_transaction(item) for item in value.get("transfer_legs", [])
        ],
        "transfer_legs_pagination": _pick(
            value.get("transfer_legs_pagination"),
            ("total", "shown", "limit", "truncated"),
        ),
        "assessments": [
            _safe_assessment(item) for item in value.get("assessments", [])
        ],
        "alerts": [
            _pick(
                item, ("id", "reference", "status", "priority", "summary", "created_at")
            )
            for item in value.get("alerts", [])
        ],
        "timeline": [_safe_timeline_event(item) for item in value.get("timeline", [])],
        "related_transactions": [
            _safe_transaction(item) for item in value.get("related_transactions", [])
        ],
        "account_histories": [],
    }
    for history in value.get("account_histories", []):
        output["account_histories"].append(
            {
                "account": _safe_account(history.get("account")),
                "transactions": [
                    _safe_transaction(item) for item in history.get("transactions", [])
                ],
            }
        )
    return output


def _safe_case_summary(value: Any) -> dict[str, Any]:
    return _pick(value, _CASE_FIELDS)


def _safe_case_detail(value: Mapping[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {"case": _safe_case_summary(value["case"])}
    output["links"] = [
        _pick(
            link,
            (
                "id",
                "alert_id",
                "alert_reference",
                "alert_summary",
                "alert_status",
                "transaction_id",
                "transaction_reference",
                "linked_by",
                "linked_at",
                "unlinked_by",
                "unlinked_at",
                "unlink_reason",
                "active",
            ),
        )
        for link in value.get("links", [])
    ]
    output["notes"] = [
        _pick(note, ("id", "type", "body", "author", "noted_at"))
        for note in value.get("notes", [])
    ]
    output["decisions"] = [
        _pick(
            decision,
            (
                "id",
                "type",
                "rationale",
                "decided_by",
                "decided_at",
                "alert_id",
                "alert_reference",
            ),
        )
        for decision in value.get("decisions", [])
    ]
    output["audit_events"] = []
    for event in value.get("audit_events", []):
        safe_event = _pick(
            event,
            ("event_type", "summary", "actor", "occurred_at"),
        )
        details = event.get("details")
        if isinstance(details, Mapping):
            safe_event["details"] = _pick(details, _AUDIT_DETAIL_FIELDS)
        output["audit_events"].append(safe_event)
    return output


def _workflow_status(exc: WorkflowValidationError) -> int:
    code = exc.issue.code
    if code in _NOT_FOUND_CODES or code.endswith("_NOT_FOUND"):
        return 404
    if code in _FORBIDDEN_CODES or code == "CASE_PERMISSION_DENIED":
        return 403
    if code in _CONFLICT_CODES or code.endswith("_UNCHANGED"):
        return 409
    return 422


def _workflow_error_response(exc: WorkflowValidationError):
    issue = exc.issue
    if issue.entity_type == "case" and issue.code in _HIDDEN_CASE_CODES:
        return _error("not_found", "The requested resource was not found.", 404)
    details = {"field": issue.field} if issue.field else None
    return _error(
        issue.code.lower(), issue.message, _workflow_status(exc), details=details
    )


def _execute_mutation(
    operation: Callable[[], T | None],
    serialize: Callable[[T], Any],
    *,
    success_status: int = 200,
):
    try:
        result = operation()
        if result is None:
            db.session.rollback()
            return _error("not_found", "The requested resource was not found.", 404)
        payload = serialize(result)
        db.session.commit()
    except WorkflowValidationError as exc:
        db.session.rollback()
        return _workflow_error_response(exc)
    except IntegrityError:
        db.session.rollback()
        return _error(
            "conflict",
            "The request conflicts with a concurrent or existing change.",
            409,
        )
    except SQLAlchemyError:
        db.session.rollback()
        raise
    return jsonify({"data": payload}), success_status


def _actor():
    return current_user._get_current_object()


@api_bp.errorhandler(CSRFError)
def handle_csrf_error(_exc: CSRFError):
    return _error(
        "csrf_failed",
        "A valid CSRF token is required for this request.",
        _exc.code or 400,
    )


@api_bp.get("/csrf-token")
@_api_role_required(*REVIEW_ROLES)
def csrf_token():
    """Return a session-bound CSRF token for authenticated browser clients."""

    response = make_response(jsonify({"data": {"csrf_token": generate_csrf()}}))
    response.headers["Cache-Control"] = "no-store"
    response.headers["Vary"] = "Cookie"
    return response


@api_bp.get("/alerts")
@_api_role_required(*REVIEW_ROLES)
def alerts_index():
    query, error = _load_query(AlertListQuerySchema())
    if error is not None:
        return error
    result = list_alerts(
        db.session,
        q=query["q"],
        priority=AlertPriority(query["priority"]) if query.get("priority") else None,
        status=AlertStatus(query["status"]) if query.get("status") else None,
        risk_level=RiskLevel(query["risk_level"]) if query.get("risk_level") else None,
        date_from=query.get("date_from"),
        date_to=query.get("date_to"),
        page=query["page"],
        per_page=query["per_page"],
    )
    return jsonify(
        {
            "data": [_safe_alert(item) for item in result["items"]],
            "pagination": result["pagination"],
        }
    )


@api_bp.get("/alerts/<int:alert_id>")
@_api_role_required(*REVIEW_ROLES)
def alert_detail(alert_id: int):
    result = get_alert_detail(db.session, alert_id)
    if result is None:
        return _error("not_found", "The alert was not found.", 404)
    return jsonify({"data": _safe_alert(result)})


@api_bp.post("/alerts/<int:alert_id>/assignment")
@_api_role_required(*REVIEW_ROLES)
def alert_assignment(alert_id: int):
    payload, error = _load_body(AlertAssignmentSchema())
    if error is not None:
        return error
    return _execute_mutation(
        lambda: assign_alert(
            db.session,
            alert_id,
            _actor(),
            payload["assignee_id"],
        ),
        lambda alert: _safe_alert(
            {
                "alert": {
                    "id": alert.id,
                    "reference": alert.alert_reference,
                    "status": alert.status.value,
                    "priority": alert.priority.value,
                    "assigned_to_user_id": alert.assigned_to_user_id,
                }
            }
        )["alert"],
    )


@api_bp.post("/alerts/<int:alert_id>/acknowledge")
@_api_role_required(*REVIEW_ROLES)
def alert_acknowledge(alert_id: int):
    payload, error = _load_body(EmptyBodySchema())
    if error is not None:
        return error
    del payload
    return _execute_mutation(
        lambda: acknowledge_alert(db.session, alert_id, _actor()),
        lambda alert: {
            "id": alert.id,
            "reference": alert.alert_reference,
            "status": alert.status.value,
            "acknowledged_at": (
                alert.acknowledged_at.isoformat() if alert.acknowledged_at else None
            ),
        },
    )


@api_bp.post("/alerts/<int:alert_id>/close")
@_api_role_required(*REVIEW_ROLES)
def alert_close(alert_id: int):
    payload, error = _load_body(ReasonSchema())
    if error is not None:
        return error
    return _execute_mutation(
        lambda: close_alert(db.session, alert_id, _actor(), payload["reason"]),
        lambda alert: {
            "id": alert.id,
            "reference": alert.alert_reference,
            "status": alert.status.value,
            "closed_at": alert.closed_at.isoformat() if alert.closed_at else None,
        },
    )


@api_bp.post("/alerts/<int:alert_id>/dismiss")
@_api_role_required(*REVIEW_ROLES)
def alert_dismiss(alert_id: int):
    payload, error = _load_body(ReasonSchema())
    if error is not None:
        return error
    return _execute_mutation(
        lambda: dismiss_alert(db.session, alert_id, _actor(), payload["reason"]),
        lambda alert: {
            "id": alert.id,
            "reference": alert.alert_reference,
            "status": alert.status.value,
            "closed_at": alert.closed_at.isoformat() if alert.closed_at else None,
        },
    )


@api_bp.get("/transactions")
@_api_role_required(*REVIEW_ROLES)
def transaction_lookup():
    query, error = _load_query(TransactionLookupQuerySchema())
    if error is not None:
        return error
    transaction_id = find_transaction_id(db.session, query["q"])
    if transaction_id is None:
        return _error("not_found", "The transaction was not found.", 404)
    result = get_transaction_investigation(db.session, transaction_id)
    if result is None:
        return _error("not_found", "The transaction was not found.", 404)
    return jsonify({"data": _safe_investigation(result)})


@api_bp.get("/transactions/<int:transaction_id>")
@_api_role_required(*REVIEW_ROLES)
def transaction_detail(transaction_id: int):
    result = get_transaction_investigation(db.session, transaction_id)
    if result is None:
        return _error("not_found", "The transaction was not found.", 404)
    return jsonify({"data": _safe_investigation(result)})


@api_bp.get("/accounts/<int:account_id>/transactions")
@_api_role_required(*REVIEW_ROLES)
def account_transactions(account_id: int):
    query, error = _load_query(TransactionHistoryQuerySchema())
    if error is not None:
        return error
    result = get_account_transaction_history(
        db.session,
        account_id,
        page=query["page"],
        per_page=query["per_page"],
    )
    if result is None:
        return _error("not_found", "The account was not found.", 404)
    return jsonify(
        {
            "data": {
                "account": _safe_account(result["account"]),
                "items": [_safe_transaction(item) for item in result["items"]],
            },
            "pagination": result["pagination"],
        }
    )


@api_bp.get("/cases")
@_api_role_required(*REVIEW_ROLES)
def cases_index():
    query, error = _load_query(CaseListQuerySchema())
    if error is not None:
        return error
    assigned_to = query["assigned_to"].strip()
    assigned_to_user_id = None
    unassigned_only = assigned_to.lower() == "unassigned"
    if assigned_to and not unassigned_only:
        try:
            assigned_to_user_id = int(assigned_to)
        except ValueError:
            return _error(
                "validation_error",
                "assigned_to must be a positive user ID or 'unassigned'.",
                422,
                details={"assigned_to": ["Not a valid user ID."]},
            )
        if assigned_to_user_id < 1:
            return _error(
                "validation_error",
                "assigned_to must be a positive user ID or 'unassigned'.",
                422,
                details={"assigned_to": ["Must be greater than zero."]},
            )
    result = list_cases(
        db.session,
        q=query["q"],
        status=CaseStatus(query["status"]) if query.get("status") else None,
        priority=CasePriority(query["priority"]) if query.get("priority") else None,
        assigned_to_user_id=assigned_to_user_id,
        unassigned_only=unassigned_only,
        visible_to_user_id=(
            current_user.id if current_user.role == UserRole.ANALYST else None
        ),
        page=query["page"],
        per_page=query["per_page"],
    )
    return jsonify(
        {
            "data": result["items"],
            "pagination": result["pagination"],
        }
    )


@api_bp.post("/cases")
@_api_role_required(*REVIEW_ROLES)
def case_create():
    payload, error = _load_body(CaseCreateSchema())
    if error is not None:
        return error
    return _execute_mutation(
        lambda: create_case(
            db.session,
            _actor(),
            title=payload["title"],
            description=payload["description"],
            priority=CasePriority(payload["priority"]),
            alert_ids=payload["alert_ids"],
        ),
        lambda case: {
            "id": case.id,
            "reference": case.case_reference,
            "title": case.title,
            "status": case.status.value,
            "priority": case.priority.value,
            "assigned_to_user_id": case.assigned_to_user_id,
        },
        success_status=201,
    )


@api_bp.get("/cases/<int:case_id>")
@_api_role_required(*REVIEW_ROLES)
def case_detail(case_id: int):
    result = get_case_detail(db.session, case_id)
    if result is None:
        return _error("not_found", "The case was not found.", 404)
    case = result["case"]
    if current_user.role == UserRole.ANALYST and case["assigned_to_user_id"] not in (
        None,
        current_user.id,
    ):
        return _error("not_found", "The case was not found.", 404)
    return jsonify({"data": _safe_case_detail(result)})


@api_bp.post("/cases/<int:case_id>/claim")
@_api_role_required(*REVIEW_ROLES)
def case_claim(case_id: int):
    payload, error = _load_body(EmptyBodySchema())
    if error is not None:
        return error
    del payload
    return _execute_mutation(
        lambda: claim_case(db.session, case_id, _actor()),
        lambda case: _safe_case_summary(
            {
                "id": case.id,
                "reference": case.case_reference,
                "title": case.title,
                "status": case.status.value,
                "priority": case.priority.value,
                "assigned_to_user_id": case.assigned_to_user_id,
            }
        ),
    )


@api_bp.post("/cases/<int:case_id>/assignment")
@_api_role_required(*REVIEW_ROLES)
def case_assignment(case_id: int):
    payload, error = _load_body(CaseAssignmentSchema())
    if error is not None:
        return error
    return _execute_mutation(
        lambda: assign_case(
            db.session,
            case_id,
            _actor(),
            payload["assignee_id"],
        ),
        lambda case: {
            "id": case.id,
            "assigned_to_user_id": case.assigned_to_user_id,
            "status": case.status.value,
        },
    )


@api_bp.post("/cases/<int:case_id>/priority")
@_api_role_required(*REVIEW_ROLES)
def case_priority(case_id: int):
    payload, error = _load_body(CasePrioritySchema())
    if error is not None:
        return error
    return _execute_mutation(
        lambda: set_case_priority(
            db.session,
            case_id,
            _actor(),
            CasePriority(payload["priority"]),
        ),
        lambda case: {
            "id": case.id,
            "priority": case.priority.value,
            "status": case.status.value,
        },
    )


@api_bp.post("/cases/<int:case_id>/status")
@_api_role_required(*REVIEW_ROLES)
def case_status(case_id: int):
    payload, error = _load_body(CaseStatusSchema())
    if error is not None:
        return error
    return _execute_mutation(
        lambda: transition_case(
            db.session,
            case_id,
            _actor(),
            CaseStatus(payload["status"]),
            payload["reason"],
        ),
        lambda case: {
            "id": case.id,
            "status": case.status.value,
            "closed_at": case.closed_at.isoformat() if case.closed_at else None,
        },
    )


@api_bp.post("/cases/<int:case_id>/alerts")
@_api_role_required(*REVIEW_ROLES)
def case_link_alert(case_id: int):
    payload, error = _load_body(AlertLinkSchema())
    if error is not None:
        return error
    alert_id = payload["alert_id"]
    return _execute_mutation(
        lambda: link_alert_to_case(db.session, case_id, alert_id, _actor()),
        lambda link: {
            "case_id": link.case_id,
            "alert_id": link.alert_id,
            "active": True,
        },
        success_status=201,
    )


@api_bp.post("/cases/<int:case_id>/alerts/<int:link_id>/unlink")
@_api_role_required(*REVIEW_ROLES)
def case_unlink_alert(case_id: int, link_id: int):
    payload, error = _load_body(ReasonSchema())
    if error is not None:
        return error
    return _execute_mutation(
        lambda: unlink_alert_from_case(
            db.session,
            case_id,
            link_id,
            _actor(),
            payload["reason"],
        ),
        lambda link: {
            "case_id": case_id,
            "link_id": link.id,
            "alert_id": link.alert_id,
            "active": False,
        },
    )


@api_bp.post("/cases/<int:case_id>/notes")
@_api_role_required(*REVIEW_ROLES)
def case_add_note(case_id: int):
    payload, error = _load_body(CaseNoteSchema())
    if error is not None:
        return error
    return _execute_mutation(
        lambda: add_case_note(
            db.session,
            case_id,
            _actor(),
            body=payload["body"],
            note_type=CaseNoteType(payload["note_type"]),
        ),
        lambda note: {
            "id": note.id,
            "case_id": note.case_id,
            "type": note.note_type.value,
            "noted_at": note.noted_at.isoformat(),
        },
        success_status=201,
    )


@api_bp.post("/cases/<int:case_id>/decisions")
@_api_role_required(*REVIEW_ROLES)
def case_add_decision(case_id: int):
    payload, error = _load_body(CaseDecisionSchema())
    if error is not None:
        return error
    return _execute_mutation(
        lambda: add_case_decision(
            db.session,
            case_id,
            _actor(),
            alert_id=payload["alert_id"],
            decision=CaseDecisionType(payload["decision"]),
            rationale=payload["rationale"],
        ),
        lambda decision: {
            "id": decision.id,
            "case_id": decision.case_id,
            "alert_id": decision.triggering_alert_id,
            "decision": decision.decision.value,
            "decided_at": decision.decided_at.isoformat(),
        },
        success_status=201,
    )
