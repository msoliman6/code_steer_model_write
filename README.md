<p align="center"><picture>
<source media="(prefers-color-scheme: dark)" srcset="docs/media/banner-dark.svg">
<img src="docs/media/banner.svg" alt="Code steers, models write" width="720">
</picture></p>

<p align="center"><b>Code steers, models write: a template for agentic AI workflows that are versatile, reliable and fast to start.</b></p>

<p align="center">
<a href="LICENSE"><img alt="license: MIT" src="https://img.shields.io/badge/license-MIT-bb8009?style=flat-square"></a>
<a href="https://www.python.org/"><img alt="python: 3.11+" src="https://img.shields.io/badge/python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white"></a>
</p>
<p align="center">
<a href="https://docs.anthropic.com/en/docs/claude-code"><img alt="Claude Code: author" src="https://img.shields.io/badge/Claude_Code-author-d97757?style=flat-square"></a>
<a href="https://openai.com/codex/"><img alt="OpenAI Codex: adversarial checker" src="https://img.shields.io/badge/OpenAI_Codex-adversarial%20checker-10a37f?style=flat-square"></a>
</p>

<p align="center"><a href="#the-14-universal-rules">The 14 rules</a> · <a href="#workflow">Workflow</a> · <a href="#execution-layers-and-governance-planes">The layers</a> · <a href="#install">Install</a> · <a href="#first-run">First run</a> · <a href="#settings-you-choose-once">Settings</a> · <a href="#read-more">Read more</a></p>

<p align="center">
<a href="docs/PLAN.md"><img alt="docs: the plan" src="https://img.shields.io/badge/docs-the%20plan-30363d?style=flat-square"></a>
<a href="docs/QUICKSTART.md"><img alt="docs: quick start" src="https://img.shields.io/badge/docs-quick%20start-30363d?style=flat-square"></a>
<a href="docs/HACKATHON-30MIN.md"><img alt="docs: hackathon in 30 min" src="https://img.shields.io/badge/docs-hackathon%20in%2030%20min-30363d?style=flat-square"></a>
<a href="docs/ADD-A-RECIPE.md"><img alt="docs: add a recipe" src="https://img.shields.io/badge/docs-add%20a%20recipe-30363d?style=flat-square"></a>
<a href="docs/DASHBOARD-DESIGN.md"><img alt="docs: dashboard design" src="https://img.shields.io/badge/docs-dashboard%20design-30363d?style=flat-square"></a>
</p>

<p align="center"><i>Independent open-source project. Not affiliated with or endorsed by Anthropic or OpenAI.<br>Claude and Claude Code are trademarks of Anthropic; Codex and GPT are trademarks of OpenAI. Prefect, MLflow, Reflex, PydanticAI, pydantic, Guardrails AI, Cedar, Docker, Colima, obstore, Typer, Jinja2, SQLite, OpenTelemetry, the Model Context Protocol, ruff, pyright and pytest belong to their owners.</i></p>

## The 14 universal rules

1. **Code controls the workflow end to end.** Sequencing, the next step, whether a step counts,
   every file write, every check run. Models only fill schemas.
2. **Agents read markdown rendered by code from JSON, and write only schema-constrained JSON.**
   No tools, files or shell unless the task needs them, and then only inside the folder the
   agent writes its output to (that folder is the sandbox root).
3. **No agent grades its own work.** The checker gets a frozen copy, and a different vendor
   where possible.
4. **One owner per fact, everything else derives.** The pydantic class owns the shape; JSON
   owns the content and markdown is a view; one gate record feeds every renderer.
5. **Every element has a code-assigned id, never renumbered.** Findings cite ids, so coverage
   is a set difference, not a judgment.
6. **Nothing is recorded from a refused answer.** Stage → check → atomic replace. A refusal is
   re-asked with the exact problems and the refused answer, bounded, stopping when the problem
   set repeats.
