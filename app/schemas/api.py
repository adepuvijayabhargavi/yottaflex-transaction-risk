"""Strict request schemas for the versioned JSON API."""

from __future__ import annotations

from marshmallow import RAISE, Schema, fields, validate

from app.models.enums import (
    AlertPriority,
    AlertStatus,
    CaseDecisionType,
    CaseNoteType,
    CasePriority,
    CaseStatus,
    RiskLevel,
)


def _enum_values(enum_type: type) -> list[str]:
    return [member.value for member in enum_type]


class StrictSchema(Schema):
    class Meta:
        unknown = RAISE


class PaginationQuerySchema(StrictSchema):
    page = fields.Integer(load_default=1, validate=validate.Range(min=1))
    per_page = fields.Integer(
        load_default=20,
        validate=validate.Range(min=1, max=100),
    )


class AlertListQuerySchema(PaginationQuerySchema):
    q = fields.String(load_default="", validate=validate.Length(max=100))
    priority = fields.String(validate=validate.OneOf(_enum_values(AlertPriority)))
    status = fields.String(validate=validate.OneOf(_enum_values(AlertStatus)))
    risk_level = fields.String(validate=validate.OneOf(_enum_values(RiskLevel)))
    date_from = fields.Date()
    date_to = fields.Date()


class CaseListQuerySchema(PaginationQuerySchema):
    q = fields.String(load_default="", validate=validate.Length(max=100))
    status = fields.String(validate=validate.OneOf(_enum_values(CaseStatus)))
    priority = fields.String(validate=validate.OneOf(_enum_values(CasePriority)))
    assigned_to = fields.String(load_default="", validate=validate.Length(max=20))


class TransactionHistoryQuerySchema(PaginationQuerySchema):
    pass


class TransactionLookupQuerySchema(StrictSchema):
    q = fields.String(required=True, validate=validate.Length(min=1, max=40))


class AlertAssignmentSchema(StrictSchema):
    assignee_id = fields.Integer(
        allow_none=True, required=True, validate=validate.Range(min=1)
    )


class ReasonSchema(StrictSchema):
    reason = fields.String(required=True, validate=validate.Length(min=1, max=500))


class CaseCreateSchema(StrictSchema):
    title = fields.String(required=True, validate=validate.Length(min=1, max=200))
    description = fields.String(
        allow_none=True, load_default=None, validate=validate.Length(max=5000)
    )
    priority = fields.String(
        load_default=CasePriority.MEDIUM.value,
        validate=validate.OneOf(_enum_values(CasePriority)),
    )
    alert_ids = fields.List(
        fields.Integer(validate=validate.Range(min=1)),
        required=True,
        validate=validate.Length(min=1, max=100),
    )


class CaseAssignmentSchema(StrictSchema):
    assignee_id = fields.Integer(
        allow_none=True, required=True, validate=validate.Range(min=1)
    )


class CasePrioritySchema(StrictSchema):
    priority = fields.String(
        required=True, validate=validate.OneOf(_enum_values(CasePriority))
    )


class CaseStatusSchema(StrictSchema):
    status = fields.String(
        required=True, validate=validate.OneOf(_enum_values(CaseStatus))
    )
    reason = fields.String(load_default="", validate=validate.Length(max=500))


class AlertLinkSchema(StrictSchema):
    alert_id = fields.Integer(required=True, validate=validate.Range(min=1))


class CaseNoteSchema(StrictSchema):
    body = fields.String(required=True, validate=validate.Length(min=1, max=5000))
    note_type = fields.String(
        load_default=CaseNoteType.INVESTIGATION.value,
        validate=validate.OneOf(_enum_values(CaseNoteType)),
    )


class CaseDecisionSchema(StrictSchema):
    alert_id = fields.Integer(required=True, validate=validate.Range(min=1))
    decision = fields.String(
        required=True,
        validate=validate.OneOf(_enum_values(CaseDecisionType)),
    )
    rationale = fields.String(required=True, validate=validate.Length(min=1, max=5000))


class EmptyBodySchema(StrictSchema):
    pass
