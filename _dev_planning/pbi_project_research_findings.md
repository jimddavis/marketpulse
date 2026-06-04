# Research findings — WSL-bridge Claude Code + pbi-cli for Power BI on Databricks Gold

**Date:** 2026-06-03 · **Depth:** deep (web research, multi-source) · **Input prompt:**
`_dev_planning/pbi_project_research_prompt.md` · **Next step:** feed to `/sc:design`.
**Scope:** research only — no implementation, no decisions made for you (recommendations are for human approval).

> **Confidence legend:** **Verified** = corroborated by official docs or multiple independent sources ·
> **Projected** = single source / reasonable inference, not confirmed · **Unverified** = plausible but
> needs an empirical test before relying on it.

---

## Executive summary

1. **The WSL-bridge is technically possible but swims upstream** and has two real friction points, neither
   fatal but both needing an empirical test: (a) pbi-cli's value is *in-process sub-second* execution on
   Windows, which **WSL→Windows interop erodes** (each `*.exe` call from WSL pays Windows-process-launch
   overhead — observed ~seconds for `powershell.exe`); (b) the **`.pbip` files must be shared** across the
   boundary, and Power BI Desktop is exactly the kind of heavy, autosaving, file-locking Windows app that
   `\\wsl$` access is documented as *risky* for. **The realistic fallback remains Claude Code native on
   Windows.** [Verified that pbi-cli/Desktop are Windows-only and that interop + `\\wsl$` have these
   characteristics; **Unverified** that the full bridge works end-to-end.]
2. **Connectivity is the big win.** For a Gold *star schema*, **Import mode** via the Databricks Power BI
   connector is the recommended default. Crucially, the connector **copies Databricks column COMMENTs to
   Power BI column descriptions and preserves foreign-key relationships in the published dataset** — so our
   Gold layer (rich COMMENTs + declared PK/FK) can **auto-generate most of the semantic model**. [Verified]
3. **PBIP + TMDL + PBIR in git** is the modern, well-supported source-control story; pbi-cli is one tool in
   a mature ecosystem (Tabular Editor, pbi-tools, Fabric CLI). [Verified]
4. **Licensing:** local Desktop dev (where pbi-cli operates) is **free**; *sharing* a report needs **Pro
   ($14/user/mo)** to publish, and viewers need Pro unless on **F64+/P1+** capacity. [Verified]

---

## Q1 — Making the WSL-bridge work (lead question)

**Hard facts (Verified):**
- pbi-cli's **semantic-model layer is Windows-only** (TOM/ADOMD .NET DLLs) and connects **in-process to a
  locally running Power BI Desktop**; macOS/Linux unsupported. Power BI Desktop is itself Windows-only.
- **WSL2 interop can invoke Windows `.exe`s** from Linux (this is how Claude Code in WSL already opens
  Windows Chrome / runs `powershell.exe`). So `pbi-cli.exe` *can* be launched from WSL.
- **Interop has latency:** repeated `powershell.exe` calls in Claude Code's WSL startup cost ~10s each
  (~60s total) — a documented perf wart. Per-call Windows process launch overhead is real.
- **`\\wsl$` file access:** the safe way for Windows apps to reach Linux files; fine for *simple* editors,
  but **"heavy desktop applications that autosave, create temp files, or index directory trees" are riskier**
  and can corrupt/lock. Power BI Desktop is in that risky category. Conversely, putting the repo on `/mnt/c`
  (NTFS) makes WSL-side git/Claude operations slower (the standard WSL2 perf guidance: keep project files on
  the Linux fs for speed).

**The bridge mechanism (Projected / Unverified — must be tested):**
- Install **pbi-cli on the Windows side** (`pipx` under Windows Python); Power BI Desktop on Windows.
- Claude Code runs in **WSL2** and invokes the model-layer commands as **`pbi-cli.exe`** via interop (likely
  wrapped in a thin WSL shell shim that translates paths with `wslpath`).
- **Skills mismatch to resolve:** `pbi-cli skills install` writes skill markdown into a Claude Code skills
  dir. Run on Windows it targets *Windows* Claude Code; a WSL Claude Code reads *its* skills dir. So you must
  either point/copy the skills into the WSL `~/.claude/skills` (or project `.claude/skills`) and ensure the
  skill commands resolve to the **Windows binary** (interop PATH or shim). *(Unverified — the key thing to
  prove first.)*
- **File-location decision (the central trade):** repo + TMDL/PBIR on the **WSL filesystem** (fast for
  git/Claude) with Desktop opening the `.pbip` via `\\wsl$\…` (accept locking risk; mitigate: don't run git
  ops while Desktop holds the file, close Desktop before merges) — **vs** repo on **`/mnt/c`** (safe for
  Desktop, slower for WSL tooling). Neither is clean.

