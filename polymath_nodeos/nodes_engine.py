import json
import math
import os
import sqlite3
import sys

class Point:
    def __init__(self, x, y, node_id, node_type, mass=1.0, name="unknown", calls=None, filepath=None, line_number=None):
        self.x = x
        self.y = y
        self.vx = 0.0
        self.vy = 0.0
        self.fx = 0.0
        self.fy = 0.0
        self.mass = mass
        self.node_id = node_id
        self.node_type = node_type
        self.name = name
        self.calls = calls if calls else []
        self.edges = []
        self.filepath = filepath
        self.line_number = line_number

class Rectangle:
    def __init__(self, x, y, w, h):
        self.x = x
        self.y = y
        self.w = w
        self.h = h

    def contains(self, point):
        return (self.x - self.w <= point.x <= self.x + self.w and
                self.y - self.h <= point.y <= self.y + self.h)

    def intersects(self, range_rect):
        return not (range_rect.x - range_rect.w > self.x + self.w or
                    range_rect.x + range_rect.w < self.x - self.w or
                    range_rect.y - range_rect.h > self.y + self.h or
                    range_rect.y + range_rect.h < self.y - self.h)

class QuadTree:
    def __init__(self, boundary, capacity):
        self.boundary = boundary
        self.capacity = capacity
        self.points = []
        self.divided = False

    def subdivide(self):
        x, y, w, h = self.boundary.x, self.boundary.y, self.boundary.w / 2, self.boundary.h / 2
        self.northeast = QuadTree(Rectangle(x + w, y - h, w, h), self.capacity)
        self.northwest = QuadTree(Rectangle(x - w, y - h, w, h), self.capacity)
        self.southeast = QuadTree(Rectangle(x + w, y + h, w, h), self.capacity)
        self.southwest = QuadTree(Rectangle(x - w, y + h, w, h), self.capacity)
        self.divided = True

    def insert(self, point):
        if not self.boundary.contains(point):
            return False
        if len(self.points) < self.capacity:
            self.points.append(point)
            return True
        if not self.divided:
            self.subdivide()
        return (self.northeast.insert(point) or self.northwest.insert(point) or 
                self.southeast.insert(point) or self.southwest.insert(point))

    def query(self, range_rect, found=None):
        if found is None: found = []
        if not self.boundary.intersects(range_rect): return found
        for p in self.points:
            if range_rect.contains(p): found.append(p)
        if self.divided:
            self.northwest.query(range_rect, found)
            self.northeast.query(range_rect, found)
            self.southwest.query(range_rect, found)
            self.southeast.query(range_rect, found)
        return found