7. **The verification ladder.** Code checks first, an AI judge only where no field can answer,
   a human only for a value only they have or a judgment only they can make. Verdicts are
   graded severities, never booleans.
8. **Every loop is bounded by code and carries its full trajectory verbatim.** Convergence is
   computed, not asked. The unresolved is carried into the report, never hidden. The last
   revision always gets a closing read.
9. **No step is issued with nothing to do.** Zero findings → no arbitration; zero questions →
   no gate.
10. **One append-only event log, written as a side effect of the work.** Two signals side by
    side: did the process run, is the product right. Halts are reports, resume comes from disk,
    exit codes are honest (0 done, 1 record, 2 refusal).
11. **Human attention is the scarcest resource.** Batch questions, confirm by exception,
    pre-fill defaults, a mode dial whose auto-answers are flagged, never let waiting look like
    silence.
12. **Prove it offline first.** Fake models walk every branch with zero tokens before any live
    run. A check that never runs is not a check.
13. **Prompts are code-filled templates, not skills.** A missing key refuses before a token is
    spent. Tool denial is stated as fact in the prompt and enforced by the runtime.
14. **Cost is a design axis.** No unused tools, thinking off where a check catches every
    mistake, calls batched, tokens as the honest measure.

## This is a template, not a project

Do not build a specific workflow inside this repository. It holds the runtime, the recipes and
the rules; a project is a **separate repo** scaffolded from it:

```bash
copier copy gh:<you>/code_steer_model_write ../my-workflow    # a new repo outside this one
cd ../my-workflow && csmw doctor
```

Your workflow's brief, task specs, prompts, fixtures and runs live there. Changes that belong
to everyone -- a new recipe, a fixed check, a better renderer -- come back here as a commit;
`copier update` carries them into every project.

## What it is

A Python package (`code_steer_model_write`, CLI `csmw`) plus workflows. A **workflow** declares
itself as data: stages, who authors and who checks each one, the pydantic schema every model
answer must fit, the code checks, the human gates, the evaluations. A coded driver derives the
next step from disk and runs it, resumable, with one append-only event log; ten layers sit
around that loop, each behind a seam with one tool chosen for it (the table below). One `ask()`
fronts every model call; behind it PydanticAI (Anthropic and OpenAI through it), the `claude`
and `codex` CLIs on their logins, and a fake backend that walks the whole pipeline offline with
zero tokens.

Workflows in the box: **code-builder** (plan → contract → freeze → tests by one model, source by
the other, side by side → null run → verify → triage; walked offline on 10 legs, proven live on
`claude -p` + `codex exec` through every layer) and **debate** (hypotheses → support vs challenge
→ rebuttal by id → a fresh judge on a rubric; walked offline, unproven live). The architecture
these layers implement is the parent repository, `production_agentic_workflow`.

The workflow diagram is generated from the code so it cannot drift from it (`just figure`):

## Workflow

The block diagram of the workflow itself, generated from the recipe (`csmw figure code_builder`):
what each stage does, who writes and who attacks, where code freezes, merges and runs.

<p align="center"><picture>
<source media="(prefers-color-scheme: dark)" srcset="docs/media/workflow-dark.svg">
<img src="docs/media/workflow.svg" alt="How the code-builder workflow operates" width="820">
</picture></p>

## Execution layers and governance planes

Any workflow the runtime runs sits on seven execution layers and three cross-cutting planes,
each behind a seam with one production tool chosen for it. Every choice is free, self-hosted and
a Python SDK; the offline walk proves every layer with fake models before any live run.

<p align="center"><picture>
<source media="(prefers-color-scheme: dark)" srcset="docs/media/layers-dark.svg">
<img src="docs/media/layers.svg" alt="The ten layers: the request path, the execution pair, the three planes, the record" width="900">
</picture></p>

