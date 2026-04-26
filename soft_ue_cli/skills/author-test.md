---
name: author-test
description: Choose the right committed C++ gameplay test shape, then route to the matching authoring sub-skill. Use when the user wants to write a new regression test but has not yet picked the best test category.
version: 3.0.0
---

# author-test

Use this skill when the user wants to create a new committed gameplay regression test and needs help choosing the right shape first.

This is a routing skill. It does not scaffold files itself. Its job is to classify the request, recommend the best test type, and then hand off to one of the authoring sub-skills below.

## Test architecture

Use a two-layer workflow:

- Exploration layer: CLI + bridge + Python scripts to inspect runtime state, find the signal, and validate the repro quickly.
- Committed layer: C++ Automation Spec tests checked into the project's test module.

The output of every `author-*` skill is a committed C++ test scaffold, not a Python test file. Python/CLI material is supporting evidence and iteration tooling, not the final artifact.

## Do not use for

- Running existing tests.
- General bug investigation without a stable repro yet.
- Interactive debugging without intent to convert the result into a committed C++ test.

## Supported test types

| Skill | Best fit | Output location |
|---|---|---|
| `author-regression-test` | General reproducible sequence plus one or more observations | `Source/<Project>Tests/Private/Regression/TEST_<Slug>.cpp` |
| `author-anim-state-test` | Anim state machine, montage, or blend-weight regressions | `Source/<Project>Tests/Private/Anim/TEST_<Slug>.cpp` |
| `author-bp-parity-test` | BP to C++ parity checks using golden inputs and outputs | `Source/<Project>Tests/Private/Parity/TEST_<Slug>.cpp` plus optional fixture data |
| `author-invariant-test` | Single property invariant after setup | `Source/<Project>Tests/Private/Invariants/TEST_<Slug>.cpp` |

## Routing checklist

Ask only the minimum needed to classify the request:

1. What exact behavior should stay true?
2. What setup is required before the assertion?
3. Is the signal an animation trace, a BP/C++ parity comparison, a single property value, or a broader runtime observation?
4. What did the current session already learn from CLI/Python exploration that the C++ test should encode?

## Recommendation rules

- If the signal lives in animation state data such as state machines, montages, selected databases, or blend weights, choose `author-anim-state-test`.
- If the goal is proving a Blueprint port matches C++ for the same inputs, choose `author-bp-parity-test`.
- If the assertion is a single property read after setup, choose `author-invariant-test`.
- Otherwise choose `author-regression-test`.

## Common source material

All sub-skills should use what was learned in the current session from CLI/bridge/Python exploration:

- runtime signals discovered with tools such as `inspect-anim-instance`, `query-asset`, `call-function`, or `run-python-script`
- map and setup details
- the specific assertion that proves the bug or regression

That exploration material is input to the C++ scaffold. It is not the committed test target.

## Response pattern

State the recommendation explicitly before handing off:

> Based on your repro, the best fit is `author-anim-state-test` because the assertion lives in animation-state data across a tick window. I'll use that sub-skill to scaffold the committed C++ Automation Spec.

If the user agrees, retrieve the chosen sub-skill and follow it. After the sub-skill finishes and the file exists, offer the project-native Automation command needed to build and run the generated C++ test.
