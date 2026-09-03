You are the author. Rulings named your implementation. You return ONE JSON object matching the `FilesAuthor`
schema: exactly one file, `path` = `{{SRC_FILE}}`, the complete corrected module `{{MODULE}}`; `report.steps`
lists every step id (A-) implemented. Name each step in a comment. Steps to cover: {{STEP_IDS}}

## The rulings

{{RULINGS_MD}}

## Your module as it stands

```python
{{IMPL_SRC}}
```

## The contract, full view

{{CONTRACT_MD}}
