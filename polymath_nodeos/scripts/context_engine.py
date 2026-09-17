import os
import re
import sqlite3
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ContextEngine")

class ContextEngine:
    """
    Built-in reasoning system for Context Storing Sub-Parent Node.
    Parses, deduplicates, and syncs context.md to the NodeOS SQLite Graph.
    """
    def __init__(self, db_path='agy_nodeos.db'):
        self.db_path = db_path

    def parse_and_deduplicate(self, filepath):
        states = {}
        entities = {}
        memories = []

        if not os.path.exists(filepath):
            return states, entities, memories

        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        current_section = None
        
        # Matches "- [Key]: Value" or "- [Key] Value"
        kv_pattern = re.compile(r'^\s*-\s*\[(.*?)\]:?\s*(.*)')

        for line in lines:
            stripped = line.strip()
            if stripped.startswith('## 1. Task State'):
                current_section = 'state'
            elif stripped.startswith('## 2. Discovered Entities'):
                current_section = 'entities'
            elif stripped.startswith('## 3. Working Memory'):
                current_section = 'memory'
            elif stripped.startswith('##'):
                current_section = 'other'
            elif stripped.startswith('- '):
                match = kv_pattern.match(stripped)
                if current_section == 'state' and match:
                    states[match.group(1).strip()] = match.group(2).strip()
                elif current_section == 'entities' and match:
                    # Deduplication happens automatically by overwriting dict keys
                    entities[match.group(1).strip()] = match.group(2).strip()
                elif current_section == 'memory':
                    memories.append(stripped[2:].strip())

        # Keep only the last 15 memories for sliding window
        memories = memories[-15:]
        
        return states, entities, memories

    def process_and_sync(self, filepath):
        logger.info(f"Processing context file: {filepath}")
        states, entities, memories = self.parse_and_deduplicate(filepath)

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 1. Purge stale context child nodes to prepare for clean rewrite
                cursor.execute("DELETE FROM nodes WHERE node_type IN ('CONTEXT_ENTITY', 'CONTEXT_STATE', 'CONTEXT_MEMORY')")
                cursor.execute("DELETE FROM edges WHERE relation_type = 'HAS_CONTEXT'")
                
                # 2. Upsert Root Node
                cursor.execute('''
                    INSERT OR REPLACE INTO nodes (node_id, node_type, name, filepath, last_updated)
                    VALUES ('ctx_root', 'CONTEXT_ROOT', 'Agent Context', ?, CURRENT_TIMESTAMP)
                ''', (os.path.basename(filepath),))
                
                # 3. Insert Deduplicated Entities
                for entity_name, desc in entities.items():
                    node_id = f"ctx_ent_{hash(entity_name)}"
                    cursor.execute('''
                        INSERT OR REPLACE INTO nodes (node_id, node_type, name, hash, last_updated)
                        VALUES (?, 'CONTEXT_ENTITY', ?, ?, CURRENT_TIMESTAMP)
                    ''', (node_id, entity_name, desc))
                    
                    cursor.execute('''
                        INSERT OR REPLACE INTO edges (source_id, target_id, relation_type)
                        VALUES ('ctx_root', ?, 'HAS_CONTEXT')
                    ''', (node_id,))

                # 4. Insert Task States
                for state_key, state_val in states.items():
                    node_id = f"ctx_state_{hash(state_key)}"
                    cursor.execute('''
                        INSERT OR REPLACE INTO nodes (node_id, node_type, name, hash, last_updated)
                        VALUES (?, 'CONTEXT_STATE', ?, ?, CURRENT_TIMESTAMP)
                    ''', (node_id, state_key, state_val))
                    
                    cursor.execute('''
                        INSERT OR REPLACE INTO edges (source_id, target_id, relation_type)
                        VALUES ('ctx_root', ?, 'HAS_CONTEXT')
                    ''', (node_id,))

                conn.commit()
                logger.info(f"Successfully synced {len(entities)} entities and {len(states)} states to SQLite.")
        except sqlite3.Error as e:
            logger.error(f"SQLite error during context sync: {e}")
