#!/usr/bin/env python3
import asyncio
import os
import sqlite3
import sys

# We are now a fully packaged module. No sys.path hacking required.

import subprocess
import threading
import json
from multiprocessing.connection import Listener

from polymath_nodeos.graph_manager import AGYGraphManager
from polymath_nodeos.jage_engine import JageASTEngine
from polymath_nodeos.nodes_engine import NativeNodesEngine

class AGYRawWatchdog:
    """
    ZERO-DEPENDENCY RAW FILE OBSERVER
    Eliminates the need for 'pip install watchdog'. Uses lightweight asyncio polling.
    """
    def __init__(self, directory, callback, interval=1.0):
        self.directory = directory
        self.callback = callback
        self.interval = interval
        self.state = {}
        self.running = False
        self._initialize_state()

    # Internal OS state folders and vendored dependencies. Matched as exact path
    # SEGMENTS, never as substrings: 'env' in path would also skip a real project
    # named 'env-tools', and 'build' would skip 'buildserver/'.
    IGNORED_DIR_SEGMENTS = frozenset({
        '.jsagent', '.agents', '__pycache__', '.git', 'node_modules',
        'build', 'dist', '.venv', 'venv', '.build_cache', 'site-packages', 'env',
    })

    def _should_ignore(self, path):
        try:
            parts = os.path.normpath(path).split(os.sep)
        except (TypeError, ValueError):
            return False
        return any(part in self.IGNORED_DIR_SEGMENTS for part in parts)

    def _initialize_state(self):
        for root, _, files in os.walk(self.directory):
            if self._should_ignore(root):
                continue
            for file in files:
                if file.endswith(('.py', '.json')):
                    path = os.path.join(root, file)
                    self.state[path] = os.stat(path).st_mtime

    async def start(self):
        self.running = True
        print(f"[Raw Watchdog] Natively polling {self.directory} every {self.interval}s...")
        while self.running:
            await asyncio.sleep(self.interval)
            current_files = set()
            for root, _, files in os.walk(self.directory):
                if self._should_ignore(root):
                    continue
                for file in files:
                    if file.endswith(('.py', '.json')) or file == 'context.md':
                        path = os.path.join(root, file)
                        current_files.add(path)
                        try:
                            mtime = os.stat(path).st_mtime
                            if path not in self.state:
                                self.state[path] = mtime
                                self.callback(path, "created")
                            elif mtime > self.state[path]:
                                self.state[path] = mtime
                                self.callback(path, "modified")
                        except FileNotFoundError:
                            pass
            
            deleted_files = set(self.state.keys()) - current_files
            for path in deleted_files:
                self.callback(path, "deleted")
                del self.state[path]

