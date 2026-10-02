"""
Reconciliation guard for the NodeOS spatial graph (Category A/B/G).

This is the check that did not exist while twelve defects accumulated. Every bug in the
additive-only state family — stale rows (bug 12), duplicated ingestion paths (bug 1/6),
ambiguous identity (bug 7) — shares one invariant: the `nodes` table must equal a fresh
parse of the workspace. Nothing asserted it, so nothing caught it.

The reconciler recomputes the truth and diffs it against stored state. It is READ-ONLY.
Use it to verify a fix; the destructive side (pruning) lives in the ingestion path, and
this module deliberately does not write to the database.

Run:
    python3 -m polymath_nodeos.scripts.graph_reconciler [workspace]
"""
import os
import sqlite3
import sys

CODE_NODE_TYPES = ("FunctionDef", "AsyncFunctionDef", "ClassDef", "JS_Node")
SOURCE_SUFFIXES = ('.py', '.js', '.ts')
# Node types owned by ContextEngine, not by the AST parser. ctx_root carries context.md as
# its filepath, so it would otherwise look like a stale code row on every run. Compare them
# in their own process (process_and_sync rewrites them wholesale) rather than here.
CONTEXT_NODE_TYPES = ("CONTEXT_ROOT", "CONTEXT_ENTITY", "CONTEXT_STATE", "CONTEXT_MEMORY")


def iter_source_files(workspace, ignore_check):
    for root, _, files in os.walk(workspace):
        if ignore_check(root):
            continue
        for name in files:
            if name.endswith(SOURCE_SUFFIXES):
                yield os.path.join(root, name)


def reconcile(workspace, db_path, parse_file, ignore_check):
    """Return a diff between the freshly parsed graph and the stored graph.

    parse_file(path) -> list of node dicts with at least 'hash' and 'filepath'.
    ignore_check(dir) -> True to skip a directory.
    """
    # Normalise every path to absolute. The DB stores absolute filepaths; a workspace
    # given as '.' would otherwise produce relative ones and silently compare unequal,
    # yielding a false 'reconciled' verdict. This bug shipped in the first draft of this
    # very guard — the category-G failure mode, caught only because the counts disagreed.
    workspace = os.path.abspath(workspace)

    conn = sqlite3.connect(db_path)
    try:
        stored = {
            nid: os.path.abspath(fp) for nid, fp in conn.execute(
                "SELECT node_id, filepath FROM nodes "
                "WHERE filepath IS NOT NULL AND node_type NOT IN ({})".format(
                    ','.join('?' * len(CONTEXT_NODE_TYPES))),
                CONTEXT_NODE_TYPES,
            ).fetchall()
        }
    finally:
        conn.close()

    parsed = {}
    for path in iter_source_files(workspace, ignore_check):
        for node in parse_file(path) or []:
            if node.get('hash'):
                parsed[node['hash']] = os.path.abspath(path)

    stored_hashes = set(stored)
    parsed_hashes = set(parsed)

    only_stored = stored_hashes - parsed_hashes
    live_files = set(parsed.values())
    stale = {h: stored[h] for h in only_stored
             if stored[h] in live_files or not os.path.exists(stored[h])}
    missing = parsed_hashes - stored_hashes

    # A clean verdict requires the two hash sets to be EQUAL, which implies equal size.
    # The only self-contradiction is "we are about to report RECONCILED but the sizes
    # differ" — that can only mean the diff itself is broken (e.g. a path-format bug made
    # two disjoint sets look identical). A mere size difference is the normal, expected
    # signature of a dirty graph, NOT a guard bug, so it must not trip this check.
    would_be_clean = not stale and not missing
    consistent = (not would_be_clean) or (
        len(stored_hashes) == len(parsed_hashes))

    return {
        'stored_count': len(stored_hashes),
        'parsed_count': len(parsed_hashes),
        'stale': stale,        # in DB, not produced by any current file (or file gone)
        'missing': missing,    # produced now, absent from DB
        'consistent': consistent,
    }


def main():
    from polymath_nodeos.jage_engine import JageASTEngine
    from polymath_nodeos.daemon import AGYRawWatchdog

    workspace = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    db_path = os.path.join(workspace, 'agy_nodeos.db')
    if not os.path.exists(db_path):
        print(f"[Reconciler] No graph database at {db_path}; nothing to reconcile.")
        return 0

    jage = JageASTEngine()
    watchdog = AGYRawWatchdog(workspace, callback=None)
    result = reconcile(workspace, db_path, jage.parse_file, watchdog._should_ignore)

    print(f"[Reconciler] workspace : {workspace}")
    print(f"[Reconciler] stored    : {result['stored_count']} code nodes")
    print(f"[Reconciler] parsed    : {result['parsed_count']} code nodes")
    print(f"[Reconciler] stale     : {len(result['stale'])} rows the DB holds but no current "
          f"file produces (duplicate/obsolete hashes, or deleted files)")
    print(f"[Reconciler] missing   : {len(result['missing'])} nodes current files produce but "
          f"the DB lacks (ingestion gap)")

    for h, path in list(result['stale'].items())[:10]:
        exists = "file-gone" if not os.path.exists(path) else "superseded"
        print(f"           - {h[:16]}  {exists}  {path}")
    if len(result['stale']) > 10:
        print(f"           ... and {len(result['stale']) - 10} more")

    if not result['consistent']:
        print(f"[Reconciler] INCONSISTENT INPUT — stored {result['stored_count']} != parsed "
              f"{result['parsed_count']}; refusing a verdict (this indicates a guard bug, "
              f"not a graph bug).")
        return 2
    if result['stale'] or result['missing']:
        print("[Reconciler] UNRECONCILED — the graph does not match a fresh parse.")
        return 1
    print("[Reconciler] RECONCILED — the graph matches a fresh parse.")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())