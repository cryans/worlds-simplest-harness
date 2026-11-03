---
branch: "typed-session-contract"
feature: "typed-session-contract"
status: "complete"
references:
  - "plans/feature-typed-session-contract-requirements.md"
  - "plans/feature-typed-session-contract-design.md"
  - "plans/feature-typed-session-contract-plan.md"
---

# Typed session contract — retro

**Well:** the spike (step 1) de-risked the one uncertain piece before any real work — and found the
real gotcha: `openapi-typescript` does not name an inline union, so `SseEvent` must be registered
explicitly in `components.schemas`. The generated TS narrows under `tsc --strict`, and `check:api`
fails on a renamed Pydantic field and passes after revert.

**Didn't:** two plan verifies were wrong on arrival and had to be corrected mid-flight — step 3 was
internally contradictory (`prepare_session` returns a model, "no test edits", "32 passed" can't all
be true), and step 7's grep flagged the intended aliases, not the hand-written shapes it meant to
catch. The design doc also shipped with one unclosed mermaid fence, caught only by inspection.

**Learned:** when a type describes existing wire data, the *model must bend to the wire*, not the
other way — `manage_plan` returns a string, so `ToolStep.result` became `dict | str | None` and the
UI finally renders string results instead of `[exit undefined]`. Verifies written before the
generated shape exists should say *what property* to check ("no object-literal API shapes"), not a
literal grep.
