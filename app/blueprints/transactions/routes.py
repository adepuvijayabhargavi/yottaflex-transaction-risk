"""Read-only transaction investigation routes."""

from __future__ import annotations

from flask import Blueprint, abort, redirect, render_template, request, url_for

from app.extensions import db
from app.models.enums import UserRole
from app.services.transactions import (
    find_transaction_id,
    get_account_transaction_history,
    get_transaction_investigation,
)

from ..auth.security import role_required

transactions_bp = Blueprint("transactions", __name__, url_prefix="/transactions")


@transactions_bp.get("/")
@role_required(UserRole.ANALYST, UserRole.SUPERVISOR, UserRole.ADMIN)
def index():
    """Find a transaction by exact reference or numeric ID."""

    query = request.args.get("q", "").strip()[:40]
    if query:
        transaction_id = find_transaction_id(db.session, query)
        if transaction_id is not None:
            return redirect(
                url_for("transactions.detail", transaction_id=transaction_id)
            )
    return render_template(
        "transactions/detail.html",
        view_mode="search",
        query=query,
        no_results=bool(query),
    )


@transactions_bp.get("/<int:transaction_id>")
@role_required(UserRole.ANALYST, UserRole.SUPERVISOR, UserRole.ADMIN)
def detail(transaction_id: int):
    """Render a read-only investigation of one transaction."""

    investigation = get_transaction_investigation(db.session, transaction_id)
    if investigation is None:
        abort(404)
    return render_template(
        "transactions/detail.html",
        view_mode="transaction",
        investigation=investigation,
    )


@transactions_bp.get("/accounts/<int:account_id>")
@role_required(UserRole.ANALYST, UserRole.SUPERVISOR, UserRole.ADMIN)
def account_history(account_id: int):
    """Render paginated transactions involving an account."""

    history = get_account_transaction_history(
        db.session,
        account_id,
        page=request.args.get("page", 1),
        per_page=request.args.get("per_page", 20),
    )
    if history is None:
        abort(404)
    return render_template(
        "transactions/detail.html",
        view_mode="account_history",
        history=history,
    )
