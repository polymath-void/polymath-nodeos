import sqlite3
import os
import glob
from datetime import datetime

class AGYGraphManager:
    def __init__(self, db_path="agy_nodeos.db"):
        self.db_path = db_path
        self.skills_dir = os.path.expanduser("~/.gemini/config/skills")
        self.rules_dir = os.path.expanduser("~/.gemini/config/rules")
        self._init_db()

    def _init_db(self):
        """Initializes the native SQLite Parent Node database for AGY-NodeOS."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Parent Node Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS nodes (
                node_id TEXT PRIMARY KEY,
                node_type TEXT,
                name TEXT,
                filepath TEXT,
                hash TEXT,
                calls TEXT,
                x_coord REAL DEFAULT 500,
                y_coord REAL DEFAULT 500,
                last_updated TIMESTAMP
            )
        ''')

        # Migrate older databases that predate the calls column. Without it, hydration
        # returns nodes with an empty call list and resolve_edges can never rebuild
        # the dependency graph after a restart.
        columns = {row[1] for row in cursor.execute("PRAGMA table_info(nodes)")}
        if 'calls' not in columns:
            cursor.execute("ALTER TABLE nodes ADD COLUMN calls TEXT")
            print("[AGY-NodeOS] Migrated nodes table: added 'calls' column.")
        
        # Graph Edges (Relationships)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS edges (
                source_id TEXT,
                target_id TEXT,
                relation_type TEXT,
                PRIMARY KEY (source_id, target_id, relation_type)
            )
        ''')
        conn.commit()
        conn.close()

    def purge_file_nodes(self, filepath):
        """Purges all nodes (and their edges) associated with a deleted file."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM nodes WHERE filepath = ?", (filepath,))
        cursor.execute("""
            DELETE FROM edges WHERE 
            source_id NOT IN (SELECT node_id FROM nodes) OR 
            target_id NOT IN (SELECT node_id FROM nodes)
        """)
        
        conn.commit()
        conn.close()
        print(f"[AGY-NodeOS] Purged nodes for {filepath} from SQLite graph.")

    def index_system_nodes(self):
        """Indexes all AGY Built-in Skills and Rules natively as System Nodes."""
        print("[AGY-NodeOS] Indexing System Nodes natively...")
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Map Skills
        skill_files = glob.glob(os.path.join(self.skills_dir, "*", "SKILL.md"))
        for filepath in skill_files:
            skill_name = os.path.basename(os.path.dirname(filepath))
            node_id = f"skill_{skill_name}"
            cursor.execute('''
                INSERT OR REPLACE INTO nodes (node_id, node_type, name, filepath, last_updated)
                VALUES (?, ?, ?, ?, ?)
            ''', (node_id, 'SYSTEM_SKILL', skill_name, filepath, datetime.now()))

        # Map Rules
        rule_files = glob.glob(os.path.join(self.rules_dir, "*.md"))
        for filepath in rule_files:
            rule_name = os.path.basename(filepath).replace(".md", "")
            node_id = f"rule_{rule_name}"
            cursor.execute('''
                INSERT OR REPLACE INTO nodes (node_id, node_type, name, filepath, last_updated)
                VALUES (?, ?, ?, ?, ?)
            ''', (node_id, 'SYSTEM_RULE', rule_name, filepath, datetime.now()))

        conn.commit()
        conn.close()
        print("[AGY-NodeOS] Internal System Node Indexing Complete.")

class InternalSwarmDispatcher:
    """
    NATIVE SWARM MANAGEMENT
    Replaces external third-party neural playgrounds. 
    Manages local sub-agents natively within AGY-NodeOS.
    """
    def __init__(self, graph_manager):
        self.graph = graph_manager
        
    def dispatch_internal_task(self, task_type, payload):
        """
        Dispatches tasks using internal threads/processes, 
        directly utilizing the local SQLite Graph without relying on external ports.
        """
        print(f"[Internal Swarm] Dispatching native {task_type} task. Fetching local graph context...")
        # Logic to launch a local Python process or AGY native subagent
        return {"status": "success", "context_used": "native"}

if __name__ == "__main__":
    manager = AGYGraphManager()
    manager.index_system_nodes()
    
    swarm = InternalSwarmDispatcher(manager)
    swarm.dispatch_internal_task("code_generation", {"target": "calculator"})

# touch
