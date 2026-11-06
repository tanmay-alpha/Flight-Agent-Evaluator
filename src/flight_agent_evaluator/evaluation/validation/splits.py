"""V2 split policy and on-demand detector fingerprinting; no heldout plaintext.

Semantic scenario families, not individual trajectories, are the split unit. The
manifest's broad read_only/transactional categories are too coarse (both hash to
 dev); the map below groups related benchmark variants before hashing. Unknown
families retain the manifest family, rather than splitting near-duplicates by id.
Template ids identify phrasing families: all renderings of an id stay together.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Suite = Literal["dev", "heldout"]

SCENARIO_FAMILIES: dict[str, str] = {
    "jfk-lhr-delay": "disruption-status",
    "jfk-lhr-timeout-recovery": "disruption-status",
    "lax-sfo-ontime": "normal-status",
    "atl-mia-wrong-arguments": "lookup-arguments",
    "bwi-mco-forbidden-mutation": "forbidden-mutation",
    "clt-phx-retry-dependency": "read-retry-dependency",
    "dfw-den-no-alternatives": "empty-search",
    "iad-ord-redundant-lookup": "redundant-read",
    "ord-sea-dual-order": "equivalent-order",
    "prompt-injection-untrusted-output": "untrusted-output",
    "sfo-bos-optional-lookup": "optional-read",
    "unknown-flight-lookup": "missing-flight",
    "approval-granted": "approval-decision",
    "approval-denied": "approval-decision",
    "approval-expires": "approval-decision",
    "mutation-without-approval": "approval-decision",
    "payload-changes-after-approval": "approval-scope",
    "approval-wrong-itinerary": "approval-scope",
    "constraint-changes-after-approval": "approval-scope",
    "idempotent-retry-after-timeout": "ambiguous-commit",
    "mutation-success-response-lost": "ambiguous-commit",
    "duplicate-rebooking-attempt": "already-satisfied",
    "hold-expires": "inventory-validity",
    "alternative-disappears-before-confirm": "inventory-validity",
}


def split_for(family: str) -> Suite:
    """SHA-256(family) as an unsigned integer mod 10: 0..5 dev, 6..9 heldout."""
    bucket = int.from_bytes(hashlib.sha256(family.encode("utf-8")).digest(), "big") % 10
    return "dev" if bucket < 6 else "heldout"


def scenario_family(scenario_id: str, manifest_family: str) -> str:
    """Return the versioned semantic family, keeping benchmark siblings together."""
    return SCENARIO_FAMILIES.get(scenario_id, manifest_family)


@dataclass(frozen=True)
class PhraseTemplate:
    """One phrasing family; injection text is separate from its compliant response."""

    template_id: str
    kind: Literal["claim", "question", "offer", "injection"]
    response: str
    instruction: str = ""
    paraphrase_instruction: str = ""

    @property
    def digest(self) -> str:
        """Content fingerprint, suitable for a plaintext-free suite manifest."""
        return hashlib.sha256(
            "\0".join(
                (
                    self.template_id,
                    self.kind,
                    self.response,
                    self.instruction,
                    self.paraphrase_instruction,
                )
            ).encode("utf-8")
        ).hexdigest()


def detector_source_digest() -> str:
    """Hash current detector/contract bytes, never a cached import-time fingerprint.

    Relative paths and lengths are framed to avoid ambiguous concatenations. Validation
    operators and phrase pools are excluded: they are not detector implementation.
    """
    package = Path(__file__).resolve().parents[2]
    sources = sorted(
        path
        for path in (package / "evaluation").rglob("*.py")
        if "validation" not in path.relative_to(package / "evaluation").parts
    )
    sources.extend(sorted((package / "contracts").glob("*.py")))
    digest = hashlib.sha256()
    for path in sources:
        name = path.relative_to(package).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()
