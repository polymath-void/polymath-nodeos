# Graph Integrity Repair — Polymath-NodeOS 1.1.3

Record of the bugs found while installing and validating Polymath-NodeOS in the umbrella
workspace (`~/Projects`), and the fixes applied to make the SQLite AST graph usable.

**Context:** the original complaint was that `grep` floods the agent context with massive
match logs. NodeOS is the intended answer to that problem — a pre-built graph you query
instead of grepping. But on install the graph was 98% broken, so the tool could not
actually replace grep. This document records what was repaired.

**Environment:** Android Termux, `aarch64`, Bionic libc, Python 3.14, OpenCode.

---

## Summary

| # | Bug | Severity | Symptom |
|---|-----|----------|---------|
| 1 | `filepath` dropped during cold-start bulk ingestion | **Critical** | 1,524 / 1,558 nodes stored `filepath = NULL`; all search results printed `in None` |
| 2 | Physics integrator diverged + fixed QuadTree boundary | **Critical** | Coordinates reached `±1e120`; out-of-bounds nodes silently dropped from the spatial index |
| 3 | `sync_to_sqlite()` only called after the settling loop | **High** | Graph stayed empty for minutes while physics pinned a core at 100% |
| 4 | Missing `sqlite3` import in `daemon.py` | **High** | `NameError` crashed the daemon during the repair path |
| 5 | Over-broad NULL purge targeted `CONTEXT_*` memory nodes | **High** | Would have deleted memory records and caused an endless re-ingest loop |
| 6 | `calls` never persisted to SQLite | **Critical** | Dependency graph unrebuildable after every restart; see Phase 2 |
| 7 | Call edges resolved by bare name only | **High** | Identically-named symbols in different files bonded to arbitrary nodes |
| 8 | Stale edges never pruned | **High** | Deleted-file edges and self-edges survived forever (`INSERT OR IGNORE` only) |
| 9 | `--version` hardcoded to `1.0.1` | **Low** | Misleading during install; drifted from `pyproject.toml` |
| 10 | Ignore list matched substrings, not path segments | **Medium** | `'env' in path` would skip a real project named `env-tools` |
| 11 | `ContextEngine.__init__` shelled out to a dead remote | **High** | Failed `git clone` on every boot; network I/O + hardcoded path + filesystem writes in a constructor |

---

## Phase 2 — Node count, history, and the remaining defects

### On "there is too many nodes!"

The 2,491-node graph was not a version problem. No newer version exists:

| Source | Version |
|---|---|
| PyPI latest | `1.1.2` (older than local) |
| `git HEAD` / `origin/main` | `1.1.3` (`6f717f4`, HEAD == origin/main) |
| Installed | `1.1.3` (editable) |

