---
name: agy-nodeos-installer
description: Standard Operating Procedure for injecting and activating the AGY-NodeOS background daemon and hook into a target workspace.
---

# AGY-NodeOS Injection Protocol

Whenever you are tasked with initializing a project or establishing the AGY-NodeOS 24/7 background architecture in a workspace, you MUST follow these steps to inject the lifecycle hooks.

## 1. Verify Target Workspace
Ensure you are operating inside the intended project directory. If the project does not have a local `.agents` folder, you must create it:
```bash
mkdir -p .agents
```

## 2. Copy the Lifecycle Hook
The master hook file resides in the core AGY-NodeOS repository. You must copy it into the local project's `.agents` directory so the Antigravity CLI binds the daemon to the workspace.
```bash
cp ~/.gemini/config/skills/agy-nodeos-installer/hooks.json .agents/hooks.json
```

## 3. Validate Daemon Boot
Once the hook is copied, the `agy-nodeos-boot` script will automatically trigger on the very next `PreInvocation` event (which means the next time the agent is prompted). 

The hook executes the following:
`pgrep -f 'nodeos -d' > /dev/null || (nohup nodeos -d > daemon.log 2>&1 &)`

This guarantees the native Python AST Engine, SQLite Graph Manager, and QuadTree Spatial Physics Matrix are running silently in the background 24/7.

## 4. Sub-Agent Intent Handling
Do NOT manually run `python daemon.py` in the terminal. The hook handles it autonomously.

Remember that AGY-NodeOS is completely decoupled from execution logic. It acts purely as a physical environment and **Intent Emitter**. 
When you (the main agent) observe `workflow.json` transitioning to `"status": "pending"`, you must use your `invoke_subagent` tool to spawn a specialized AGY agent to perform the task. 
## 5. Native Codebase Context (Search Protocol)
When operating inside an AGY-NodeOS initialized workspace, you are strictly prohibited from relying on manual `grep` scans for structural understanding. 
Instead, rely on the native Graph Database by querying the search utility:
```bash
python nodeos_search.py "<TargetClassNameOrFunction>"
```
This utility natively computes K-Nearest Neighbors (KNN) from the QuadTree physics matrix and pulls edge targets, providing you with a clean JSON payload of both direct code dependencies and physical spatial neighbors (blast radius context).

## 6. Context Sub-Parent Node Protocol
The workspace utilizes a deduplicating context engine natively built into NodeOS.
- **Writing Context:** When reasoning or discovering new facts, you must append them to `context.md` at the workspace root, using standard Markdown headers (e.g., `## 1. Task State`, `## 2. Discovered Entities`, `## 3. Working Memory`).
- **Reading Context:** The background daemon intercepts `context.md` edits and writes them cleanly into `agy_nodeos.db`. Do not read `context.md`; instead query SQLite for nodes with `node_type` like `CONTEXT_%` to retrieve accurate, deduplicated state.