<img alt="interface & control" src="https://img.shields.io/badge/-interface%20%26%20control-5646ED?style=flat-square"> <img alt="orchestration & runtime" src="https://img.shields.io/badge/-orchestration%20%26%20runtime-d04a45?style=flat-square"> <img alt="execution & tools" src="https://img.shields.io/badge/-execution%20%26%20tools-2496ED?style=flat-square"> <img alt="state" src="https://img.shields.io/badge/-state-1f6feb?style=flat-square"> <img alt="cross-cutting planes" src="https://img.shields.io/badge/-cross--cutting%20planes-bb8009?style=flat-square">

| group | layer | what it owns | behind the seam |
|---|---|---|---|
| <img alt="interface & control" src="https://img.shields.io/badge/-control-5646ED?style=flat-square"> | **L1 UI** | a home of every run, the run page, the start page | <a href="https://reflex.dev/"><img alt="UI: Reflex" src="https://img.shields.io/badge/UI-Reflex-5646ED?style=flat-square&logo=reflex&logoColor=white"></a> <a href="https://jinja.palletsprojects.com/"><img alt="pages: Jinja2" src="https://img.shields.io/badge/pages-Jinja2-B41717?style=flat-square&logo=jinja&logoColor=white"></a> |
| <img alt="interface & control" src="https://img.shields.io/badge/-control-5646ED?style=flat-square"> | **L2 control plane** | the task, the budgets, the run registry, the MCP server every entry point calls (twelve tools) | <a href="https://docs.pydantic.dev/"><img alt="schemas: pydantic v2" src="https://img.shields.io/badge/schemas-pydantic%20v2-E92063?style=flat-square&logo=pydantic&logoColor=white"></a> <a href="https://modelcontextprotocol.io/"><img alt="gateway: MCP SDK" src="https://img.shields.io/badge/gateway-MCP%20SDK-30363d?style=flat-square"></a> <a href="https://typer.tiangolo.com/"><img alt="CLI: Typer" src="https://img.shields.io/badge/CLI-Typer-1f6feb?style=flat-square"></a> <a href="https://www.sqlite.org/"><img alt="run registry: SQLite" src="https://img.shields.io/badge/run%20registry-SQLite-003B57?style=flat-square&logo=sqlite&logoColor=white"></a> |
| <img alt="orchestration & runtime" src="https://img.shields.io/badge/-runtime-d04a45?style=flat-square"> | **L3 orchestration** | the sequence: the driver derives the next step from disk; the runner detaches, cancels, pauses, resumes, runs the tests and the source side by side | <a href="https://www.prefect.io/"><img alt="runner: Prefect 3" src="https://img.shields.io/badge/runner-Prefect%203-d04a45?style=flat-square&logo=prefect&logoColor=white"></a> |
| <img alt="orchestration & runtime" src="https://img.shields.io/badge/-runtime-d04a45?style=flat-square"> | **L4 agent runtime** | one model call under a schema, or a bounded tool loop the vendor never runs | <a href="https://docs.anthropic.com/en/docs/claude-code"><img alt="author: Claude Code" src="https://img.shields.io/badge/author-Claude%20Code-d97757?style=flat-square"></a> <a href="https://github.com/openai/codex"><img alt="checker: OpenAI Codex" src="https://img.shields.io/badge/checker-OpenAI%20Codex-10a37f?style=flat-square"></a> <a href="https://ai.pydantic.dev/"><img alt="API path: PydanticAI" src="https://img.shields.io/badge/API%20path-PydanticAI-E92063?style=flat-square&logo=pydantic&logoColor=white"></a> |
| <img alt="execution & tools" src="https://img.shields.io/badge/-execution-2496ED?style=flat-square"> | **L5 sandbox** | where every check runs, bounded: network off, the run folder the only mount | <a href="https://docs.docker.com/engine/api/sdk/"><img alt="sandbox: Docker SDK" src="https://img.shields.io/badge/sandbox-Docker%20SDK-2496ED?style=flat-square&logo=docker&logoColor=white"></a> <a href="https://github.com/abiosoft/colima"><img alt="engine: Colima" src="https://img.shields.io/badge/engine-Colima-2496ED?style=flat-square"></a> |
| <img alt="execution & tools" src="https://img.shields.io/badge/-execution-2496ED?style=flat-square"> | **L6 tools** | the typed registry of git, pytest, ruff and pyright, every call an event; a workflow adds its own | <a href="https://git-scm.com/"><img alt="tool: git" src="https://img.shields.io/badge/tool-git-F05032?style=flat-square&logo=git&logoColor=white"></a> <a href="https://docs.pytest.org/"><img alt="verification: pytest" src="https://img.shields.io/badge/verification-pytest-0A9EDC?style=flat-square&logo=pytest&logoColor=white"></a> <a href="https://docs.astral.sh/ruff/"><img alt="check: ruff" src="https://img.shields.io/badge/check-ruff-D7FF64?style=flat-square&logo=ruff&logoColor=black"></a> <a href="https://github.com/microsoft/pyright"><img alt="check: pyright" src="https://img.shields.io/badge/check-pyright-9a6ee0?style=flat-square"></a> |
| <img alt="state" src="https://img.shields.io/badge/-state-1f6feb?style=flat-square"> | **L7 state** | the record: files per run, versioned artifacts, the index across runs | <a href="https://www.sqlite.org/"><img alt="run registry: SQLite" src="https://img.shields.io/badge/run%20registry-SQLite-003B57?style=flat-square&logo=sqlite&logoColor=white"></a> <a href="https://developmentseed.org/obstore/"><img alt="artifacts: obstore" src="https://img.shields.io/badge/artifacts-obstore-003B57?style=flat-square"></a> |
| <img alt="cross-cutting planes" src="https://img.shields.io/badge/-plane-bb8009?style=flat-square"> | **L8 observability** | traces, tokens, the five evaluations, trends across runs | <a href="https://mlflow.org/"><img alt="traces & evals: MLflow 3" src="https://img.shields.io/badge/traces%20%26%20evals-MLflow%203-2fa39a?style=flat-square&logo=mlflow&logoColor=white"></a> <a href="https://opentelemetry.io/docs/specs/semconv/gen-ai/"><img alt="names: OpenTelemetry" src="https://img.shields.io/badge/names-OpenTelemetry-425CC7?style=flat-square&logo=opentelemetry&logoColor=white"></a> |
| <img alt="cross-cutting planes" src="https://img.shields.io/badge/-plane-bb8009?style=flat-square"> | **L9 authorization** | may this side author, judge, write or call this | <a href="https://www.cedarpolicy.com/"><img alt="authorization: Cedar" src="https://img.shields.io/badge/authorization-Cedar-5a4fcf?style=flat-square"></a> |
| <img alt="cross-cutting planes" src="https://img.shields.io/badge/-plane-bb8009?style=flat-square"> | **L10 guardrails** | before the prompt, after the answer, before a tool call | <a href="https://www.guardrailsai.com/"><img alt="guardrails: Guardrails AI" src="https://img.shields.io/badge/guardrails-Guardrails%20AI-1f6feb?style=flat-square"></a> <a href="https://docs.pydantic.dev/"><img alt="schemas: pydantic v2" src="https://img.shields.io/badge/schemas-pydantic%20v2-E92063?style=flat-square&logo=pydantic&logoColor=white"></a> |

