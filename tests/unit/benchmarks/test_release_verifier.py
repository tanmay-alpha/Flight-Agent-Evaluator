"""Unit tests for the ReleaseVerifier engine."""

from __future__ import annotations

from flight_agent_evaluator.benchmarks.release_verifier import (
    ReleaseCheckItem,
    ReleaseVerificationReport,
    ReleaseVerifier,
)


def test_release_verifier_full_run():
    verifier = ReleaseVerifier()
    report = verifier.verify_installed_release()
    assert isinstance(report, ReleaseVerificationReport)
    assert report.valid is True
    assert report.total_checks >= 6
    assert report.passed_checks == report.total_checks
    assert report.failed_checks == 0
    assert len(report.checks) >= 6

    d = report.to_dict()
    assert d["valid"] is True
    assert d["passed_checks"] == d["total_checks"]
    assert "checks" in d


def test_release_check_item_dataclass():
    item = ReleaseCheckItem(
        check_id="TEST-01",
        description="Sample check",
        passed=True,
        details="All ok",
    )
    assert item.check_id == "TEST-01"
    assert item.passed is True