class NativeNodesEngine:
    """
    NATIVE SPATIAL CLUSTERING & PHYSICS ENGINE
    Implements Force-Directed Graph physics (Repulsion + Gravity + Hooke's Law Springs) and batch SQLite sync.
    """
    def __init__(self, db_path='agy_nodeos.db'):
        self.db_path = db_path
        self.boundary = Rectangle(500, 500, 500, 500)
        self.center = (500.0, 500.0)
        self.qtree = QuadTree(self.boundary, 4)
        self._physics_running = False
        self.all_nodes = []
        # Nodes hydrated from the DB whose filepath was lost (NULL). They cannot be
        # attributed to a file, so the graph must be re-ingested rather than trusted.
        self.null_filepath_nodes = 0
        # Category E health counters. QuadTree.insert returns False for an out-of-bounds
        # point and never raises, so an ignored return value silently emptied the spatial
        # index (bug 2). These make such losses visible instead of invisible.
        self.spatial_rejects = 0   # nodes dropped from the QuadTree for falling outside it
        self.ambiguous_calls = 0   # calls skipped because the name was ambiguous across files
        # Scratch buffers so hydrate can fit the boundary before inserting (see hydrate_from_db).
        self._hydrate_xs = []
        self._hydrate_ys = []
        # Same scoping as the daemon purge: only code nodes are expected to have a filepath.
        self.code_node_types = ("FunctionDef", "AsyncFunctionDef", "ClassDef", "JS_Node", "Variable", "Parameter")
        self.hydrate_from_db()
        # Tick budget scales down as the graph grows. Pure-Python Euler integration is
        # O(ticks * N * neighbourhood); a fixed 100 ticks pins a core for minutes on a
        # few thousand nodes, which is what starved sync_to_sqlite on Termux.
        self.physics_ticks = self._budget_ticks(len(self.all_nodes))

    @staticmethod
    def _budget_ticks(node_count):
        """Pick a tick budget that keeps a single settling pass bounded on mobile."""
        if node_count < 500:
            return 100
        if node_count < 2000:
            return 40
        return 15

    def hydrate_from_db(self):
        print("[Physics Engine] Hydrating spatial matrix from SQLite Database...")
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT node_id, node_type, x_coord, y_coord, name, filepath, calls, line_number FROM nodes"
            )
            rows = cursor.fetchall()
            # Fit the boundary to the incoming rows BEFORE inserting any of them. Inserting
            # into the constructor's fixed Rectangle(500,500,500,500) first made insert()
            # reject every node outside that box — measured at 44 of 53 here — inflating
            # spatial_rejects with what is really a bootstrap artifact. Those rejects were
            # harmless (rebuild_qtree re-fits and re-inserts everything) but they made the
            # counter unreadable as a health signal, defeating its purpose.
            for row in rows:
                if row[2] is not None and row[3] is not None:
                    if math.isfinite(row[2]) and math.isfinite(row[3]):
                        self._hydrate_xs.append(row[2])
                        self._hydrate_ys.append(row[3])
            if self._hydrate_xs:
                _margin = 400.0
                _xs, _ys = self._hydrate_xs, self._hydrate_ys
                _cx = (min(_xs) + max(_xs)) / 2.0
                _cy = (min(_ys) + max(_ys)) / 2.0
                self.boundary = Rectangle(
                    _cx, _cy,
                    max(max(_xs) - _cx, _cx - min(_xs)) + _margin,
                    max(max(_ys) - _cy, _cy - min(_ys)) + _margin)
                self.center = (_cx, _cy)
                self.qtree = QuadTree(self.boundary, 4)
            for row in rows:
                if row[2] is not None and row[3] is not None:
                    # Reject non-finite coordinates left behind by a diverged simulation.
                    # math.isfinite guards against inf/nan written by an older build.
                    if not (math.isfinite(row[2]) and math.isfinite(row[3])):
                        continue
                    name = row[4] if len(row) > 4 else "unknown"
                    filepath = row[5] if len(row) > 5 else None
                    calls = []
                    if len(row) > 6 and row[6]:
                        try:
                            parsed = json.loads(row[6])
                            if isinstance(parsed, list):
                                calls = [str(c) for c in parsed]
                        except (TypeError, ValueError):
                            calls = []
                    line_number = row[7] if len(row) > 7 else None
                    p = Point(row[2], row[3], row[0], row[1], name=name,
                              calls=calls, filepath=filepath, line_number=line_number)
                    self.all_nodes.append(p)
                    # Do NOT ignore the return: insert() returns False for an out-of-bounds
                    # point and never raises. Count the loss so it is reported, not silent.
                    if not self.qtree.insert(p):
                        self.spatial_rejects += 1
                    # CONTEXT_* memory records legitimately have no filepath; only count
                    # code nodes, otherwise the workspace re-ingests on every boot forever.
                    if not filepath and row[1] in self.code_node_types:
                        self.null_filepath_nodes += 1
            print(f"[Physics Engine] Hydrated {len(self.all_nodes)} kinetic nodes.")
            if self.null_filepath_nodes:
                print(f"[Physics Engine] WARNING: {self.null_filepath_nodes} code nodes have a NULL filepath. "
                      f"Graph is unsearchable by file; a re-ingest will be triggered.")
        except sqlite3.OperationalError:
            print("[Physics Engine] Table not initialized. Skipping hydration.")
        conn.close()

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

    def rebuild_qtree(self):
        self._fit_boundary()
        self.qtree = QuadTree(self.boundary, 4)
        # Category E: never discard an insert() failure silently. After _fit_boundary every
        # node should be in bounds; a non-zero count means the boundary fit is wrong (e.g.
        # NaN coords), which previously emptied the spatial index with no output at all.
        rejected = 0
        for p in self.all_nodes:
            if not self.qtree.insert(p):
                rejected += 1
        self.spatial_rejects += rejected
        if rejected:
            sys.stderr.write(
                f"[Physics Engine] WARNING: {rejected}/{len(self.all_nodes)} nodes fell "
                f"outside the QuadTree boundary (center={self.boundary.x},{self.boundary.y} "
                f"w={self.boundary.w} h={self.boundary.h}) and were DROPPED from the spatial "
                f"index. Queries will miss them.\n"
            )
        return rejected

    def _build_call_index(self):
        """Index nodes by bare name, preferring same-file matches.

        The AST only records call NAMES (`ast.Name.id` / `ast.Attribute.attr`), not
        qualified paths. A single flat {name: node} map silently resolved every call to
        whichever duplicate happened to be ingested last, so `Rectangle` in one module
        could bond to `Rectangle` in an unrelated one. Build a name -> [nodes] index and
        resolve same-file first, then a unique global match, and never guess when the name
        is genuinely ambiguous across files.
        """
        by_name = {}
        for p in self.all_nodes:
            by_name.setdefault(p.name, []).append(p)
        return by_name

    def _resolve_target(self, by_name, caller, call_name):
        """Pick the best definition for `call_name` as seen from `caller`."""
        candidates = by_name.get(call_name)
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        # Same file wins: a module referring to its own symbol is by far the common case.
        same_file = [c for c in candidates if c.filepath and c.filepath == caller.filepath]
        if len(same_file) == 1:
            return same_file[0]
        if len(same_file) > 1:
            # Same name declared more than once in one file (overloads/redefinitions):
            # fall back to the first declaration, which is what Python binds for the
            # earliest call site.
            return same_file[0]
        return None  # Ambiguous across files: refuse to invent an edge.

    def resolve_edges(self):
        """Resolve string AST calls into physical Point references for spring physics.

        ORDERING CONTRACT — do not reorder the following three stages. This sequence is
        load-bearing and was previously implicit, which is how commit 6ed6388 ("Optimize
        physics engine to O(N log N) and offload to thread") silently broke it while
        appearing to be a pure performance change:

            1. structural sync  — persist the graph (nodes, calls, CALL edges)
            2. physics start    — settle positions in a background thread
            3. final sync       — persist settled coordinates (end of simulate_physics)

        The original guarantee held by accident: physics was synchronous, so the graph was
        always synced from a settled state. Threading stage 2 turned the sync into a
        concurrent read of coordinates the simulation thread was still mutating.

        The invariant that must hold: THE GRAPH MUST BE QUERYABLE BEFORE PHYSICS RUNS.
        Positions are cosmetic; `nodeos -c search` and `blast` are not. If you move
        sync_to_sqlite after the thread spawn, a boot on a large workspace shows an empty
        graph for minutes while a core pins at 100% (bug 3). Keep stage 1 where it is.
        """
        print("[Physics Engine] Resolving execution call graph into physical edges...")
        by_name = self._build_call_index()
        edge_count = 0
        ambiguous = 0

        # Clear in-memory edges to mirror the DB purge below. Without this, the
        # `target not in p.edges` guard would suppress every re-insert on a second
        # resolve, leaving the CALL set permanently empty after one boot cycle.
        for p in self.all_nodes:
            p.edges = []

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Safety gate. Hydration can legitimately produce zero call data: a pre-migration
        # database has no calls column, or every node is CONTEXT_* memory. Purging CALL
        # edges in that state would delete a valid graph, so only rebuild when there is
        # something to rebuild from.
        if not any(p.calls for p in self.all_nodes):
            dangling = cursor.execute("""
                SELECT COUNT(*) FROM edges WHERE
                source_id NOT IN (SELECT node_id FROM nodes) OR
                target_id NOT IN (SELECT node_id FROM nodes) OR
                source_id = target_id
            """).fetchone()[0]
            if dangling:
                print(f"[Physics Engine] No call data available (pre-migration or empty graph). "
                      f"Pruning {dangling} invalid edge(s) without rebuilding CALL edges.")
                cursor.execute("""
                    DELETE FROM edges WHERE
                    source_id NOT IN (SELECT node_id FROM nodes) OR
                    target_id NOT IN (SELECT node_id FROM nodes) OR
                    source_id = target_id
                """)
                conn.commit()
            conn.close()
            return

        # Drop stale edges BEFORE inserting. resolve_edges only ever INSERT OR IGNOREs, so
        # edges from deleted files, older builds, or the pre-scoping resolver would survive
        # forever. Purge dangling endpoints and self-edges, then rebuild the CALL set.
        cursor.execute("""
            DELETE FROM edges WHERE
            source_id NOT IN (SELECT node_id FROM nodes) OR
            target_id NOT IN (SELECT node_id FROM nodes) OR
            source_id = target_id
        """)
        cursor.execute("DELETE FROM edges WHERE relation_type = 'CALL'")

        for p in self.all_nodes:
            for call_name in p.calls:
                target = self._resolve_target(by_name, p, call_name)
                if target is None:
                    if len(by_name.get(call_name, [])) > 1:
                        ambiguous += 1
                    continue
                if target is not p and target not in p.edges:
                    p.edges.append(target)
                    edge_count += 1
                    try:
                        cursor.execute('''
                            INSERT OR IGNORE INTO edges (source_id, target_id, relation_type) 
                            VALUES (?, ?, "CALL")
                        ''', (p.node_id, target.node_id))
                    except sqlite3.OperationalError:
                        pass # Ignore if edges table missing/already exists

        conn.commit()
        conn.close()
        # Persist as an inspectable counter, not only a boot-time print: an unresolved
        # call is silent data loss in the dependency graph and must be queryable later.
        self.ambiguous_calls = ambiguous
        if ambiguous:
            print(f"[Physics Engine] Skipped {ambiguous} ambiguous call(s): the name exists in "
                  f"multiple files with no same-file match. Rename or qualify to disambiguate.")
        print(f"[Physics Engine] Bonded {edge_count} structural connections. Syncing graph to SQLite...")
        # ORDERING CONTRACT stage 1 of 3 — see the resolve_edges docstring. Structural data
        # is persisted here, BEFORE the physics thread is spawned below. Position layout is
        # cosmetic; the graph must be queryable even if the simulation is slow or still
        # running. Moving this call after the spawn reintroduces bug 3.
        self.sync_to_sqlite()

        if edge_count > 0:
            import threading
            # Run physics simulation in the background so it doesn't block the Daemon event loop.
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

            # ORDERING CONTRACT stage 2 of 3 — this thread is deliberately NOT joined.
            # It runs detached so a slow settle cannot block ingestion, and because the
            # structural graph was already persisted above, the daemon stays queryable
            # while positions settle. The trade-off: if the process exits mid-simulation
            # the final sync in simulate_physics never runs, and the DB keeps the
            # pre-settle coordinates from stage 1. That is acceptable — the next boot
            # re-settles — and is strictly better than the pre-6ed6388 behaviour of an
            # empty graph. Never move the sync_to_sqlite call above this spawn.
            threading.Thread(target=_run, daemon=True).start()

    def simulate_physics(self, ticks=50):
        """Euler Integration of Coulomb Repulsion, Central Gravity, and Hooke's Law Springs."""
        damping = 0.85
        time_step = 1.0
        k_repulse = 5000.0
        k_gravity = 0.05
        k_spring = 0.1  # Hooke's Law spring constant
        ideal_length = 50.0  # Ideal distance between connected nodes
        # Numerical guards. Without these the integrator diverges: at dist_sq == 1 the
        # repulsion term is k_repulse (5000), which launches nodes to ~1e120 within a
        # few ticks and leaves the graph with garbage coordinates.
        min_dist_sq = 100.0      # 10px minimum separation keeps 1/d^2 bounded
        max_force = 5_000.0      # per-node force clamp per axis
        max_velocity = 200.0     # per-node velocity clamp per axis

        for tick in range(ticks):
            # Rebuild QuadTree for rapid O(N log N) spatial queries
            self.rebuild_qtree()
            center_x, center_y = self.center

            for node in self.all_nodes:
                node.fx = (center_x - node.x) * k_gravity
                node.fy = (center_y - node.y) * k_gravity

                # Optimized Local Repulsion: Only repel against nodes within 150px radius using QuadTree
                range_rect = Rectangle(node.x, node.y, 150, 150)
                nearby_nodes = self.qtree.query(range_rect)

                for other in nearby_nodes:
                    if other == node:
                        continue
                    dx, dy = node.x - other.x, node.y - other.y
                    dist_sq = dx**2 + dy**2
                    if dist_sq <= 0:
                        continue
                    force = k_repulse / max(dist_sq, min_dist_sq)
                    dist = math.sqrt(dist_sq)
                    node.fx += force * (dx / dist)
                    node.fy += force * (dy / dist)

                node.fx = max(-max_force, min(max_force, node.fx))
                node.fy = max(-max_force, min(max_force, node.fy))

            # Hooke's Law Spring Attraction between CONNECTED nodes
            for n1 in self.all_nodes:
                for n2 in n1.edges:
                    dx, dy = n2.x - n1.x, n2.y - n1.y
                    dist = math.sqrt(dx**2 + dy**2)
                    if dist > 0:
                        force = k_spring * (dist - ideal_length)
                        fx = force * (dx / dist)
                        fy = force * (dy / dist)
                        n1.fx += fx
                        n1.fy += fy
                        n2.fx -= fx
                        n2.fy -= fy

            # Euler Integration
            for node in self.all_nodes:
                ax = node.fx / node.mass
                ay = node.fy / node.mass
                node.vx = (node.vx + ax * time_step) * damping
                node.vy = (node.vy + ay * time_step) * damping
                node.vx = max(-max_velocity, min(max_velocity, node.vx))
                node.vy = max(-max_velocity, min(max_velocity, node.vy))
                node.x += node.vx * time_step
                node.y += node.vy * time_step

        self.rebuild_qtree()
        # ORDERING CONTRACT stage 3 of 3 — persist settled coordinates. Reached only on
        # normal completion; if the process exits early this is skipped by design and the
        # graph keeps its stage-1 coordinates (see the note at the thread spawn).
        self.sync_to_sqlite()
        sys.stderr.write(f"[Physics Engine] Successfully settled {len(self.all_nodes)} nodes. Syncing to SQLite.\n")

    def sync_to_sqlite(self):
        """Batch update physical positions to SQLite to save I/O overhead."""
        import json
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        for p in self.all_nodes:
            # CONTEXT_* memory records are owned exclusively by ContextEngine, which
            # rewrites them wholesale on every sync. Hydration loads them (they carry
            # coordinates), so this loop used to re-insert them immediately after
            # ContextEngine deleted them — resurrecting rows it had just purged. Combined
            # with ContextEngine's per-process `hash()` ids, every boot leaked a fresh set
            # of CONTEXT rows: 25 accumulated where 5 belong. The physics engine has no
            # business writing them, so it must not.
            if p.node_type not in self.code_node_types:
                continue
            # calls MUST be persisted: they are the only record of which symbols a node
            # references. Without this column, hydration after a restart yields empty
            # call lists and the dependency graph cannot be rebuilt.
            calls_json = json.dumps(sorted(p.calls))
            cursor.execute('''
                INSERT INTO nodes (node_id, node_type, name, filepath, calls, x_coord, y_coord, line_number, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(node_id) DO UPDATE SET 
                    name=excluded.name, 
                    filepath=excluded.filepath,
                    calls=excluded.calls,
                    x_coord=excluded.x_coord, 
                    y_coord=excluded.y_coord, 
                    line_number=excluded.line_number,
                    last_updated=excluded.last_updated
            ''', (p.node_id, p.node_type, p.name, p.filepath, calls_json, p.x, p.y, p.line_number))
        conn.commit()
        conn.close()

    def ingest_file(self, filepath, ast_nodes):
        """Single entry point for putting a file's nodes into the graph.

        Category C: the cold-start deep scan and the live filesystem watcher each used to
        parse and add nodes independently. They were free to disagree, and did — one
        forwarded `filepath` and the other silently dropped it, so 1,524 of 1,558 nodes
        were written with a NULL path (bug 1). Two copies of one contract is zero
        enforcement of that contract.

        Both callers now route through here, so a divergence cannot be reintroduced by
        editing one site. Returns the set of node_ids the file currently contributes,
        which is what reconciliation needs in order to retire the superseded ones.
        """
        live_hashes = set()
        for node in ast_nodes or []:
            node_id = node.get('hash')
            if not node_id:
                continue
            self.add_node(node_id, node.get('type', 'unknown'),
                          node.get('name', 'unknown'), node.get('calls', []),
                          filepath=filepath, line_number=node.get('line_number'))
            live_hashes.add(node_id)
        self.retire_superseded_nodes(filepath, live_hashes)
        return live_hashes

    def retire_superseded_nodes(self, filepath, live_hashes):
        """Delete rows for `filepath` whose node_id the current parse no longer emits.

        Category A. node_id is a content hash, so editing a file mints new ids for the
        symbols in it while every previous id survives — the writes in this engine are
        additive-only (INSERT ... ON CONFLICT DO UPDATE), which can add and update but
        never subtract. Without this, the node count grows monotonically forever: 29 stale
        rows after a handful of edits on a 12-file repo, and one live demonstration when a
        single edit to nodes_engine.py added 4 duplicate class rows.

        Only ids attributed to THIS file are considered, so a concurrent edit elsewhere is
        never at risk. The same ids are dropped from memory, otherwise the next
        sync_to_sqlite re-inserts them (the bug-8 lesson). Returns rows removed.
        """
        if not live_hashes:
            return 0
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            placeholders = ','.join('?' * len(live_hashes))
            cursor.execute(
                f"SELECT node_id FROM nodes WHERE filepath = ? "
                f"AND node_id NOT IN ({placeholders})",
                (filepath, *live_hashes))
            stale_ids = {row[0] for row in cursor.fetchall()}
            if not stale_ids:
                conn.close()
                return 0
            dead = ','.join('?' * len(stale_ids))
            cursor.execute(f"DELETE FROM edges WHERE source_id IN ({dead}) "
                           f"OR target_id IN ({dead})", tuple(stale_ids) * 2)
            cursor.execute(f"DELETE FROM nodes WHERE node_id IN ({dead})", tuple(stale_ids))
            conn.commit()
            conn.close()
            # Mirror the deletion in memory so sync_to_sqlite cannot resurrect them.
            self.all_nodes = [n for n in self.all_nodes if n.node_id not in stale_ids]
            sys.stderr.write(
                f"[Physics Engine] Retired {len(stale_ids)} superseded node(s) for "
                f"{filepath} (content hash changed on edit).\n")
            return len(stale_ids)
        except sqlite3.OperationalError as exc:
            sys.stderr.write(f"[Physics Engine] Could not retire nodes for {filepath}: {exc}\n")
            return 0

    def reconcile_against_source(self, workspace, parse_file, should_ignore,
                                 suffixes=('.py', '.js', '.ts')):
        """Startup pass: re-parse every live source file and retire rows it no longer emits.

        This is the fix that makes Category A actually close. Per-file retirement inside
        ingest_file only helps when a file is re-ingested, but a boot whose graph already
        looks healthy (filepaths present, call data above threshold) skips the deep scan
        entirely — so superseded rows accumulate forever and are re-hydrated on every
        subsequent boot. Measured on this repo: stale rows grew 29 -> 38 across edits while
        the daemon reported nothing wrong.

        Deleting a deleted file's rows is handled separately by prune_vanished_files; this
        handles files that still exist but whose symbols changed.

        Retirement is idempotent: a file whose parse is unchanged contributes its current
        hashes as the keep-set, so no row is removed. Returns (retired_rows, files_scanned).
        """
        retired = 0
        scanned = 0
        for root, _, files in os.walk(workspace):
            if should_ignore(root):
                continue
            for name in files:
                if not name.endswith(suffixes):
                    continue
                filepath = os.path.join(root, name)
                try:
                    ast_nodes = parse_file(filepath)
                except (OSError, UnicodeDecodeError, SyntaxError) as exc:
                    # A file we cannot parse must not cause its existing rows to be deleted.
                    # Refusing to retire is the safe direction: it may leave stale rows, but
                    # it can never delete live ones.
                    sys.stderr.write(
                        f"[Physics Engine] Skipping reconcile of {filepath}: {exc}. "
                        f"Existing rows preserved.\n")
                    continue
                scanned += 1
                live = {n.get('hash') for n in (ast_nodes or []) if n.get('hash')}
                if live:
                    retired += self.retire_superseded_nodes(filepath, live)
        if retired:
            self.rebuild_qtree()
        return retired, scanned

    def prune_vanished_files(self):
        """Remove rows whose source file no longer exists on disk.

        The startup counterpart to retire_superseded_nodes: edits are handled at ingestion
        time, but a file deleted while the daemon was stopped is only discovered here. Both
        SQLite and memory are pruned so a restart cannot re-hydrate the orphans.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT filepath FROM nodes WHERE filepath IS NOT NULL")
            filepaths = [row[0] for row in cursor.fetchall()]
            conn.close()
        except sqlite3.OperationalError:
            return 0

        vanished = [fp for fp in filepaths if not os.path.exists(fp)]
        total = 0
        for filepath in vanished:
            sys.stderr.write(
                f"[Physics Engine] Source file vanished; purging its nodes: {filepath}\n")
            total += self.delete_nodes_for_file(filepath)
        if total:
            self.all_nodes = [n for n in self.all_nodes
                              if not n.filepath or os.path.exists(n.filepath)]
            self.rebuild_qtree()
        return total

    def remove_nodes_by_file(self, filepath):
        """Removes every node belonging to a deleted file, in memory AND in SQLite.

        This previously filtered only `self.all_nodes`. Because sync_to_sqlite never
        subtracts, the rows stayed in the database forever and were re-hydrated on the next
        boot — a deleted file left permanent orphans behind (Category A).
        """
        sys.stderr.write(f"[Physics Engine] Removing spatial nodes for deleted file: {filepath}\n")
        self.all_nodes = [node for node in self.all_nodes if node.filepath != filepath]
        for node in self.all_nodes:
            node.edges = [e for e in node.edges if e.filepath != filepath]
        self.rebuild_qtree()
        self.delete_nodes_for_file(filepath)

    def delete_nodes_for_file(self, filepath):
        """Delete a file's rows (and their edges) from SQLite. Returns rows removed.

        Scoped to nodes that actually carry this filepath; CONTEXT_* memory records have
        none and are never touched.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM edges WHERE source_id IN "
                           "(SELECT node_id FROM nodes WHERE filepath = ?) "
                           "OR target_id IN (SELECT node_id FROM nodes WHERE filepath = ?)",
                           (filepath, filepath))
            cursor.execute("DELETE FROM nodes WHERE filepath = ?", (filepath,))
            removed = cursor.rowcount
            conn.commit()
            conn.close()
            if removed:
                sys.stderr.write(
                    f"[Physics Engine] Purged {removed} node row(s) for deleted file: {filepath}\n")
            return removed
        except sqlite3.OperationalError as exc:
            # A missing table is not a reason to abort ingestion; report and move on.
            sys.stderr.write(f"[Physics Engine] Could not purge rows for {filepath}: {exc}\n")
            return 0

    def add_node(self, node_id, node_type, name="unknown", calls=None, parent_x=500, parent_y=500, filepath=None, line_number=None):
        import random
        drop_x = parent_x + random.uniform(-10, 10)
        drop_y = parent_y + random.uniform(-10, 10)
        
        existing = next((n for n in self.all_nodes if n.node_id == node_id), None)
        if not existing:
            p = Point(drop_x, drop_y, node_id, node_type, name=name, calls=calls, filepath=filepath, line_number=line_number)
            self.all_nodes.append(p)
            sys.stderr.write(f"[Physics Engine] Dropped {node_type} '{name}' into kinetic simulation.\n")
            return p
        else:
            existing.name = name
            if filepath:
                existing.filepath = filepath
            if calls:
                existing.calls = calls
            if line_number:
                existing.line_number = line_number
            return existing
