# Deep-research prompt — WSL-bridge Claude Code + pbi-cli for Power BI on Databricks Gold

> **Purpose.** Hand this to a deep-research pass (e.g. `/sc:research` or an external deep-research
> tool). Its findings then feed `/sc:design` to design a new, standalone Power BI project. This is a
> planning artifact for the [[powerbi-followon-project]] — separate repo, own `CLAUDE.md`, own skills.
>
> **Preliminary findings that motivated this prompt (2026-06-03):** pbi-cli (github.com/MinaSaad1/pbi-cli,
> MIT, `pipx install pbi-cli-tool`, Python 3.10+) installs ~12–13 Claude Code skills + ~27 commands across
> a **semantic-model layer** (in-process .NET TOM/ADOMD to a locally-running Power BI Desktop) and a
> **report layer** (PBIR/.pbip JSON on disk). Auth = Desktop's running instance (no XMLA / service
> principal / Fabric). **Constraint: the model layer is Windows-only and needs Power BI Desktop running
> locally — no native Linux/WSL/Service support.** Topology chosen by the user: **WSL-bridge** (Claude
> Code in WSL2 drives pbi-cli/Desktop on the Windows side); Windows-native is the fallback. Exact skill
> counts/specifics are Projected — pin them down. Data source = the completed `marketpulse.gold` star
> schema; contract artifacts = `_dev_planning/silver_gold_column_name_mapping.md` + `gold_ddl.py`.

---

## Prompt (copy below this line)

**Deep research: a WSL-bridge Claude Code workflow for Power BI development against a Databricks Gold layer, using pbi-cli.**

**Context.** I develop on Windows with **WSL2** and run **Claude Code CLI inside WSL**. I'm building a **new, standalone project** (own repo, `CLAUDE.md`, skills) for **Power BI** work whose data source is an existing **Databricks Unity Catalog Gold layer** — a conformed star schema (3 dimensions + 4 facts, declared PK/FK, descriptive column COMMENTs), already complete. Tooling is **pbi-cli** (github.com/MinaSaad1/pbi-cli): it installs Claude Code skills but its semantic-model layer is **Windows-only and needs Power BI Desktop running locally** (in-process TOM/ADOMD; no native Linux/WSL/Service/XMLA). **Chosen topology: the WSL-bridge** — Claude Code stays in WSL2 and drives pbi-cli/Desktop on the Windows side.

**Objective.** Produce the evidence and recommendations to design this project for the WSL-bridge topology: the exact bridge mechanism + config, plus toolchain, repo/folder structure, `CLAUDE.md` content, skills set, and the Gold→Power-BI data-contract approach.

**Key questions:**

1. **Make the WSL-bridge work (lead question).** Define concretely how Claude Code in **WSL2** drives pbi-cli whose model layer runs on **Windows**: invoking Windows `pbi-cli.exe` and Power BI Desktop from WSL via interop; whether `pbi-cli skills install` skills function across the WSL↔Windows boundary (and whether to install pbi-cli on the Windows side, the WSL side, or both); path translation (`/mnt/c` ↔ `C:\`, `wslpath`), file-locking on `.pbip`/PBIR shared between WSL git and Windows Desktop, line-endings, and auth. Give a **step-by-step working setup** and the failure modes. Specify **Windows-native Claude Code as the fallback** only, with the trip-wire conditions that would force switching to it.

2. **pbi-cli capabilities & maturity.** Confirm exact skills/commands, the **TMDL** and **PBIR/.pbip** workflows, token-efficiency claims, current version/stability, and known rough edges; what it does *not* do (Service deployment, refresh, Fabric).

3. **Gold→Power BI connectivity.** Best practice connecting a PBI semantic model to **Databricks UC gold tables** (Databricks connector / Partner Connect; **Import vs DirectQuery vs Direct Lake**); how a conformed star schema (PK/FK + descriptions) maps to a PBI model; how to carry the contract (names/types/grain) and surface Gold column COMMENTs as model descriptions.

4. **Source-controlled PBI dev.** Best practices for **.pbip + TMDL + PBIR in git** (diff/review/CI-CD) given the files live on the WSL filesystem but Desktop edits them from Windows; where pbi-cli fits vs complements (**Tabular Editor 2/3, pbi-tools, Fabric CLI, semantic-link/sempy, DAX style guides**); rely solely on pbi-cli or combine.

5. **Auth, licensing, cost.** Local Desktop dev (free) vs publishing to the **Service** (Pro / PPU / Premium / **Fabric capacity**) — what's needed to share a report, and cost implications.

6. **Project conventions.** What belongs in a Power-BI **CLAUDE.md** (DAX/measure standards, model naming, TMDL layout, RLS, report/theme conventions, the Gold data-contract rules, **and the WSL-bridge operating notes**) and what the project's **skills set** should contain.

**Constraints.** Prefer **verified, current** info (pbi-cli and Power BI/Fabric move fast) — cite sources + dates, grade uncertain claims. This is a **separate project** from the Databricks repo, joined only at the Gold data contract.

**Deliverable.** A structured findings report ending with: (a) a **validated WSL-bridge setup** (exact steps + config; or, if it can't be made reliable, the evidence and the Windows-native fallback); (b) a **proposed toolchain**; (c) a **draft repo/folder structure**; (d) a **CLAUDE.md outline**; (e) a **skills-set list**; (f) the **Gold→PBI data-contract approach** — everything `/sc:design` needs as input.

---

## Honest flag for when results return

The WSL-bridge is the path **both initial sources say isn't supported**. The research must actually *prove* the bridge is reliable (skills functioning across the boundary, Desktop driven from WSL, no file-lock/path breakage). If it can't be made reliable, the **Windows-native Claude Code fallback is the realistic answer** — know that before committing `/sc:design` to the bridge.
