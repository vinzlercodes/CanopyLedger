# CanopyLedger Contributor Instructions

Before planning or implementing any substantial change:

1. Read `CANOPYLEDGER_MASTER_PLAN.md`; it is the authoritative contract.
2. Read `PROGRESS.md`; continue from recorded state and remaining work.
3. Read the relevant files under `docs/contracts/`.
4. Use test-driven development for behavior changes.
5. Update `PROGRESS.md` in the same change whenever built scope, remaining scope, milestone status,
   verification evidence, blockers, or architectural decisions change.

`MASTER_PLAN.md` is a condensed implementation guide. It cannot override
`CANOPYLEDGER_MASTER_PLAN.md`.

Never mark a milestone `DONE` without executable gate evidence. Never silently weaken snapshot
immutability, independent CBB/IRC semantics, human approval, reproducibility, SQL containment, or
authoritative-calculation boundaries.