**Recommendation:** treat the bridge as **"validate before committing."** Stand up a 30-minute spike:
install pbi-cli on Windows, open a trivial `.pbip`, and from WSL Claude Code attempt one model-layer skill
(e.g. `dax execute`) and one report-layer edit, with the file on `\\wsl$`. **Trip-wires that force the
Windows-native fallback:** skills can't resolve the Windows binary; interop latency makes interactive use
painful; or `.pbip` locking/corruption under Desktop. Document the working recipe (or the fallback) for the
project `CLAUDE.md`.

> *Note:* the report layer (PBIR JSON on disk) is pure text manipulation and is the part most likely to work
> cleanly from WSL; the **model layer** (needs the live Desktop/TOM connection) is where the bridge is
> genuinely uncertain.

## Q2 — pbi-cli capabilities & maturity [Verified, with one discrepancy]

- PyPI `pbi-cli-tool` (latest ~**3.11.1**, May 2026), MIT; ~344★. Two layers: **semantic model** (in-process
  .NET TOM/ADOMD → Desktop) and **report** (PBIR JSON on disk, offline/CI-friendly). No MCP server, no
  sidecar, sub-second in-process execution.
- `pbi-cli skills install` registers **~13 Claude Code skills** (sources disagree 12 vs 13 — *pin this down at
  install time*): model-side (DAX, Modeling/tables-columns-measures-relationships, Deployment/TMDL,
  Security/RLS, Docs, Partitions, Diagnostics) + report-side (Report, Visuals, Pages, Themes, Filters, Custom
  Visuals, Bookmarks). ~27 command groups, all `--json`.
- **TMDL** export/import/diff/snapshot; **PBIR** create/visuals/pages/filters/custom-visuals.
- **Does NOT do:** Power BI **Service** deployment, dataset refresh, Fabric, or XMLA/service-principal —
  strictly a **local Desktop** tool. Known rough edges when Desktop isn't running or `.pbip` layout is
  non-standard.

## Q3 — Gold → Power BI connectivity [Verified — the strongest finding]

- **Import vs DirectQuery vs Direct Lake:** for a Gold *star schema*, **Import mode** is the recommended
  default (lowest latency, full DAX; needs scheduled refresh). **DirectQuery** only when freshness must beat
  the refresh cadence (live queries to a Databricks **SQL warehouse**; every interaction is a round-trip).
  **Direct Lake is Microsoft-Fabric/OneLake-only — NOT a native Databricks→Power BI option** (reachable only
  by mirroring/shortcutting Databricks into OneLake first). Composite/Dual is possible later.
- **Auto-generated model from the contract (key):** the Databricks connector **copies column COMMENTs →
  Power BI column descriptions** and **preserves foreign-key relationships** in the published dataset. Our
  Gold has rich COMMENTs + declared PK/FK → much of the semantic model materializes for free.
  **Caveat:** Power BI allows **one active relationship path** between two tables; multiple paths → some
  relationships imported **inactive** (watch where facts share `geo_key`/`date_key` to the same dims).
- **Modeling guidance:** keep narrow dimensions, avoid wide unused fact columns (each costs memory in Import /
  payload in DirectQuery). Our Gold is already conformed and narrow → good fit.

## Q4 — Source-controlled PBI development [Verified]

- **PBIP** = `.pbip` manifest + `.SemanticModel/` (**TMDL**, human-readable YAML-like) + `.Report/` (**PBIR**
  JSON). Commit TMDL/PBIR + `.pbip`; **exclude `.pbix`/cache** (`.gitignore` auto-created on first PBIP save).
- **Merge-conflict avoidance:** organize measures into **thematic display folders** → TMDL writes them to
  separate files → fewer conflicts. Small frequent commits; feature branches → PR to protected `main`.
- **Tooling ecosystem (pbi-cli is one of several):** **Tabular Editor 2** (free, Windows) / **3** (paid) =
  the heavy-duty model/DAX editor; **pbi-tools** = CLI for source-control/DevOps; **Fabric CLI** + Fabric Git
  integration = deploy `.pbip` to a workspace; **semantic-link / sempy** = Fabric-notebook-oriented (less
  relevant unless you adopt Fabric). Reasonable stance: **pbi-cli for AI-driven edits, Tabular Editor 2 as the
  power tool, git for the PBIP** — don't rely on a single tool.

## Q5 — Auth, licensing, cost [Verified, 2026 pricing]

- **Local Desktop development is free** — pbi-cli operates entirely here (Desktop's own running instance; no
  cloud auth).
- **To share:** publishing to a shared workspace needs **Power BI Pro ($14/user/mo)** per creator (also
  required even on Premium/Fabric capacity). **Viewers** need Pro **unless** the workspace is on **F64+/P1+**
  capacity (then free viewers). **PPU ($24/user/mo)** adds paginated reports, 48 daily refreshes, deployment
  pipelines. **Fabric** F2 ≈ $262/mo … F64 ≈ $5k/mo (break-even vs all-Pro ≈ 500 viewers).
- **Implication:** a solo/small project = Pro for the author; capacity only worthwhile at scale. Direct Lake
  would *require* Fabric capacity — another reason Import-from-Databricks is the pragmatic path.

