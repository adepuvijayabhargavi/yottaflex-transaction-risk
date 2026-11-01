# Versioned Operations API

The authenticated JSON API is available under `/api/v1`. It uses the same
Flask-Login session cookie and application database session as the web
application. It does not issue API tokens or JWTs. All endpoints require an
active analyst, supervisor, or admin session.

## Session and CSRF

For browser clients, first sign in through the existing web login. Fetch a
session-bound CSRF token and send it as `X-CSRFToken` on every `POST`:

```http
GET /api/v1/csrf-token
Cookie: session=...
```

```json
{"data":{"csrf_token":"..."}}
```

The token response is marked `Cache-Control: no-store`. Mutations are not
exempt from the application's global CSRF middleware. Read endpoints do not
require a CSRF header.

## Response conventions

Successful single-resource responses use `{"data": ...}`. Collection responses
use `{"data": [...], "pagination": {...}}`. Errors use:

```json
{
  "error": {
    "code": "validation_error",
    "message": "The request contains invalid fields.",
    "details": {"status": ["Must be one of: OPEN, IN_REVIEW, ESCALATED, CLOSED."]}
  }
}
```

Validation errors return 422, malformed JSON returns 400, an unsupported body
media type returns 415, missing or hidden resources return 404, permission
failures return 403, state conflicts return 409, and missing authentication
returns 401. Page size is limited to 100. Unknown request fields and query
parameters are rejected. Responses use explicit field allowlists and omit
customer email/phone, full account numbers, account balances, device
fingerprints, and unapproved evidence fields.

## Alerts

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/alerts` | Filter and page alerts with `q`, `priority`, `status`, `risk_level`, `date_from`, `date_to`, `page`, and `per_page`. |
| GET | `/alerts/{alert_id}` | Retrieve alert and stored assessment/finding context. |
| POST | `/alerts/{alert_id}/assignment` | Assign or unassign an alert. |
| POST | `/alerts/{alert_id}/acknowledge` | Acknowledge an open alert. Send `{}`. |
| POST | `/alerts/{alert_id}/close` | Close an open or acknowledged alert with a reason. |
| POST | `/alerts/{alert_id}/dismiss` | Dismiss an open or acknowledged alert with a reason. |

Assignment request:

```json
{"assignee_id": 12}
```

Use `{"assignee_id": null}` to unassign. Close and dismiss requests use
`{"reason":"Reviewed and resolved"}`. Alert mutations preserve existing
workflow validation and append the same audit events as the web application.

## Transaction investigation

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/transactions?q={reference-or-id}` | Find an exact transaction reference or numeric transaction ID. |
| GET | `/transactions/{transaction_id}` | Read stored transaction investigation context. |
| GET | `/accounts/{account_id}/transactions?page=1&per_page=20` | Read a stable, paginated account transaction history. |

Investigation endpoints are read-only and use stored application records. They
do not rerun risk assessments or access evaluation or ground-truth databases.
Transfer legs are capped at 100 and account-history page size at 100.

## Cases

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/cases` | Filter and page visible cases with `q`, `status`, `priority`, `assigned_to`, `page`, and `per_page`. |
| POST | `/cases` | Create a case and link one or more eligible alerts. |
| GET | `/cases/{case_id}` | Retrieve case, retained alert-link history, notes, decisions, and audit history. |
| POST | `/cases/{case_id}/claim` | Claim an unassigned case. Send `{}`. |
| POST | `/cases/{case_id}/assignment` | Manager assignment or unassignment. |
| POST | `/cases/{case_id}/priority` | Manager priority change. |
| POST | `/cases/{case_id}/status` | Apply an allowed case status transition. |
| POST | `/cases/{case_id}/alerts` | Link an eligible alert. |
| POST | `/cases/{case_id}/alerts/{link_id}/unlink` | Soft-unlink an active alert link with a reason. |
| POST | `/cases/{case_id}/notes` | Append a note. |
| POST | `/cases/{case_id}/decisions` | Append a decision for an actively linked alert. |

Create request:

```json
{
  "title": "Review repeated transfers",
  "description": "Investigate the linked alerts.",
  "priority": "HIGH",
  "alert_ids": [25, 26]
}
```

An alert can have only one active case link and must be OPEN or ACKNOWLEDGED
when newly linked. A case must retain at least one active alert. Case statuses
follow the existing state machine: OPEN may move to IN_REVIEW, ESCALATED, or
CLOSED; IN_REVIEW may move to OPEN, ESCALATED, or CLOSED; ESCALATED may move
to IN_REVIEW or CLOSED; CLOSED is terminal. Escalation and closure require a
reason.

Analysts can create cases, see cases assigned to them or unassigned, claim
unassigned cases, and work on cases they are assigned. Supervisors and admins
can oversee all cases and manage assignments, priorities, escalations, and
closures. Attempts to access a case assigned to another analyst return 404.
Every successful case mutation and alert workflow mutation records its audit
event in the same application database transaction.

## Storage and data boundaries

The API reuses the configured `db.session` and existing alert, transaction, and
case services. It introduces no schema migration, database URL fallback,
alternate database session, or new authentication mechanism. Transaction
investigation and all API reads leave stored risk findings and history
unchanged.
