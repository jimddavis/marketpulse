# Research pass (revised) — Windows-native Claude Code + pbi-cli for Power BI on Databricks Gold

**Date:** 2026-06-03 · **Depth:** focused topology pass · **Relationship:** revises **Q1 (topology)** of
`pbi_project_research_findings.md` to **feature the Windows-native option**; **Q2–Q6 of that doc are
unchanged** (pbi-cli capabilities, Gold→PBI connectivity, source control, licensing, conventions are
topology-agnostic) and are not repeated here. **Research only — no implementation, no final decision.**

> **Confidence legend:** **Verified** = official docs / multiple independent sources · **Projected** =
> single source / inference · **Unverified** = needs an empirical test.

---

## Executive summary

- **Windows-native Claude Code is the validated, lower-risk topology for this project**, and for PBI work
  specifically it's arguably the *better* primary, not a fallback. Power BI Desktop and pbi-cli are both
  Windows-native; co-locating Claude Code on Windows **eliminates the WSL-bridge's two unproven risks
  entirely** — no WSL→Windows interop latency, and no `\\wsl$` file-locking of the live `.pbip`. **[Verified]**
- The Windows-native pbi-cli + Claude Code path is **documented and practitioner-proven** (official setup
  docs + multiple third-party "built a Power BI dashboard with Claude Code on Windows" write-ups), whereas
  the WSL-bridge is the path both original sources say is unsupported. **[Verified]**
- The cost is **a one-time Windows dev-environment setup** (a second Claude Code install + SuperClaude +
  MCP, with a couple of well-known PATH fixes) and **two environments to maintain** (WSL for the Databricks
  pipeline, Windows for the PBI project). Given the two projects are already separate ([[powerbi-followon-project]]),
  that split is natural, not overhead. **[Verified]**

**Net recommendation:** feature **Windows-native** as the topology `/sc:design` is built around; keep the
**WSL-bridge as the documented alternative** for anyone who insists on a single WSL environment.

---

## Q1 (revised) — Windows-native topology, featured

### Why it's the clean choice here
The whole reason the WSL-bridge was uncertain was the boundary: pbi-cli's model layer is **in-process .NET
to a locally-running Power BI Desktop**, both Windows-only. Put Claude Code on Windows and the boundary
disappears:

- **No interop tax.** pbi-cli's advertised **sub-second in-process** execution is preserved — Claude Code
  calls `pbi`/`pbi-cli` as a normal local command, not a cross-OS `*.exe` launch.
- **No file-locking risk.** The `.pbip`/TMDL/PBIR files, the git repo, Power BI Desktop, and Claude Code all
  live on the **same NTFS filesystem** — no `\\wsl$` access by a heavy autosaving Desktop app.
- **Skills land in the right place.** `pbi-cli skills install` writes into the **same Windows Claude Code**
  that will use them — none of the WSL↔Windows skills-dir mismatch the bridge introduced.

