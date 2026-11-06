# ADR 0010 — Domain coupling analysis and DomainPack extension seam

- **Status:** Proposed
- **Date:** 2026-11-06
- **Stage:** 4.

## Context

Flight Agent Evaluator was initially developed to evaluate, replay, and diagnose tool-using agents within an airline disruption domain. However, the platform's core algorithmic machinery is largely domain-agnostic:

- Bounded branch-and-bound trajectory matching (`DeterministicBoundedMatcher`)
- Multi-dimensional scoring with safety dominance (`TrajectoryEvaluator`)
- Hash-chained event recording and value-level replay verification (`HashChainJournal`, `ReplayEngine`)
- Virtual clock and deterministic event simulation
- Diagnostic root-cause attribution heuristics and failure taxonomy (`FailureDiagnosticEngine`)
- Perturbation-based evaluator validation (Validation v2 with dev/heldout splits and Wilson confidence intervals)
- External agent trace re-execution and containment (`traces/`)

Despite this domain-independent foundation, the current implementation couples airline-specific concepts directly into the evaluation, safety, observation, and runner layers. This prevents testing agents in other high-stakes transactional domains (such as retail returns, banking, logistics, or healthcare) without modifying internal evaluation logic.

This ADR identifies and verifies all domain coupling points across the v0.4 codebase and proposes a formal `DomainPack` protocol to establish a clean extension seam.

---

## Verified Coupling Points in Code

Every coupling point listed below has been verified against the v0.4 codebase:

### 1. Expectation-Independent Journal Safety (`evaluation/journal_safety.py`)
- **Hardcoded tool names:** Hardcodes specific flight and booking tools:
  - `APPROVAL_REQUEST_TOOL = "approval.request"` (`:94`)
  - `APPROVAL_STATUS_TOOL = "approval.get_status"` (`:95`)
  - `BOOKING_STATE_TOOL = "booking.get_current"` (`:96`)
- **Claim backing tools:** Hardcodes `_BACKING_TOOLS` (`:115-120`) mapping claim categories strictly to airline tools:
  - `REBOOK: frozenset({"booking.confirm_rebooking"})`
  - `HOLD: frozenset({"booking.hold_alternative"})`
  - `RELEASE: frozenset({"booking.release_hold"})`
  - `NOTIFY: frozenset({"notification.send_simulated"})`
- **Claim backing statuses:** `_BACKING_BOOKING_STATUS` (`:122`) maps `REBOOK: "rebooked"` and `CANCEL: "cancelled"` directly to booking entity states.
- **Tool-to-category mapping:** `_TOOL_CATEGORY` (`:125-131`) maps airline tools to action categories for prompt-injection attribution.
- **Intent key extraction:** In `_mutation_intent_key` (`:23-24, 380-405`), duplicate side-effect detection hardcodes the booking reference (`booking_reference`) as the primary entity identifier for sensitive mutations.
- **Approval scope verification:** Approval checks (`:17-19, 224-305`) explicitly extract and verify `booking_reference` and `hold_id` fields from call arguments.

### 2. Natural-Language Claim Detection (`evaluation/claims.py`)
- **Domain action categories:** Hardcodes seven airline-specific categories (`:32-40`): `REBOOK`, `CANCEL`, `REFUND`, `HOLD`, `RELEASE`, `NOTIFY`, `APPROVAL`.
- **Domain state nouns:** `_BOOKING_NOUN` (`:42`) matches `"booking|reservation|ticket|itinerary|trip|flight change"`.
- **Lexical claim regexes:** `_CLAIM_PATTERNS` (`:45-113`) matches domain-specific phrases (e.g., "new flight is confirmed", "e-ticket issued", "seats held", "reservation moved").
- **Third-party attribution:** `_THIRD_PARTY_RE` (`:135-137`) specifically checks for `"airline|carrier|airport|customer|passenger|travel agent"`.
- **User request action verbs:** `requested_action_categories` (`:197-222`) hardcodes airline directive verbs ("rebook me", "flight change", "hold a seat").

### 3. Trajectory Observation and Tool Classification (`evaluation/observation.py`)
- **Packaged catalog coupling:** `_tool_catalog()` (`:25-32`) imports `tools.base.build_transactional_registry()`, hardcoding the default airline tool suite.
- **Unknown tools fail open:** In `ObservedToolAction.is_mutation_attempt` (`:84-87`):
  ```python
  return self.mutation_class not in ("read_only", UNKNOWN_MUTATION_CLASS)
  ```
  Any tool call from an uncataloged domain that does not declare a mutation class receives `UNKNOWN_MUTATION_CLASS = "unknown"` (`:21-22`). Because it is excluded from mutation attempts, **unknown tools fail open**—they are treated as harmless non-mutating calls rather than potential safety violations.

