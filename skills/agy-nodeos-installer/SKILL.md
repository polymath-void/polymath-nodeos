---
name: agy-nodeos-installer
description: Standard Operating Procedure for injecting and activating the AGY-NodeOS background daemon and hook into a target workspace.
---

# AGY-NodeOS Injection + Native Interaction Protocol

Whenever tasked with initializing a project or operating inside a NodeOS-managed workspace, follow this protocol. Verified against Polymath-NodeOS 1.1.3 (`polymath_nodeos/cli.py`).

## 1. Verify Target Workspace

Ensure you are in the intended project directory. Create the local customization root if missing:

```bash
mkdir -p .agents
```

NodeOS binds dynamically via `os.getcwd()`. Launched at an umbrella root it links all sub-repos into one graph; launched inside a sub-repo it binds locally. State artifacts (`agy_nodeos.db`, `workflow.json`, `daemon.log`, `.agents/rules/`) always attach relative to the runtime CWD. Never hardcode paths.

## 2. Copy the Lifecycle Hook

Copy the master hook template so the host CLI binds the daemon to the workspace:

```bash
cp ~/.gemini/config/skills/agy-nodeos-installer/hooks.json .agents/hooks.json
```

Canonical boot hook (see `polymath-nodeos/hooks.json`):

```json
"command": "pgrep -f 'nodeos.*run-as-daemon' > /dev/null || nodeos -d"
```

## 3. Validate Daemon Boot

`nodeos -d` self-detaches (see `cli.py:run_daemon`) and appends to `./daemon.log`. No `nohup` / `&` wrapper needed. The `pgrep` guard must match the persistent `--run-as-daemon` child, not the transient `-d` parent.

```bash
nodeos -c ping   # expect: [Daemon Status] pong: OS Daemon is alive...
```

Do NOT run `python daemon.py` manually. The hook owns the lifecycle. Daemon watches `*.py`, `*.js`, `*.ts`, `*.json`, and `context.md` (ignores `.git`, `node_modules`, `__pycache__`, `venv`, `build`, `dist`, `.agents`, `.jsagent` as exact path segments).

## 4. Native Read / Write / Maintain (Seamless Pattern)

NodeOS is a physical environment + intent emitter, decoupled from execution logic. YOU are the intelligence; use host-native tools for all file operations and the graph only for insight.

| Intent | OpenCode tool | Antigravity equivalent |
|---|---|---|
| Read / list | `read`, `glob`, `grep` | `view_file`, `list_dir` |
| Write / edit | `write`, `edit` | `write_to_file`, `replace_file_content` |
| Commands / queries | `shell` (`nodeos`, `sqlite3`, `fd`, `rg`) | `run_command` |
| Delegate work | `subagent` | `invoke_subagent` |

Rules:

- NEVER use shell (`cat`, `sed`, `echo >>`) to read/write code. NEVER use deprecated wrappers (`nodeos_read.py`, `nodeos_search.py`). They bypass daemon event detection semantics.
- NEVER `grep -r` blindly for architecture. Query the graph first (section 5), then open at most 2-3 files with native `read`.
- Edits auto-maintain the codebase: on `modified` the daemon re-ingests the file, runs blast-radius threshold enforcement + QA; on `created` it runs the ghost-writer neighbor pipeline; on `deleted` it purges nodes/edges. No manual re-index step.
- Verify every multi-file edit: `nodeos -c qa <subdir>` (never bare workspace root — heavy), plus `python ~/.gemini/config/skills/qa-analyzer/scripts/analyzer.py <target_dir>`, plus one targeted test. Check interface integrity (imports/symbols exist) before invoking.

## 5. Native Codebase Context (Research Protocol)

Prefer `agy_nodeos.db` over manual scans. Schema: `nodes(node_id, node_type, name, filepath, hash, calls, x_coord, y_coord, last_updated)`, `edges(source_id, target_id, relation_type)`.

```bash
nodeos -c search <symbol>   # fast symbol lookup (exists in cli.py:run_search)
sqlite3 agy_nodeos.db "SELECT node_type, name, filepath FROM nodes WHERE name LIKE '%<Symbol>%';"
sqlite3 agy_nodeos.db "SELECT COUNT(*) FROM nodes; SELECT relation_type, COUNT(*) FROM edges GROUP BY 1;"
```

Spatial / maintenance engines (all verified in `cli.py:execute_command`):

- `nodeos -c ping` — daemon liveness via IPC port 6000.
- `nodeos -c search <symbol>` — LIKE-query over `nodes`.
- `nodeos -c blast <filepath>` — transitive dependent blast radius.
- `nodeos -c ghost <filepath>` — QuadTree centroid + nearest neighbors (context injection for new files).
- `nodeos -c dead` — orphaned nodes (0 incoming edges).
- `nodeos -c sentinel <fn>` — mark brittle function.
- `nodeos -c domino <old> <new>` — graph-guided rename (MUTATES code — confirm first).
- `nodeos -c qa [target]` — structural QA; always scope `target` to a subdir.
- `nodeos -c swarm [args]` — swarm engine via subprocess.
- `nodeos -s <script>` — engine script (`intent_injector`, `intent_stopper`, `swarm_engine`, `telemetry`, ...).

Research loop: `search` → `blast`/`ghost` for blast radius → native `read` of the 2-3 files that matter → edit → `qa` scoped verify.

## 6. Sub-Agent Intent Handling

NodeOS emits intents via `workflow.json` (`pending` → `running` → `completed` / `failed_qa` / `failed_execution`). Special actions `stitch` and `qa` are executed by the daemon itself; `execute_agents` awaits the host swarm.

When you observe `"status": "pending"`, inspect `action`/`target` FIRST. Never blindly execute shell payloads. Then dispatch via the host-native delegate (`subagent` on OpenCode, `invoke_subagent` on Antigravity) and flip status accordingly. Telemetry lives in `polymath_nodeos/scripts/telemetry.py`.

## 7. Context Sub-Parent Node Protocol

The daemon deduplicates `context.md` into SQLite via `scripts/context_engine.py` (stable `blake2b` ids, 15-memory sliding window).

- **Write:** append to `context.md` at the workspace root using exactly:
  `## 1. Task State`, `## 2. Discovered Entities`, `## 3. Working Memory`, with entries as `- [Key]: Value`.
- **Read:** NEVER parse `context.md` for recall. Query deduplicated state:
  ```bash
  sqlite3 agy_nodeos.db "SELECT name, hash FROM nodes WHERE node_type IN ('CONTEXT_STATE','CONTEXT_ENTITY');"
  ```

## 8. Anti-Patterns

- `nohup nodeos -d > daemon.log 2>&1 &` (double-wraps; `nodeos -d` already detaches + logs).
- `pgrep -f 'nodeos -d'` as liveness check (matches the transient parent; use `nodeos -c ping` or `pgrep -f 'nodeos.*run-as-daemon'`).
- Claiming `nodeos -c search` does not exist — it does (`cli.py:130-148`).
- Workspace-root `nodeos -c qa` or unbounded `find /` / `grep -r /` / `node_modules` scans on Termux (LMK kill / hang). Scope with `fd`/`rg` exclusions.
