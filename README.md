# upstream-tracker

Hourly GitHub Actions tracker for the upstream repos our GCI builds depend on:

- **SUSFS** — `gitlab.com/simonpunk/susfs4ksu` (gki-android* + master) → re-syncs `KairoVera/susfs4ksu-mirror`
- **Wild GCI** — `github.com/WildKernels/GKI_KernelSU_SUSFS` (main)
- **SukiSU-Ultra** — `github.com/SukiSU-Ultra/SukiSU-Ultra` (builtin/main/builtin-new)

On any branch-tip change it posts a signed Feishu card (`FEISHU_WEBHOOK`+`FEISHU_SECRET`)
listing the new commits. Mirror re-sync needs `MIRROR_TOKEN` (a KairoVera PAT with repo scope).
Tips are persisted in `state.json` (committed back each run).
