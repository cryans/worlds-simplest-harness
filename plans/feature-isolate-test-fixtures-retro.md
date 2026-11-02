---
branch: "isolate-test-fixtures"
feature: "isolate-test-fixtures"
status: "complete"
references:
  - "plans/feature-isolate-test-fixtures-requirements.md"
  - "plans/feature-isolate-test-fixtures-plan.md"
---

# Isolate test fixtures — retro

**Well:** `logs/` gone, still 32 green. The guard names the offending path instead of `assert 0 == 9`.

**Didn't:** the requirements doc was 821 words for four mechanical edits, and I defended the length
instead of cutting sections. Proposed criteria needed a subprocess to verify — out of scope.

**Learned:** the plan's step 4 was broken and its own Verify still passed. The adversarial step found
it. Every architectural assertion needs that step before it can be trusted.
