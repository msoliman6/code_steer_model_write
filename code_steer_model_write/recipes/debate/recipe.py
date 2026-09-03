"""The debate recipe: hypotheses (A, attacked by B for rounds) -> the strongest supporting case
(A) -> the strongest challenge (B) -> A answers every challenge argument by id -> a fresh B
session scores the rubric and rules. Status: unproven until one clean live pass."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field

from ...artifacts.brief import Brief
from ...artifacts.debate import Case, Hypotheses, Rebuttal, Ruling
from ...artifacts.render import render
from ...artifacts.report import Carried, Report
from ...artifacts.store import Store
from ...driver.steps import ProgramContext, Step, StepKind
from ...gates.gate import GateBuilder, read_decision
from ...ids import Prefix, next_id
from ...review.rounds import ReviewLoop
from ...spec.base import Artifact
from ...spec.decisions import Gate, Question
from ...spec.findings import Arbitrated, Findings
from ...state.lock import atomic_write_text
from ...state.run import CarriedRecord, RunPaths, RunState
from ..base import CheckKind, EvalSpec, FigurePhrases, GateSpec, Recipe, RecipeSpec, StageSpec
from ..code_builder.recipe import CodeBuilder

ROOT = Path(__file__).resolve().parents[3]


class DebateParams(BaseModel):
    brief: Brief
    rubric: dict[str, float] = Field(
        default_factory=lambda: {
            "evidence_quality": 1.0,
            "novelty": 0.5,
            "feasibility": 1.0,
            "challenge_survival": 1.5,
        }
    )


SPEC = RecipeSpec(
    name="debate",
    version="0.1.0",
    status="unproven",
    assumes=[
        "the question fits one claim a judge can score on a rubric",
        "evidence is what the brief hands over; no tools search for more",
    ],
    if_wrong=[
        "a multi-claim question needs one debate per claim",
        "a retrieval stage (the research recipe) must precede it",
    ],
    params_model=DebateParams,
    roles={"author": "a", "checker": "b"},
    stages=[
        StageSpec(
            id="hypotheses",
            n=0,
            title="Hypotheses",
            emoji="💡",
            hue="blue",
            author="author",
            checker="checker",
            description="The author proposes up to five falsifiable hypotheses and picks one; the checker attacks the set for rounds; the author arbitrates by id.",
            figure=FigurePhrases(
                author="{A} proposes the hypotheses", checker="{B} attacks them", rounds="rounds"
            ),
            gates_after=["rubric"],
        ),
        StageSpec(
            id="cases",
            n=1,
            title="Cases",
            emoji="⚖️",
            hue="gold",
            author="author",
            checker="checker",
            description="The author builds the strongest supporting case; the checker builds the strongest challenge, both citing the hypothesis and each other by id. Code checks every cite and refuses hedge words.",
            figure=FigurePhrases(author="{A} argues for it", checker="{B} argues against it"),
        ),
        StageSpec(
            id="rebuttal",
            n=2,
            title="Rebuttal",
            emoji="🔁",
            hue="violet",
            author="author",
            checker="none",
            description="The author answers every challenge argument by id: conceded, with what it changes, or rebutted in twelve or more words that engage it. The claim is revised in one sentence.",
            figure=FigurePhrases(author="{A} answers every challenge by id"),
        ),
        StageSpec(
            id="judgment",
            n=3,
            title="Judgment",
            emoji="🧑‍⚖️",
            hue="red",
            author="checker",
            checker="none",
            description="A fresh checker session scores every rubric row and rules: supported, refuted or undecided. An undecided ruling comes to you.",
            figure=FigurePhrases(
                author="{B} scores the rubric and rules", second_line="supported · refuted · undecided"
            ),
            gates_after=["verdict"],
        ),
    ],
    gates=[
        GateSpec(
            id="rubric",
            after_stage="hypotheses",
            kind="input",
            trigger="always",
            title="Confirm the rubric weights",
            figure_label="You confirm the rubric",
        ),
        GateSpec(
            id="verdict",
            after_stage="judgment",
            kind="judgment",
            trigger="exception",
            title="Rule on an undecided debate",
            figure_label="You rule when undecided",
        ),
    ],
    evals=[
        EvalSpec(metric="rubric_total", tier="code"),
        EvalSpec(metric="citation_correctness", tier="code", target=1.0),
        EvalSpec(metric="conceded_ratio", tier="code", higher_is_better=False),
        EvalSpec(metric="carried_findings", tier="code", target=0, higher_is_better=False),
    ],
    required_checks={
        CheckKind.SCHEMA,
        CheckKind.CITES_RESOLVE,
        CheckKind.BANNED_WORDS,
        CheckKind.AI_REVIEW,
        CheckKind.AI_JUDGE,
        CheckKind.HUMAN_GATE,
        CheckKind.ARBITRATION_ENGAGES,
        CheckKind.ANTI_FATIGUE,
    },
    output_label="hypothesis · cases · ruling · REPORT.md",
    footnote=[
        "Every model box is a fresh agent — a new, independent context given only the markdown code rendered for it;",
        "every review round is handed the whole trajectory by code — the record is on disk, never in a thread.",
        "Slate boxes and every arrow are code: the driver sequences the run — a workflow enforced by code, not by agents.",
        "An agent's only power is filling in a JSON schema, enforced at generation by constrained decoding —",
        "no file reads, no shell, no edits, no tools: the agent answers; code writes every file and decides every step.",
    ],
)


class Debate(Recipe):
    spec = SPEC
    prompts_root = ROOT / "prompts" / "debate"
    fixtures_root = ROOT / "fixtures" / "debate"

    def __init__(self) -> None:
        arb = Arbitrated[Hypotheses]  # type: ignore[valid-type]
        arb.schema_title = "ArbitratedHypotheses"
        self.schemas: dict[str, type[Artifact]] = {
            "Hypotheses": Hypotheses,
            "Findings": Findings,
            arb.schema_name(): arb,
            "Case": Case,
            "Rebuttal": Rebuttal,
            "Ruling": Ruling,
        }
        self.code_steps: dict[str, Callable[[ProgramContext], None]] = {
            "brief": self._c_brief,
            "report": self._c_report,
        }
        self.checks: dict[str, Callable[[ProgramContext], list[str]]] = {}

    def provided_checks(self) -> set[CheckKind]:
        return set(SPEC.required_checks)

    def _loop(self, state: RunState) -> ReviewLoop:
        return ReviewLoop(
            key="hypotheses",
            artifact_key="hypotheses",
            schema=Hypotheses,
            reviewer_role="checker",
            author_role="author",
            cap=state.task.rounds,
            phase="0",
            review_prompt="review",
            arbitrate_prompt="arbitrate",
            after=["p0-hypotheses"],
            extra_sets={"ARTIFACT_NAME": "hypotheses"},
            transform=lambda prev, new: new.with_ids(prev),
        )

    def steps(self, state: RunState, paths: RunPaths, store: Store) -> list[Step]:
        run = paths.run_dir
        A = Step
        out = [
            A(
                key="p0-brief",
                kind=StepKind.CODE,
                phase="0",
                fn="brief",
                deliverables=["artifacts/brief/v001.json"],
                note="code writes the brief",
            )
        ]
        if not store.exists("brief"):
            return out
        brief_md = render(store.read("brief", Brief), "model")
        out.append(
            A(
                key="p0-hypotheses",
                kind=StepKind.AUTHOR,
                phase="0",
                after=["p0-brief"],
                prompt="hypotheses",
                schema_name="Hypotheses",
                role="author",
                sets={"BRIEF_MD": brief_md},
                rendered_keys=["brief"],
                land="hypotheses",
                fixture="hypotheses",
                deliverables=["artifacts/hypotheses/v001.json"],
                note="the author proposes the hypotheses",
            )
        )
        if not store.exists("hypotheses"):
            return out
        loop = self._loop(state)
        out += loop.steps(store, run)
        if not loop.is_done(run):
            return out
        out.append(
            A(
                key="p0-gate-rubric",
                kind=StepKind.GATE,
                phase="0",
                after=[loop.last_step_key(run)],
                gate="rubric.r1",
                deliverables=["gates/rubric.r1.decision.json"],
                note="you confirm the rubric weights",
            )
        )
        if read_decision(paths, "rubric.r1") is None:
            return out
        hyps = store.read("hypotheses", Hypotheses)
        hid = hyps.chosen_id()
        hyp_md = render(hyps, "model")
        out.append(
            A(
                key="p1-support",
                kind=StepKind.AUTHOR,
                phase="1",
                after=["p0-gate-rubric"],
                prompt="support",
                schema_name="Case",
                role="author",
                sets={"BRIEF_MD": brief_md, "HYPOTHESES_MD": hyp_md, "CHOSEN": hid},
                rendered_keys=["brief", "hypotheses"],
                land="support",
                fixture="support",
                check_extra={"side": "support"},
                deliverables=["artifacts/support/v001.json"],
                note="the author argues for it",
            )
        )
        out.append(
            A(
                key="p1-challenge",
                kind=StepKind.AUTHOR,
                phase="1",
                after=["p0-gate-rubric"],
                prompt="challenge",
                schema_name="Case",
                role="checker",
                sets={"BRIEF_MD": brief_md, "HYPOTHESES_MD": hyp_md, "CHOSEN": hid},
                rendered_keys=["brief", "hypotheses"],
                land="challenge",
                fixture="challenge",
                check_extra={"side": "challenge"},
                deliverables=["artifacts/challenge/v001.json"],
                note="the checker argues against it",
            )
        )
        if not (store.exists("support") and store.exists("challenge")):
            return out
        challenge = store.read("challenge", Case)
        support = store.read("support", Case)
        out.append(
            A(
                key="p2-rebuttal",
                kind=StepKind.AUTHOR,
                phase="2",
                after=["p1-support", "p1-challenge"],
                prompt="rebut",
                schema_name="Rebuttal",
                role="author",
                sets={
                    "HYPOTHESES_MD": hyp_md,
                    "SUPPORT_MD": render(support, "model"),
                    "CHALLENGE_MD": render(challenge, "model"),
                    "CHOSEN": hid,
                },
                rendered_keys=["hypotheses", "support", "challenge"],
                land="rebuttal",
                fixture="rebuttal",
                check_extra={"argument_ids": [a.id for a in challenge.arguments]},
                deliverables=["artifacts/rebuttal/v001.json"],
                note="the author answers every challenge by id",
            )
        )
        if not store.exists("rebuttal"):
            return out
        params = self.params(state.task)
        weights = self._weights(paths, params)
        out.append(
            A(
                key="p3-judge",
                kind=StepKind.AUTHOR,
                phase="3",
                after=["p2-rebuttal"],
                prompt="judge",
                schema_name="Ruling",
                role="checker",
                sets={
                    "HYPOTHESES_MD": hyp_md,
                    "SUPPORT_MD": render(support, "model"),
                    "CHALLENGE_MD": render(challenge, "model"),
                    "REBUTTAL_MD": render(store.read("rebuttal", Rebuttal), "model"),
                    "CHOSEN": hid,
                    "RUBRIC_MD": "\n".join(f"- **{k}** (weight {w})" for k, w in weights.items()),
                },
                rendered_keys=["hypotheses", "support", "challenge", "rebuttal"],
                land="ruling",
                fixture="judge",
                check_extra={"rubric": list(weights)},
                deliverables=["artifacts/ruling/v001.json"],
                note="a fresh checker session scores and rules",
            )
        )
        if not store.exists("ruling"):
            return out
        out.append(
            A(
                key="p3-gate-verdict",
                kind=StepKind.GATE,
                phase="3",
                after=["p3-judge"],
                gate="verdict.r1",
                deliverables=["gates/verdict.r1.decision.json"],
                note="you rule when the judge could not",
            )
        )
        if read_decision(paths, "verdict.r1") is None:
            return out
        out.append(
            A(
                key="p3-report",
                kind=StepKind.CODE,
                phase="3",
                after=["p3-gate-verdict"],
                fn="report",
                deliverables=["artifacts/report/v001.json", "REPORT.md"],
                note="code writes the report",
            )
        )
        return out

    def _weights(self, paths: RunPaths, params: DebateParams) -> dict[str, float]:
        d = read_decision(paths, "rubric.r1")
        w = dict(params.rubric)
        if d:
            for x in d.decisions:
                name = x.question_id.split(":", 1)[1] if ":" in x.question_id else None
                if name in w:
                    try:
                        w[name] = float(x.answer)
                    except ValueError:
                        pass
        return w

    def land(self, step: Step, value: Artifact, ctx: ProgramContext) -> list[str]:
        assert step.land
        if step.land.startswith("review:"):
            return self._loop(ctx.state).land(step, value, ctx)
        if step.land == "hypotheses":
            assert isinstance(value, Hypotheses)
            v = ctx.store.write("hypotheses", value.with_ids(None))
            return [f"artifacts/hypotheses/v{v:03d}.json"]
        if step.land in ("support", "challenge"):
            assert isinstance(value, Case)
            taken = []
            for k in ("support", "challenge"):
                if ctx.store.exists(k):
                    taken += [a.id for a in ctx.store.read(k, Case).arguments if a.id]
            v = ctx.store.write(step.land, value.with_ids(taken))
            return [f"artifacts/{step.land}/v{v:03d}.json"]
        if step.land == "ruling":
            assert isinstance(value, Ruling)
            value.id = next_id(Prefix.RULING, [])
            ctx.events.append(
                "judge.verdict",
                step=step.key,
                verdict=value.verdict,
                total=value.total(self._weights(ctx.paths, self.params(ctx.state.task))),
            )
        v = ctx.store.write(step.land, value)
        return [f"artifacts/{step.land}/v{v:03d}.json"]

    def gate_builders(self) -> dict[str, GateBuilder]:
        return {"rubric": self._g_rubric, "verdict": self._g_verdict}

    def _g_rubric(self, step: Step, ctx: ProgramContext) -> Gate:
        params = self.params(ctx.state.task)
        qs = [
            Question(
                id=f"Q-{i + 1:04d}:{name}",
                text=f"weight of {name}",
                kind="number",
                default=str(w),
                recommended=str(w),
                risky=False,
            )
            for i, (name, w) in enumerate(params.rubric.items())
        ]
        return Gate(
            id="rubric.r1",
            name="rubric",
            kind="input",
            title="Confirm the rubric weights",
            questions=qs,
            can_revise=False,
        )

    def _g_verdict(self, step: Step, ctx: ProgramContext) -> Gate:
        r = ctx.store.read("ruling", Ruling)
        carried = (
            []
            if r.verdict != "undecided"
            else [{"id": r.id, "kind": "undecided", "argument": r.argument[:300]}]
        )
        loop = self._loop(ctx.state)
        carried += [f.model_dump(mode="json") for f in loop.status(ctx.paths.run_dir).carried]
        qs = (
            [
                Question(
                    id="Q-0001",
                    text="The judge could not decide. Your ruling:",
                    kind="choice",
                    options=["supported", "refuted", "undecided"],
                    default=r.verdict,
                    recommended=r.verdict,
                    risky=True,
                )
            ]
            if r.verdict == "undecided"
            else []
        )
        return Gate(
            id="verdict.r1",
            name="verdict",
            kind="judgment",
            title="Rule on the debate",
            questions=qs,
            carried=carried,
            can_revise=False,
        )

    def _c_brief(self, ctx: ProgramContext) -> None:
        ctx.store.write("brief", self.params(ctx.state.task).brief)

    def _c_report(self, ctx: ProgramContext) -> None:
        run = ctx.paths.run_dir
        st = ctx.state
        ruling = ctx.store.read("ruling", Ruling)
        weights = self._weights(ctx.paths, self.params(st.task))
        reb = ctx.store.read("rebuttal", Rebuttal)
        loop = self._loop(st)
        carried = [
            Carried(
                kind="finding",
                id=f.id or "",
                summary=f"[{f.severity}/{f.klass}] {f.argument[:160]}",
                from_step=f"hypotheses round {f.round}",
            )
            for f in loop.status(run).carried + loop.status(run).escalated
        ]
        d = read_decision(ctx.paths, "verdict.r1")
        verdict = ruling.verdict
        if d and d.decisions and d.decisions[0].answered_by == "human":
            verdict = d.decisions[0].answer
        if ruling.verdict == "undecided":
            carried.append(
                Carried(
                    kind="ambiguity",
                    id=ruling.id or "",
                    summary=f"judge undecided; human ruled {verdict}"
                    if verdict != "undecided"
                    else "undecided",
                    from_step="judgment",
                )
            )
        conceded = sum(1 for i in reb.items if i.status == "conceded")
        metrics = {
            "rubric_total": ruling.total(weights),
            "citation_correctness": 1.0,
            "conceded_ratio": round(conceded / max(len(reb.items), 1), 3),
            "carried_findings": len(carried),
        }
        atomic_write_text(run / "evals.json", json.dumps(metrics, indent=2))
        rep = Report(
            run_id=st.run_id,
            recipe=self.name,
            outcome=(st.outcome.value if st.outcome else "running"),
            verdict=f"{verdict} · rubric {metrics['rubric_total']:.2f} · {conceded}/{len(reb.items)} challenges conceded",
            carried=carried,
            waste=CodeBuilder._waste(ctx),
            flagged_decisions=[x["id"] for x in CodeBuilder._flagged(ctx)],
            halts=st.resumed_count,
            resumed=st.resumed_count,
        )
        ctx.store.write("report", rep)
        atomic_write_text(
            run / "REPORT.md", render(rep, "human") + "\n\n## Ruling\n\n" + render(ruling, "human")
        )
        st.carried = [
            CarriedRecord(kind=c.kind, id=c.id, summary=c.summary, from_step=c.from_step) for c in carried
        ]
        st.save(ctx.paths)

    def fakers(self, paths: RunPaths, store: Store) -> dict[str, Callable[[Any], dict[str, Any]]]:
        from .fake import fakers

        return fakers(paths, store)
