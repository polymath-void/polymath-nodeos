# NodeOS Upgrade Plan: Accuracy & Token Optimization

**Goal:** Enhance the Polymath-NodeOS context protocol to provide faster, highly accurate spatial adaptation with significantly reduced token usage during Swarm intents (GhostWriter).

## Phase 1: High-Accuracy JS/TS AST Parser (`jage_engine.py`)
Currently, the fallback JS/TS parser extracts only the first line of a function/class declaration, stripping it of its body and dependency edges. 

*   **Bracket-Matching Stack Parser:** Replace the `line.strip()` extraction with a robust bracket-matching algorithm. Once a declaration is matched via Regex, the engine will use a `{` and `}` stack to accurately extract the *entire* function or class body.
*   **Edge Heuristics:** Implement a secondary Regex pass over the extracted JS/TS body to identify potential function invocations (e.g., `(\w+)\s*\(`).
*   **Result:** JS/TS nodes will be fully populated, allowing them to participate in the physical `edges` table and cluster correctly in the Force-Directed Graph (`nodes_engine.py`).

## Phase 2: "Skeleton" Interfaces for Token Reduction
Currently, `GhostWriterEngine` pulls the complete, raw source code for its K-nearest neighbors, costing massive token overhead for large files.

*   **Skeleton Generation (`jage_engine.py`):** 
    *   *Python:* Use `ast.unparse` (or AST manipulation) to strip out function/class logic, replacing bodies with `pass`, retaining only definitions and docstrings.
    *   *JS/TS:* Retain the declaration line and append `{ ... }`.
*   **Schema Update:** Save this reduced interface as a new `"skeleton"` key alongside the raw `"source"` inside the `.jsagent/schema/<hash>.json` files.
*   **GhostWriter Update (`ghost_writer_engine.py`):** Modify `extract_ast_signatures()` to prioritize injecting the `"skeleton"` into the spatial context payload instead of the full `"source"`.
*   **Result:** The AI receives exact architectural awareness of surrounding nodes but consumes a fraction of the tokens.

## Phase 3: Validation & Restart
*   Run the offline Universal QA Analyzer (`analyzer.py`) over `polymath-nodeos` to ensure bracket and structural integrity.
*   Restart the NodeOS daemon: `pkill -f "nodeos -d" && nohup nodeos -d > daemon.log 2>&1 &`
*   Test spatial generation using: `nodeos -c blast <filepath>`