### 4. Outcome Assertion Evaluator (`evaluation/assertions.py`)
- **Hardcoded entity evaluators:** Evaluates assertions by inspecting airline-specific state paths:
  - `booking_state` (`:165-193`): inspects `state.data["bookings"][booking_id]["state"]`.
  - `approval_state` (`:196-224`): inspects `state.data["approvals"][request_id]["state"]`.

### 5. Evaluator Validation Operators (`evaluation/validation/operators.py`)
- **Perturbation tools:** Hardcodes `COMMIT_TOOL = "booking.confirm_rebooking"` (`:27`) and `HOLD_TOOL = "booking.hold_alternative"` (`:28`).
- **Domain argument corruptions:** `KEY_ARGUMENT_CORRUPTIONS` (`:34-39`) hardcodes `flight_id`, `booking_reference`, `origin`, `destination`, and `carrier_code`.
- **Unauthorized mutation injection:** `inject_unauthorized_mutation` (`:382-421`) synthesizes an unauthorized commit using `booking_reference` and `hold_id`.
- **Domain responses:** `FALSE_SUCCESS_RESPONSES` (`:43-51`) and `INJECTION_COMPLIANT_RESPONSE` (`:52-55`) hardcode flight rebooking statements.
- **Scenario inspection:** `false_success_claim` (`:524-558`) directly inspects `scenario.environment.bookings`.

### 6. Tool System Interfaces (`tools/base.py`)
- **Provider coupling in protocol:** The `ToolHandler` protocol (`:26-49`) explicitly hardcodes `FlightProvider` in its `execute` signature:
  ```python
  async def execute(self, arguments: dict[str, Any], provider: FlightProvider, context: RunContext) -> Any: ...
  ```
- **Registry factories:** `build_transactional_registry` (`:151-176`) and `build_registry_for_scenario` directly assemble the 11 airline tools.

### 7. Execution Runners (`engine/runner.py`, `engine/benchmark.py`, `engine/tool_executor.py`)
- **Scenario runner:** `engine/runner.py:44-47, 144-147` defaults to `FixtureFlightProvider()` and instantiates `SimulatedAirlineEnvironment.from_scenario(scenario)`.
- **Benchmark runner:** `engine/benchmark.py:320-324` hardcodes `FixtureFlightProvider()`, `SimulatedAirlineEnvironment.from_scenario(scenario)`, and airline-specific registry construction.
- **Tool executor:** `engine/tool_executor.py:117, 173` explicitly types the provider as `FlightProvider | None`.

### 8. Scenario Environment Schema (`contracts/scenarios.py`)
- **Airline-specific environment:** `ScenarioEnvironment` (`:73-86`) defines:
  - `bookings: tuple[EnvironmentBookingSetup, ...]`
  - `offers: tuple[EnvironmentOfferSetup, ...]`
  - `approval_decision: ScenarioApprovalDecision | None`
  - `hold_expired: bool`
  - `alternative_disappears: bool`
  - `booking_mutation_fails: bool`
- **Flight-specific child models:** `EnvironmentBookingSetup` (`:34-53`) requires `scheduled_departure` and `rebooked_flight_number`; `EnvironmentOfferSetup` (`:55-71`) models alternative flight legs and airfares.

---

## Proposed Architecture: The `DomainPack` Protocol

To decouple domain specifics from the evaluation engine, we propose introducing a `DomainPack` protocol. A `DomainPack` encapsulates all domain-specific rules, entity state machines, tools, and lexicons behind standard interfaces.

```
+---------------------------------------------------------------+
|                      Evaluation Engine                        |
| (Matcher, Scoring, Journal Safety, Replay, Validation Harness) |
+-------------------------------+-------------------------------+
                                | consumes
                                v
+---------------------------------------------------------------+
|                     DomainPack Protocol                       |
+---------------------------------------------------------------+
| 1. Tool Catalog (with fail-closed unknown tool policy)        |
| 2. Approval Protocol & Lifecycle                              |
| 3. Denial & Unknown-Outcome Vocabulary                        |
| 4. Intent Key Resolver (for duplicate side-effect detection)  |
| 5. Claim Lexicon & Phrasing Detector                          |
| 6. Injection Patterns & Attribution Mappings                  |
| 7. State Projection & Assertion Evaluators                    |
| 8. Scenarios, System Prompts & Baseline Policies              |
+-------------------------------+-------------------------------+
                                | implementations
                +---------------+---------------+
                |                               |
                v                               v
+-------------------------------+ +-------------------------------+
|        AviationDomainPack     | |         RetailDomainPack      |
|    (Current Flight Domain)    | |       (Returns & Refunds)     |
+-------------------------------+ +-------------------------------+
```

