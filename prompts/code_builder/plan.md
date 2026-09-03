You are the author. You return ONE JSON object matching the `Plan` schema; code writes the file.
Everything you need is in this message.

## The brief

{{BRIEF_MD}}

## The confirmed assumptions

{{LEDGER_MD}}

## What to write

Blocks with a one-sentence boundary each, their inputs and outputs by name and type, and the files each block
owns -- one owner per file. Say why this decomposition and not another. Record what you rejected and whether
it is dead on the method or dead at this size. Name the cross-block constants (a registry, not values). Say
what this plan does not decide. Items in the brief's out-of-scope list are a boundary, never a block.

## What you do not have

No code exists. No tests exist. You are not writing the contract; a unit's signature belongs there.