class AGYNodeOSEventHandler:
    def __init__(self, jage, spatial, graph, loop, workspace=None):
        self.jage = jage
        self.spatial = spatial
        self.graph = graph
        self.loop = loop
        self.workspace = workspace or os.getcwd()

    def on_event(self, filepath, event_type):
        if event_type in ("created", "modified"):
            print(f"\n[Daemon] Detected {event_type} in: {filepath}")
            
            if os.path.basename(filepath) == "context.md":
                print(f"[Daemon] Context modified. Initiating reasoning & sync...")
                try:
                    from polymath_nodeos.scripts.context_engine import ContextEngine
                    ContextEngine(self.graph.db_path).process_and_sync(filepath)
                except Exception as e:
                    print(f"[Swarm OS] Context Engine failed: {e}")
                return

            if filepath.endswith('.json'):
                print(f"[Event Loop] Picked up agent JSON workflow from {filepath}!")
                asyncio.run_coroutine_threadsafe(
                    self.dispatch_workflow([{'hash': 'workflow', 'type': 'JSON_Task', 'file': filepath}]), self.loop
                )
                return
            
            ast_nodes = self.jage.parse_file(filepath)
            if ast_nodes:
                # Single shared ingestion path (Category C) — the cold-start scan uses the
                # same method, so the two cannot drift apart again.
                self.spatial.ingest_file(filepath, ast_nodes)
                self.spatial.resolve_edges()
                
            # -- BEGIN NEW SWARM OS FEATURES --
            if event_type == "modified":
                try:
                    from polymath_nodeos.scripts.blast_radius_engine import BlastRadiusEngine
                    br_engine = BlastRadiusEngine(db_path=self.graph.db_path, workspace=self.workspace, threshold=10)
                    br_engine.enforce_threshold(filepath)
                except Exception as e:
                    print(f"[Swarm OS] Blast Radius Engine failed: {e}")
                    
                if filepath.endswith(('.py', '.kt', '.js', '.ts')):
                    try:
                        from polymath_nodeos.scripts.qa_engine import QAEngine
                        qa_engine = QAEngine()
                        errors, _ = qa_engine.run(filepath)
                        if errors:
                            print(f"[Swarm OS] Real-time QA caught structural errors in {filepath}: {errors}")
                    except Exception as e:
                        print(f"[Swarm OS] QA Engine failed: {e}")
                    
            elif event_type == "created":
                try:
                    from polymath_nodeos.scripts.ghost_writer_engine import GhostWriterEngine
                    gw_engine = GhostWriterEngine(workspace_root=self.workspace, db_name=self.graph.db_path)
                    gw_engine.execute_pipeline(filepath)
                except Exception as e:
                    print(f"[Swarm OS] Ghost Writer Engine failed: {e}")
            # -- END NEW SWARM OS FEATURES --

        elif event_type == "deleted":
            print(f"\n[Daemon] Detected deletion of: {filepath}")
            if not filepath.endswith('.json'):
                self.graph.purge_file_nodes(filepath)
                self.spatial.remove_nodes_by_file(filepath)
                self.jage.purge_file_cache(filepath)

    async def dispatch_workflow(self, nodes):
        """True Swarm Dispatcher: Parses JSON and emits intents for AGY Agents to execute, acting as the state manager."""
        for node in nodes:
            if node['type'] == 'JSON_Task':
                workflow_file = node['file']
                try:
                    workflow = None
                    for attempt in range(5):
                        try:
                            with open(workflow_file, 'r') as f:
                                workflow = json.load(f)
                            break
                        except json.JSONDecodeError:
                            if attempt < 4:
                                await asyncio.sleep(0.1)
                            else:
                                raise
                    
                    if not workflow:
                        continue
                    
                    status = workflow.get('status')
                    
                    if status == 'pending':
                        # Handle native Re-Stitch action requested by an agent
                        if workflow.get('action') == 'stitch':
                            print(f"[Swarm Dispatcher] Processing Re-Stitch request for hash {workflow.get('node_hash')[:8]}...")
                            workflow['status'] = 'running'
                            with open(workflow_file, 'w') as f: json.dump(workflow, f, indent=4)
                            
                            result = self.jage.re_stitch(workflow.get('node_hash'), workflow.get('new_source'))
                            
                            if result is True:
                                workflow['status'] = 'completed'
                            else:
                                workflow['status'] = 'failed_qa'
                                workflow['error_log'] = result
                                print(f"[Swarm Feedback Loop] Sent QA failure back to agent: {result}")
                                
                            with open(workflow_file, 'w') as f: json.dump(workflow, f, indent=4)
                            print(f"[Event Loop] Jage Re-Stitch workflow completed.")
                            continue
                            
                        if workflow.get('action') == 'qa':
                            target = workflow.get('target', self.workspace)
                            print(f"[Swarm Dispatcher] Processing QA request for {target}...")
                            workflow['status'] = 'running'
                            with open(workflow_file, 'w') as f: json.dump(workflow, f, indent=4)
                            
                            from polymath_nodeos.scripts.qa_engine import QAEngine
                            qa_engine = QAEngine()
                            errors, warnings = qa_engine.run(target)
                            
                            if not errors:
                                workflow['status'] = 'completed'
                            else:
                                workflow['status'] = 'failed_qa'
                                workflow['error_log'] = errors
                                
                            with open(workflow_file, 'w') as f: json.dump(workflow, f, indent=4)
                            continue
                            
                        # Handle Swarm Agent execution
                        agent_list = workflow.get('agents', [])
                        print(f"[Swarm Dispatcher] Emitting Swarm intent for AGY external swarm: {agent_list}")
                        print(f"[Swarm Dispatcher] Intent stored. Awaiting Antigravity Hook lifecycle to pick it up.")
                    
                    elif status == 'running':
                        print(f"[Swarm Dispatcher] AGY Swarm has picked up the task. Monitoring execution...")
                        
                    elif status == 'completed':
                        print(f"[Event Loop] Swarm workflow fully executed by AGY agents.")
                        
                    elif status == 'failed_execution' or status == 'failed_qa':
                        print(f"[Swarm Error] AGY Workflow failed. Awaiting human or agent intervention.")
                        
                except Exception as e:
                    print(f"[Swarm Error] Failed to process workflow state: {e}")

