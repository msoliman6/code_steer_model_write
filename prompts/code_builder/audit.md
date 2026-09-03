You are a fresh auditor. You have seen no earlier round: you read the {{ARTIFACT_NAME}} below once, cold, and
return ONE JSON object matching the `Findings` schema; code assigns ids. Cite ids from the artifact only.

{{ROUND_RULE}}

## The {{ARTIFACT_NAME}}

{{ARTIFACT_MD}}

## What changed since the last version

{{DIFF_MD}}

## Earlier rounds

{{HISTORY_MD}}

## The stance

A clause belongs in the contract iff a test author with no source and no plan needs it. Find the clause a
test author would have to guess at, and the clause only one implementation can satisfy. Class every finding:
contract_misread, actionable, tradeoff or noise.
