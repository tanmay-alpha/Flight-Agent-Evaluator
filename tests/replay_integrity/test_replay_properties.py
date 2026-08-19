"""Hypothesis property tests for Layer 4 Replay and Evidence Integrity (P-R1 to P-R6)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

from flight_agent_evaluator.contracts.model import ModelConfiguration, ModelRequest
from flight_agent_evaluator.judges.contracts import (
    JudgeEvidencePackage,
    TrustedObservation,
)
from flight_agent_evaluator.recording.journal import (
    HashChainJournal,
)
from flight_agent_evaluator.recording.store import FileRecordingStore, RecordingPathError
from flight_agent_evaluator.replay.comparator import (
    SemanticReplayComparator,
)
from flight_agent_evaluator.replay.projection import (
    project_semantic_event,
)


@given(
    tool_name=st.text(
        alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")), min_size=1, max_size=20
    ),
    arg_val=st.text(min_size=1, max_size=20),
)
@settings(max_examples=25)
def test_property_p_r1_semantic_replay_equivalence(tool_name: str, arg_val: str):
    """P-R1: Re-executing identical sequence produces verified == True and zero divergences."""
    run_id = str(uuid.uuid4())
    j1 = HashChainJournal()
    j1.append_event(
        "tool_call",
        run_id,
        "c1",
        datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        {"tool_name": f"flight.{tool_name}", "arguments": {"arg": arg_val}, "call_id": "call-1"},
    )
    j2 = HashChainJournal()
    j2.append_event(
        "tool_call",
        run_id,
        "c1",
        datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        {"tool_name": f"flight.{tool_name}", "arguments": {"arg": arg_val}, "call_id": "call-1"},
    )

    ev1 = tuple(project_semantic_event(e) for e in j1.entries)
    ev2 = tuple(project_semantic_event(e) for e in j2.entries)

    comp = SemanticReplayComparator().compare(ev1, ev2)
    assert comp.verified
    assert len(comp.divergences) == 0


@given(
    original_val=st.text(min_size=1, max_size=10),
    tampered_val=st.text(min_size=1, max_size=10),
)
@settings(max_examples=25)
def test_property_p_r2_semantic_divergence_sensitivity(original_val: str, tampered_val: str):
    """P-R2: Any semantic argument mutation causes comparator verification to fail."""
    if original_val == tampered_val:
        return

    run_id = str(uuid.uuid4())
    j1 = HashChainJournal()
    j1.append_event(
        "tool_call",
        run_id,
        "c1",
        datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        {"tool_name": "flight.get_status", "arguments": {"val": original_val}, "call_id": "call-1"},
    )
    j2 = HashChainJournal()
    j2.append_event(
        "tool_call",
        run_id,
        "c1",
        datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        {"tool_name": "flight.get_status", "arguments": {"val": tampered_val}, "call_id": "call-1"},
    )

    ev1 = tuple(project_semantic_event(e) for e in j1.entries)
    ev2 = tuple(project_semantic_event(e) for e in j2.entries)

    comp = SemanticReplayComparator().compare(ev1, ev2)
    assert not comp.verified
    assert len(comp.divergences) > 0


@given(
    msg1=st.text(min_size=1, max_size=15),
    msg2=st.text(min_size=1, max_size=15),
)
@settings(max_examples=25)
def test_property_p_r3_model_request_fingerprint_bijection(msg1: str, msg2: str):
    """P-R3: Different model requests produce distinct canonical fingerprints."""
    if msg1 == msg2:
        return

    req1 = ModelRequest(
        provider="replay",
        model_id="gpt-4o-mini",
        prompt_policy_id="default",
        prompt_policy_version="1.0.0",
        prompt_digest="0" * 64,
        turn_index=0,
        messages=[{"role": "user", "content": msg1}],
        model_configuration=ModelConfiguration(),
    )
    req2 = ModelRequest(
        provider="replay",
        model_id="gpt-4o-mini",
        prompt_policy_id="default",
        prompt_policy_version="1.0.0",
        prompt_digest="0" * 64,
        turn_index=0,
        messages=[{"role": "user", "content": msg2}],
        model_configuration=ModelConfiguration(),
    )

    assert req1.canonical_fingerprint() != req2.canonical_fingerprint()


@given(
    obs_val1=st.text(min_size=1, max_size=15),
    obs_val2=st.text(min_size=1, max_size=15),
)
@settings(max_examples=25)
def test_property_p_r4_judge_evidence_digest_sensitivity(obs_val1: str, obs_val2: str):
    """P-R4: Mutating trusted observations changes JudgeEvidencePackage semantic digest."""
    if obs_val1 == obs_val2:
        return

    pkg1 = JudgeEvidencePackage(
        package_id="pkg-1",
        scenario_id="s1",
        run_id=str(uuid.uuid4()),
        public_task="Task",
        trusted_observations=[
            TrustedObservation(
                evidence_id="obs-1", source="seq:1", description="desc", value=obs_val1
            )
        ],
        final_response="Response",
        created_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
    )
    pkg2 = JudgeEvidencePackage(
        package_id="pkg-2",  # Different package_id ignored in semantic digest
        scenario_id="s1",
        run_id=str(uuid.uuid4()),  # Different run_id ignored in semantic digest
        public_task="Task",
        trusted_observations=[
            TrustedObservation(
                evidence_id="obs-1", source="seq:1", description="desc", value=obs_val2
            )
        ],
        final_response="Response",
        created_at=datetime(2026, 1, 1, 15, 0, 0, tzinfo=UTC),  # Different created_at ignored
    )

    assert pkg1.semantic_digest() != pkg2.semantic_digest()


@given(
    bad_stem=st.sampled_from(
        [
            "../traversal",
            "..\\traversal",
            "sub/dir",
            "sub\\dir",
            "C:\\Windows\\System32",
            "\\\\server\\share",
            "stem\x00null",
            "",
            "   ",
            ".",
            "..",
        ]
    )
)
@settings(max_examples=20)
def test_property_p_r6_path_traversal_rejection(bad_stem: str):
    """P-R6: Any unsafe run_id is unconditionally rejected with RecordingPathError."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        store = FileRecordingStore(Path(td))
        with pytest.raises(RecordingPathError):
            store.resolve_safe_path(bad_stem)