class AGYDaemon:
    def _ensure_native_rules(self):
        rules_dir = os.path.join(self.workspace, ".agents", "rules")
        os.makedirs(rules_dir, exist_ok=True)
        
        rule_path = os.path.join(rules_dir, "nodeos_native_interaction.md")
        rule_content = """# NodeOS Native Interaction Paradigm

Whenever operating inside this NodeOS-managed workspace, you MUST follow these constraints:
1. You MUST use built-in system tools (view_file, list_dir, replace_file_content) to interact directly with the file system.
2. For spatial architectural insight and dependency resolution, query the SQLite database natively (e.g., `sqlite3 agy_nodeos.db "SELECT * FROM nodes;"`).
3. For task dispatching and swarm intent, directly modify `workflow.json` at the root of the workspace.
4. **Context Protocol:** You MUST store all task context, discovered entities, and working memory by appending to `context.md` following its Markdown schema. The NodeOS daemon will automatically deduplicate and sync this into the SQLite database.
5. **Context Retrieval:** Never parse `context.md` to remember things. Instead, query the SQLite graph for `CONTEXT_ENTITY` and `CONTEXT_STATE` nodes to fetch deduplicated facts.
"""
        if not os.path.exists(rule_path):
            with open(rule_path, "w") as f:
                f.write(rule_content)
            print(f"[NodeOS] Injected local workspace rules -> {rule_path}")

    def __init__(self, workspace_dir):
        self.workspace = workspace_dir
        self._ensure_native_rules()
        self.graph = AGYGraphManager()
        self.jage = JageASTEngine()
        self.spatial = NativeNodesEngine()
        self.loop = asyncio.new_event_loop()
        
        self.event_handler = AGYNodeOSEventHandler(self.jage, self.spatial, self.graph, self.loop, workspace=self.workspace)
        
        # Initialize our zero-dependency raw watchdog
        self.raw_watchdog = AGYRawWatchdog(self.workspace, self.event_handler.on_event, interval=1.0)
        
        self.ipc_thread = threading.Thread(target=self.start_ipc_server, daemon=True)
        self.ipc_thread.start()

    def start_ipc_server(self):
        address = ('localhost', 6000)
        try:
            with Listener(address, authkey=b'agy-nodeos-secret') as listener:
                while True:
                    with listener.accept() as conn:
                        msg = conn.recv()
                        if msg == 'ping':
                            conn.send('pong: OS Daemon is alive and running invisibly.')
                        elif msg == 'status':
                            conn.send(f'Active Workflows: OK | Watchdog: {self.workspace}')
                        else:
                            conn.send('unknown_syscall')
        except OSError:
            print("[System] IPC Address 6000 already in use. A daemon is already running! Terminating duplicate process.")
            os._exit(1)

    # Node types that MUST carry a filepath. CONTEXT_* nodes are memory records and are
    # legitimately file-less, so they are excluded from the corruption check and the purge.
    CODE_NODE_TYPES = ("FunctionDef", "AsyncFunctionDef", "ClassDef", "JS_Node")

    def purge_orphan_filepath_nodes(self):
        """Drops code nodes whose filepath is NULL. They cannot be attributed to a source
        file, so they only poison the graph. CONTEXT_* memory nodes are left untouched."""
        types_sql = ",".join("?" * len(self.CODE_NODE_TYPES))
        conn = sqlite3.connect(self.graph.db_path)
        cur = conn.cursor()
        before = cur.execute(
            f"SELECT COUNT(*) FROM nodes WHERE filepath IS NULL AND node_type IN ({types_sql})",
            self.CODE_NODE_TYPES,
        ).fetchone()[0]
        if before:
            cur.execute(
                f"DELETE FROM nodes WHERE filepath IS NULL AND node_type IN ({types_sql})",
                self.CODE_NODE_TYPES,
            )
            cur.execute("""
                DELETE FROM edges WHERE
                source_id NOT IN (SELECT node_id FROM nodes) OR
                target_id NOT IN (SELECT node_id FROM nodes)
            """)
            conn.commit()
        conn.close()
        if before:
            print(f"[NodeOS] Purged {before} orphaned nodes with NULL filepath from the graph.")

    def cold_start_ingestion(self):
        # Retire rows whose source file no longer exists. Deletions that happened while the
        # daemon was stopped are otherwise undetectable — hydration cannot tell an orphaned
        # row from a live one, and the writes in this engine never subtract (Category A).
        self.spatial.prune_vanished_files()
        # Retire rows for files that still exist but whose symbols changed. Without this,
        # a boot whose graph looks healthy skips the deep scan, so superseded rows pile up
        # silently and are re-hydrated forever (Category A / bug 12).
        retired, scanned = self.spatial.reconcile_against_source(
            self.workspace, self.jage.parse_file, self.raw_watchdog._should_ignore)
        if retired:
            print(f"[NodeOS] Reconciled {retired} superseded node row(s) across {scanned} "
                  f"scanned file(s).")
        # Re-ingest when the workspace is empty OR when hydrated nodes lost their filepath
        # (older builds omitted filepath during bulk ingestion, leaving the graph unsearchable).
        self.purge_orphan_filepath_nodes()
        self.spatial.all_nodes = [
            p for p in self.spatial.all_nodes
            if p.filepath or p.node_type not in self.CODE_NODE_TYPES
        ]
        self.spatial.rebuild_qtree()

        # A graph whose code nodes carry no call data cannot have its dependencies
        # rebuilt after a restart (see nodes_engine.resolve_edges safety gate). That is
        # the state of every database written before the calls column existed.
        # "No call data" must be judged as a RATIO, not per-node.
        #   - `all(not p.calls ...)` is wrong in the other direction: leaf functions
        #     legitimately call nothing, so a single empty node flips the test and
        #     triggers a full workspace re-scan on every boot.
        #   - `any(p.calls ...)` is wrong too: a partially migrated database keeps a
        #     handful of populated rows and would never re-ingest, leaving most of the
        #     dependency graph unresolvable.
        # Require a healthy majority to consider the graph's call data usable.
        code_nodes = [p for p in self.spatial.all_nodes
                      if p.node_type in self.CODE_NODE_TYPES]
        with_calls = sum(1 for p in code_nodes if p.calls)
        missing_calls = bool(code_nodes) and (with_calls / len(code_nodes)) < 0.5

        if len(self.spatial.all_nodes) == 0 or self.spatial.null_filepath_nodes or missing_calls:
            if missing_calls:
                print(f"[NodeOS] Only {with_calls}/{len(code_nodes)} code nodes carry call data. "
                      f"Re-ingesting to rebuild the dependency graph.")
            print("[NodeOS] Detected Uninitialized or Corrupt Project Workspace. Initiating Deep Ingestion...")
            # 1. Deep scan the workspace
            for root, _, files in os.walk(self.workspace):
                if self.raw_watchdog._should_ignore(root):
                    continue
                for file in files:
                    if file.endswith(('.py', '.js', '.ts')):
                        filepath = os.path.join(root, file)
                        ast_nodes = self.jage.parse_file(filepath)
                        if ast_nodes:
                            # Identical contract to the live watcher above, by construction:
                            # both call ingest_file, so `filepath` can no longer be dropped
                            # on one path and forwarded on the other (bug 1, Category C).
                            self.spatial.ingest_file(filepath, ast_nodes)
            
            # Refresh the tick budget now that the real node count is known, then resolve
            # physical edges. resolve_edges syncs the graph to SQLite before settling.
            self.spatial.physics_ticks = self.spatial._budget_ticks(len(self.spatial.all_nodes))
            self.spatial.resolve_edges()
            
            print(f"[NodeOS] Deep Scan complete. Ingested {len(self.spatial.all_nodes)} kinetic nodes.")
            
            # 2. Check for missing Architectural Nodes
            architect_exists = os.path.exists(os.path.join(self.workspace, "architect_parent_node.md"))
            blueprint_exists = os.path.exists(os.path.join(self.workspace, "impl_blueprint_node.md"))
            
            if not architect_exists or not blueprint_exists:
                print("[NodeOS] Essential structural nodes missing. Dispatching Architect Designer Sub-Agent...")
                workflow_file = os.path.join(self.workspace, "workflow.json")
                workflow = {
                    "type": "JSON_Task",
                    "status": "pending",
                    "action": "execute_agents",
                    "agents": ["architect_designer"]
                }
                import json
                with open(workflow_file, "w") as f:
                    json.dump(workflow, f, indent=4)
                print("[NodeOS] Workflow payload dropped. Architect worker will bootstrap the project.")

    async def _async_run(self):
        # Run the deep scan ingestion immediately before starting the real-time event loop
        self.cold_start_ingestion()
        
        # The raw watchdog runs in the asyncio event loop natively
        await self.raw_watchdog.start()

    def run(self):
        try:
            self.loop.run_until_complete(self._async_run())
        finally:
            self.loop.close()