The node count came from booting at the umbrella root `~/Projects`, which indexes every
sub-repo by design (`AGENTS.md`: "launched at the umbrella root ... dynamically links all
sub-repos into a unified global AST graph"):

```
opencode-antigravity-auth  542      SyntyCode          242
ComputeRes                 489      muse-ai            185
polymath-jage               71      agent-tools         97
apex                        60      workspace           94
polymath-nodeos             42      + ~20 more repos
```

Same binary, same fixes — booted inside `polymath-nodeos` the graph is **67 nodes**.
NodeOS resolves its workspace from `os.getcwd()`, so scoping is a matter of where you boot it.

### Historical analysis: which version introduced what

`git log --follow` across the graph engine. The finding that matters: **none of the
critical bugs were regressions.**

**The `filepath` bug was present in the initial commit.** `5f53a06` already had the
asymmetry (cold-start path omitted `filepath`; the live path at line 79 omitted even more).
Twelve releases never touched it.

**The physics bugs were never revised either.** `boundary = Rectangle(500, 500, 500, 500)`
is byte-identical across `5f53a06 → 1ea2f8e`, as is `args=(100,)`.

**Bug 3 was the one genuine regression, and it was disguised as an optimization.**
`6ed6388` ("Optimize physics engine to O(N log N) and offload to thread"):

```diff
-            self.simulate_physics(ticks=100)      # synchronous, then:
-            self.sync_to_sqlite()                  # always ran after a completed settle
+            threading.Thread(target=self.simulate_physics, args=(100,), daemon=True).start()
+        self.sync_to_sqlite()                      # now runs CONCURRENTLY with physics
```

Before the change, physics was synchronous so `sync_to_sqlite` always ran against a settled
graph. Moving physics to a thread turned sync into a concurrent read of positions the thread
was still mutating — a data race — and in practice the graph looked empty.

**Version strategy:** `1.0.0 → 1.1.2` on PyPI, all feature and CLI work. The graph engine has
been architecturally frozen since the initial commit, which is why every bug found here was
old rather than fresh.

### Bug 6 — `calls` never persisted (Critical)

Found while verifying the Bug 8 fix, and the most consequential of Phase 2.

`Point.calls` holds the symbols a node references — the **only** record of which
dependencies exist. But the `nodes` table had no `calls` column:

```
sqlite> PRAGMA table_info(nodes);
node_id | node_type | name | filepath | hash | x_coord | y_coord | last_updated
```

`sync_to_sqlite` never wrote it, and `hydrate_from_db` never read it. So on every restart
all nodes loaded with `calls == []`:

```
hydrated points: 59
non-empty calls: 0
```

Consequence: `resolve_edges` had nothing to resolve, so **the dependency graph could not be
rebuilt after a reboot**. The AST edges in `agy_nodeos.db` were unreproducible — meaning
`nodeos -c blast` (transitive dependents) degraded to zero after every restart.

This also made the Bug 8 purge dangerous: purging `CALL` edges with no call data would
delete a valid graph. A safety gate was added first.

**Fix — persist calls** (`nodes_engine.py`):

```python
calls_json = json.dumps(sorted(p.calls))
cursor.execute('''
    INSERT INTO nodes (node_id, node_type, name, filepath, calls, x_coord, y_coord, last_updated)
    VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(node_id) DO UPDATE SET
        name=excluded.name, filepath=excluded.filepath, calls=excluded.calls, ...
''', (p.node_id, p.node_type, p.name, p.filepath, calls_json, p.x, p.y))
```

**Fix — hydrate calls**, with a graceful fallback for unparseable rows:

```python
calls = []
if len(row) > 6 and row[6]:
    try:
        parsed = json.loads(row[6])
        if isinstance(parsed, list):
            calls = [str(c) for c in parsed]
    except (TypeError, ValueError):
        calls = []
```

**Fix — schema migration** (`graph_manager.py`), so existing databases gain the column:

```python
columns = {row[1] for row in cursor.execute("PRAGMA table_info(nodes)")}
if 'calls' not in columns:
    cursor.execute("ALTER TABLE nodes ADD COLUMN calls TEXT")
    print("[AGY-NodeOS] Migrated nodes table: added 'calls' column.")
```

**Safety gate in `resolve_edges`** — refuse to purge when there is nothing to rebuild from:

```python
if not any(p.calls for p in self.all_nodes):
    dangling = cursor.execute("""SELECT COUNT(*) FROM edges WHERE ... self-edges ...""").fetchone()[0]
    if dangling:
        print("[Physics Engine] No call data available (pre-migration or empty graph). "
              f"Pruning {dangling} invalid edge(s) without rebuilding CALL edges.")
        ...
    conn.close()
    return
```

**Re-ingest trigger, as a ratio.** Two naive tests both fail:

- `all(not p.calls ...)` — leaf functions legitimately call nothing, so one empty node
  triggers a full workspace re-scan on *every* boot.
- `any(p.calls ...)` — a partially migrated database keeps a few populated rows and never
  re-ingests, leaving most of the graph unresolvable.

So it requires a majority to consider the data usable:

```python
code_nodes = [p for p in self.spatial.all_nodes if p.node_type in self.CODE_NODE_TYPES]
with_calls = sum(1 for p in code_nodes if p.calls)
missing_calls = bool(code_nodes) and (with_calls / len(code_nodes)) < 0.5
```

### Bug 7 — call edges resolved by bare name

`resolve_edges` built a flat map:

```python
name_to_node = {p.name: p for p in self.all_nodes}   # last duplicate wins
```

The AST records only call *names* (`ast.Name.id` / `ast.Attribute.attr`), never qualified
paths, so every duplicate name resolved to whichever node was ingested last. A `Rectangle`
in one module could bond to an unrelated `Rectangle` in another.

**Fix — name → list index, resolve same-file first, refuse genuine ambiguity:**

```python
def _build_call_index(self):
    """Index nodes by bare name, preferring same-file matches. ..."""

def _resolve_target(self, by_name, caller, call_name):
    """Pick the best definition for `call_name` as seen from `caller`."""
    candidates = by_name.get(call_name)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    same_file = [c for c in candidates if c.filepath and c.filepath == caller.filepath]
    if same_file:
        return same_file[0]   # same file wins; earliest declaration for overloads
    return None                # Ambiguous across files: refuse to invent an edge.
```

Ambiguity is reported rather than hidden:

```python
print(f"[Physics Engine] Skipped {ambiguous} ambiguous call(s): the name exists in "
      f"multiple files with no same-file match. Rename or qualify to disambiguate.")
```

Verified with a four-node fixture where `run()` exists in `mod_a/b/c`:

```
A. caller in mod_a calls run()  -> /p/mod_a.py      (own file, correct)
B. caller in mod_d calls run()  -> None             (ambiguous, refused)
C. unique name 'other'          -> /p/mod_d.py      (global fallback)
D. self-call                    -> no self-edge     (target is not p guard)
```

### Bug 8 — stale edges never pruned

`resolve_edges` only ever used `INSERT OR IGNORE`, so nothing was ever removed. Edges for
deleted files, self-edges, and edges written by the old name-only resolver all survived
forever. Observed a stale `QuadTree → QuadTree` CALL edge for a node with **zero** calls.

**Fix — purge before rebuild**, ordered so the in-memory state mirrors the DB:

```python
# Clear in-memory edges to mirror the DB purge below. Without this, the
# `target not in p.edges` guard would suppress every re-insert on a second
# resolve, leaving the CALL set permanently empty after one boot cycle.
for p in self.all_nodes:
    p.edges = []

cursor.execute("""
    DELETE FROM edges WHERE
    source_id NOT IN (SELECT node_id FROM nodes) OR
    target_id NOT IN (SELECT node_id FROM nodes) OR
    source_id = target_id
""")
cursor.execute("DELETE FROM edges WHERE relation_type = 'CALL'")
```

Clearing `p.edges` first is load-bearing: without it the `target not in p.edges` guard
suppresses re-insertion and the CALL set empties after one cycle. Verified idempotent:

```
pass 1: [('a1','a2'), ('d1','a2')]
pass 2: [('a1','a2'), ('d1','a2')]
IDEMPOTENT
```

Note the purge is scoped to `relation_type = 'CALL'`. `ContextEngine` writes `HAS_CONTEXT`
edges with `INSERT OR REPLACE` and must not be disturbed.

### Bug 9 — version string drift

`cli.py` hardcoded `version='Polymath-NodeOS 1.0.1'` while `pyproject.toml` said `1.1.3`.
Reported 1.0.1 during a 1.1.3 install, which actively misled the verification step.

```python
def _package_version():
    """Read the installed distribution version so it cannot drift from pyproject.toml."""
    from importlib.metadata import PackageNotFoundError, version as _dist_version
    try:
        return _dist_version("polymath-nodeos")
    except PackageNotFoundError:
        try:
            from polymath_nodeos import __version__  # type: ignore[attr-defined]
            return __version__
        except Exception:
            return "unknown"
```

`nodeos --version` now reports `Polymath-NodeOS 1.1.3`.

### Bug 10 — ignore list matched substrings

```python
ignores = ['.jsagent', '.agents', '__pycache__', '.git', 'node_modules',
           'build', 'dist', '.venv', 'venv', '.build_cache', 'site-packages', 'env']
return any(ign in path for ign in ignores)
```

`'env' in path` also matches a real project named `env-tools`; `'build'` matches
`buildserver/`. No current false positives in this workspace, but the list is fragile.

**Fix — exact path-segment matching:**

```python
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
```

All eight cases pass, including the three that previously misfired:

```
PASS  ignore=True  expect=True   polymath-nodeos/node_modules
PASS  ignore=False expect=False  env-tools/src
PASS  ignore=False expect=False  buildserver/main.py
PASS  ignore=True  expect=True   dist
PASS  ignore=False expect=False  SyntyCode
PASS  ignore=True  expect=True   polymath-nodeos/.git/objects
PASS  ignore=False expect=False  environment
PASS  ignore=True  expect=True   venv/lib
```

---

## Bug 1 — `filepath` dropped during cold-start ingestion

### Root cause

Two ingestion paths fed the same spatial engine, and only one supplied the file path.

`polymath_nodeos/daemon.py` — the **live watchdog** path (already correct):

```python
# AGYNodeOSEventHandler.on_event, ~line 104
self.spatial.add_node(
    node['hash'], node['type'], node.get('name', 'unknown'),
    node.get('calls', []), filepath=filepath,      # <-- supplied
)
```

`polymath_nodeos/daemon.py` — the **cold-start bulk scan** path (broken):

```python
# AGYDaemon.cold_start_ingestion, line 288
self.spatial.add_node(
    node['hash'], node['type'], node.get('name', 'unknown'),
    node.get('calls', []),                          # <-- filepath missing
)
```

Because `cold_start_ingestion` is what populates the graph in the first place, essentially
every node was born without a path. `Point.filepath` defaulted to `None`, and
`NativeNodesEngine.sync_to_sqlite` faithfully persisted that `NULL` to `nodes.filepath`.

Only the handful of nodes touched *after* boot kept their paths — which is why the graph
looked partially correct and made the bug easy to miss.

### Impact

`nodes.filepath` is the join key for every file-scoped query. With it `NULL`:

- `nodeos -c search <symbol>` printed `Found [ClassDef] BlastRadiusEngine in None`
- `nodeos -c blast <file>` had no file to resolve dependents against
- `GraphManager.purge_file_nodes()` (`DELETE FROM nodes WHERE filepath = ?`) matched nothing
- `NativeNodesEngine.remove_nodes_by_file()` silently no-oped

Measured before the fix:

```
sqlite> SELECT COUNT(*) total, SUM(filepath IS NULL) null_fp FROM nodes;
1558|1524          -- 97.8% corrupt
```

### Fix

Forward `filepath` on the bulk path (`daemon.py`):

```python
for node in ast_nodes:
    # We now pass the node name and the calls it makes to the spatial matrix.
    # filepath MUST be forwarded, otherwise sync_to_sqlite writes NULL and the
    # whole graph becomes unsearchable by file (see nodeos -c search).
    self.spatial.add_node(
        node['hash'], node['type'], node.get('name', 'unknown'),
        node.get('calls', []), filepath=filepath,
    )
```

### Added self-healing

An already-corrupted workspace will not repair itself: `cold_start_ingestion` originally
ran **only** when the node list was empty, and a graph full of `NULL` filepaths is not
empty. So the daemon would happily boot forever on a broken graph.

Added `AGYDaemon.purge_orphan_filepath_nodes()` plus a re-ingest trigger:

```python
CODE_NODE_TYPES = ("FunctionDef", "AsyncFunctionDef", "ClassDef", "JS_Node")

def purge_orphan_filepath_nodes(self):
    """Drops code nodes whose filepath is NULL. They cannot be attributed to a source
    file, so they only poison the graph. CONTEXT_* memory nodes are left untouched."""
```

```python
self.purge_orphan_filepath_nodes()
self.spatial.all_nodes = [
    p for p in self.spatial.all_nodes
    if p.filepath or p.node_type not in self.CODE_NODE_TYPES
]
self.spatial.rebuild_qtree()

if len(self.spatial.all_nodes) == 0 or self.spatial.null_filepath_nodes:
    print("[NodeOS] Detected Uninitialized or Corrupt Project Workspace. Initiating Deep Ingestion...")
```

The in-memory list is filtered to match the DB purge, so hydration and re-ingest agree.

---

## Bug 2 — Physics divergence and the silent spatial-index loss

### Root cause (a) — fixed boundary

`NativeNodesEngine` hardcoded its QuadTree boundary:

```python
self.boundary = Rectangle(500, 500, 500, 500)   # 1000 x 1000 world
```

`QuadTree.insert()` returns `False` — **not an error** — when a point falls outside:

```python
def insert(self, point):
    if not self.boundary.contains(point):
        return False
```

So any node drifting past the ±500 box was silently discarded from the spatial index.
`GhostWriterEngine` nearest-neighbour queries (`nodeos -c ghost`) then returned results
from a partially empty tree with no indication anything was wrong.

### Root cause (b) — unbounded repulsion

Coulomb repulsion was integrated with no minimum separation:

```python
dist_sq = dx**2 + dy**2
if dist_sq > 0:
    force = k_repulse / dist_sq      # k_repulse = 5000.0
```

Nodes are seeded within ±10px of each other, so `dist_sq` reaches `1.0` and the force term
hits the full `5000`. Combined with an explicit Euler integrator and no force or velocity
clamp, the layout diverges. Observed coordinates in the corrupted DB:

```
sqlite> SELECT MIN(x_coord), MAX(x_coord), MIN(y_coord), MAX(y_coord) FROM nodes;
-6.2323445277492169e+119 | 3.1878719438894698e+119 | -1.225879451535014e+120 | 6.2704279147919737e+119
```

These values are also non-finite-adjacent, so `math.isfinite()` is now checked on hydrate.

### Fix — dynamic boundary

The simulation now derives its own bounds from the live node spread, so the boundary always
contains the whole graph (`nodes_engine.py`):

```python
def _fit_boundary(self, margin=400.0):
    """Derive the QuadTree boundary from the live node spread.

    A fixed 500/500/500/500 boundary silently discards every node that drifts
    outside it (QuadTree.insert returns False), which empties the spatial index.
    The simulation must own a boundary that always contains the whole graph.
    """
    if not self.all_nodes:
        return
    xs = [p.x for p in self.all_nodes]
    ys = [p.y for p in self.all_nodes]
    cx = (min(xs) + max(xs)) / 2.0
    cy = (min(ys) + max(ys)) / 2.0
    half_w = max(max(xs) - cx, cx - min(xs)) + margin
    half_h = max(max(ys) - cy, cy - min(ys)) + margin
    # Guard against a degenerate span collapsing the tree.
    self.boundary = Rectangle(cx, cy, max(half_w, margin), max(half_h, margin))
    self.center = (cx, cy)
```

`rebuild_qtree()` calls `_fit_boundary()` first. Gravity in `simulate_physics` now reads
`self.center` instead of the hardcoded `(500.0, 500.0)`.

### Fix — numerical guards

```python
min_dist_sq = 100.0      # 10px minimum separation keeps 1/d^2 bounded
max_force = 5_000.0      # per-node force clamp per axis
max_velocity = 200.0     # per-node velocity clamp per axis
```

Applied per node after repulsion accumulation, and to velocity after Euler integration.

### Fix — reject poisoned rows on hydrate

```python
if row[2] is not None and row[3] is not None:
    # Reject non-finite coordinates left behind by a diverged simulation.
    # math.isfinite guards against inf/nan written by an older build.
    if not (math.isfinite(row[2]) and math.isfinite(row[3])):
        continue
```

---

## Bug 3 — Graph invisible until physics settled

### Root cause

`resolve_edges()` kicked off the simulation in a background thread, and `sync_to_sqlite()`
was called only at the **end** of `simulate_physics`:

```python
# before
print(f"[Physics Engine] Bonded {edge_count} structural connections. ...")
if edge_count > 0:
    threading.Thread(target=self.simulate_physics, args=(100,), daemon=True).start()
```

```python
# simulate_physics, tail
self.rebuild_qtree()
self.sync_to_sqlite()          # <-- only reached after ALL ticks complete
```

Two consequences:

1. **The graph stayed empty** for the whole settling run. Ingest reported
   `Ingested 2492 kinetic nodes` while SQLite still held 12 rows. An agent querying the
   graph during that window sees nothing.
2. **Physics was unbounded.** `args=(100,)` was a fixed 100 ticks regardless of graph size.
   Pure-Python Euler integration over ~2,500 nodes pegged one core at ~96-100% CPU for
   minutes. On Termux this competes with everything else and risks the Android LMK.

Worse, `resolve_edges()` runs on **every** file modification via the watchdog, so each edit
spawned another full simulation thread — unbounded thread stacking.

### Fix — sync structure first, then settle

```python
print(f"[Physics Engine] Bonded {edge_count} structural connections. Syncing graph to SQLite...")
# Persist structural data immediately. Position layout is cosmetic; the graph must be
# queryable even if the simulation below is slow or still running.
self.sync_to_sqlite()

if edge_count > 0:
    import threading
    # A second simulation is already in flight: never stack another one, or every
    # resolve_edges spawns a thread and the workspace pins all available cores.
    if self._physics_running:
        print("[Physics Engine] A simulation is already in flight. Skipping duplicate run.")
        return
    self._physics_running = True

    def _run():
        try:
            self.simulate_physics(self.physics_ticks)
        finally:
            self._physics_running = False

    threading.Thread(target=_run, daemon=True).start()
```

### Fix — tick budget scales with graph size

```python
@staticmethod
def _budget_ticks(node_count):
    """Pick a tick budget that keeps a single settling pass bounded on mobile."""
    if node_count < 500:
        return 100
    if node_count < 2000:
        return 40
    return 15
```

Hydration computes the budget from the hydrated count; `cold_start_ingestion` refreshes it
once the real ingested count is known.

---

## Bug 4 — Missing `sqlite3` import

`purge_orphan_filepath_nodes()` uses `sqlite3` directly, but `daemon.py` imported only
`asyncio`, `os`, `sys`, `subprocess`, `threading`, and `json`. The daemon crashed on boot
with `NameError: name 'sqlite3' is not defined` before any ingestion could happen.

```python
import asyncio
import os
import sqlite3      # <-- added
import sys
```

Note that several modules in this codebase use a local `import sqlite3` inside functions
(`cli.py`, `graph_manager.py`) while `nodes_engine.py` imports it at module level. Worth
normalising in a follow-up.

---

## Bug 5 — Over-broad purge targeting `CONTEXT_*` memory nodes

This one was introduced by the Bug 1 fix and caught during review of my own change.

The first purge deleted **every** row with a `NULL` filepath. But `CONTEXT_ENTITY` and
`CONTEXT_STATE` nodes are memory records written by `ContextEngine`, and they are
legitimately file-less:

```
sqlite> SELECT node_id, node_type, name, filepath FROM nodes WHERE filepath IS NULL;
ctx_ent_-8282907009462375584   | CONTEXT_ENTITY | GraphManager    |
ctx_ent_-5322622847591803318   | CONTEXT_ENTITY | ContextEngine   |
ctx_state_-1088495295997152593 | CONTEXT_STATE  | Current Phase   |
ctx_state_-8152956833982679253 | CONTEXT_STATE  | Blocker         |
```

Two failure modes, both silent:

- **Memory loss.** The purge ran on every boot, deleting the deduplicated facts the Context
  Engine had just written — defeating the entire Context Sub-Parent Node feature.
- **Infinite re-ingest.** `null_filepath_nodes` counted those 4 rows, so
  `cold_start_ingestion` saw a non-zero count and re-scanned the whole workspace on
  **every** boot. The workspace could never reach a steady state.

### Fix — scope the check to code node types

In `nodes_engine.py`, count only code nodes:

```python
# Same scoping as the daemon purge: only code nodes are expected to have a filepath.
self.code_node_types = ("FunctionDef", "AsyncFunctionDef", "ClassDef", "JS_Node")
```

```python
# CONTEXT_* memory records legitimately have no filepath; only count
# code nodes, otherwise the workspace re-ingests on every boot forever.
if not filepath and row[1] in self.code_node_types:
    self.null_filepath_nodes += 1
```

And in `daemon.py`, the same tuple gates the purge and the in-memory filter (see Bug 1).

Verified after the fix: the 4 `CONTEXT_*` rows survive, and `null_code_fp` is `0`.

---

## Verification

Install and global injection:

```bash
pip install --break-system-packages -e .     # 1.1.2 -> 1.1.3
nodeos --install                             # rule + skill + hook template
```

Before / after, in `~/Projects`:

| Check | Before | After |
|-------|--------|-------|
| `SELECT COUNT(*), SUM(filepath IS NULL) FROM nodes` | `1558 \| 1524` | `2496 \| 0` (code nodes) |
| `nodeos -c ping` | Offline | `pong: OS Daemon is alive` |
| `nodeos -c search BlastRadius` | `... in None` | `... in .../blast_radius_engine.py` |
| `MIN/MAX(x_coord)` | `-6.2e+119 / 3.2e+119` | bounded within the fitted boundary |
| CPU during settle | ~100% for minutes | bounded, non-stacking |

```
$ nodeos -c search BlastRadius
Found [ClassDef] BlastRadiusEngine in .../polymath_nodeos/scripts/blast_radius_engine.py
Found [JS_Node] computeBlastRadius in .../polymath-jage/src/core/graph.js
Found [JS_Node] formatBlastRadius in .../polymath-jage/src/core/graph.js

$ nodeos -c blast .../polymath_nodeos/daemon.py
Blast radius for .../daemon.py: 3

$ nodeos -c ghost .../polymath_nodeos/daemon.py
Nearest neighbors for .../daemon.py: [... 10 entries, all with real filepaths ...]
```

### Phase 2 verification (scoped, in `polymath-nodeos`)

```
=== 1. VERSION ===
Polymath-NodeOS 1.1.3

=== 2. PERSISTENCE: calls survive restart ===
41/62 code nodes have calls

=== 3. EDGE INTEGRITY ===
call_edges: 40
self_edges: 0
dangling: 0

=== 4. NULL FILEPATH ===
null_code_filepath: 0
context_nodes_preserved: 5

=== 5. COORD SANITY ===
x_range: 358.0 to 895.0
```

**Restart cycle** — the check that matters most, since Bug 6 was a restart-only failure:

```
before: nodes=67 call_edges=40
after:  nodes=67 call_edges=40
re-ingest count: 1   (no repeat loop)
```

Node count and edge set are stable across a reboot, and the re-ingest trigger fires exactly
once rather than on every boot.

## Data safety

The repair purges rows, so the original DB was backed up before the first destructive run:

```
agy_nodeos.db.bak.1790875860
```

Rows written by the diverged simulation were also removed
(`ABS(x_coord) > 1e6 OR ABS(y_coord) > 1e6`), since they carry no usable spatial meaning.

## Files changed

| File | Change |
|------|--------|
| `polymath_nodeos/daemon.py` | forward `filepath` on cold-start path; `sqlite3` import; `CODE_NODE_TYPES`; `purge_orphan_filepath_nodes()`; re-ingest triggers (NULL filepath **and** call-data ratio); refresh `physics_ticks` post-ingest; `IGNORED_DIR_SEGMENTS` segment matching |
| `polymath_nodeos/nodes_engine.py` | `null_filepath_nodes` + code-type scoping; `math.isfinite` hydrate guard; `_fit_boundary()`; `self.center`; repulsion/velocity clamps; sync-before-settle; `_physics_running` guard; `_budget_ticks()`; persist + hydrate `calls`; `_build_call_index()` / `_resolve_target()`; stale-edge purge with in-memory reset; no-call-data safety gate |
| `polymath_nodeos/graph_manager.py` | `calls` column in `nodes`; `ALTER TABLE` migration for existing databases |
| `polymath_nodeos/cli.py` | `_package_version()` from distribution metadata |
| `polymath_nodeos/scripts/context_engine.py` | removed dead-remote `git clone` / venv / pip setup from the constructor |

### Bug 11 — Context Engine shelled out to a dead remote on every boot

`ContextEngine.__init__` did unrelated setup work, entirely unrelated to parsing `context.md`:

```python
def __init__(self, db_path='agy_nodeos.db'):
    import subprocess
    workspace = "/data/data/com.termux/files/home/Projects"   # hardcoded absolute path
    jev_dir = os.path.join(workspace, "use-jev-playbook")
    if not os.path.exists(jev_dir):
        try:
            subprocess.run(["git", "clone", "https://github.com/BodilJasi/use-jev-playbook.git", jev_dir], ...)
            subprocess.run(["python3", "-m", "venv", ".venv"], cwd=jev_dir, check=True)
            subprocess.run([".venv/bin/pip", "install", "-r", "requirements.txt", ...])
            subprocess.run(["cp", "config.example.yaml", "config.yaml"], cwd=jev_dir, check=True)
            ...
        except Exception as e:
            with open("/data/data/com.termux/files/home/Projects/context_engine_err.log", "w") as f:
                f.write(str(e))
    self.db_path = db_path
```

The remote no longer exists, so every daemon boot — triggered by *any* `context.md` write —
attempted a clone, failed with exit 128, and wrote an error file. Four distinct problems:

1. **Network I/O in a constructor.** A context-parsing class should never shell out to the network.
2. **Hardcoded absolute path** to one developer's machine, ignoring `os.getcwd()` — the exact
   convention the rest of NodeOS follows.
3. **`check=True` on `venv`/`pip install` against a directory that may not exist**, so a failed
   clone produced a cascade of confusing secondary errors rather than one clear failure.
4. **Side effects on read.** Constructing the engine mutated the filesystem outside the workspace.

The setup work is removed; the constructor now only records its own state:

```python
def __init__(self, db_path='agy_nodeos.db'):
    self.db_path = db_path
```

Verified: no `jev`/`subprocess`/hardcoded-path references remain, the daemon boots clean with
no network activity, and context sync still works (`Successfully synced 2 entities and 2 states`).
The stale `context_engine_err.log` was removed and does not regenerate.

## Notes and follow-ups

- **`resolve_edges` still keys on bare names.** The AST does not record qualified paths, so
  same-file preference plus refuse-on-ambiguity is the best available heuristic. Resolving
  `ast.Attribute` chains to their full dotted module path would make edges exact.
- **`import sqlite3` placement is inconsistent.** `nodes_engine.py` and now `daemon.py` import
  at module level; `cli.py` and `graph_manager.py` use function-local imports. Worth
  normalising.
- **The `.jsagent` schema cache writes one JSON per node** (`_store_schema`). At ~2,500 nodes
  in umbrella mode that is thousands of small writes per full scan; the directory already
  runs to several MB.
- **Umbrella-root mode indexes everything.** There is no allowlist or `.nodeosignore`. If
  umbrella coverage is wanted permanently rather than occasionally, an ignore file would be
  the natural mechanism.