## Q6 — Project conventions (inputs for the CLAUDE.md + skills) [Projected — synthesis]

- **CLAUDE.md should cover:** project context (**data source = marketpulse Gold contract**); **WSL-bridge
  operating notes** (how to invoke `pbi-cli.exe` from WSL, the `.pbip` file-location rule, "close Desktop
  before git ops"); **connection mode = Import**; model/naming conventions (**mirror Gold names/grain**); DAX
  & measure standards (measure tables, thematic folders, DAX style); RLS conventions; report/theme
  conventions; the **Gold data-contract rules** (names/types/grain are authoritative, sourced from
  `silver_gold_column_name_mapping.md` + `gold_ddl.py`); confidence grading; scope/non-goals (no Service
  deploy automation v1, no Fabric v1).
- **Skills set:** the pbi-cli skills (≈13) **plus** project-specific skills, e.g. *sync-model-from-gold-
  contract*, *scaffold-measure* (house DAX pattern), *wsl-bridge-doctor* (verify Desktop running + binary
  reachable), *report-page-scaffold*.

---

## Recommendations for `/sc:design` (for human approval — not decisions)

1. **Topology:** proceed with the **WSL-bridge as chosen**, but gate the design on a **validation spike**
   (Q1). Carry the **Windows-native fallback** as a first-class branch with explicit trip-wires.
2. **Connection:** **Import mode** via the Databricks connector; lean on **auto-propagated descriptions + FK
   relationships** to generate the base model from Gold; handle the inactive-relationship caveat for shared
   keys.
3. **Toolchain:** PBIP (.pbip + TMDL + PBIR) in git; VS Code; pbi-cli for AI edits; Tabular Editor 2 as the
   power tool; defer Fabric CLI/pipelines.
4. **Repo skeleton (draft):** `marketpulse-pbi/` → `<model>.pbip`, `<model>.SemanticModel/` (TMDL),
   `<model>.Report/` (PBIR), `.gitignore`, `CLAUDE.md`, `.claude/skills/`, `docs/gold_data_contract.md`
   (derived from the marketpulse contract), `docs/wsl_bridge_setup.md`.
5. **Contract hand-off:** copy a **frozen Gold data-contract spec** into the PBI repo (per [[CLAUDE §21]]) so
   the PBI project reads an artifact, not this conversation.

## Open items requiring an empirical test (cannot be settled by research)

- **[Unverified, blocking the topology]** Does a WSL Claude Code actually drive pbi-cli's model layer
  end-to-end (skills resolve the Windows binary; TOM connects to Desktop)? → the spike in Q1.
- **[Unverified]** `.pbip` location: `\\wsl$` (locking risk w/ Desktop) vs `/mnt/c` (slow WSL tooling) — test
  both with a real model.
- **[Projected]** `pbi-cli skills install` target/relocation for a WSL Claude Code skills dir.
- **[Projected]** Exact skill count/names (12 vs 13) — confirm at install.

## Sources
- pbi-cli: <https://github.com/MinaSaad1/pbi-cli> · <https://github.com/MinaSaad1/pbi-cli/blob/master/README.md> · <https://libraries.io/pypi/pbi-cli-tool> · <https://community.fabric.microsoft.com/t5/Power-BI-Community-Blog/pbi-cli-Gi-Claude-Code-the-Power-BI-Skills-It-Needs-Semantic/ba-p/5146283>
- WSL2 interop / files: <https://aicodeinvest.com/claude-code-windows-11-wsl2-development-environment-guide/> · <https://github.com/anthropics/claude-code/issues/14352> · <https://pomeroy.me/2023/12/how-i-fixed-wsl-2-filesystem-performance-issues/> · <https://www.howtogeek.com/your-wsl2-projects-are-running-much-slower-because-you-put-them-on-the-windows-filesystem/>
- Databricks ↔ Power BI: <https://learn.microsoft.com/en-us/azure/databricks/partners/bi/power-bi-desktop> · <https://docs.databricks.com/aws/en/partners/bi/power-bi-service> · <https://www.dawiso.com/glossary/connecting-power-bi-to-databricks-complete-integration-guide> · <https://powerbiconsulting.com/blog/connect-databricks-power-bi-integration-guide-2026>
- PBIP/TMDL/git: <https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-overview> · <https://xebia.com/blog/power-bi-source-control/> · <https://powerbiconsulting.com/blog/power-bi-project-format-pbip-git-ci-cd>
- Tooling: <https://www.sqlbi.com/articles/tools-in-power-bi/> · <https://tabulareditor.com/> · <https://pbi.tools/cli/> · <https://learn.microsoft.com/en-us/fabric/data-science/semantic-link-power-bi>
- Licensing: <https://www.microsoft.com/en-us/power-platform/products/power-bi/pricing> · <https://powerbiconsulting.com/blog/power-bi-pricing-licensing-guide-2026> · <https://sranalytics.io/blog/power-bi-licenses/>