The layering is the shape the production platforms have converged on. AWS Bedrock AgentCore
names thirteen services [1], Google Vertex Agent Engine eleven [2], Palantir AIP twelve [3],
Microsoft Foundry seven plus four [4], IBM watsonx Orchestrate about eleven [5]; strip each to
what a single-machine runtime needs and the same ten remain: a core of interface, control,
orchestration, model runtime, execution, tools and state, with authorization, guardrails and
observability cut across all of them. The academic reference architectures draw the same
picture [6, 7, 8], and the separation of the planes from the model is the reference-monitor
principle [9, 10] as the agent-security work applies it [11, 12, 13]. Per layer:

| layer | grounded in |
|---|---|
| L1 UI | agents must have well-defined human controllers [14]; the human-in-the-loop patterns of the vendor guides [15, 16, 17] |
| L2 control plane | AgentCore's Gateway, Registry and Policy [1]; Vertex's Agent Gateway and Sessions [2]; the budget as a first-class control [7]; the control plane of the agent OS [18] |
| L3 orchestration | Microsoft's orchestration patterns and durable task ledger [17]; Prefect's flow-run model as the runner; the decision procedure of a cognitive architecture, code sequencing and the model never [19] |
| L4 agent runtime | AgentCore Runtime [1], Vertex Agent Runtime [2], Foundry Agent Runtime [4]; the model's action space as one structured answer [19]; the vendor CLIs' own runtimes [20, 21] |
| L5 sandbox | AgentCore Code Interpreter and Vertex Code Execution as separate services [1, 2]; the sandboxing designs of Claude Code and Codex [20, 21]; security function isolation [22]; the "lethal trifecta" [23]; capability-based isolation [11] |
| L6 tools | AgentCore Gateway's tool contract and Vertex's tool services [1, 2]; the Model Context Protocol [24]; privilege control per tool with a closed declared list [12] |
| L7 state | Google ADK's split of session state, memory and versioned artifacts [25]; AgentCore Memory's short-term events and long-term store [1]; memory as its own tier [26, 27, 28]; provenance of every artifact [29, 30] |
| L8 observability | AgentCore Observability and Evaluations [1]; Vertex Evaluation Service [2]; Databricks Mosaic AI on MLflow tracing and agent evaluation [31]; OpenAI's trace and span model [16]; provenance graphs of agent runs [29, 30]; repudiation as a named agent threat [32] |
| L9 authorization | AgentCore Identity and Policy, Cedar at the gateway [1]; Vertex Agent Identity [2]; Foundry's identity and RBAC [4]; the reference monitor [9]; attribute-based access control and the policy-decision / policy-enforcement split [33, 34]; least privilege for agent powers [14, 10]; context-derived policies for agents [13] |
| L10 guardrails | OpenAI's input, output and tool guardrails [16]; Salesforce's Einstein Trust Layer [35]; NVIDIA's rail types [36]; prompt injection as the top LLM threat [37]; defence by design [11]; the injection benchmark rails are measured against [38] |

