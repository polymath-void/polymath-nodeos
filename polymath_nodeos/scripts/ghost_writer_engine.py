import os
import json
import sqlite3
import logging
from typing import List, Dict, Optional, Tuple

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("GhostWriterEngine")

class GhostWriterEngine:
    """
    Advanced Spatial Context Ghost Writing Engine.
    Leverages physical coordinates to resolve contextual dependencies.
    """
    def __init__(self, workspace_root: str, db_name: str = 'agy_nodeos.db'):
        self.workspace_root = workspace_root
        self.db_path = os.path.join(workspace_root, db_name) if not os.path.isabs(db_name) else db_name

    def calculate_centroid(self, target_filepath: str) -> Optional[Tuple[float, float]]:
        """Calculates the center of mass (centroid) of the target file's AST nodes."""
        logger.info(f"Calculating spatial centroid for {target_filepath}")
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT AVG(x_coord), AVG(y_coord) FROM nodes WHERE filepath = ?", 
                    (target_filepath,)
                )
                row = cursor.fetchone()
                
                if row and row[0] is not None and row[1] is not None:
                    return float(row[0]), float(row[1])
        except sqlite3.Error as e:
            logger.error(f"Database error during centroid calculation: {e}")
        
        return None

    def find_nearest_neighbors(self, cx: float, cy: float, target_filepath: str, k: int = 10) -> List[Tuple[str, str, str]]:
        """Queries the physics engine DB for the K-nearest physical neighbors using squared distance."""
        logger.info(f"Querying top {k} physical neighbors from ({cx:.2f}, {cy:.2f})")
        neighbors = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # Optimized Euclidean squared-distance query
                cursor.execute("""
                    SELECT node_id, filepath, name, 
                           ((x_coord - ?)*(x_coord - ?) + (y_coord - ?)*(y_coord - ?)) AS dist 
                    FROM nodes 
                    WHERE filepath != ? 
                    ORDER BY dist ASC 
                    LIMIT ?
                """, (cx, cx, cy, cy, target_filepath, k))
                
                rows = cursor.fetchall()
                for row in rows:
                    neighbors.append((row[0], row[1], row[2]))
        except sqlite3.Error as e:
            logger.error(f"Database error during neighbor resolution: {e}")
            
        return neighbors

    def extract_ast_signatures(self, neighbors: List[Tuple[str, str, str]]) -> List[Dict[str, str]]:
        """Extracts AST signatures from .jsagent/schema files for the resolved neighbors."""
        spatial_context = []
        for node_id, filepath, name in neighbors:
            schema_path = os.path.join(self.workspace_root, '.jsagent', 'schema', f"{node_id}.json")
            signature = ""
            
            if os.path.exists(schema_path):
                try:
                    with open(schema_path, 'r', encoding='utf-8') as f:
                        schema_data = json.load(f)
                        signature = schema_data.get('skeleton', schema_data.get('source', ''))
                except (json.JSONDecodeError, IOError) as e:
                    logger.warning(f"Failed to read AST schema for node {node_id}: {e}")
            else:
                logger.debug(f"Schema not found for node {node_id} at {schema_path}")
                
            spatial_context.append({
                "node_name": name,
                "filepath": filepath,
                "signature": signature
            })
            
        return spatial_context

    def emit_workflow_intent(self, target_filepath: str, spatial_context: List[Dict[str, str]]) -> bool:
        """Bundles the context payload and drops it into workflow.json for the NodeOS daemon."""
        logger.info(f"Bundling {len(spatial_context)} contextual signatures into workflow intent.")
        workflow_payload = {
            "type": "JSON_Task",
            "status": "pending",
            "action": "ghost_write",
            "target_file": target_filepath,
            "spatial_context": spatial_context
        }
        
        workflow_path = os.path.join(self.workspace_root, 'workflow.json')
        try:
            with open(workflow_path, 'w', encoding='utf-8') as f:
                json.dump(workflow_payload, f, indent=4)
            logger.info("Successfully dropped intent into workflow.json")
            return True
        except IOError as e:
            logger.error(f"Failed to emit workflow intent: {e}")
            return False

    def execute_pipeline(self, target_filepath: str) -> bool:
        """Executes the full Ghost Writer pipeline."""
        centroid = self.calculate_centroid(target_filepath)
        if not centroid:
            logger.warning("Aborting pipeline: Centroid could not be calculated.")
            return False
            
        cx, cy = centroid
        neighbors = self.find_nearest_neighbors(cx, cy, target_filepath)
        
        if not neighbors:
            logger.warning("No spatial neighbors found for context.")
        
        spatial_context = self.extract_ast_signatures(neighbors)
        return self.emit_workflow_intent(target_filepath, spatial_context)

if __name__ == "__main__":
    import sys
    import argparse

    parser = argparse.ArgumentParser(description="Spatial Context Ghost Writer Engine")
    parser.add_argument("target_file", help="The newly created file to ghost write")
    parser.add_argument("--workspace", default=os.getcwd(), help="Root directory of the NodeOS workspace")
    args = parser.parse_args()

    engine = GhostWriterEngine(workspace_root=args.workspace)
    engine.execute_pipeline(args.target_file)
