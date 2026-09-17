# Architectural Blueprint: Context Storing Sub-Parent Node

## 1. Overview
Agents will write unoptimized, continuous context findings into a `context.md` file in the workspace. The `AGYRawWatchdog` in `daemon.py` will track this file alongside source files. Upon modification, the `AGYNodeOSEventHandler` will parse the file, prune redundant or outdated information (deduplication), and persist the cleaned representation into the existing SQLite graph (`agy_nodeos.db`). Agents can then query this database for a structured, noise-free context graph.

---

## 2. Context Schema (`context.md`)
To allow the daemon to effectively parse and reason over the context, agents must adhere to a strict Markdown schema. 

```markdown
# Context Sub-Parent Node

## 1. Task State
- [Current Phase]: Architecting Graph Integration
- [Blocker]: None

## 2. Discovered Entities
- [GraphManager]: Manages SQLite connections and table schema.
- [JageASTEngine]: Parses Python/JS files into kinetic AST nodes.
- [GraphManager]: (Duplicate/Update) Now includes spatial edge resolution.

## 3. Working Memory
- 2026-09-17T10:00:00Z: Initialized watchdog observation.
- 2026-09-17T10:05:00Z: Noticed watchdog ignores .md files.
```

---

## 3. Daemon & Watchdog Integration (`daemon.py`)

### A. Extend Watchdog File Targeting
Currently, `AGYRawWatchdog._initialize_state()` and `start()` only watch `.py` and `.json` files.
**Modification:** Update the tuple to explicitly track `context.md`.

### B. Event Handler Pipeline
Add a conditional block in `AGYNodeOSEventHandler.on_event()` to intercept `context.md` modifications.

### C. Deduplication & Reasoning Logic (`process_context_file`)
Implement a parsing method inside `AGYNodeOSEventHandler` (or a dedicated engine) that:
1. **Parses** the Markdown into distinct groups (Task State, Entities, Memory).
2. **Deduplicates**: 
   - *Entities*: If an entity (e.g., `[GraphManager]`) is redefined later in the list, the newer definition overwrites the older one.
   - *Working Memory*: Drops entries older than a specific time horizon or truncates to the latest $N$ entries.
3. **Synchronizes**: Pushes the cleaned data to the SQLite graph via `graph_manager.py`.

---

## 4. Graph Manager & SQLite Integration (`graph_manager.py`)

To remain completely non-destructive to the existing schema (`nodes` and `edges` tables), we model the Context as a true **Sub-Parent Graph**. 

Instead of altering the schema to hold large text blobs, the context is broken down into spatial nodes:

### Node Types
1. **`CONTEXT_ROOT`**: Represents the `context.md` file itself.
2. **`CONTEXT_ENTITY`**: Represents a deduplicated entity.
3. **`CONTEXT_STATE`**: Represents a key-value task state.

### Implementation in `AGYGraphManager`
Adds a new method `sync_context_graph(self, context_dict)` that purges old context nodes and upserts the deduplicated entries.

---

## 5. Agent Access Pattern (Querying)

Agents operating natively in the workspace will no longer read the chaotic, growing `context.md` file. Instead, following the *NodeOS Native Interaction Paradigm*, they fetch precise, deduplicated context via standard SQLite queries:

```bash
# Agents execute this to get the exact state of a specific entity without noise
sqlite3 agy_nodeos.db "SELECT name, hash FROM nodes WHERE node_type='CONTEXT_ENTITY';"
```
