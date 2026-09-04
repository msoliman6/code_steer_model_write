"""The code-builder recipe: plan -> contract -> freeze -> verification design by the other side
-> tests by one side, source by the other -> null run -> verify -> triage -> report.

Every step is derived from the files in the run dir (rule 1). Roles: `author` (side A: plan,
contract, source, coverage review, ruling on the test) and `checker` (side B: reviews, the
verification spec, the tests, ruling on the code). Whoever wrote a thing never checks it
(rule 3).
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field

from ...artifacts.brief import Brief
from ...artifacts.contract import Contract
from ...artifacts.files import FilesAuthor
from ...artifacts.ledger import AssumptionsLedger
from ...artifacts.plan import Plan
from ...artifacts.render import render
from ...artifacts.report import Carried, Report, WasteRow
from ...artifacts.results import Results, Ruling
from ...artifacts.store import Store
from ...artifacts.tasks import TaskRow, Tasks
from ...artifacts.vspec import VerificationSpec
from ...checks.code import set_difference
from ...checks.nullimpl import null_module
from ...checks.pycheck import check_python
from ...checks.runtests import run_all
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

ROOT = Path(__file__).resolve().parents[3]


class CodeBuilderParams(BaseModel):
    brief: Brief
    fix_rounds: int = Field(default=1, ge=0, le=3)


SPEC = RecipeSpec(
    name="code_builder",
    version="0.1.0",
    status="unproven",
    assumes=[
        "the deliverable is one importable Python module per block, tested by pytest",
        "a block's contract fits one model call; the source of a block fits one file",
        "ruff, pyright and pytest are on PATH (each SKIPPED and recorded when not)",
    ],
    if_wrong=[
        "a multi-file block needs one implementer call per file and an ownership check per file",
        "a non-Python target needs a check profile (compile, lint, test runner) for its language",
    ],
    params_model=CodeBuilderParams,
    roles={"author": "a", "checker": "b"},
    stages=[
        StageSpec(
            id="plan",
            side_labels={"author": "writes the plan", "checker": "attacks it"},
            n=0,
            title="Plan",
            emoji="🗺",
            hue="blue",
            author="author",
            checker="checker",
            description="The author reads the brief and the confirmed assumptions and writes the plan: blocks, boundaries, what is rejected. The checker attacks it for rounds; the author arbitrates every finding by id.",
            figure=FigurePhrases(author="{A} writes the plan", checker="{B} attacks it", rounds="rounds"),
        ),
        StageSpec(
            id="contracts",
            side_labels={"author": "writes the contract", "checker": "attacks it, then audits"},
            n=1,
            title="Contracts",
            emoji="📜",
            hue="gold",
            author="author",
            checker="checker",
            description="The author writes the contract for every block: vocabulary, interface, invariants, negative scope, failure policy, tolerances and the algorithm. The checker attacks it for rounds, then a fresh session audits it once. You confirm the blocks; the contract is frozen and hashed in two views.",
            figure=FigurePhrases(
                author="{A} writes the contract", checker="{B} attacks it", rounds="rounds + a fresh audit"
            ),
            freeze_label="Freeze — the contract is hashed",
            gates_after=["blocks", "tolerances"],
        ),
        StageSpec(
            id="verification",
            side_labels={"checker": "writes the properties", "author": "reviews coverage"},
            n=2,
            title="Verification Design",
            emoji="🧪",
            hue="violet",
            author="checker",
            checker="author",
            description="The checker writes the properties from the test-visible contract alone, never having seen the algorithm. The author reviews coverage; the checker arbitrates. A code check confirms every clause is cited.",
            figure=FigurePhrases(
                author="{B} writes the properties", checker="{A} reviews coverage", extra=["{B} arbitrates"]
            ),
            gates_after=["verification"],
        ),
        StageSpec(
            id="build",
            side_labels={"checker": "writes the tests", "author": "writes the source"},
            n=3,
            title="Build",
            emoji="🔨",
            hue="teal",
            author="author",
            checker="checker",
            description="The checker writes the tests without the source; the author writes the source without the tests. Code compiles, lints and type-checks each, refuses a test that passes against the null implementation, then merges.",
            figure=FigurePhrases(
                author="{B} writes the tests\nwithout the source",
                checker="{A} writes the source\nwithout the tests",
                extra=["merge · null run · real run"],
            ),
            qualifier="TWO ISOLATED AUTHORS",
        ),
        StageSpec(
            id="verify",
            side_labels={"author": "rules on the test", "checker": "rules on the code"},
            n=4,
            title="Verification Run",
            emoji="🚑",
            hue="red",
            author="author",
            checker="checker",
            description="Every property runs three times against the source and once against the null. Each failure is ruled on by the side that did not write the failing thing: is the test wrong? If not, is it the contract, the algorithm or the implementation? It is fixed and re-run within the cap.",
            figure=FigurePhrases(
                author="Each failure is ruled on by the side that did not write it",
                second_line="fix · re-run",
            ),
        ),
    ],
    gates=[
        GateSpec(
            id="ledger",
            after_stage="plan",
            kind="input",
            trigger="always",
            title="Confirm the assumptions",
            figure_label="You confirm the assumptions",
        ),
        GateSpec(
            id="blocks",
            after_stage="contracts",
            kind="judgment",
            trigger="always",
            title="Confirm the blocks",
            figure_label="You confirm the blocks",
        ),
        GateSpec(
            id="tolerances",
            after_stage="contracts",
            kind="input",
            trigger="conditional",
            title="Set the open tolerances",
            figure_label="You set the tolerances",
        ),
        GateSpec(
            id="verification",
            after_stage="verification",
            kind="judgment",
            trigger="exception",
            title="Confirm the verification design",
            figure_label="You confirm the verification",
        ),
    ],
    evals=[
        EvalSpec(metric="pass_rate", tier="code", target=1.0),
        EvalSpec(metric="null_fail_rate", tier="code", target=1.0),
        EvalSpec(metric="carried_findings", tier="code", target=0, higher_is_better=False),
        EvalSpec(metric="rounds_to_converge", tier="code", higher_is_better=False),
        EvalSpec(metric="refused_answers", tier="code", higher_is_better=False),
    ],
    required_checks={
        CheckKind.SCHEMA,
        CheckKind.CITES_RESOLVE,
        CheckKind.BANNED_WORDS,
        CheckKind.NULL_RUN,
        CheckKind.COVERAGE,
        CheckKind.ENVELOPE,
        CheckKind.COMPILE,
        CheckKind.AI_REVIEW,
        CheckKind.HUMAN_GATE,
        CheckKind.ARBITRATION_ENGAGES,
        CheckKind.ANTI_FATIGUE,
    },
    output_label="src · tests · REPORT.md · PAGE.html",
    footnote=[
        "Every model box is a fresh agent — a new, independent context given only the markdown code rendered for it;",
        "every review round is handed the whole trajectory by code — the record is on disk, never in a thread.",
        "Slate boxes and every arrow are code: the driver sequences the run — a workflow enforced by code, not by agents.",
        "An agent's only power is filling in a JSON schema, enforced at generation by constrained decoding —",
        "no file reads, no shell, no edits, no tools: the agent answers; code writes every file and decides every step.",
    ],
)


def _brief_md(brief: Brief) -> str:
    return render(brief, "model")


class CodeBuilder(Recipe):
    spec = SPEC
    prompts_root = ROOT / "prompts" / "code_builder"
    fixtures_root = ROOT / "fixtures" / "code_builder"

    def __init__(self) -> None:
        self.schemas: dict[str, type[Artifact]] = {
            "AssumptionsLedger": AssumptionsLedger,
            "Plan": Plan,
            "Contract": Contract,
            "Findings": Findings,
            "VerificationSpec": VerificationSpec,
            "FilesAuthor": FilesAuthor,
            "Ruling": Ruling,
        }
        for base in (Plan, Contract, VerificationSpec):  # the arbitration schemas the loops answer with
            arb = Arbitrated[base]  # type: ignore[valid-type]
            arb.schema_title = f"Arbitrated{base.__name__}"
            self.schemas[arb.schema_name()] = arb
        self.code_steps: dict[str, Callable[[ProgramContext], None]] = {
            "brief": self._c_brief,
            "freeze": self._c_freeze,
            "fill_tolerances": self._c_fill_tolerances,
            "tasks": self._c_tasks,
            "verify": self._c_verify,
            "report": self._c_report,
        }
        self.checks: dict[str, Callable[[ProgramContext], list[str]]] = {
            "coverage": self._k_coverage,
            "compile_answer": self._k_compile,
            "null_run": self._k_null_run,
            "impl_steps": self._k_impl_steps,
            "lint_answer": self._k_lint,
        }

    def provided_checks(self) -> set[CheckKind]:
        return {
            CheckKind.SCHEMA,
            CheckKind.CITES_RESOLVE,
            CheckKind.BANNED_WORDS,
            CheckKind.ENVELOPE,
            CheckKind.AI_REVIEW,
            CheckKind.HUMAN_GATE,
            CheckKind.ARBITRATION_ENGAGES,
            CheckKind.ANTI_FATIGUE,
            CheckKind.COMPILE,
            CheckKind.NULL_RUN,
            CheckKind.COVERAGE,
        }

    # ---- loops (rule 8) -----------------------------------------------------------------

    def _loops(self, state: RunState) -> dict[str, ReviewLoop]:
        cap = state.task.rounds
        return {
            "plan": ReviewLoop(
                key="plan",
                artifact_key="plan",
                schema=Plan,
                reviewer_role="checker",
                author_role="author",
                cap=cap,
                phase="0",
                review_prompt="review",
                arbitrate_prompt="arbitrate",
                after=["p0-plan"],
                extra_sets={"ARTIFACT_NAME": "plan"},
                transform=lambda prev, new: new.with_ids(prev),
            ),
            "contract": ReviewLoop(
                key="contract",
                artifact_key="contract",
                schema=Contract,
                reviewer_role="checker",
                author_role="author",
                cap=cap,
                phase="1",
                review_prompt="review",
                arbitrate_prompt="arbitrate",
                after=["p1-contract"],
                extra_sets={"ARTIFACT_NAME": "contract"},
                transform=lambda prev, new: new.with_ids(prev),
            ),
            "contract_audit": ReviewLoop(
                key="contract_audit",
                artifact_key="contract",
                schema=Contract,
                reviewer_role="checker",
                author_role="author",
                cap=1,
                phase="1",
                review_prompt="audit",
                arbitrate_prompt="arbitrate",
                extra_sets={"ARTIFACT_NAME": "contract"},
                transform=lambda prev, new: new.with_ids(prev),
            ),
            "vspec": ReviewLoop(
                key="vspec",
                artifact_key="vspec",
                schema=VerificationSpec,
                reviewer_role="author",
                author_role="checker",
                cap=cap,
                phase="2",
                review_prompt="coverage",
                arbitrate_prompt="vspec-arbitrate",
                after=["p2-vspec"],
                extra_sets={"ARTIFACT_NAME": "verification spec"},
                transform=lambda prev, new: new.with_ids(
                    [p.id for p in prev.properties if p.id] + [g.id for g in prev.contract_gaps if g.id]
                ),
            ),
        }

    # ---- the generator (rule 1: derived from the files) -------------------------------------

    def steps(self, state: RunState, paths: RunPaths, store: Store) -> list[Step]:
        return self._with_stage_roles(self._steps(state, paths, store), state)

    def _with_stage_roles(self, steps: list[Step], state: RunState) -> list[Step]:
        from ...settings_form import stage_role

        phase_stage = {str(st.n): st.id for st in self.spec.stages}
        for s in steps:
            if s.kind is StepKind.AUTHOR and s.role and s.phase in phase_stage:
                rs = stage_role(state.task, phase_stage[s.phase], s.role)
                s.model, s.effort = rs.model, rs.effort
        return steps

    def _steps(self, state: RunState, paths: RunPaths, store: Store) -> list[Step]:
        run = paths.run_dir
        loops = self._loops(state)
        out: list[Step] = []
        A = Step
        out.append(
            A(
                key="p0-brief",
                kind=StepKind.CODE,
                phase="0",
                fn="brief",
                deliverables=["artifacts/brief/v001.json"],
                note="code writes the brief",
            )
        )
        if not store.exists("brief"):
            return out
        brief_md = _brief_md(store.read("brief", Brief))
        out.append(
            A(
                key="p0-ledger",
                kind=StepKind.AUTHOR,
                phase="0",
                after=["p0-brief"],
                prompt="ledger",
                schema_name="AssumptionsLedger",
                role="author",
                sets={"BRIEF_MD": brief_md},
                rendered_keys=["brief"],
                land="ledger",
                fixture="ledger",
                deliverables=["artifacts/ledger/v001.json"],
                note="the author lists the assumptions the plan will rest on",
            )
        )
        if not store.exists("ledger"):
            return out
        out.append(
            A(
                key="p0-gate-ledger",
                kind=StepKind.GATE,
                phase="0",
                after=["p0-ledger"],
                gate="ledger.r1",
                deliverables=["gates/ledger.r1.decision.json"],
                note="you confirm the assumptions, by exception",
            )
        )
        if read_decision(paths, "ledger.r1") is None:
            return out
        ledger_md = render(store.read("ledger", AssumptionsLedger), "model")
        out.append(
            A(
                key="p0-plan",
                kind=StepKind.AUTHOR,
                phase="0",
                after=["p0-gate-ledger"],
                prompt="plan",
                schema_name="Plan",
                role="author",
                sets={"BRIEF_MD": brief_md, "LEDGER_MD": ledger_md},
                rendered_keys=["brief", "ledger"],
                land="plan",
                fixture="plan",
                deliverables=["artifacts/plan/v001.json"],
                note="the author writes the plan",
            )
        )
        if not store.exists("plan"):
            return out
        out += loops["plan"].steps(store, run)
        if not loops["plan"].is_done(run):
            return out
        plan_md = render(store.read("plan", Plan), "model")
        out.append(
            A(
                key="p1-contract",
                kind=StepKind.AUTHOR,
                phase="1",
                after=[loops["plan"].last_step_key(run)],
                prompt="contract",
                schema_name="Contract",
                role="author",
                sets={"BRIEF_MD": brief_md, "PLAN_MD": plan_md, "LEDGER_MD": ledger_md},
                rendered_keys=["brief", "plan", "ledger"],
                land="contract",
                fixture="contract",
                deliverables=["artifacts/contract/v001.json"],
                note="the author writes the contract",
            )
        )
        if not store.exists("contract"):
            return out
        out += loops["contract"].steps(store, run)
        if not loops["contract"].is_done(run):
            return out
        loops["contract_audit"].after = [loops["contract"].last_step_key(run)]
        out += loops["contract_audit"].steps(store, run)
        if not loops["contract_audit"].is_done(run):
            return out
        # the blocks gate, with revise rounds
        prev = loops["contract_audit"].last_step_key(run)
        r = 1
        while True:
            gid = f"blocks.r{r}"
            out.append(
                A(
                    key=f"p1-gate-blocks-r{r}",
                    kind=StepKind.GATE,
                    phase="1",
                    after=[prev],
                    gate=gid,
                    deliverables=[f"gates/{gid}.decision.json"],
                    note="you confirm the blocks",
                )
            )
            d = read_decision(paths, gid)
            if d is None:
                return out
            if d.action == "proceed":
                break
            key = f"p1-contract-revise-r{r}"
            comments = (
                "\n".join(f"- **{k}**: {v}" for k, v in d.comments.items())
                or "(no comments; the gate was sent back)"
            )
            out.append(
                A(
                    key=key,
                    kind=StepKind.AUTHOR,
                    phase="1",
                    after=[f"p1-gate-blocks-r{r}"],
                    prompt="contract-revise",
                    schema_name="Contract",
                    role="author",
                    land="contract",
                    fixture="contract",
                    sets={
                        "CONTRACT_MD": render(store.read("contract", Contract), "model"),
                        "COMMENTS_MD": comments,
                    },
                    rendered_keys=["contract"],
                    deliverables=[f"gates/revise-r{r}.done"],
                    note="the author revises the contract on your words",
                )
            )
            if not (paths.run_dir / "gates" / f"revise-r{r}.done").exists():
                return out
            prev = key
            r += 1
        out.append(
            A(
                key="p1-freeze",
                kind=StepKind.CODE,
                phase="1",
                after=[f"p1-gate-blocks-r{r}"],
                fn="freeze",
                deliverables=["freeze.json", "CONTRACT.full.md", "CONTRACT.test-visible.md"],
                note="freeze: the contract is hashed",
            )
        )
        if not (run / "freeze.json").exists():
            return out
        contract = store.read("contract", Contract)
        open_tol = [t for t in contract.tolerances if t.value == "UNDECIDED"]
        after_tol = ["p1-freeze"]
        if open_tol:
            out.append(
                A(
                    key="p1-gate-tolerances",
                    kind=StepKind.GATE,
                    phase="1",
                    after=["p1-freeze"],
                    gate="tolerances.r1",
                    deliverables=["gates/tolerances.r1.decision.json"],
                    note="you set the open tolerances",
                )
            )
            if read_decision(paths, "tolerances.r1") is None:
                return out
            out.append(
                A(
                    key="p1-fill",
                    kind=StepKind.CODE,
                    phase="1",
                    after=["p1-gate-tolerances"],
                    fn="fill_tolerances",
                    deliverables=["tolerances.filled"],
                    note="code fills the tolerance slots and re-hashes",
                )
            )
            if not (run / "tolerances.filled").exists():
                return out
            after_tol = ["p1-fill"]
            contract = store.read("contract", Contract)
        tv_md = render(contract.test_visible(), "model", drop={"algorithm"})
        out.append(
            A(
                key="p2-vspec",
                kind=StepKind.AUTHOR,
                phase="2",
                after=after_tol,
                prompt="vspec",
                schema_name="VerificationSpec",
                role="checker",
                sets={"CONTRACT_TV_MD": tv_md},
                rendered_keys=["contract"],
                land="vspec",
                fixture="vspec",
                deliverables=["artifacts/vspec/v001.json"],
                note="the checker writes the properties from the test-visible contract",
            )
        )
        if not store.exists("vspec"):
            return out
        loops["vspec"].extra_sets["CONTRACT_TV_MD"] = tv_md
        out += loops["vspec"].steps(store, run)
        if not loops["vspec"].is_done(run):
            return out
        out.append(
            A(
                key="p2-coverage",
                kind=StepKind.CHECK,
                phase="2",
                after=[loops["vspec"].last_step_key(run)],
                fn="coverage",
                on_problems="carry",
                deliverables=["coverage.json"],
                note="code checks every clause is cited by a property",
            )
        )
        if not (run / "coverage.json").exists():
            return out
        out.append(
            A(
                key="p2-gate-verification",
                kind=StepKind.GATE,
                phase="2",
                after=["p2-coverage"],
                gate="verification.r1",
                deliverables=["gates/verification.r1.decision.json"],
                note="you confirm the verification design",
            )
        )
        if read_decision(paths, "verification.r1") is None:
            return out
        out.append(
            A(
                key="p2-tasks",
                kind=StepKind.CODE,
                phase="2",
                after=["p2-gate-verification"],
                fn="tasks",
                deliverables=["artifacts/tasks/v001.json"],
                note="code derives the build ledger",
            )
        )
        if not store.exists("tasks"):
            return out
        tasks = store.read("tasks", Tasks)
        vspec = store.read("vspec", VerificationSpec)
        module = self._module(store)
        trow = tasks.by_kind("T")[0]
        brow = tasks.by_kind("B")[0]
        vspec_md = render(vspec, "model")
        null_src = null_module(contract)
        out.append(
            A(
                key="p3-tests",
                kind=StepKind.AUTHOR,
                phase="3",
                after=["p2-tasks"],
                prompt="test-author",
                schema_name="FilesAuthor",
                role="checker",
                fixture="tests",
                land=f"file:{trow.writes[0]}",
                check_extra={"path": trow.writes[0], "kind": "tests"},
                checks=["compile_answer", "lint_answer", "null_run"],
                sets={
                    "CONTRACT_TV_MD": tv_md,
                    "VSPEC_MD": vspec_md,
                    "TEST_FILE": trow.writes[0],
                    "MODULE": module,
                    "NULL_SRC": null_src,
                    "PROPERTY_IDS": ", ".join(p.id or "" for p in vspec.properties),
                },
                rendered_keys=["contract", "vspec"],
                deliverables=[f"build/{trow.writes[0]}", "build/manifest.json"],
                note="the checker writes the tests without the source",
            )
        )
        out.append(
            A(
                key="p3-implement",
                kind=StepKind.AUTHOR,
                phase="3",
                after=["p2-tasks"],
                prompt="implement",
                schema_name="FilesAuthor",
                role="author",
                fixture="implement",
                land=f"file:{brow.writes[0]}",
                check_extra={"path": brow.writes[0], "kind": "src"},
                checks=["compile_answer", "lint_answer", "impl_steps"],
                sets={
                    "CONTRACT_MD": render(contract, "model"),
                    "SRC_FILE": brow.writes[0],
                    "MODULE": module,
                    "STEP_IDS": ", ".join(s.id or "" for s in contract.steps()),
                },
                rendered_keys=["contract"],
                deliverables=[f"build/{brow.writes[0]}"],
                note="the author writes the source without the tests",
            )
        )
        if not (run / "build" / trow.writes[0]).exists() or not (run / "build" / brow.writes[0]).exists():
            return out
        out.append(
            A(
                key="p4-verify-1",
                kind=StepKind.CODE,
                phase="4",
                after=["p3-tests", "p3-implement"],
                fn="verify",
                deliverables=["artifacts/results/v001.json"],
                note="the real run and the null run",
            )
        )
        if not store.exists("results"):
            return out
        # triage: one fix cycle per failing property set, bounded by fix_rounds
        params = self.params(state.task)
        cycle = 1
        prev = "p4-verify-1"
        while True:
            results = store.read("results", Results, cycle)
            failing = [p for p in results.properties if p.real in ("fail", "error", "nondeterministic")]
            if not failing or cycle > params.fix_rounds:
                break
            fix_tests: list[str] = []
            fix_src: list[str] = []
            last_keys: list[str] = []
            for pr in failing:
                pid = pr.property
                prop = next((p for p in vspec.properties if p.id == pid), None)
                clause_md = "\n".join(f"- {c}" for c in (prop.cites if prop else []))
                q1 = f"p4-ruling-{pid}-q1-c{cycle}"
                out.append(
                    A(
                        key=q1,
                        kind=StepKind.AUTHOR,
                        phase="4",
                        after=[prev],
                        prompt="ruling-q1",
                        schema_name="Ruling",
                        role="author",
                        fixture="ruling-q1",
                        land=f"ruling:{pid}:1:{cycle}",
                        check_extra={"question": 1},
                        sets={
                            "PROPERTY_ID": pid,
                            "PROPERTY_MD": render(prop, "model") if prop else "(unknown property)",
                            "TEST_SRC": self._read_build(run, trow.writes[0]),
                            "ASSERTION": pr.assertion or "(no assertion text)",
                            "CONTRACT_TV_MD": tv_md,
                            "CITES": clause_md,
                        },
                        rendered_keys=["vspec", "contract"],
                        deliverables=[f"triage/{pid}-q1-c{cycle}.json"],
                        note=f"a fresh author session rules on the test for {pid}",
                    )
                )
                r1 = self._read_ruling(run, pid, 1, cycle)
                if r1 is None:
                    last_keys.append(q1)
                    continue
                if r1.verdict == "test_bug":
                    fix_tests.append(pid)
                    last_keys.append(q1)
                    continue
                q2 = f"p4-ruling-{pid}-q2-c{cycle}"
                out.append(
                    A(
                        key=q2,
                        kind=StepKind.AUTHOR,
                        phase="4",
                        after=[q1],
                        prompt="ruling-q2",
                        schema_name="Ruling",
                        role="checker",
                        fixture="ruling-q2",
                        land=f"ruling:{pid}:2:{cycle}",
                        check_extra={"question": 2},
                        sets={
                            "PROPERTY_ID": pid,
                            "PROPERTY_MD": render(prop, "model") if prop else "(unknown property)",
                            "TEST_SRC": self._read_build(run, trow.writes[0]),
                            "IMPL_SRC": self._read_build(run, brow.writes[0]),
                            "ASSERTION": pr.assertion or "(no assertion text)",
                            "CONTRACT_MD": render(contract, "model"),
                            "RULING_Q1_MD": render(r1, "model"),
                        },
                        rendered_keys=["vspec", "contract"],
                        deliverables=[f"triage/{pid}-q2-c{cycle}.json"],
                        note=f"a fresh checker session rules on the code for {pid}",
                    )
                )
                r2 = self._read_ruling(run, pid, 2, cycle)
                last_keys.append(q2)
                if r2 is None:
                    continue
                if r2.verdict in ("implementation_bug", "algorithm_defect"):
                    fix_src.append(pid)
                # contract_ambiguity: carried as a result by the report
            if any(self._read_ruling(run, p.property, 1, cycle) is None for p in failing):
                return out
            pending_q2 = [
                p.property
                for p in failing
                if self._read_ruling(run, p.property, 1, cycle).verdict == "test_stands"
                and self._read_ruling(run, p.property, 2, cycle) is None
            ]
            if pending_q2:
                return out
            fix_keys: list[str] = []
            if fix_tests:
                k = f"p4-fix-tests-c{cycle}"
                rulings_md = "\n\n".join(
                    render(self._read_ruling(run, p, 1, cycle), "model") for p in fix_tests
                )
                out.append(
                    A(
                        key=k,
                        kind=StepKind.AUTHOR,
                        phase="4",
                        after=last_keys,
                        prompt="fix-tests",
                        schema_name="FilesAuthor",
                        role="checker",
                        fixture="fix-tests",
                        land=f"file:{trow.writes[0]}",
                        check_extra={"path": trow.writes[0], "kind": "tests"},
                        checks=["compile_answer", "lint_answer", "null_run"],
                        sets={
                            "CONTRACT_TV_MD": tv_md,
                            "VSPEC_MD": vspec_md,
                            "TEST_FILE": trow.writes[0],
                            "MODULE": module,
                            "NULL_SRC": null_src,
                            "TEST_SRC": self._read_build(run, trow.writes[0]),
                            "RULINGS_MD": rulings_md,
                            "PROPERTY_IDS": ", ".join(p.id or "" for p in vspec.properties),
                        },
                        rendered_keys=["contract", "vspec"],
                        deliverables=[f"build/.fix-tests-c{cycle}.done"],
                        note="the checker fixes the tests the rulings named",
                    )
                )
                fix_keys.append(k)
            if fix_src:
                k = f"p4-fix-src-c{cycle}"
                rulings_md = "\n\n".join(
                    render(self._read_ruling(run, p, 2, cycle), "model") for p in fix_src
                )
                out.append(
                    A(
                        key=k,
                        kind=StepKind.AUTHOR,
                        phase="4",
                        after=last_keys,
                        prompt="fix-src",
                        schema_name="FilesAuthor",
                        role="author",
                        fixture="fix-src",
                        land=f"file:{brow.writes[0]}",
                        check_extra={"path": brow.writes[0], "kind": "src"},
                        checks=["compile_answer", "lint_answer", "impl_steps"],
                        sets={
                            "CONTRACT_MD": render(contract, "model"),
                            "SRC_FILE": brow.writes[0],
                            "MODULE": module,
                            "IMPL_SRC": self._read_build(run, brow.writes[0]),
                            "RULINGS_MD": rulings_md,
                            "STEP_IDS": ", ".join(s.id or "" for s in contract.steps()),
                        },
                        rendered_keys=["contract"],
                        deliverables=[f"build/.fix-src-c{cycle}.done"],
                        note="the author fixes the source the rulings named",
                    )
                )
                fix_keys.append(k)
            if not fix_keys:
                break  # every failure is a carried ambiguity
            done_marks = [
                run / "build" / f".fix-tests-c{cycle}.done",
                run / "build" / f".fix-src-c{cycle}.done",
            ]
            if not all(
                m.exists()
                for m, need in zip(done_marks, (bool(fix_tests), bool(fix_src)), strict=True)
                if need
            ):
                return out
            cycle += 1
            k = f"p4-verify-{cycle}"
            out.append(
                A(
                    key=k,
                    kind=StepKind.CODE,
                    phase="4",
                    after=fix_keys,
                    fn="verify",
                    deliverables=[f"artifacts/results/v{cycle:03d}.json"],
                    note="re-run after the fixes",
                )
            )
            prev = k
            if store.latest_version("results") < cycle:
                return out
        out.append(
            A(
                key="p4-report",
                kind=StepKind.CODE,
                phase="4",
                after=[prev],
                fn="report",
                deliverables=["artifacts/report/v001.json", "REPORT.md"],
                note="code writes the report",
            )
        )
        return out

    # ---- helpers ------------------------------------------------------------------------

    def _module(self, store: Store) -> str:
        brief = store.read("brief", Brief)
        return brief.module or re.sub(r"[^a-z0-9_]", "_", store.read("plan", Plan).blocks[0].name.lower())

    @staticmethod
    def _read_build(run: Path, rel: str) -> str:
        p = run / "build" / rel
        return p.read_text(encoding="utf-8") if p.exists() else "(not written yet)"

    @staticmethod
    def _read_ruling(run: Path, pid: str, q: int, cycle: int) -> Ruling | None:
        p = run / "triage" / f"{pid}-q{q}-c{cycle}.json"
        return Ruling.model_validate_json(p.read_text(encoding="utf-8")) if p.exists() else None

    # ---- landing (rule 6: code writes) ------------------------------------------------------

    def land(self, step: Step, value: Artifact, ctx: ProgramContext) -> list[str]:
        assert step.land
        run = ctx.paths.run_dir
        loops = self._loops(ctx.state)
        if step.land.startswith("review:"):
            return loops[step.land.split(":")[1]].land(step, value, ctx)
        if step.land == "contract":
            assert isinstance(value, Contract)
            prev = ctx.store.read("contract", Contract) if ctx.store.exists("contract") else None
            v = ctx.store.write("contract", value.with_ids(prev))
            if step.key.startswith("p1-contract-revise-r"):
                r = step.key.rsplit("r", 1)[1]
                (run / "gates" / f"revise-r{r}.done").write_text("1")
                return [f"artifacts/contract/v{v:03d}.json", f"gates/revise-r{r}.done"]
            return [f"artifacts/contract/v{v:03d}.json"]
        if step.land == "plan":
            assert isinstance(value, Plan)
            v = ctx.store.write("plan", value.with_ids(None))
            return [f"artifacts/plan/v{v:03d}.json"]
        if step.land == "vspec":
            assert isinstance(value, VerificationSpec)
            v = ctx.store.write("vspec", value.with_ids([]))
            return [f"artifacts/vspec/v{v:03d}.json"]
        if step.land.startswith("file:"):
            assert isinstance(value, FilesAuthor)
            rel = step.land.split(":", 1)[1]
            target = run / "build" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(target, value.files[0].content)
            produced = [f"build/{rel}"]
            if step.check_extra.get("kind") == "tests":
                manifest = self._manifest(value.files[0].content, rel)
                atomic_write_text(run / "build" / "manifest.json", json.dumps(manifest, indent=2))
                produced.append("build/manifest.json")
            if step.key.startswith("p4-fix-"):
                mark = run / "build" / f".{step.key[3:]}.done"
                mark.write_text("1")
                produced.append(f"build/{mark.name}")
            return produced
        if step.land.startswith("ruling:"):
            assert isinstance(value, Ruling)
            _, pid, q, cycle = step.land.split(":")
            taken = (
                [json.loads(p.read_text())["id"] for p in (run / "triage").glob("*.json")]
                if (run / "triage").exists()
                else []
            )
            value.id = next_id(Prefix.RULING, [t for t in taken if t])
            out = run / "triage" / f"{pid}-q{q}-c{cycle}.json"
            atomic_write_text(out, value.model_dump_json(indent=2))
            ctx.events.append(
                "judge.verdict",
                step=step.key,
                property=pid,
                question=int(q),
                verdict=value.verdict,
                id=value.id,
            )
            return [f"triage/{pid}-q{q}-c{cycle}.json"]
        v = ctx.store.write(step.land, value)
        return [f"artifacts/{step.land}/v{v:03d}.json"]

    @staticmethod
    def _manifest(test_src: str, rel: str) -> dict[str, str]:
        """P-NNNN -> node id, from the test function names (an anchored regex on the def line,
        the one place a name is read; the runner then looks up, never matches)."""
        out: dict[str, str] = {}
        for m in re.finditer(r"^def (test_(P_\d{4})\w*)\s*\(", test_src, re.M):
            pid = m.group(2).replace("_", "-")
            out.setdefault(pid, f"{rel}::{m.group(1)}")
        return out

    # ---- code steps --------------------------------------------------------------------------

    def _c_brief(self, ctx: ProgramContext) -> None:
        params = self.params(ctx.state.task)
        ctx.store.write("brief", params.brief)

    def _c_freeze(self, ctx: ProgramContext) -> None:
        c = ctx.store.read("contract", Contract)
        run = ctx.paths.run_dir
        rec = {
            "version": c.version,
            "sha_full": c.sha(),
            "sha_test_visible": c.test_visible().sha(),
            "clauses": len(c.clauses()),
            "steps": len(c.steps()),
            "retired": c.retired,
        }
        atomic_write_text(run / "freeze.json", json.dumps(rec, indent=2))
        atomic_write_text(run / "CONTRACT.full.md", render(c, "model"))
        atomic_write_text(
            run / "CONTRACT.test-visible.md", render(c.test_visible(), "model", drop={"algorithm"})
        )
        ctx.events.append(
            "artifact.written",
            step=ctx.step.key,
            path="freeze.json",
            **{k: v for k, v in rec.items() if k != "retired"},
        )

    def _c_fill_tolerances(self, ctx: ProgramContext) -> None:
        c = ctx.store.read("contract", Contract)
        d = read_decision(ctx.paths, "tolerances.r1")
        assert d is not None
        answers = {x.question_id: x.answer for x in d.decisions}
        gate = json.loads((ctx.paths.gates / "tolerances.r1.ask.json").read_text())
        qmap = {q["id"]: q["cites"][0] for q in gate["questions"] if q.get("cites")}
        new = c.model_copy(deep=True)
        for t in new.tolerances:
            for qid, key in qmap.items():
                if key == t.key and qid in answers and answers[qid].strip():
                    t.value = answers[qid].strip()
        ctx.store.write("contract", new.with_ids(c))
        self._c_freeze(ctx)
        (ctx.paths.run_dir / "tolerances.filled").write_text("1")

    def _c_tasks(self, ctx: ProgramContext) -> None:
        c = ctx.store.read("contract", Contract)
        v = ctx.store.read("vspec", VerificationSpec)
        module = self._module(ctx.store)
        rows = [
            TaskRow(
                id="T-0001",
                kind="B",
                owner="author",
                produces=f"the {c.block} module",
                writes=[f"src/{module}.py"],
                covers=[u.id or "" for u in c.units],
                done_when="compiles, lints, names every A- step, passes the properties",
            )
        ]
        rows.append(
            TaskRow(
                id="T-0002",
                kind="T",
                owner="checker",
                produces=f"the {c.block} tests",
                writes=[f"tests/test_{module}.py"],
                covers=[p.id or "" for p in v.properties],
                depends=[],
                done_when="one test per property, every test fails against the null",
            )
        )
        ctx.store.write("tasks", Tasks(rows=rows))

    def _c_verify(self, ctx: ProgramContext) -> None:
        run = ctx.paths.run_dir
        c = ctx.store.read("contract", Contract)
        module = self._module(ctx.store)
        build = run / "build"
        null_dir = build / "null"
        null_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(null_dir / f"{module}.py", null_module(c))
        manifest = json.loads((build / "manifest.json").read_text())
        n = (ctx.store.latest_version("results") or 0) + 1
        res = run_all(
            build / "tests", build / "src", null_dir, manifest, run / "streams" / f"verify-{n}", repeats=3
        )
        ctx.store.write("results", res)
        ctx.events.append(
            "check.result",
            step=ctx.step.key,
            problems=[
                f"{p.property} {p.real} (null: {p.null})"
                for p in res.properties
                if p.real != "pass" or p.null == "pass"
            ],
            passed=sum(1 for p in res.properties if p.real == "pass"),
            total=len(res.properties),
            vacuous=len(res.vacuous),
        )

    def _c_report(self, ctx: ProgramContext) -> None:
        run = ctx.paths.run_dir
        st = ctx.state
        loops = self._loops(st)
        results = ctx.store.read("results", Results)
        carried: list[Carried] = []
        for name, loop in loops.items():
            for f in loop.status(run).carried + loop.status(run).escalated:
                carried.append(
                    Carried(
                        kind="finding",
                        id=f.id or "",
                        summary=f"[{f.severity}/{f.klass}] {f.argument[:160]}",
                        from_step=f"{name} round {f.round}",
                    )
                )
        for p in results.properties:
            if p.real != "pass":
                carried.append(
                    Carried(
                        kind="property",
                        id=p.property,
                        summary=f"{p.real}: {p.assertion[:160]}",
                        from_step="verify",
                    )
                )
        for f in (run / "triage").glob("*-q2-*.json") if (run / "triage").exists() else []:
            r = Ruling.model_validate_json(f.read_text())
            if r.verdict == "contract_ambiguity":
                carried.append(
                    Carried(
                        kind="ambiguity",
                        id=r.id or "",
                        summary=f"{r.property}: {r.readings}",
                        from_step="triage",
                    )
                )
        cov = json.loads((run / "coverage.json").read_text()) if (run / "coverage.json").exists() else {}
        for g in cov.get("uncovered", []):
            carried.append(
                Carried(kind="gap", id=g, summary="clause not cited by any property", from_step="coverage")
            )
        waste = self._waste(ctx)
        passed = sum(1 for p in results.properties if p.real == "pass")
        verdict = f"{passed}/{len(results.properties)} properties pass · {len(results.properties) - len(results.vacuous)}/{len(results.properties)} fail on the null"
        rep = Report(
            run_id=st.run_id,
            recipe=self.name,
            outcome=(st.outcome.value if st.outcome else "running"),
            verdict=verdict,
            carried=carried,
            waste=waste,
            flagged_decisions=[d["id"] for d in self._flagged(ctx)],
            halts=st.resumed_count,
            resumed=st.resumed_count,
        )
        ctx.store.write("report", rep)
        atomic_write_text(run / "REPORT.md", render(rep, "human"))
        st.carried = [
            CarriedRecord(kind=c.kind, id=c.id, summary=c.summary, from_step=c.from_step) for c in carried
        ]
        st.save(ctx.paths)

    @staticmethod
    def _flagged(ctx: ProgramContext) -> list[dict[str, Any]]:
        p = ctx.paths.decisions
        return [d for d in json.loads(p.read_text()) if d.get("flagged")] if p.exists() else []

    @staticmethod
    def _waste(ctx: ProgramContext) -> list[WasteRow]:
        rows: dict[str, WasteRow] = {}
        started: dict[str, float] = {}
        for e in ctx.events.all():
            role = e.role or ("code" if e.kind.startswith("step.") else None)
            if role is None:
                continue
            row = rows.setdefault(role, WasteRow(side=role))
            if e.kind == "call.started":
                row.calls += 1
                started[f"{e.step}:{e.attempt}"] = e.ts.timestamp()
            elif e.kind == "call.usage":
                row.input_tokens += int(e.data.get("input_tokens", 0))
                row.output_tokens += int(e.data.get("output_tokens", 0))
                row.turns += int(e.data.get("turns", 0))
                row.tool_calls += int(e.data.get("tool_calls", 0))
            elif e.kind == "call.final":
                t0 = started.pop(f"{e.step}:{e.attempt}", None)
                if t0 is not None:
                    row.seconds += round(e.ts.timestamp() - t0, 2)
            elif e.kind == "step.refused":
                row.refused_answers += 1
        return [r for r in rows.values() if r.side != "code"]

    # ---- checks (rule 7) -----------------------------------------------------------------

    def _k_coverage(self, ctx: ProgramContext) -> list[str]:
        c = ctx.store.read("contract", Contract)
        v = ctx.store.read("vspec", VerificationSpec)
        checkable = {x.id for x in c.invariants + c.negative + c.failure + c.units if x.id}
        cited = {i for p in v.properties for i in p.cites} | {i for g in v.contract_gaps for i in g.cites}
        probs = set_difference(checkable, cited & checkable, what="clauses")
        uncovered = sorted(checkable - cited)
        atomic_write_text(
            ctx.paths.run_dir / "coverage.json",
            json.dumps(
                {
                    "checkable": sorted(checkable),
                    "cited": sorted(cited & checkable),
                    "uncovered": uncovered,
                    "gaps": len(v.contract_gaps),
                },
                indent=2,
            ),
        )
        if uncovered:
            ctx.state.carried += [
                CarriedRecord(
                    kind="gap", id=i, summary="clause not cited by any property", from_step="p2-coverage"
                )
                for i in uncovered
            ]
            ctx.state.save(ctx.paths)
        return [str(p) for p in probs if p.code == "clauses_missing"]

    def _k_compile(self, ctx: ProgramContext) -> list[str]:
        a = ctx.answer
        assert isinstance(a, FilesAuthor)
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / Path(a.files[0].path).name
            f.write_text(a.files[0].content)
            r = check_python([f], types=False)
            return [f"{p.code}: {p.message}" for p in r.problems]

    def _k_lint(self, ctx: ProgramContext) -> list[str]:
        a = ctx.answer
        assert isinstance(a, FilesAuthor)
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / Path(a.files[0].path).name
            f.write_text(a.files[0].content)
            r = check_python([f], types=(ctx.step.check_extra.get("kind") == "src"))
            if r.skipped:
                ctx.events.append(
                    "step.skipped", step=ctx.step.key, tools=r.skipped, reason="tool not on PATH"
                )
            return [f"{p.code}: {p.message}" for p in r.problems]

    def _k_null_run(self, ctx: ProgramContext) -> list[str]:
        """Every test the author names must FAIL against the null implementation."""
        a = ctx.answer
        assert isinstance(a, FilesAuthor)
        c = ctx.store.read("contract", Contract)
        module = self._module(ctx.store)
        rel = a.files[0].path
        manifest = self._manifest(a.files[0].content, rel)
        if not manifest:
            return ["no_tests: no `def test_P_NNNN_...` function found; name each test after its property id"]
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "null").mkdir()
            (root / "null" / f"{module}.py").write_text(null_module(c))
            t = root / rel
            t.parent.mkdir(parents=True, exist_ok=True)
            t.write_text(a.files[0].content)
            res = run_all(t.parent, root / "null", root / "null", manifest, root / "out", repeats=1)
        out: list[str] = []
        for p in res.properties:
            if p.null == "pass":
                out.append(
                    f"vacuous_test: {p.test} passes against the null implementation; anchor the assertion on the input"
                )
            elif p.null == "error":
                out.append(
                    f"inconclusive_test: {p.test} errors against the null; check the call reaches the stub ({p.assertion})"
                )
        return out

    def _k_impl_steps(self, ctx: ProgramContext) -> list[str]:
        a = ctx.answer
        assert isinstance(a, FilesAuthor)
        c = ctx.store.read("contract", Contract)
        want = {s.id for s in c.steps() if s.id}
        probs = [str(p) for p in set_difference(want, set(a.report.steps), what="steps")]
        missing_comments = sorted(i for i in want if i not in a.files[0].content)
        if missing_comments:
            probs.append(
                f"steps_uncommented: name each step id in a comment where it is implemented: {missing_comments}"
            )
        return probs

    # ---- gates (rule 11) -------------------------------------------------------------------

    def gate_builders(self) -> dict[str, GateBuilder]:
        return {
            "ledger": self._g_ledger,
            "blocks": self._g_blocks,
            "tolerances": self._g_tolerances,
            "verification": self._g_verification,
        }

    def _g_ledger(self, step: Step, ctx: ProgramContext) -> Gate:
        led = ctx.store.read("ledger", AssumptionsLedger)
        qs = [
            Question(
                id=f"Q-{i + 1:04d}",
                text=f"{r.assumption} (basis: {r.basis}; if wrong: {r.if_wrong})",
                kind="confirm",
                default="yes",
                options=["yes", "no"],
                risky=False,
            )
            for i, r in enumerate(led.rows)
        ]
        qs += [
            Question(
                id=f"Q-{len(led.rows) + i + 1:04d}",
                text=f"{q.question} (decides: {q.decides})",
                kind="text",
                default="",
                risky=True,
            )
            for i, q in enumerate(led.queue)
        ]
        return Gate(
            id=step.gate or "ledger.r1",
            name="ledger",
            kind="input",
            title="Confirm the assumptions, by exception",
            questions=qs,
            can_revise=False,
        )

    def _g_blocks(self, step: Step, ctx: ProgramContext) -> Gate:
        c = ctx.store.read("contract", Contract)
        loops = self._loops(ctx.state)
        carried = [
            f.model_dump(mode="json")
            for k in ("contract", "contract_audit")
            for f in loops[k].status(ctx.paths.run_dir).carried
        ]
        gid = step.gate or "blocks.r1"
        qs = [
            Question(
                id=f"Q-{i + 1:04d}",
                text=f"Unit `{u.name}({', '.join(p.name for p in u.params)}) -> {u.returns}`: {u.holds}",
                kind="confirm",
                default="yes",
                options=["yes", "no"],
                cites=[u.id or ""],
                gloss=u.holds,
            )
            for i, u in enumerate(c.units)
        ]
        return Gate(
            id=gid,
            name="blocks",
            round=int(gid.rsplit("r", 1)[1]),
            kind="judgment",
            title="Confirm the blocks",
            questions=qs,
            carried=carried,
        )

    def _g_tolerances(self, step: Step, ctx: ProgramContext) -> Gate:
        c = ctx.store.read("contract", Contract)
        qs = [
            Question(
                id=f"Q-{i + 1:04d}",
                text=f"{t.clause}: {t.kind} tolerance",
                kind="number",
                default="0",
                recommended="0",
                risky=True,
                cites=[t.key],
            )
            for i, t in enumerate(x for x in c.tolerances if x.value == "UNDECIDED")
        ]
        return Gate(
            id="tolerances.r1",
            name="tolerances",
            kind="input",
            title="Set the open tolerances",
            questions=qs,
            can_revise=False,
        )

    def _g_verification(self, step: Step, ctx: ProgramContext) -> Gate:
        loops = self._loops(ctx.state)
        v = ctx.store.read("vspec", VerificationSpec)
        carried = [f.model_dump(mode="json") for f in loops["vspec"].status(ctx.paths.run_dir).carried]
        carried += [
            {"id": g.id, "kind": "gap", "argument": g.text, "cites": g.cites} for g in v.contract_gaps
        ]
        cov = (
            json.loads((ctx.paths.run_dir / "coverage.json").read_text())
            if (ctx.paths.run_dir / "coverage.json").exists()
            else {}
        )
        carried += [
            {"id": i, "kind": "uncovered", "argument": "no property cites this clause"}
            for i in cov.get("uncovered", [])
        ]
        return Gate(
            id="verification.r1",
            name="verification",
            kind="judgment",
            title="Confirm the verification design",
            questions=[],
            carried=carried,
        )

    # ---- fakers (rule 12) --------------------------------------------------------------------

    def fakers(self, paths: RunPaths, store: Store) -> dict[str, Callable[[Any], dict[str, Any]]]:
        from .fake import fakers

        return fakers(paths, store)
