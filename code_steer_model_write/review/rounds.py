"""The review loop -- bounded by code, carrying the full trajectory verbatim (rules 3, 5, 8, 9).

Round n: the reviewer (the other side) files findings on the current artifact; the author
arbitrates each by id and re-emits the whole artifact. Round n exists only when round n-1's
files exist. Rounds 1..cap are answered; round cap+1 is the closing read nobody answers, so
the last revision is never unreviewed. The packet handed to every call is the current
artifact, every prior round verbatim and a code-computed diff -- never a summary. Convergence
is computed here from the records; a model is never asked whether things are getting better.
Findings still open after the closing read are carried into the report. A finding re-raised
after two rejections is escalated to the human (two informed parties disagreeing twice will
not be settled by a third exchange). Two or more rounds with zero findings classed actionable
is doubt theater: the reviewer is validating, not reviewing -- a check, not a prompt.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from ..artifacts.render import render
from ..artifacts.store import Store
from ..config import review_round_open
from ..driver.steps import ProgramContext, Step, StepKind
from ..ids import Prefix, assign
from ..spec.base import Artifact
from ..spec.findings import Arbitrated, Finding, Findings, FindingStatus, Klass, Severity, Verdict
from ..state.lock import atomic_write_text


class LoopStatus(BaseModel):
    rounds_filed: int
    converged: bool
    closing_done: bool
    carried: list[Finding]
    escalated: list[Finding]
    doubt_theater: bool
    last_verdict: str | None


class ReviewLoop:
    def __init__(
        self,
        *,
        key: str,
        artifact_key: str,
        schema: type[Artifact],
        reviewer_role: str,
        author_role: str,
        cap: int,
        phase: str,
        review_prompt: str,
        arbitrate_prompt: str,
        after: list[str] | None = None,
        fixture_prefix: str | None = None,
        extra_sets: dict[str, str] | None = None,
    ) -> None:
        self.key = key
        self.artifact_key = artifact_key
        self.schema = schema
        self.arb_schema = Arbitrated[schema]  # type: ignore[valid-type]
        self.arb_schema.schema_title = f"Arbitrated{schema.__name__}"
        self.reviewer_role = reviewer_role
        self.author_role = author_role
        self.cap = cap
        self.phase = phase
        self.review_prompt = review_prompt
        self.arbitrate_prompt = arbitrate_prompt
        self.after = after or []
        self.fixture_prefix = fixture_prefix
        self.extra_sets = extra_sets or {}

    # ---- files -------------------------------------------------------------------------

    def dir(self, run_dir: Path) -> Path:
        return run_dir / "review" / self.key

    def findings_path(self, run_dir: Path, n: int) -> Path:
        return self.dir(run_dir) / f"round-{n}.findings.json"

    def arbitration_path(self, run_dir: Path, n: int) -> Path:
        return self.dir(run_dir) / f"round-{n}.arbitration.json"

    def read_findings(self, run_dir: Path, n: int) -> list[Finding] | None:
        p = self.findings_path(run_dir, n)
        if not p.exists():
            return None
        return [Finding.model_validate(x) for x in json.loads(p.read_text(encoding="utf-8"))]

    def _write_findings(self, run_dir: Path, n: int, items: list[Finding]) -> None:
        atomic_write_text(
            self.findings_path(run_dir, n), json.dumps([f.model_dump(mode="json") for f in items], indent=2)
        )

    def all_findings(self, run_dir: Path) -> list[Finding]:
        out: list[Finding] = []
        n = 1
        while (fs := self.read_findings(run_dir, n)) is not None:
            out += fs
            n += 1
        return out

    def rounds_filed(self, run_dir: Path) -> int:
        n = 0
        while self.findings_path(run_dir, n + 1).exists():
            n += 1
        return n

    # ---- derived state (rule 8: computed, never asked) -------------------------------------

    def status(self, run_dir: Path) -> LoopStatus:
        filed = self.rounds_filed(run_dir)
        converged = False
        closing_done = False
        last_verdict = None
        for n in range(1, filed + 1):
            fs = self.read_findings(run_dir, n) or []
            last_verdict = "APPROVED" if not fs else "REVISE"
            if review_round_open(n, self.cap) == "closing":
                closing_done = True
                converged = not fs
            elif not fs:
                converged = True
                break
        allf = self.all_findings(run_dir)
        carried = [f for f in allf if f.status is FindingStatus.CARRIED]
        escalated = [f for f in allf if f.status is FindingStatus.ESCALATED]
        rounds_with_findings = [self.read_findings(run_dir, n) or [] for n in range(1, filed + 1)]
        non_actionable_rounds = sum(
            1 for fs in rounds_with_findings if not any(f.klass is Klass.ACTIONABLE for f in fs)
        )
        return LoopStatus(
            rounds_filed=filed,
            converged=converged,
            closing_done=closing_done,
            carried=carried,
            escalated=escalated,
            doubt_theater=filed >= 2 and non_actionable_rounds >= 2,
            last_verdict=last_verdict,
        )

    def is_done(self, run_dir: Path) -> bool:
        st = self.status(run_dir)
        return st.converged or st.closing_done

    # ---- steps (rule 1: derived from the files) ----------------------------------------------

    def steps(self, store: Store, run_dir: Path) -> list[Step]:
        """Every step of the loop, done or pending, derived from the files: a program lists all
        its steps so the driver can verify each deliverable (rule 10)."""
        if not store.exists(self.artifact_key):
            return []
        out: list[Step] = []
        prev = self.after
        for n in range(1, self.cap + 2):
            fs = self.read_findings(run_dir, n)
            out.append(self._review_step(n, prev, store, run_dir))
            if fs is None:
                break
            mode = review_round_open(n, self.cap)
            if mode == "closing" or not fs:
                break  # converged, or the closing read is filed: the loop is over
            out.append(self._arbitrate_step(n, prev, store, run_dir, fs))
            if not self.arbitration_path(run_dir, n).exists():
                break
            prev = [f"{self.key}-arbitrate-r{n}"]
        return out

    def last_step_key(self, run_dir: Path) -> str:
        """The key the next stage waits on once the loop is done."""
        return f"{self.key}-review-r{self.rounds_filed(run_dir)}"

    def _review_step(self, n: int, after: list[str], store: Store, run_dir: Path) -> Step:
        closing = review_round_open(n, self.cap) == "closing"
        return Step(
            key=f"{self.key}-review-r{n}",
            kind=StepKind.AUTHOR,
            phase=self.phase,
            after=list(after),
            prompt=self.review_prompt,
            schema_name="Findings",
            role=self.reviewer_role,
            sets=self.packet(n, store, run_dir),
            rendered_keys=[self.artifact_key],
            fixture=f"{self.fixture_prefix}.review-r{n}" if self.fixture_prefix else None,
            land=f"review:{self.key}:findings:{n}",
            deliverables=[str(self.findings_path(run_dir, n).relative_to(run_dir))],
            note=(
                f"closing read of the {self.artifact_key}"
                if closing
                else f"round {n} of {self.cap}: the {self.artifact_key} is attacked"
            ),
        )

    def _arbitrate_step(
        self, n: int, after: list[str], store: Store, run_dir: Path, fs: list[Finding]
    ) -> Step:
        sets = self.packet(n, store, run_dir)
        sets["FINDINGS_MD"] = self.render_findings(fs, audience="model")
        return Step(
            key=f"{self.key}-arbitrate-r{n}",
            kind=StepKind.AUTHOR,
            phase=self.phase,
            after=[f"{self.key}-review-r{n}"],
            prompt=self.arbitrate_prompt,
            schema_name=self.arb_schema.schema_name(),
            role=self.author_role,
            sets=sets,
            rendered_keys=[self.artifact_key],
            fixture=f"{self.fixture_prefix}.arbitrate-r{n}" if self.fixture_prefix else None,
            check_extra={"finding_ids": [f.id for f in fs if f.status is FindingStatus.OPEN]},
            land=f"review:{self.key}:arbitration:{n}",
            deliverables=[str(self.arbitration_path(run_dir, n).relative_to(run_dir))],
            note=f"round {n}: the author arbitrates {len(fs)} finding(s) and re-emits the {self.artifact_key}",
        )

    # ---- the packet (rule 8: verbatim history + computed diff) ----------------------------

    def packet(self, n: int, store: Store, run_dir: Path) -> dict[str, str]:
        current = store.read(self.artifact_key, self.schema)
        latest = store.latest_version(self.artifact_key) or 1
        sets: dict[str, str] = {"ARTIFACT_MD": render(current, "model"), "ROUND_RULE": self.round_rule(n)}
        history: list[str] = []
        for k in range(1, n):
            fs = self.read_findings(run_dir, k) or []
            history.append(
                f"### Round {k}: findings\n\n"
                + (self.render_findings(fs, audience="model") if fs else "(none: APPROVED)")
            )
            ap = self.arbitration_path(run_dir, k)
            if ap.exists():
                arb = json.loads(ap.read_text(encoding="utf-8"))
                lines = [
                    f"- **{d['id']}** {d['status']}: {d['arbitration']}" for d in arb.get("decisions", [])
                ]
                history.append(f"### Round {k}: the author's arbitration\n\n" + "\n".join(lines))
        sets["HISTORY_MD"] = "\n\n".join(history) if history else "(this is the first round)"
        if latest >= 2:
            a = render(store.read(self.artifact_key, self.schema, latest - 1), "model")
            b = render(current, "model")
            sets["DIFF_MD"] = (
                "```diff\n" + store.diff(self.artifact_key, latest - 1, latest, rendered=(a, b)) + "\n```"
            )
        else:
            sets["DIFF_MD"] = "(no earlier version)"
        sets.update(self.extra_sets)
        return sets

    def round_rule(self, n: int) -> str:
        mode = review_round_open(n, self.cap)
        if mode == "closing":
            return (
                f"This is the closing read after {self.cap} answered round(s). Nobody answers it: anything you file is "
                "carried into the report as unresolved. File only what still stands."
            )
        return (
            f"Round {n} of {self.cap}. `APPROVED` only if you found nothing. Finding nothing after several rounds is "
            "weak evidence: say so in the argument of a `minor` finding rather than inventing a defect, and rather "
            "than approving because you are tired. Every finding carries a reconcile class; a `contract_misread` "
            "means the input says otherwise and you cite where."
        )

    @staticmethod
    def render_findings(fs: list[Finding], *, audience: Literal["model", "human"]) -> str:
        if not fs:
            return "(none)"
        lines = [
            "| id | severity | class | required | cites | status | argument |",
            "|---|---|---|---|---|---|---|",
        ]
        for f in fs:
            lines.append(
                f"| {f.id} | {f.severity} | {f.klass} | {'yes' if f.required else 'no'} | {', '.join(f.cites)} | {f.status} | {f.argument.replace('|', '/')} |"
            )
        return "\n".join(lines)

    # ---- landing (rule 6: code writes; rule 5: code assigns ids) ------------------------------

    def land(self, step: Step, value: Artifact, ctx: ProgramContext) -> list[str]:
        assert step.land and step.land.startswith(f"review:{self.key}:")
        _, _, what, n_s = step.land.split(":")
        n = int(n_s)
        if what == "findings":
            assert isinstance(value, Findings)
            return self._land_findings(n, value, ctx)
        assert what == "arbitration"
        return self._land_arbitration(n, value, ctx)

    def _land_findings(self, n: int, value: Findings, ctx: ProgramContext) -> list[str]:
        run_dir = ctx.paths.run_dir
        taken = [f.id for f in self.all_findings(run_dir) if f.id]
        ids = assign(Prefix.FINDING, len(value.findings), taken)
        closing = review_round_open(n, self.cap) == "closing"
        items: list[Finding] = []
        earlier = self.all_findings(run_dir)
        for f, fid in zip(value.findings, ids, strict=True):
            g = f.model_copy(
                update={
                    "id": fid,
                    "round": n,
                    "status": FindingStatus.CARRIED if closing else FindingStatus.OPEN,
                }
            )
            rejections = [
                e
                for e in earlier
                if e.status is FindingStatus.REJECTED
                and set(e.cites) == set(g.cites)
                and e.severity == g.severity
            ]
            if not closing and len(rejections) >= 2:
                g.status = FindingStatus.ESCALATED
                ctx.events.append(
                    "finding.carried",
                    step=ctx.step.key,
                    id=fid,
                    escalated=True,
                    after_rejections=len(rejections),
                )
            items.append(g)
            ctx.events.append(
                "finding.filed",
                step=ctx.step.key,
                id=fid,
                severity=g.severity.value,
                klass=g.klass.value,
                cites=g.cites,
                round=n,
            )
        self._write_findings(run_dir, n, items)
        st = self.status(run_dir)
        ctx.events.append(
            "round.closed",
            step=ctx.step.key,
            loop=self.key,
            round=n,
            verdict=value.verdict,
            findings=len(items),
            converged=st.converged,
            closing=closing,
            carried=len(st.carried),
            doubt_theater=st.doubt_theater,
        )
        if st.doubt_theater:
            ctx.events.append(
                "check.result",
                step=ctx.step.key,
                problems=[
                    f"doubt_theater: {n} rounds and no finding classed actionable -- the reviewer is validating, not reviewing"
                ],
            )
        return [str(self.findings_path(run_dir, n).relative_to(run_dir))]

    def _land_arbitration(self, n: int, value: Any, ctx: ProgramContext) -> list[str]:
        run_dir = ctx.paths.run_dir
        fs = self.read_findings(run_dir, n) or []
        by_id = {d.id: d for d in value.decisions}
        for f in fs:
            d = by_id.get(f.id)
            if d is None or f.status is not FindingStatus.OPEN:
                continue
            f.status = FindingStatus.ACCEPTED if d.status == "accepted" else FindingStatus.REJECTED
            f.arbitration = d.arbitration
            ctx.events.append("finding.decided", step=ctx.step.key, id=f.id, status=f.status.value)
        self._write_findings(run_dir, n, fs)
        v = ctx.store.write(self.artifact_key, value.artifact)
        atomic_write_text(
            self.arbitration_path(run_dir, n),
            json.dumps(
                {
                    "round": n,
                    "artifact_version": v,
                    "decisions": [d.model_dump(mode="json") for d in value.decisions],
                },
                indent=2,
            ),
        )
        return [
            str(self.arbitration_path(run_dir, n).relative_to(run_dir)),
            f"artifacts/{self.artifact_key}/v{v:03d}.json",
        ]

    def verdict(self, run_dir: Path) -> Verdict:
        st = self.status(run_dir)
        return Verdict.of(
            self.all_findings(run_dir), escalate_at=Severity.BLOCKING, cap_reached=st.closing_done
        )