<details>
<summary><b>References</b></summary>

Industry platforms and guides

1. AWS, Amazon Bedrock AgentCore developer guide: Harness, Runtime, Memory, Gateway, Identity, Code Interpreter, Browser, Observability, Payments, Evaluations, Optimization, Policy, Registry. https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html
2. Google Cloud, Vertex AI Agent Engine overview: Agent Runtime, Sessions, Memory Bank, Code Execution, Evaluation Service, Agent Identity, Agent Gateway, Observability and others. https://docs.cloud.google.com/vertex-ai/generative-ai/docs/agent-engine/overview
3. Palantir, AIP architecture. https://www.palantir.com/docs/foundry/architecture-center/aip-architecture
4. Microsoft, Azure AI Foundry Agent Service overview. https://learn.microsoft.com/en-us/azure/ai-foundry/agents/overview
5. IBM, watsonx Orchestrate overview. https://www.ibm.com/docs/en/watsonx/watson-orchestrate/base?topic=overview
6. A reference architecture for LLM-based agentic systems: Interface, Core, Control, Memory, Tooling, with Governance and Observability cross-cutting. arXiv 2026. https://arxiv.org/abs/2602.10479
7. Liu et al., "Agent Design Pattern Catalogue" (CSIRO). arXiv 2024. https://arxiv.org/abs/2405.10467
8. Lu et al., "A Reference Architecture for Designing Foundation Model based Agents" (CSIRO). arXiv 2023. https://arxiv.org/abs/2311.13148
9. Anderson, "Computer Security Technology Planning Study" (the reference monitor). 1972. https://csrc.nist.gov/files/pubs/conference/1998/10/08/proceedings-of-the-21st-nissc-1998/final/docs/early-cs-papers/ande72a.pdf
10. Saltzer and Schroeder, "The Protection of Information in Computer Systems". 1975. https://www.cs.virginia.edu/~evans/cs551/saltzer/
11. Debenedetti et al., "CaMeL: Defeating Prompt Injections by Design" (Google DeepMind, ETH). arXiv 2025. https://arxiv.org/abs/2503.18813
12. Shi et al., "Progent: Programmable Privilege Control for LLM Agents". arXiv 2025. https://arxiv.org/abs/2504.11703
13. Tsai and Bagdasarian, "Conseca: Context-derived Security Policies for LLM Agents". arXiv 2025. https://arxiv.org/abs/2501.17070
14. Google, "An Introduction to Google's Approach for Secure AI Agents". 2025. https://research.google/pubs/an-introduction-to-googles-approach-for-secure-ai-agents/
15. Anthropic, "Building Effective Agents". 2024. https://www.anthropic.com/research/building-effective-agents
16. OpenAI, "A Practical Guide to Building Agents" and the Agents SDK guardrails and tracing documentation. 2025. https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf
17. Microsoft, Azure Architecture Center, "AI agent orchestration patterns". 2026. https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/ai-agent-design-patterns
18. Mei et al., "AIOS: LLM Agent Operating System". arXiv 2024, COLM 2025. https://arxiv.org/abs/2403.16971
19. Sumers, Yao, Narasimhan and Griffiths, "Cognitive Architectures for Language Agents" (CoALA). TMLR 2024. https://arxiv.org/abs/2309.02427
20. Anthropic, Claude Code security and sandboxing. https://code.claude.com/docs/en/sandboxing
21. OpenAI, Codex agent approvals and security. https://learn.chatgpt.com/codex/agent-approvals-security
22. NIST SP 800-53 rev. 5, control SC-3, security function isolation. https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/final
23. Willison, "The Lethal Trifecta for AI Agents". 2025. https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/
24. Model Context Protocol, specification, architecture. https://modelcontextprotocol.io/specification/2025-06-18/architecture
25. Google, Agent Development Kit: sessions, state, memory and artifacts. https://google.github.io/adk-docs/agents/
26. Packer et al., "MemGPT: Towards LLMs as Operating Systems". arXiv 2023. https://arxiv.org/abs/2310.08560
27. Park et al., "Generative Agents: Interactive Simulacra of Human Behavior". UIST 2023. https://arxiv.org/abs/2304.03442
28. Zhang et al., "A Survey on the Memory Mechanism of Large Language Model based Agents". arXiv 2024. https://arxiv.org/abs/2404.13501
29. Souza et al., "PROV-AGENT". IEEE e-Science 2025. https://arxiv.org/abs/2508.02866
30. Wu, Castelo, Liu, Silva and Freire, "AgentTrails". VLDB 2026 DASHSys workshop. https://arxiv.org/abs/2607.18816
31. Databricks, Mosaic AI agent framework: MLflow tracing and agent evaluation. https://docs.databricks.com/aws/en/generative-ai/agent-framework/build-genai-apps
32. OWASP, "Agentic AI Threats and Mitigations" (T8, repudiation and untraceability). 2025. https://genai.owasp.org/resource/agentic-ai-threats-and-mitigations/
33. NIST SP 800-162, "Guide to Attribute Based Access Control". https://nvlpubs.nist.gov/nistpubs/specialpublications/NIST.sp.800-162.pdf
34. OASIS, XACML 3.0 core specification (PDP, PEP, PIP, PAP). https://docs.oasis-open.org/xacml/3.0/xacml-3.0-core-spec-os-en.html
35. Salesforce, the Einstein Trust Layer. https://trailhead.salesforce.com/content/learn/modules/the-einstein-trust-layer/meet-the-einstein-trust-layer
36. NVIDIA, NeMo Guardrails: input, dialog, retrieval, execution and output rails. https://docs.nvidia.com/nemo/guardrails/
37. OWASP, "Top 10 for LLM Applications" 2025 (LLM01 prompt injection, LLM06 excessive agency). https://genai.owasp.org/llm-top-10/
38. Debenedetti et al., "AgentDojo". NeurIPS 2024 Datasets and Benchmarks. https://arxiv.org/abs/2406.13352