### The documented happy path (Verified)
1. Install **Claude Code natively on Windows** (native installer `irm https://claude.ai/install.ps1 | iex`,
   or `winget install Anthropic.ClaudeCode`). **Install [Git for Windows](https://git-scm.com/downloads/win)**
   so the **Bash tool** is available (else Claude Code uses the **PowerShell tool**).
2. Install **Python 3.10+**, then **`pipx install pbi-cli-tool`** (pipx avoids the Windows PATH problem that
   plain `pip` causes for the `pbi` entry point).
3. **`pbi-cli skills install`** (one-time) → registers the ~13 skills into Windows Claude Code.
4. Save the report as a **`.pbip`** project (File → Save As → Power BI Project) — required for the report-layer
   tools; open the `.pbix`/`.pbip` in Desktop; **`pbi connect`**.
5. (Optional) reinstall **SuperClaude** on Windows for the `/sc:*` commands (see below).

### Known setup wrinkles (Verified — minor, fixable)
- **Claude Code PATH:** the native `install.ps1` sometimes doesn't add `~/.local/bin` to PATH ("`claude` is
  not recognized") — fix by restarting the terminal or adding it manually.
- **SuperClaude on Windows:** the framework is **cross-platform by design** (PowerShell, Git Bash, WSL, etc.);
  one **known PATH-diagnostic false-negative** on Win11 PowerShell (`claude_cli not found in PATH` while
  `claude` runs fine) — cosmetic, same PATH root cause. **[Verified it installs; Projected that all `/sc:*`
  + its MCP servers (Serena/Tavily/etc.) work without per-server fiddling — reinstall and smoke-test.]**

### Shell tool — Git Bash vs the PowerShell tool (setup recommendation)
**Decision: install Git for Windows and let Claude default to the Bash tool; keep PowerShell available.**
Rationale (the lens is *agent* effectiveness, since Claude drives the shell):
- **You install Git for Windows anyway** — the PBIP+TMDL+PBIR workflow is git-based, and Git for Windows
  (the standard Windows git) **bundles Git Bash**. So enabling Claude's Bash tool is essentially **free**;
  going PowerShell-only doesn't save the install. **[Verified]**
- **Claude is more reliable in bash.** Most of its default shell patterns, skills, hooks, and examples are
  POSIX-bash-shaped (`grep`/`sed`/`find`, text pipes, `&&`, `$(...)`, heredocs). On the PowerShell tool
  those differ (object pipes, `Select-String`, different quoting), so Claude more often emits a bash-ism
  that errors then self-corrects — wasted turns. **[Projected — reasoned, not benchmarked]**
- **But the gap is narrow for THIS project:** most work is **pbi-cli** (single binary) + **git** — both
  shell-agnostic — not bash-heavy glue. So the choice is **low-stakes here**. **[Projected]**
- **PowerShell is a fine secondary:** genuinely first-class as of ~v2.1.139, better for a few Windows-native
  tasks (e.g. `Get-Process`/`Stop-Process` to check Power BI Desktop is running, ACLs, paths), and the user
  is fluent in it. You can run **both** — opt the PowerShell tool in alongside Bash via
  `CLAUDE_CODE_USE_POWERSHELL_TOOL=1`. **[Verified]**

**Net:** Git for Windows → Bash tool as the reliable default; PowerShell available for Windows-native bits.
Avoid PowerShell-only — it trades a small free win (agent reliability) for nothing actually saved.

### What you accept vs the WSL-bridge
| Dimension | Windows-native (featured) | WSL-bridge (alternative) |
|---|---|---|
| pbi-cli model layer | In-process, sub-second, **supported** | Cross-OS `.exe` via interop, **unverified** |
| `.pbip` file safety | Same NTFS fs — clean | `\\wsl$` locking risk vs `/mnt/c` slowness |
| Skills install target | Same Windows Claude Code — clean | WSL↔Windows mismatch to bridge |
| Shell / Linux tooling | **Git Bash** (most Unix tools) or PowerShell tool; narrower than a distro | Full Linux userland |
| **Sandboxing** | **Not supported on native Windows** | Supported (WSL2) |
| Setup cost | Second Claude Code + SuperClaude install (minor PATH fixes) | One environment, but bridge is unproven |
| Maintenance | Two environments (WSL=Databricks, Win=PBI) | One environment |
| Maturity | **Documented + practitioner-proven** | Swims upstream |

### The two real tradeoffs to weigh (not blockers)
1. **No sandboxing on native Windows** (Verified, from the setup docs' platform table). If you rely on
   sandboxed command execution, that's WSL-only. For a PBI repo (text/TMDL/PBIR + local Desktop), low impact.
2. **Two environments.** You keep doing Databricks/marketpulse in WSL (Linux toolchain, sandboxing, local
   PySpark) and do PBI on Windows. The projects are already separate, so this aligns with the plan rather
   than fighting it. The only shared artifact is the **Gold data contract** (a committed doc), not the env.

---

## Q2–Q6 — unchanged from `pbi_project_research_findings.md`

Topology does not change these; see the prior doc. One **delta in Q6 (project conventions / CLAUDE.md)**:

- The CLAUDE.md "operating notes" should describe the **Windows-native environment** instead of bridge notes:
  shell choice (**install Git for Windows for the Bash tool**, or note PowerShell-tool behavior), the
  **`.pbip` save step**, the **`pbi connect`** prerequisite (Desktop must be running with the project open),
  and pipx/PATH setup. The earlier "close Desktop before git ops / `\\wsl$` rule" notes are **no longer
  needed** (no cross-fs sharing).
- Everything else in Q6 stands: connection mode = **Import**; mirror Gold names/grain; DAX/measure standards;
  RLS; the **Gold data-contract rules** sourced from `silver_gold_column_name_mapping.md` + `gold_ddl.py`;
  skills set (pbi-cli ≈13 + project skills).

---

## Recommendations for `/sc:design` (for human approval)

1. **Topology: Windows-native, featured.** Build the design around a Windows-hosted Claude Code co-located
   with Power BI Desktop + pbi-cli. Document the **WSL-bridge as the alternative** (not the primary), with a
   one-paragraph "if you must stay single-environment" note.
2. **Validation is now small, not blocking.** No bridge spike required. The remaining check is an ordinary
   **fresh-Windows-setup smoke test**: install Claude Code (+ Git for Windows), `pipx install pbi-cli-tool`,
   `pbi-cli skills install`, `pbi connect` against a trivial `.pbip`, and confirm one model-layer skill +
   SuperClaude `/sc:*` run. Trip-wires are minor PATH fixes, not architecture.
3. **Connectivity / source control / licensing / tooling:** unchanged — Import mode via the Databricks
   connector (auto-propagated descriptions + FK relationships), PBIP+TMDL+PBIR in git, Pro to share.
4. **Repo & contract:** unchanged skeleton; carry a **frozen Gold data-contract spec** into the PBI repo.

## Open items (much smaller than the bridge version)
- **[Projected]** SuperClaude + its MCP servers fully functional on Windows after reinstall (minor PATH wrinkle
  known) — smoke-test.
- **[Projected]** Exact pbi-cli skill count/names (12 vs 13) — confirm at install.
- **[Verified-as-limitation]** No native-Windows sandboxing — accept or keep risky ops in WSL.

## Sources (new this pass; prior-pass sources still apply)
- Claude Code Windows setup: <https://code.claude.com/docs/en/setup> · <https://smartscope.blog/en/generative-ai/claude/claude-code-windows-native-installation/>
- SuperClaude cross-platform / Windows issues: <https://github.com/SuperClaude-Org/SuperClaude_Framework/issues/86> · <https://github.com/SuperClaude-Org/SuperClaude_Framework/issues/128>
- pbi-cli on Windows (practitioner-proven): <https://github.com/MinaSaad1/pbi-cli> · <https://www.f9finance.com/power-bi-dashboard-with-claude/> · <https://analyticalguy.substack.com/p/fully-automating-power-bi-development>
