"""Deterministic, durable approval and scoped-grant enforcement.

This is intentionally the sole policy evaluator used by dispatch and tool
execution.  A Coordinator can request work but cannot turn an `ask` or `deny`
into authority; only a persisted human resolution may create a bounded grant.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import PurePosixPath
import uuid

import aiosqlite

from app.db.repositories import EventRepository, _now_ms, _safe_json
from app.schemas.session_commands import ApprovalResolvePayload
from app.services.session_configuration_service import ConfigurationSnapshot, SessionConfigurationService


_KNOWN = frozenset({
    "workspace.read", "workspace.write", "search.files", "test.run",
    "dependency.install", "network.shell", "git.mutate", "original_project.write",
})
_NON_BYPASSABLE = frozenset({"outside_workspace", "secret.extract", "destructive.host"})
_DEFAULT_GRANT_MS = {"once": 5 * 60_000, "scope": 60 * 60_000, "session": 24 * 60 * 60_000}


class ApprovalRejected(ValueError):
    """Stable rejection used at a command or dispatch boundary."""

    def __init__(self, code: str, summary: str) -> None:
        super().__init__(summary)
        self.code = code
        self.summary = summary


@dataclass(frozen=True)
class AuthorityDecision:
    outcome: str  # allow | ask | deny
    reason: str
    grant_id: str | None = None


def _safe_relative_path(path: str) -> bool:
    candidate = PurePosixPath(path)
    return bool(path) and not candidate.is_absolute() and ".." not in candidate.parts and "\\" not in path


def _canonical_scope(path: str) -> str:
    if not _safe_relative_path(path):
        raise ApprovalRejected("invalid_workspace_scope", "The requested workspace scope is not a safe relative path.")
    normalized = str(PurePosixPath(path))
    return "." if normalized == "." else normalized.rstrip("/")


def _profile_outcome(profile: str, capability: str) -> str:
    if capability not in _KNOWN:
        return "deny"
    if profile == "strict":
        return "ask"
    if profile == "balanced":
        return "allow" if capability in {"workspace.read", "search.files", "test.run"} else "ask"
    if profile == "autonomous":
        return "ask" if capability in {"git.mutate", "original_project.write"} else "allow"
    # Expert acknowledgement is checked at configuration time.  Host-level
    # destructive and secret-extraction operations remain non-bypassable.
    return "allow"


class ApprovalGrantService:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db
        self._events = EventRepository(db)

    async def evaluate(
        self, session_id: str, *, capability: str, scope_path: str = ".", operation_class: str = "read_only",
        consume_once: bool = False,
    ) -> AuthorityDecision:
        if not _safe_relative_path(scope_path):
            return AuthorityDecision("deny", "This operation is outside the non-bypassable safety boundary.")
        scope_path = _canonical_scope(scope_path)
        snapshot = await SessionConfigurationService(self._db).current(session_id)
        return await self.evaluate_snapshot(
            session_id, snapshot, capability=capability, scope_path=scope_path,
            operation_class=operation_class, consume_once=consume_once,
        )

    async def evaluate_snapshot(
        self, session_id: str, snapshot: ConfigurationSnapshot, *, capability: str, scope_path: str,
        operation_class: str, consume_once: bool,
    ) -> AuthorityDecision:
        if not _safe_relative_path(scope_path):
            return AuthorityDecision("deny", "This operation is outside the non-bypassable safety boundary.")
        scope_path = _canonical_scope(scope_path)
        if capability in _NON_BYPASSABLE:
            return AuthorityDecision("deny", "This operation is outside the non-bypassable safety boundary.")
        policy = snapshot.approval_policy
        base = _profile_outcome(str(policy["permissionProfile"]), capability)
        override = policy.get("capabilityOverrides", {}).get(capability)
        # Overrides may only reduce the profile's authority.  An `allow`
        # override therefore cannot silently convert an approval into a grant.
        if override == "deny":
            base = "deny"
        elif override == "ask" and base == "allow":
            base = "ask"
        if base == "deny":
            return AuthorityDecision("deny", "The permission profile denies this capability.")
        behavior = str(policy["behavior"])
        if behavior in {"deny_interactive", "preauthorize_session"}:
            grant = await self._matching_grant(session_id, snapshot.policy_hash, capability, scope_path, consume_once)
            if grant is not None:
                return AuthorityDecision("allow", "A matching session pre-authorization allows this request.", str(grant["id"]))
            reason = "No-interruption mode denies requests without an active pre-authorization." if behavior == "deny_interactive" else "The session pre-authorization does not cover this capability."
            return AuthorityDecision("deny", reason)
        if behavior == "ask_each_time":
            return AuthorityDecision("ask", "The selected behavior requires a human decision for every request.")
        if base == "allow":
            return AuthorityDecision("allow", "The selected permission profile allows this workspace-scoped request.")
        grant = await self._matching_grant(session_id, snapshot.policy_hash, capability, scope_path, consume_once)
        if grant is not None:
            return AuthorityDecision("allow", "A matching active human grant allows this request.", str(grant["id"]))
        return AuthorityDecision("ask", "This capability needs a scoped human grant.")

    async def request_in_transaction(
        self, session_id: str, *, capability: str, scope_path: str, scope_summary: str,
        assignment_id: str | None = None, operation_class: str = "read_only",
    ) -> AuthorityDecision:
        scope_path = _canonical_scope(scope_path)
        decision = await self.evaluate(session_id, capability=capability, scope_path=scope_path, operation_class=operation_class)
        if decision.outcome != "ask":
            return decision
        approval_id = f"apr_{uuid.uuid4().hex}"
        now = _now_ms()
        event = await self._events._append_in_transaction(
            event_id=f"evt_{uuid.uuid4().hex}", session_id=session_id, event_type="approval.requested", actor_id="system",
            payload={"approvalId": approval_id, **({"assignmentId": assignment_id} if assignment_id else {}),
                     "capability": capability, "scopeSummary": scope_summary, "scopePath": scope_path},
            payload_json=_safe_json({"approvalId": approval_id, **({"assignmentId": assignment_id} if assignment_id else {}),
                     "capability": capability, "scopeSummary": scope_summary, "scopePath": scope_path}),
            timestamp_ms=now, correlation_id=approval_id, command_id=None,
        )
        await self._db.execute(
            """INSERT INTO approvals (id, session_id, assignment_id, capability, scope_json, scope_path, operation_class,
               decision, requested_at_ms, request_event_id) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
            (approval_id, session_id, assignment_id, capability, _safe_json({"summary": scope_summary}), scope_path,
             operation_class, now, event.event_id),
        )
        return AuthorityDecision("ask", decision.reason, approval_id)

    async def resolve_in_transaction(
        self, session_id: str, payload: ApprovalResolvePayload, resolution_event_id: str,
    ) -> tuple[str | None, int | None]:
        async with self._db.execute("SELECT * FROM approvals WHERE id = ? AND session_id = ?", (payload.approval_id, session_id)) as cursor:
            approval = await cursor.fetchone()
        if approval is None or approval["decision"] != "pending":
            raise ApprovalRejected("approval_not_pending", "The approval request is missing, stale, or already resolved.")
        now = _now_ms()
        if payload.resolution == "grant":
            snapshot = await SessionConfigurationService(self._db).current(session_id)
            requested = str(approval["capability"])
            if set(payload.grant_capabilities) != {requested}:
                raise ApprovalRejected("grant_capability_mismatch", "A grant may cover only the capability that was requested.")
            # A stale request cannot gain authority after a policy update.
            fresh = await self.evaluate_snapshot(
                session_id, snapshot, capability=requested, scope_path=str(approval["scope_path"]),
                operation_class=str(approval["operation_class"]), consume_once=False,
            )
            if fresh.outcome == "deny":
                raise ApprovalRejected("approval_policy_denied", "Current policy no longer permits this grant.")
            grant_scope = payload.grant_scope or "once"
            duration = payload.grant_duration_seconds * 1000 if payload.grant_duration_seconds is not None else _DEFAULT_GRANT_MS[grant_scope]
            expiry = now + duration
            await self._db.execute(
                """UPDATE approvals SET decision = 'granted', grant_scope = ?, policy_hash = ?, grant_expires_at_ms = ?,
                   resolver_id = 'human', resolved_at_ms = ?, resolution_event_id = ? WHERE id = ?""",
                (grant_scope, snapshot.policy_hash, expiry, now, resolution_event_id, approval["id"]),
            )
            return str(approval["id"]), expiry
        decision = "approved" if payload.resolution == "approve" else "rejected"
        await self._db.execute(
            "UPDATE approvals SET decision = ?, resolver_id = 'human', resolved_at_ms = ?, resolution_event_id = ? WHERE id = ?",
            (decision, now, resolution_event_id, approval["id"]),
        )
        return None, None

    async def create_preauthorizations_in_transaction(self, session_id: str, snapshot: ConfigurationSnapshot) -> None:
        policy = snapshot.approval_policy
        if policy["behavior"] != "preauthorize_session":
            return
        now = _now_ms()
        for capability in policy["preauthorizedCapabilities"]:
            # Preauthorization lives in the same durable table as a human
            # grant, is bound to the snapshot hash, and cannot outlive a day.
            approval_id = f"preauth_{uuid.uuid4().hex}"
            requested_payload = {
                "approvalId": approval_id, "capability": capability,
                "scopeSummary": "Session workspace only.", "scopePath": ".",
            }
            requested = await self._events._append_in_transaction(
                event_id=f"evt_{uuid.uuid4().hex}", session_id=session_id, event_type="approval.requested", actor_id="human",
                payload=requested_payload, payload_json=_safe_json(requested_payload), timestamp_ms=now,
                correlation_id=approval_id, command_id=None,
            )
            await self._db.execute(
                """INSERT INTO approvals (id, session_id, capability, scope_json, scope_path, operation_class, decision,
                   grant_scope, policy_hash, grant_expires_at_ms, resolver_id, requested_at_ms, resolved_at_ms,
                   request_event_id) VALUES (?, ?, ?, ?, '.', 'read_only', 'granted', 'session', ?, ?, 'human', ?, ?, ?)""",
                (approval_id, session_id, capability, _safe_json({"summary": "Session workspace only."}),
                 snapshot.policy_hash, now + _DEFAULT_GRANT_MS["session"], now, now, requested.event_id),
            )
            resolved_payload = {
                "approvalId": approval_id, "resolution": "granted", "grantId": approval_id,
                "grantScope": "session", "grantExpiresAtMs": now + _DEFAULT_GRANT_MS["session"],
                "reasonSummary": "Pre-authorized for this session workspace.",
            }
            resolved = await self._events._append_in_transaction(
                event_id=f"evt_{uuid.uuid4().hex}", session_id=session_id, event_type="approval.resolved", actor_id="human",
                payload=resolved_payload, payload_json=_safe_json(resolved_payload), timestamp_ms=now,
                correlation_id=approval_id, command_id=None,
            )
            await self._db.execute("UPDATE approvals SET resolution_event_id = ? WHERE id = ?", (resolved.event_id, approval_id))

    async def revoke_stale_policy_in_transaction(self, session_id: str, policy_hash: str) -> None:
        await self._db.execute(
            "UPDATE approvals SET revoked_at_ms = ? WHERE session_id = ? AND decision = 'granted' AND revoked_at_ms IS NULL AND policy_hash IS NOT NULL AND policy_hash != ?",
            (_now_ms(), session_id, policy_hash),
        )

    async def _matching_grant(self, session_id: str, policy_hash: str, capability: str, scope_path: str, consume_once: bool) -> aiosqlite.Row | None:
        now = _now_ms()
        async with self._db.execute(
            """SELECT * FROM approvals WHERE session_id = ? AND capability = ? AND decision = 'granted'
               AND policy_hash = ? AND revoked_at_ms IS NULL AND grant_expires_at_ms > ?
               AND (grant_scope != 'once' OR consumed_at_ms IS NULL) ORDER BY resolved_at_ms DESC""",
            (session_id, capability, policy_hash, now),
        ) as cursor:
            grants = await cursor.fetchall()
        for grant in grants:
            granted_path = str(grant["scope_path"])
            in_scope = scope_path == granted_path or scope_path.startswith(f"{granted_path.rstrip('/')}/")
            if grant["grant_scope"] == "scope" and not in_scope:
                continue
            if grant["grant_scope"] in {"once", "session"} and scope_path != granted_path:
                continue
            if consume_once and grant["grant_scope"] == "once":
                claimed = await self._db.execute(
                    "UPDATE approvals SET consumed_at_ms = ? WHERE id = ? AND consumed_at_ms IS NULL",
                    (now, grant["id"]),
                )
                if claimed.rowcount != 1:
                    continue
            return grant
        return None
