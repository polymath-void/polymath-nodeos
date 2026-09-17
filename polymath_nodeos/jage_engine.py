import ast
import hashlib
import json
import os
import re
import sys
import copy

class JageASTEngine:
    """
    POLYGLOT AST CODE MANAGER (Fallback Implementation)
    Because Android Termux environments fail to link `tree-sitter` ABI C-extensions securely,
    this implementation relies on Python's built-in `ast` for Python files, and uses standard regex
    chunking for JS/TS as a polyglot fallback.
    """
    def __init__(self, db_path=".jsagent"):
        self.db_path = db_path
        self.schema_dir = os.path.join(self.db_path, "schema")
        os.makedirs(self.schema_dir, exist_ok=True)

    def hash_content(self, content):
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    def parse_file(self, filepath):
        if not os.path.exists(filepath):
            return None

        if filepath.endswith('.py'):
            return self._parse_python(filepath)
        elif filepath.endswith(('.js', '.ts')):
            return self._parse_javascript(filepath)
        return []

    def _parse_python(self, filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            source = f.read()

        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            print(f"[Jage] Syntax error in {filepath}: {e}")
            return None

        nodes = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                node_source = ast.get_source_segment(source, node)
                node_hash = self.hash_content(node_source)
                
                # AST Deep Traversal: Extract all function calls for Dependency Edges
                calls = []
                for sub_node in ast.walk(node):
                    if isinstance(sub_node, ast.Call):
                        if isinstance(sub_node.func, ast.Name):
                            calls.append(sub_node.func.id)
                        elif isinstance(sub_node.func, ast.Attribute):
                            calls.append(sub_node.func.attr)
                            
                node_copy = copy.deepcopy(node)
                if hasattr(node_copy, 'body'):
                    node_copy.body = [ast.Pass()]
                try:
                    skeleton = ast.unparse(node_copy)
                except Exception:
                    skeleton = f"# signature for {node.name}\npass"

                node_data = {
                    "type": type(node).__name__,
                    "name": node.name,
                    "hash": node_hash,
                    "file": filepath,
                    "line_number": node.lineno,
                    "calls": list(set(calls))
                }
                nodes.append(node_data)
                self._store_schema(node_hash, node_data, node_source, skeleton)
        return nodes

    def _parse_javascript(self, filepath):
        """A Stack-Based Bracket Matcher fallback for Polyglot JS/TS parsing."""
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        nodes = []
        pattern = re.compile(r'(?:export\s+)?(?:async\s+)?(?:function|class)\s+([a-zA-Z0-9_]+)[^{]*{')
        
        for match in pattern.finditer(content):
            name = match.group(1)
            start_idx = match.start()
            
            brace_start = content.find('{', start_idx)
            if brace_start == -1: continue
            
            stack = 0
            end_idx = brace_start
            for i in range(brace_start, len(content)):
                if content[i] == '{': stack += 1
                elif content[i] == '}': stack -= 1
                if stack == 0:
                    end_idx = i + 1
                    break
            
            if stack != 0:
                end_idx = len(content)
                
            node_source = content[start_idx:end_idx]
            node_hash = self.hash_content(node_source)
            skeleton = content[start_idx:brace_start].strip() + " { ... }"
            
            calls = []
            call_pattern = re.compile(r'([a-zA-Z0-9_]+)\s*\(')
            for call_match in call_pattern.finditer(node_source):
                call_name = call_match.group(1)
                if call_name not in ['if', 'for', 'while', 'switch', 'catch', 'function']:
                    calls.append(call_name)
                    
            node_data = {
                "type": "JS_Node",
                "name": name,
                "hash": node_hash,
                "file": filepath,
                "line_number": content[:start_idx].count('\n') + 1,
                "calls": list(set(calls))
            }
            nodes.append(node_data)
            self._store_schema(node_hash, node_data, node_source, skeleton)
            
        return nodes

    def _store_schema(self, node_hash, metadata, source, skeleton=None):
        schema_path = os.path.join(self.schema_dir, f"{node_hash}.json")
        data = {
            "metadata": metadata,
            "source": source,
            "skeleton": skeleton if skeleton else source
        }
        with open(schema_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
        print(f"[Jage Polyglot] Mapped {metadata['type']} '{metadata['name']}' -> Hash: {node_hash[:8]}...")

    def purge_file_cache(self, filepath):
        """Purges schema JSONs associated with a deleted file."""
        if not os.path.exists(self.schema_dir):
            return
        print(f"[Jage] Purging schema JSONs for deleted file: {filepath}")
        for filename in os.listdir(self.schema_dir):
            if not filename.endswith('.json'):
                continue
            schema_path = os.path.join(self.schema_dir, filename)
            try:
                with open(schema_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if data.get("metadata", {}).get("file") == filepath:
                    os.remove(schema_path)
            except Exception as e:
                print(f"[Jage] Failed to purge {filename}: {e}")

    def re_stitch(self, node_hash, new_source):
        """
        JAGE RE-STITCHER w/ NATIVE VERIFICATION KERNEL
        Injects a modified JSON child node's source code back into the original parent source file,
        but only after applying shadow-patching and QA validation to prevent corruption.
        """
        schema_path = os.path.join(self.schema_dir, f"{node_hash}.json")
        if not os.path.exists(schema_path):
            return "Error: Hash not found in local DB."
            
        with open(schema_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        original_source = data.get("source", "")
        filepath = data["metadata"]["file"]
        
        if not os.path.exists(filepath):
            return "Error: Target file not found."
            
        with open(filepath, 'r', encoding='utf-8') as f:
            file_content = f.read()
            
        if original_source not in file_content:
            return "Error: Original source block not found. Code drifted."
            
        # 1. Shadow Patching
        updated_content = file_content.replace(original_source, new_source)
        
        # 2. Native QA Verification (Syntax Check)
        if filepath.endswith('.py'):
            try:
                ast.parse(updated_content)
            except SyntaxError as e:
                print(f"[QA Verifier] Rejected corrupted payload for {filepath}: {e}")
                return f"SyntaxError at line {e.lineno}, offset {e.offset}: {e.msg}\nCode rejected by NodeOS Firewall."
        
        # 3. Universal QA Analyzer Integration (Portable)
        # Use a dynamic relative path to ensure cross-platform NodeOS portability
        qa_script = os.path.join(os.getcwd(), '.agents', 'skills', 'qa-analyzer', 'scripts', 'analyzer.py')
        if os.path.exists(qa_script):
            import subprocess
            shadow_path = filepath + ".shadow"
            with open(shadow_path, 'w', encoding='utf-8') as f: f.write(updated_content)
            
            result = subprocess.run([sys.executable, qa_script, shadow_path], capture_output=True, text=True)
            os.remove(shadow_path)
            
            if result.returncode != 0:
                print(f"[QA Verifier] Structural analysis failed for {filepath}.")
                return f"Structural/QA Error:\n{result.stdout}\n{result.stderr}\nCode rejected by NodeOS Firewall."

        # 4. Atomic Commit
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(updated_content)
            
        print(f"[Jage Re-Stitcher] Successfully re-stitched and verified {node_hash[:8]} into {filepath}.")
        return True