</details>

Every subsystem receives the same run id, and the page joins on it:

```text
run id
   |
   +-- Prefect ------> what is executing?
   +-- MLflow -------> what did the models do, at what cost, how well?
   +-- the registry -> which runs exist, where, in what state?
   +-- the run folder -> the record: state, events, artifacts, evals
```

## Install

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cp .env.example .env          # one API key is enough to start; FAKE_MODELS=1 needs none
just doctor                   # exit 0 = ready; every line it checked is printed (or: .venv/bin/csmw doctor)
```

## First run

```bash
just walk code_builder        # the whole recipe on fake models: 10 legs, zero tokens, ~20 s
just dash                     # the dashboard on 127.0.0.1:3000
just run examples/code_builder/task.json
```

`docs/QUICKSTART.md` lists every command; `docs/HACKATHON-30MIN.md` is the first half hour.

## Settings you choose once

The run's start page is one form: the brief, then one card per setting — the running mode,
the rounds cap, the checker's model, effort and speed, then a model and an effort per stage
for the author side, then the verification-run overrides — each a row of chips with the default
pre-selected and a one-line reason for that default. The pre-selected setup is a one-round
average task: the checker at high effort (a lazy review looks identical to a clean pass), the
contract and verification rows carrying the judgment, the build on the cheapest model. Adjust
per task; your picks are remembered for the next run. The form derives from one settings
schema, which the CLI reads too. The layout is `docs/DASHBOARD-DESIGN.md` → *The start page*.

**Estimated cost.** The dashboard prices a run's tokens on read (rule 14: tokens are the fact, dollars
are a lookup). Prices come from a vendored copy of LiteLLM's model price map (`data/model_prices.json`,
420 models, the file and not the package); a run on a CLI login shows its figure "at API rates",
since the subscription bills flat. A model the map does not know shows `$?`. To override a rate, or
price a model of your own, put a `prices.json` next to your runs (or set `CSMW_PRICES_FILE`):

```json
{"my-negotiated-model": [0.25, 2.0]}
```

Values are USD per million input and output tokens; cached input is billed at the map's cached
rate where it states one.

The figure is always the API price of the tokens. A side that ran on `claude -p` or `codex exec`
under a subscription login is not billed per token, and the page marks the estimate "at API rates"
for such runs: a comparison, not a bill.

## Read more

- [docs/PLAN.md](docs/PLAN.md) — the full design: backbone, schemas, verification, recipes, dashboard, figure, build order
- [docs/RELIABILITY.md](docs/RELIABILITY.md) — the doctrine the rules come from
- [docs/BUG-LEDGER.md](docs/BUG-LEDGER.md) — the bug classes; classify before fixing, fix the class
- [docs/HACKATHON-30MIN.md](docs/HACKATHON-30MIN.md) — the first thirty minutes
- [docs/ADD-A-RECIPE.md](docs/ADD-A-RECIPE.md) — extend it

## Prior art

[claudex-loop](https://github.com/chaseai-yt/claudex-loop) showed Claude Code paired with OpenAI Codex as an
adversarial reviewer inside a Claude Code plugin; the coder project built on this template follows that pairing.

## License

MIT.
