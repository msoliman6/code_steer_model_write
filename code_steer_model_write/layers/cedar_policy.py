"""L9 first implementation (ARCHITECTURE.md 7.2): Cedar through the `cedarpy` bindings,
in-process. Default deny is Cedar's; every policy carries the runtime's rule id as an
annotation and the deciding policy is logged with the decision; the policy set is validated
against a schema before the first decision, so a policy that names an attribute the runtime
never supplies refuses to start rather than silently denying at run time.

The nine rules are the same rules `StepPolicy` holds; `tests/test_layers.py` runs both
engines over one decision table and requires them to agree."""

from __future__ import annotations

import itertools
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from .policy import Action, Decision, Principal

if TYPE_CHECKING:
    from ..events import EventLog

# ---- the policies, one per rule, annotated with the rule id ------------------------------------

RULES: list[tuple[str, str, str]] = [
    (
        "P-issue",
        "a step is issued by the driver; any minted principal may be issued its own step",
        'permit(principal, action == Action::"issue", resource);',
    ),
    (
        "P-launch",
        "a minted principal may ask for a run to start",
        'permit(principal, action == Action::"launch", resource);',
    ),
    (
        "P-author",
        "a side may author the artifact its step declares",
        'permit(principal is Side, action == Action::"author", resource);',
    ),
    (
        "P-judge",
        "a side may judge an artifact only if it is not the artifact's author",
        'permit(principal is Side, action == Action::"judge", resource)\n'
        "when { if context has author then context.author != context.principal_id else true };",
    ),
    (
        "P-tool-declared",
        "a side may call a tool only if its step declared that tool",
        'permit(principal is Side, action == Action::"tool", resource)\n'
        "when { context.declared.contains(context.tool) };",
    ),
    (
        "P-execute",
        "an execution is allowed inside the run's own root",
        'permit(principal, action == Action::"execute", resource)\nwhen { context.inside_root };',
    ),
    (
        "P-write-ownership",
        "a write is allowed only on a path the row may write",
        'permit(principal, action == Action::"write", resource)\n'
        "when { context.allowed.isEmpty() || context.allowed.contains(context.path) };",
    ),
    (
        "P-gate-human",
        "a human may decide any gate",
        'permit(principal is Human, action == Action::"gate", resource);',
    ),
    (
        "P-gate-auto",
        "auto may sign a gate only when the mode dial says no human is needed",
        'permit(principal is Side, action == Action::"gate", resource)\nwhen { context.auto_allowed };',
    ),
]
# a tool call no rule allows is denied: Cedar's default, named so the decision can cite it
DEFAULT_DENY = ("P-default-deny", "no policy allowed it; Cedar denies by default")

POLICIES = "\n\n".join(f'@id("{rid}")\n{text}' for rid, _, text in RULES)
POLICY_IDS = [rid for rid, _, _ in RULES]
REASONS = {rid: why for rid, why, _ in RULES} | {DEFAULT_DENY[0]: DEFAULT_DENY[1]}

_STR = {"type": "String"}
_BOOL = {"type": "Boolean"}
_STRSET = {"type": "Set", "element": {"type": "String"}}


def schema(tools: list[str] | None = None) -> dict[str, Any]:
    """The Cedar schema the policies are validated against: the principal kinds, the resource
    kinds, and per action the context the runtime supplies. Tool names are recorded as the
    resource ids the registry knows, so the schema is generated from the ToolSpecs (7.2)."""
    entity = {"shape": {"type": "Record", "attributes": {}}}
    tool_entity = {"shape": {"type": "Record", "attributes": {"registered": _BOOL}}}
    ctx = lambda attrs: {"type": "Record", "attributes": attrs}  # noqa: E731
    return {
        "": {
            "entityTypes": {
                "Human": entity,
                "Side": entity,
                "Tool": tool_entity,
                "Artifact": entity,
                "Step": entity,
                "Path": entity,
                "Gate": entity,
                "Workflow": entity,
            },
            "actions": {
                "issue": {
                    "appliesTo": {
                        "principalTypes": ["Human", "Side"],
                        "resourceTypes": ["Step", "Artifact"],
                        "context": ctx({}),
                    }
                },
                "launch": {
                    "appliesTo": {
                        "principalTypes": ["Human", "Side"],
                        "resourceTypes": ["Workflow"],
                        "context": ctx({}),
                    }
                },
                "author": {
                    "appliesTo": {
                        "principalTypes": ["Side"],
                        "resourceTypes": ["Artifact", "Step"],
                        "context": ctx({}),
                    }
                },
                "judge": {
                    "appliesTo": {
                        "principalTypes": ["Side"],
                        "resourceTypes": ["Artifact", "Step"],
                        "context": ctx({"author": {**_STR, "required": False}, "principal_id": _STR}),
                    }
                },
                "tool": {
                    "appliesTo": {
                        "principalTypes": ["Side"],
                        "resourceTypes": ["Tool"],
                        "context": ctx({"declared": _STRSET, "tool": _STR}),
                    }
                },
                "execute": {
                    "appliesTo": {
                        "principalTypes": ["Human", "Side"],
                        "resourceTypes": ["Step"],
                        "context": ctx({"inside_root": _BOOL}),
                    }
                },
                "write": {
                    "appliesTo": {
                        "principalTypes": ["Human", "Side"],
                        "resourceTypes": ["Path"],
                        "context": ctx({"allowed": _STRSET, "path": _STR}),
                    }
                },
                "gate": {
                    "appliesTo": {
                        "principalTypes": ["Human", "Side"],
                        "resourceTypes": ["Gate"],
                        "context": ctx({"auto_allowed": _BOOL}),
                    }
                },
            },
        }
    }


