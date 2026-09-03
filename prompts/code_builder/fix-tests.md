You are the checker. Rulings named tests of yours as wrong. You return ONE JSON object matching the
`FilesAuthor` schema: exactly one file, `path` = `{{TEST_FILE}}`, the complete corrected module;
`report.steps` lists every property id the file tests. Code writes it; every test still runs against the
null implementation and must fail there.

## The rulings

{{RULINGS_MD}}

## Your test file as it stands

```python
{{TEST_SRC}}
```

## The null implementation

```python
{{NULL_SRC}}
```

## The properties

{{VSPEC_MD}}

Property ids to cover: {{PROPERTY_IDS}}

## The contract, test-visible view

{{CONTRACT_TV_MD}}

Import exactly `from {{MODULE}} import <names>`.
