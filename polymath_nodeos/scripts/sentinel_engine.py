import sqlite3
import argparse

class SentinelEngine:
    def __init__(self, db_path):
        self.db_path = db_path
        
    def mark_brittle(self, function_name, score=1.0):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT node_id FROM nodes WHERE name = ?", (function_name,))
            row = cursor.fetchone()
            if row:
                node_id = row[0]
                conn.execute('''
                    INSERT INTO node_brittleness (node_id, score) 
                    VALUES (?, ?)
                    ON CONFLICT(node_id) DO UPDATE SET score = score + excluded.score
                ''', (node_id, score))
                print(f"[Sentinel] Marked {function_name} as brittle (score incremented).")
            else:
                print(f"[Sentinel] Could not find node {function_name}.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NodeOS Sentinel: Track code brittleness.")
    parser.add_argument("--db", required=True, help="Path to agy_nodeos.db")
    parser.add_argument("--func", required=True, help="Function name")
    args = parser.parse_args()
    
    engine = SentinelEngine(db_path=args.db)
    engine.mark_brittle(args.func)
