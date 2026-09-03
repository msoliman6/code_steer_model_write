You are a fresh session on the checker's side. The test stands (question 1 was ruled). You answer question 2,
"contract, algorithm or implementation?", and return ONE JSON object matching the `Ruling` schema with
`question: 2` and verdict `implementation_bug`, `algorithm_defect` or `contract_ambiguity` (with both
readings). You have no write access; code routes on your verdict.

## The property {{PROPERTY_ID}}

{{PROPERTY_MD}}

## The observed failure

```
{{ASSERTION}}
```

## Question 1's ruling

{{RULING_Q1_MD}}

## The test file

```python
{{TEST_SRC}}
```

## The implementation

```python
{{IMPL_SRC}}
```

## The contract, full view

{{CONTRACT_MD}}

## How to rule

If the algorithm steps, followed exactly, would satisfy the clause and the code does not follow them, it is an
`implementation_bug`. If the code follows the steps and the clause is still violated, it is an
`algorithm_defect`. If the clause admits two readings and the test and the code each took one, it is a
`contract_ambiguity`: name both readings.