_RESOURCE_TYPE: dict[str, str] = {
    "issue": "Step",
    "launch": "Workflow",
    "author": "Artifact",
    "judge": "Artifact",
    "tool": "Tool",
    "execute": "Step",
    "write": "Path",
    "gate": "Gate",
}
_PRINCIPAL_TYPE = {"human": "Human", "side": "Side", "tool": "Tool"}


def _context(action: Action, principal: Principal, resource: str, c: dict[str, Any]) -> dict[str, Any]:
    """The PIP: the attributes the runtime supplies for the PDP to decide on (NIST SP 800-162).
    Path arithmetic happens here, once, so the policy reads one boolean."""
    if action == "judge":
        out: dict[str, Any] = {"principal_id": principal.id}
        if c.get("author") is not None:
            out["author"] = str(c["author"])
        return out
    if action == "tool":
        return {"declared": sorted(str(t) for t in c.get("declared", ())), "tool": resource}
    if action == "execute":
        root, cwd = c.get("root"), c.get("cwd")
        inside = (
            root is None or cwd is None or PurePosixPath(str(cwd)).is_relative_to(PurePosixPath(str(root)))
        )
        return {"inside_root": bool(inside)}
    if action == "write":
        allowed = sorted({PurePosixPath(a).as_posix() for a in c.get("allowed", ())})
        return {"allowed": allowed, "path": PurePosixPath(resource).as_posix()}
    if action == "gate":
        return {"auto_allowed": bool(c.get("auto_allowed", False))}
    return {}


def _entity_id(s: str) -> str:
    return s.replace('"', "'")


class CedarPolicy:
    engine = "cedar"

    def __init__(self, events: "EventLog | None" = None, *, tools: list[str] | None = None) -> None:
        import cedarpy

        self._cedar = cedarpy
        self.events = events
        self._ids = itertools.count(1)
        self.schema = schema(tools)
        result = cedarpy.validate_policies(POLICIES, self.schema)
        if not result.validation_passed:
            errs = "; ".join(f"{e.policy_id}: {e.error}" for e in result.errors)
            raise RuntimeError(f"the Cedar policy set does not validate against its schema: {errs}")

    def decide(
        self, principal: Principal, action: Action, resource: str, context: dict[str, Any] | None = None
    ) -> Decision:
        c = context or {}
        rtype = _RESOURCE_TYPE[action]
        rid = _entity_id(resource)
        pid = _entity_id(principal.id.split(":", 1)[1] if ":" in principal.id else principal.id)
        ptype = _PRINCIPAL_TYPE[principal.kind]
        request = {
            "principal": f'{ptype}::"{pid}"',
            "action": f'Action::"{action}"',
            "resource": f'{rtype}::"{rid}"',
            "context": _context(action, principal, resource, c),
        }
        entities = [
            {"uid": {"type": ptype, "id": pid}, "attrs": {}, "parents": []},
            {
                "uid": {"type": rtype, "id": rid},
                "attrs": ({"registered": True} if rtype == "Tool" else {}),
                "parents": [],
            },
        ]
        r = self._cedar.is_authorized(request, POLICIES, entities, self.schema)
        allow = str(r.decision).endswith("Allow")
        # the deciding policy: Cedar reports it by position; the position maps to the rule id
        reasons = [
            POLICY_IDS[int(p.replace("policy", ""))] for p in r.diagnostics.reasons if p.startswith("policy")
        ]
        rule = reasons[0] if reasons else DEFAULT_DENY[0]
        errors = [str(e) for e in r.diagnostics.errors]
        d = Decision(
            id=f"PD-{next(self._ids):04d}",
            principal=principal.id,
            action=action,
            resource=resource,
            allow=allow,
            reason=REASONS[rule] + (f" (errors: {errors})" if errors else ""),
            policy=rule,
        )
        if self.events is not None:
            self.events.append(
                "policy.decision",
                decision=d.id,
                principal=principal.id,
                action=action,
                resource=resource,
                allow=allow,
                policy=rule,
                engine=self.engine,
            )
        return d
