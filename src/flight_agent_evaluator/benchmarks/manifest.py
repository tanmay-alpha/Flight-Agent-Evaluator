"""Strict content-addressed benchmark manifest contracts and canonical hashing."""

from __future__ import annotations

import hashlib
import json
import re
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from flight_agent_evaluator.contracts.base import ContractModel

HEX_64_REGEX = re.compile(r"^[0-9a-f]{64}$")


class ScenarioFamily(str, Enum):  # noqa: UP042
    """Benchmark scenario family."""

    READ_ONLY = "read_only"
    TRANSACTIONAL = "transactional"


class Difficulty(str, Enum):  # noqa: UP042
    """Benchmark scenario difficulty level."""

    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class BenchmarkScenarioEntry(ContractModel):
    """Authoritative manifest entry for a scenario and its paired expectation."""

    scenario_id: str = Field(..., min_length=1, max_length=128)
    scenario_version: int | str = Field(default=1)
    scenario_path: str = Field(..., min_length=1, max_length=512)
    scenario_sha256: str = Field(..., min_length=64, max_length=64)
    expectation_path: str = Field(..., min_length=1, max_length=512)
    expectation_sha256: str = Field(..., min_length=64, max_length=64)
    family: str = Field(default="read_only", max_length=64)
    difficulty: str = Field(default="medium", max_length=32)
    tags: tuple[str, ...] = Field(default_factory=tuple, max_length=100)

    @field_validator("scenario_sha256", "expectation_sha256")
    @classmethod
    def validate_sha256_format(cls, value: str) -> str:
        v = value.strip().lower()
        if not HEX_64_REGEX.match(v) or v == "0" * 64:
            raise ValueError(
                f"Digest must be a 64-character lowercase hex string and not all zeros, got '{value}'."
            )
        return v

    @field_validator("scenario_path", "expectation_path")
    @classmethod
    def validate_path_safety(cls, value: str) -> str:
        norm = value.replace("\\", "/")
        if norm.startswith("/") or bool(re.match(r"^[a-zA-Z]:", norm)):
            raise ValueError(f"Path must be relative, got absolute path '{value}'.")
        parts = PurePosixPath(norm).parts
        if ".." in parts:
            raise ValueError(f"Path traversal '..' is forbidden, got '{value}'.")
        return norm


class BenchmarkAgentEntry(ContractModel):
    """Manifest entry for a benchmark participant agent policy."""

    agent_id: str = Field(..., min_length=1, max_length=128)
    agent_version: str = Field(default="1.0.0", max_length=64)
    implementation: str = Field(..., min_length=1, max_length=128)
    configuration_digest: str | None = Field(default=None, max_length=64)

    @field_validator("configuration_digest")
    @classmethod
    def validate_opt_sha256(cls, value: str | None) -> str | None:
        if value is None:
            return None
        v = value.strip().lower()
        if not HEX_64_REGEX.match(v) or v == "0" * 64:
            raise ValueError(
                f"Configuration digest must be a 64-character lowercase hex string, got '{value}'."
            )
        return v


class BenchmarkRunPolicy(ContractModel):
    """Execution policy configuration for authoritative benchmark runs."""

    repetitions: int = Field(default=1, ge=1, le=100)
    seeds: tuple[int, ...] = Field(default=(42,), min_length=1, max_length=100)
    network_allowed: Literal[False] = False
    judge_policy: str = Field(default="offline_rubric", max_length=64)
    replay_policy: str = Field(default="deterministic", max_length=64)
    failure_policy: str = Field(default="fail_closed", max_length=64)

    @field_validator("seeds")
    @classmethod
    def validate_unique_seeds(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if len(value) != len(set(value)):
            raise ValueError("Run policy seeds must be distinct.")
        return value


class BenchmarkManifest(ContractModel):
    """Cryptographically verifiable, authoritative benchmark manifest."""

    benchmark_id: str = Field(..., min_length=1, max_length=128)
    benchmark_version: str = Field(..., min_length=1, max_length=64)
    title: str = Field(default="Flight Agent Evaluator Benchmark V1", max_length=256)
    description: str = Field(default="", max_length=2048)
    environment_version: str = Field(default="1.0.0", max_length=64)
    evaluator_version: str = Field(default="1.0.0", max_length=64)
    taxonomy_version: str = Field(default="1.0.0", max_length=64)
    scoring_profile_version: str = Field(default="1.0.0", max_length=64)
    judge_validation_status: str = Field(default="human_calibration_pending", max_length=64)
    scenarios: tuple[BenchmarkScenarioEntry, ...] = Field(..., min_length=1, max_length=500)
    agents: tuple[BenchmarkAgentEntry, ...] = Field(..., min_length=1, max_length=100)
    run_policy: BenchmarkRunPolicy = Field(default_factory=BenchmarkRunPolicy)
    manifest_digest: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def validate_manifest_integrity(self) -> BenchmarkManifest:
        sc_ids = [sc.scenario_id for sc in self.scenarios]
        if len(sc_ids) != len(set(sc_ids)):
            duplicates = [sid for sid in sc_ids if sc_ids.count(sid) > 1]
            raise ValueError(f"Duplicate scenario IDs found in manifest: {set(duplicates)}")

        ag_ids = [ag.agent_id for ag in self.agents]
        if len(ag_ids) != len(set(ag_ids)):
            duplicates = [aid for aid in ag_ids if ag_ids.count(aid) > 1]
            raise ValueError(f"Duplicate agent IDs found in manifest: {set(duplicates)}")

        return self

    def compute_canonical_digest(self) -> str:
        """Compute deterministic SHA-256 digest of the manifest structure."""
        data: dict[str, Any] = {
            "benchmark_id": self.benchmark_id,
            "benchmark_version": self.benchmark_version,
            "environment_version": self.environment_version,
            "evaluator_version": self.evaluator_version,
            "taxonomy_version": self.taxonomy_version,
            "scoring_profile_version": self.scoring_profile_version,
            "judge_validation_status": self.judge_validation_status,
            "scenarios": [
                {
                    "scenario_id": sc.scenario_id,
                    "scenario_version": sc.scenario_version,
                    "scenario_path": sc.scenario_path,
                    "scenario_sha256": sc.scenario_sha256,
                    "expectation_path": sc.expectation_path,
                    "expectation_sha256": sc.expectation_sha256,
                    "family": sc.family,
                    "difficulty": sc.difficulty,
                    "tags": list(sc.tags),
                }
                for sc in self.scenarios
            ],
            "agents": [
                {
                    "agent_id": ag.agent_id,
                    "agent_version": ag.agent_version,
                    "implementation": ag.implementation,
                    "configuration_digest": ag.configuration_digest,
                }
                for ag in self.agents
            ],
            "run_policy": {
                "repetitions": self.run_policy.repetitions,
                "seeds": list(self.run_policy.seeds),
                "network_allowed": self.run_policy.network_allowed,
                "judge_policy": self.run_policy.judge_policy,
                "replay_policy": self.run_policy.replay_policy,
                "failure_policy": self.run_policy.failure_policy,
            },
        }
        canonical_str = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()
