# Ordering Contract — `NativeNodesEngine`

The single invariant that was never written down, and that one performance commit broke
while appearing to be a pure optimisation.

## Background

Commit `6ed6388` — *"Optimize physics engine to O(N log N) and offload to thread"* —
changed `resolve_edges` so physics ran in a background thread instead of inline.

Before that commit, the code worked by accident:

```
resolve_edges()
  ... build edges ...
  simulate_physics(100)     # synchronous: blocks until settled
  sync_to_sqlite()          # always ran on a settled graph
```

The guarantee *"the graph is synced from a settled state"* was not written anywhere. It was
an emergent property of physics being synchronous. Threading the simulation turned the sync
into a concurrent read of coordinates the thread was still mutating, so on a large
workspace the graph stayed empty for minutes while a core pinned at 100%. That was bug 3,
and it shipped as a performance improvement.

**A guarantee that exists only as a consequence of code order is not a guarantee.**

## The contract

`resolve_edges` performs three stages. Their order is load-bearing.

| Stage | What | Where | Blocking? |
|-------|------|-------|-----------|
| **1** | Persist structure — nodes, `calls`, CALL edges | `nodes_engine.py` → `sync_to_sqlite()` immediately after the edge loop | Yes, fast |
| **2** | Settle positions | detached `threading.Thread` → `simulate_physics(self.physics_ticks)` — marker at the spawn site | No |
| **3** | Persist settled coordinates | end of `simulate_physics()` → `sync_to_sqlite()` | Yes, only on completion |

### Rules

1. **Stage 1 must complete before stage 2 starts.** The graph is queryable immediately;
   positions are cosmetic. `nodeos -c search` and `nodeos -c blast` must work while
   physics is still running or has not started at all.
2. **Stage 2 is detached and never joined.** A slow settle must not block ingestion. The
   `_physics_running` guard prevents a second simulation from stacking on the first.
3. **Stage 3 is best-effort.** If the process exits mid-simulation, stage 3 never runs and
   the database keeps the stage-1 coordinates. The next boot re-settles. This is the
   deliberate trade-off: stale coordinates beat an empty graph.
4. **Never move `sync_to_sqlite()` after the thread spawn.** That reintroduces bug 3
   exactly.

## Verifying the contract

```bash
nodeos -c ping                    # daemon alive
sqlite3 agy_nodeos.db "SELECT COUNT(*) FROM nodes;"   # non-zero promptly after boot
```

If the node count is 0 long after boot while a core is busy, stage 1 has been moved or
removed.

A machine-checkable version of the reconciliation half of this contract lives in
`polymath_nodeos/scripts/graph_reconciler.py`:

```bash
python3 -m polymath_nodeos.scripts.graph_reconciler .
```

It must print `RECONCILED`. That is the invariant that would have caught bug 12, and it is
the check whose absence let twelve defects accumulate.