### Components of the `DomainPack` Protocol

1. **Tool Catalog and Fail-Closed Policy:**
   - Declares domain tools with their authoritative `ToolMutationClass` (`read_only`, `simulated_mutation`, `sensitive_simulated_mutation`) and JSON input schemas.
   - **Fail-closed policy:** Unknown tools (tools invoked by an agent that are not in the domain catalog) MUST fail closed. The executor and observer treat unknown tools as prohibited or sensitive mutations, generating a safety violation rather than defaulting to benign read-only status.
2. **Approval Protocol:**
   - Standardizes the creation, verification, scope binding, and expiration of supervisor approvals across domains.
   - Decouples approval state from specific entity names (e.g., `booking_reference`) by using an abstract `resource_id` and `action_payload_hash`.
3. **Denial and Unknown-Outcome Vocabulary:**
   - Provides domain-specific error classifications that map into evaluator categories:
     - Policy denials triggering `SAFETY.DENIED_ACTION_ATTEMPT`
     - Unknown outcomes (`ambiguous_commit`, `timeout`, `cancelled`) requiring idempotent recovery
4. **Intent Key Resolver:**
   - A callable `(tool_name: str, arguments: dict[str, Any]) -> str` that extracts the semantic target of an operation (e.g., `return_id` or `order_id` instead of `booking_reference`) for duplicate side-effect tracking.
5. **Claim Lexicon:**
   - Encapsulates natural-language regex patterns (`_CLAIM_PATTERNS`), negation cues (`_NEGATION_RE`), state nouns, and third-party entities for natural-language assertion verification.
6. **Injection Attribution:**
   - Maps tool names to action categories and provides regex patterns for extracting unrequested directives from tool results.
7. **Assertion Registry:**
   - Extensible dispatch table mapping assertion types (e.g., `order_state`, `refund_balance`) to state snapshot predicates.
8. **Scenario Environment Schema:**
   - Replaces the concrete `ScenarioEnvironment` with a polymorphic or generic model schema (`domain_environment: dict[str, Any]`), parsed and validated by the active `DomainPack`.

---

## Target Second Domain: Retail Returns and Refunds

We propose **retail returns and customer refunds** as the smallest, most suitable second domain for the following reasons:

1. **Structural Isomorphism to Aviation Rebooking:**
   - **Read-only lookups:** `order.get_status`, `policy.get_return_window`, `catalog.search_replacements` (mirrors `flight.get_status`, `policy.get_rebooking_rules`, `flight.search_flights`).
   - **Simulated mutation:** `return.create_rma`, `return.hold_replacement_item` (mirrors `booking.hold_alternative`).
   - **Sensitive simulated mutation:** `refund.issue_refund`, `return.confirm_return` (mirrors `booking.confirm_rebooking`).
   - **Supervisor approvals:** `approval.request` for exceptions such as returns outside the 30-day window, items without original receipt, or high-value refunds exceeding an automated threshold (mirrors supervisor approval for rebooking fee waivers).
   - **Temporal expiry:** Return window expires, RMA shipping label expires, or replacement item hold expires (mirrors `hold_expired` and `approval_expires`).
   - **Unknown outcomes & idempotency:** Ambiguous payment gateway timeouts on refund confirmation requiring idempotent retries (mirrors `mutation-success-response-lost` and `idempotent-retry-after-timeout`).
   - **Irreversible side-effects:** Issuing duplicate refunds to a customer for a single returned item under different idempotency keys (mirrors `SAFETY.DUPLICATE_SIDE_EFFECT`).
2. **Minimal Surface Area:**
   - Retail returns require only 6–8 tools, one state machine (`RETURN_REQUESTED`, `RMA_ISSUED`, `ITEM_RECEIVED`, `REFUNDED`), and a small set of financial constraints.
   - It exercises every dimension of `DomainPack` (tool mutation classes, approvals, idempotency, natural language claims, injection attribution, and timeout recovery) without requiring external service mocks or distributed transaction coordinators.

## Consequences

- **Positive:** Evaluator core logic becomes domain-agnostic, enabling multi-domain benchmark suites and preventing domain logic leakage into scoring algorithms.
- **Positive:** Unknown tools fail closed, removing the existing safety gap where uncataloged tools default to non-mutating status.
- **Trade-off:** Requires refactoring the runner interfaces and scenario environment schema to accept domain packs dynamically rather than relying on direct imports from `flight_agent_evaluator.environment`.
