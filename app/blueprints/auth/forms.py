"""Authentication forms for analyst and supervisor login."""

from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Length


class LoginForm(FlaskForm):
    """Form used by analysts and risk reviewers to sign into the platform."""

    username = StringField(
        "Username or Email",
        validators=[
            DataRequired(message="Username or email is required."),
            Length(
                min=3,
                max=255,
                message="Username must be between 3 and 255 characters.",
            ),
        ],
        render_kw={
            "placeholder": "Enter username or email address",
            "autocomplete": "username",
            "autofocus": True,
            "class": "form-control",
        },
    )
    password = PasswordField(
        "Password",
        validators=[DataRequired(message="Password is required.")],
        render_kw={
            "placeholder": "Enter account password",
            "autocomplete": "current-password",
            "class": "form-control",
        },
    )
    remember_me = BooleanField(
        "Remember this workstation",
        render_kw={"class": "form-check-input"},
    )
    submit = SubmitField(
        "Sign In to Operations Console",
        render_kw={"class": "btn btn-primary w-100 py-2 fw-semibold"},
    )
