"""Typed errors for the judge system."""

from __future__ import annotations


class JudgeError(Exception):
    """Base exception for all judge errors."""


class JudgeUnavailableError(JudgeError):
    """The judge client is unavailable or not configured."""


class JudgeParseError(JudgeError):
    """The judge produced output that could not be parsed into a JudgeResult."""


class JudgeInvalidEvidenceError(JudgeError):
    """The judge referenced evidence IDs not present in the evidence package."""


class JudgeReplayNotFoundError(JudgeError):
    """No recorded exchange was found for the given evidence package digest."""


class JudgeValidationError(JudgeError):
    """The JudgeResult failed contract validation."""


class JudgeBudgetError(JudgeError):
    """The judge ran out of token or request budget."""
