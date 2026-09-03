"""The plan: blocks with boundaries, what was rejected and why, what the plan does not decide
(reference: plan-reference.md). Rejected is a registry so nobody rebuilds a dead end."""

from __future__ import annotations

from pydantic import Field

from ..spec.base import Artifact, CheckContext, Problem


class Block(Artifact):
    name: str = Field(description="a short slug, unique in the plan; the contract is keyed by it")
    boundary: str = Field(min_length=10, description="what is inside and what is not, in one sentence")
    inputs: list[str] = Field(description="what enters, by name and type")
    outputs: list[str] = Field(description="what leaves, by name and type")
    writes: list[str] = Field(description="the files this block owns, run-dir relative (one owner per file)")
    shape_driver: str = Field(default="", description="the constraint that decided the block's shape")


class Rejected(Artifact):
    idea: str
    why: str = Field(description="dead on the method, or dead at this size -- say which")


class Plan(Artifact):
    blocks: list[Block] = Field(min_length=1)
    decomposition: str = Field(min_length=20, description="why these blocks and not others")
    constants: list[str] = Field(
        default_factory=list, description="cross-block constants by name (a registry, not values)"
    )
    order: list[str] = Field(default_factory=list, description="block names in build order")
    rejected: list[Rejected] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    not_decided: list[str] = Field(
        default_factory=list, description="what this plan leaves to the contract or the human"
    )

    def semantic_problems(self, ctx: CheckContext) -> list[Problem]:
        out: list[Problem] = []
        names = [b.name for b in self.blocks]
        if len(set(names)) != len(names):
            out.append(Problem(code="block_names_dup", message=f"block names must be unique: {names}"))
        owners: dict[str, str] = {}
        for b in self.blocks:
            for w in b.writes:
                if w in owners:
                    out.append(
                        Problem(
                            code="file_two_owners",
                            message=f"{w} is written by {owners[w]} and {b.name}; one owner per file",
                        )
                    )
                owners[w] = b.name
        for n in self.order:
            if n not in names:
                out.append(Problem(code="order_unknown_block", message=f"order names {n!r}, not a block"))
        return out
