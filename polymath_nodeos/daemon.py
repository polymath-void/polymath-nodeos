#!/usr/bin/env python3
import asyncio
import os
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

    def _should_ignore(self, path):
        # Ignore internal OS state folders and dependencies to prevent recursive loops and bloat
        ignores = ['.jsagent', '.agents', '__pycache__', '.git', 'node_modules', 'build', 'dist', '.venv', 'venv', '.build_cache', 'site-packages', 'env']
        return any(ign in path for ign in ignores)

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
    def __init__(self, jage, spatial, graph, loop):
        self.jage = jage
        self.spatial = spatial
        self.graph = graph
        self.loop = loop

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
                for node in ast_nodes:
                    self.spatial.add_node(node['hash'], node['type'], node.get('name', 'unknown'), node.get('calls', []), filepath=filepath)
                self.spatial.resolve_edges()
                
            # -- BEGIN NEW SWARM OS FEATURES --
            if event_type == "modified":
                try:
                    from polymath_nodeos.scripts.blast_radius_engine import BlastRadiusEngine
                    br_engine = BlastRadiusEngine(db_path=self.graph.db_path, workspace=self.graph.workspace, threshold=10)
                    br_engine.enforce_threshold(filepath)
                except Exception as e:
                    print(f"[Swarm OS] Blast Radius Engine failed: {e}")
                    
            elif event_type == "created":
                try:
                    from polymath_nodeos.scripts.ghost_writer_engine import GhostWriterEngine
                    gw_engine = GhostWriterEngine(workspace_root=self.graph.workspace, db_name=self.graph.db_path)
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
        
        self.event_handler = AGYNodeOSEventHandler(self.jage, self.spatial, self.graph, self.loop)
        
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

    def cold_start_ingestion(self):
        if len(self.spatial.all_nodes) == 0:
            print("[NodeOS] Detected Uninitialized Project Workspace. Initiating Deep Ingestion...")
            # 1. Deep scan the workspace
            for root, _, files in os.walk(self.workspace):
                if self.raw_watchdog._should_ignore(root):
                    continue
                for file in files:
                    if file.endswith(('.py', '.js', '.ts')):
                        filepath = os.path.join(root, file)
                        ast_nodes = self.jage.parse_file(filepath)
                        if ast_nodes:
                            for node in ast_nodes:
                                # We now pass the node name and the calls it makes to the spatial matrix
                                self.spatial.add_node(node['hash'], node['type'], node.get('name', 'unknown'), node.get('calls', []))
            
            # Resolve physical edges using AST calls
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


