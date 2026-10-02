# NodeOS QA Analyzer Integration Plan

This plan details the migration of the standalone QA Analyzer into the core `polymath-nodeos` architecture, enabling native CLI execution, swarm intent processing, and real-time background validation.

## Phase 1: Code Migration & Refactoring
**Target File:** `polymath-nodeos/polymath_nodeos/scripts/qa_engine.py` (New File)

1. **Copy the Logic:** Migrate the contents of `~/.gemini/config/skills/qa-analyzer/scripts/analyzer.py` into the new `qa_engine.py` file.
2. **Rename for Consistency:** Rename `UniversalAnalyzer` to `QAEngine` to align with the existing NodeOS engine nomenclature (e.g., `BlastRadiusEngine`, `GhostWriterEngine`).
3. **Refactor for Programmatic Use:** Modify the `run(self, root_dir)` and `report(self)` methods in `QAEngine`. 
   - Instead of calling `sys.exit()`, the methods should return a structured dictionary or tuple containing `(errors, warnings)` so the CLI and Daemon can handle the output dynamically without crashing the background process.

## Phase 2: CLI Integration
**Target File:** `polymath-nodeos/polymath_nodeos/cli.py`

1. **Create the CLI Handler:** Inside the `execute_command(command, command_args)` function, add a new nested function `run_qa(args)`:
   ```python
   def run_qa(args):
       from polymath_nodeos.scripts.qa_engine import QAEngine
       target = args[0] if args else workspace
       engine = QAEngine()
       engine.run(target)
       engine.report() # Adjusted to print instead of sys.exit
   ```
2. **Register the Command:** Add `"qa": run_qa` to the `commands` dictionary. This enables the user to invoke `nodeos -c qa [target_dir]` directly from the terminal.

## Phase 3: Daemon Swarm Intent Integration
**Target File:** `polymath-nodeos/polymath_nodeos/daemon.py`

1. **Extend `dispatch_workflow`:** In the `AGYNodeOSEventHandler.dispatch_workflow()` async method, add logic to intercept QA intents from `workflow.json`.
2. **Handle the 'qa' Action:**
   ```python
   if workflow.get('action') == 'qa':
       print(f"[Swarm Dispatcher] Processing QA request for {workflow.get('target', self.workspace)}...")
       workflow['status'] = 'running'
       with open(workflow_file, 'w') as f: json.dump(workflow, f, indent=4)
       
       from polymath_nodeos.scripts.qa_engine import QAEngine
       qa_engine = QAEngine()
       errors, warnings = qa_engine.run(workflow.get('target', self.workspace))
       
       if not errors:
           workflow['status'] = 'completed'
       else:
           workflow['status'] = 'failed_qa'
           workflow['error_log'] = errors
           
       with open(workflow_file, 'w') as f: json.dump(workflow, f, indent=4)
       continue
   ```
   This allows external agents to drop a QA task into `workflow.json` and receive native feedback via the NodeOS daemon.

## Phase 4: Watchdog Real-Time Hook (Optional)
**Target File:** `polymath-nodeos/polymath_nodeos/daemon.py`

1. **Extend `on_event`:** Within the `on_event(self, filepath, event_type)` method, add a lightweight hook when `event_type == "modified"`.
2. **Trigger Immediate Validation:**
   ```python
   if event_type == "modified" and filepath.endswith(('.py', '.kt', '.js', '.ts')):
       try:
           from polymath_nodeos.scripts.qa_engine import QAEngine
           # Run QA only on the modified file to preserve CPU/battery on Android
           qa_engine = QAEngine()
           errors, _ = qa_engine.run(filepath)
           if errors:
               print(f"[Swarm OS] Real-time QA caught structural errors in {filepath}: {errors}")
       except Exception as e:
           print(f"[Swarm OS] QA Engine failed: {e}")
   ```
