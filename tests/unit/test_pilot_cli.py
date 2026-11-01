"""Flask CLI registration and argument validation for pilot commands."""

from __future__ import annotations

from types import SimpleNamespace


def test_pilot_cli_is_registered(app):
    result = app.test_cli_runner().invoke(args=["pilot", "--help"])

    assert result.exit_code == 0
    assert "generate" in result.output
    assert "reset" in result.output
    assert "verify" in result.output
    assert "export" in result.output


def test_pilot_reset_requires_exactly_one_mode(app):
    runner = app.test_cli_runner()

    neither = runner.invoke(args=["pilot", "reset"])
    both = runner.invoke(args=["pilot", "reset", "--dry-run", "--confirm"])

    assert neither.exit_code == 2
    assert "exactly one" in neither.output
    assert both.exit_code == 2
    assert "exactly one" in both.output


def test_pilot_export_cli_forwards_validated_options(app, monkeypatch):
    observed = {}

    def fake_export(**kwargs):
        observed.update(kwargs)
        return SimpleNamespace(
            to_dict=lambda: {
                "run_reference": kwargs["run_reference"],
                "formats": [kwargs["formats"]],
                "manifest": "manifests/EXPORT-1.json",
                "files": [],
            }
        )

    monkeypatch.setattr(
        "app.services.data_generator.runner.export_pilot_dataset",
        fake_export,
    )
    result = app.test_cli_runner().invoke(
        args=[
            "pilot",
            "export",
            "--profile",
            "pilot",
            "--seed",
            "20261022",
            "--run-reference",
            "EXPORT-1",
            "--format",
            "JSON",
        ]
    )

    assert result.exit_code == 0, result.output
    assert observed == {
        "profile_name": "pilot",
        "seed": 20261022,
        "run_reference": "EXPORT-1",
        "formats": "json",
    }
    assert '"run_reference": "EXPORT-1"' in result.output


def test_pilot_export_cli_rejects_unsupported_format(app):
    result = app.test_cli_runner().invoke(args=["pilot", "export", "--format", "yaml"])

    assert result.exit_code == 2
    assert "Invalid value" in result.output
