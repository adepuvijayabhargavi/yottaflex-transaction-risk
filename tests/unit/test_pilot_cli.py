"""Flask CLI registration and argument validation for pilot commands."""

from __future__ import annotations


def test_pilot_cli_is_registered(app):
    result = app.test_cli_runner().invoke(args=["pilot", "--help"])

    assert result.exit_code == 0
    assert "generate" in result.output
    assert "reset" in result.output
    assert "verify" in result.output


def test_pilot_reset_requires_exactly_one_mode(app):
    runner = app.test_cli_runner()

    neither = runner.invoke(args=["pilot", "reset"])
    both = runner.invoke(args=["pilot", "reset", "--dry-run", "--confirm"])

    assert neither.exit_code == 2
    assert "exactly one" in neither.output
    assert both.exit_code == 2
    assert "exactly one" in both.output
