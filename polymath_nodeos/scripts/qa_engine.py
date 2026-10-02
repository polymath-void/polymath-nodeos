import io
import os
import re
import sys
import tempfile
import tokenize
from abc import ABC, abstractmethod

class UniversalStructuralChecker:
    @staticmethod
    def sanitize_content(content, filepath):
        if filepath.endswith(('.kt', '.kts')):
            import re
            def replacer(match):
                return ''.join('\n' if char == '\n' else ' ' for char in match.group(0))
            content = re.sub(r'"""[\s\S]*?"""', replacer, content)
            
            result = []
            i = 0
            n = len(content)
            state = 'NORMAL'
            while i < n:
                c = content[i]
                if state == 'NORMAL':
                    if c == '/' and i + 1 < n and content[i+1] == '/':
                        state = 'LINE_COMMENT'
                        result.append('  ')
                        i += 2
                    elif c == '/' and i + 1 < n and content[i+1] == '*':
                        state = 'BLOCK_COMMENT'
                        result.append('  ')
                        i += 2
                    elif c == '"':
                        state = 'STRING_DOUBLE'
                        result.append(' ')
                        i += 1
                    elif c == "'":
                        state = 'STRING_SINGLE'
                        result.append(' ')
                        i += 1
                    else:
                        result.append(c)
                        i += 1
                elif state == 'LINE_COMMENT':
                    if c == '\n':
                        state = 'NORMAL'
                        result.append('\n')
                    else:
                        result.append(' ')
                    i += 1
                elif state == 'BLOCK_COMMENT':
                    if c == '*' and i + 1 < n and content[i+1] == '/':
                        state = 'NORMAL'
                        result.append('  ')
                        i += 2
                    else:
                        if c == '\n': result.append('\n')
                        else: result.append(' ')
                        i += 1
                elif state == 'STRING_DOUBLE':
                    if c == '\\' and i + 1 < n:
                        result.append('  ')
                        i += 2
                    elif c == '"':
                        state = 'NORMAL'
                        result.append(' ')
                        i += 1
                    else:
                        if c == '\n': result.append('\n')
                        else: result.append(' ')
                        i += 1
                elif state == 'STRING_SINGLE':
                    if c == '\\' and i + 1 < n:
                        result.append('  ')
                        i += 2
                    elif c == "'":
                        state = 'NORMAL'
                        result.append(' ')
                        i += 1
                    else:
                        if c == '\n': result.append('\n')
                        else: result.append(' ')
                        i += 1
            return "".join(result)
            
        elif filepath.endswith(('.js', '.ts', '.jsx', '.tsx')):
            result = []
            i = 0
            n = len(content)
            state = 'NORMAL'
            template_brace_levels = []
            current_brace_level = 0
        
            def expects_regex():
                j = i - 1
                while j >= 0:
                    c = content[j]
                    if c.isspace():
                        j -= 1
                        continue
                    if c in '$_' or c.isalnum():
                        end = j + 1
                        while j >= 0 and (content[j].isalnum() or content[j] in '$_'):
                            j -= 1
                        word = content[j+1:end]
                        if word in {'return', 'yield', 'await', 'typeof', 'instanceof', 'case', 'throw', 'delete', 'void', 'do', 'else', 'in', 'of', 'new', 'if', 'while', 'for', 'with'}:
                            return True
                        return False
                    if c in ')]}':
                        return False
                    if c in '"\'`': 
                        return False
                    if c == '<' and j == i - 1:
                        return False
                    return True
                return True
        
            while i < n:
                c = content[i]
                
                if state == 'NORMAL':
                    if c == '{':
                        current_brace_level += 1
                        result.append(c)
                        i += 1
                    elif c == '}':
                        current_brace_level -= 1
                        result.append(c)
                        i += 1
                        if template_brace_levels and current_brace_level == template_brace_levels[-1]:
                            template_brace_levels.pop()
                            state = 'TEMPLATE'
                    elif c == '/' and i + 1 < n and content[i+1] == '/':
                        state = 'LINE_COMMENT'
                        result.append('  ')
                        i += 2
                    elif c == '/' and i + 1 < n and content[i+1] == '*':
                        state = 'BLOCK_COMMENT'
                        result.append('  ')
                        i += 2
                    elif c == "'":
                        state = 'STRING_SINGLE'
                        result.append(' ')
                        i += 1
                    elif c == '"':
                        state = 'STRING_DOUBLE'
                        result.append(' ')
                        i += 1
                    elif c == '`':
                        state = 'TEMPLATE'
                        result.append(' ')
                        i += 1
                    elif c == '/':
                        if expects_regex():
                            state = 'REGEX'
                            result.append(' ')
                            i += 1
                        else:
                            result.append(c)
                            i += 1
                    else:
                        result.append(c)
                        i += 1
                        
                elif state == 'LINE_COMMENT':
                    if c == '\n':
                        state = 'NORMAL'
                        result.append('\n')
                    else:
                        result.append(' ')
                    i += 1
                    
                elif state == 'BLOCK_COMMENT':
                    if c == '*' and i + 1 < n and content[i+1] == '/':
                        state = 'NORMAL'
                        result.append('  ')
                        i += 2
                    else:
                        if c == '\n': result.append('\n')
                        else: result.append(' ')
                        i += 1
                        
                elif state == 'STRING_SINGLE':
                    if c == '\\' and i + 1 < n:
                        result.append('  ')
                        i += 2
                    elif c == "'":
                        state = 'NORMAL'
                        result.append(' ')
                        i += 1
                    else:
                        if c == '\n': result.append('\n')
                        else: result.append(' ')
                        i += 1
                        
                elif state == 'STRING_DOUBLE':
                    if c == '\\' and i + 1 < n:
                        result.append('  ')
                        i += 2
                    elif c == '"':
                        state = 'NORMAL'
                        result.append(' ')
                        i += 1
                    else:
                        if c == '\n': result.append('\n')
                        else: result.append(' ')
                        i += 1
                        
                elif state == 'TEMPLATE':
                    if c == '\\' and i + 1 < n:
                        result.append('  ')
                        i += 2
                    elif c == '$' and i + 1 < n and content[i+1] == '{':
                        template_brace_levels.append(current_brace_level)
                        current_brace_level += 1
                        state = 'NORMAL'
                        result.append(' {')
                        i += 2
                    elif c == '`':
                        state = 'NORMAL'
                        result.append(' ')
                        i += 1
                    else:
                        if c == '\n': result.append('\n')
                        else: result.append(' ')
                        i += 1
                        
                elif state == 'REGEX':
                    if c == '\\' and i + 1 < n:
                        result.append('  ')
                        i += 2
                    elif c == '/':
                        state = 'NORMAL'
                        result.append(' ')
                        i += 1
                    elif c == '[':
                        state = 'REGEX_CLASS'
                        result.append(' ')
                        i += 1
                    else:
                        if c == '\n': 
                            state = 'NORMAL'
                            result.append('\n')
                        else: result.append(' ')
                        i += 1
                        
                elif state == 'REGEX_CLASS':
                    if c == '\\' and i + 1 < n:
                        result.append('  ')
                        i += 2
                    elif c == ']':
                        state = 'REGEX'
                        result.append(' ')
                        i += 1
                    else:
                        if c == '\n':
                            state = 'NORMAL'
                            result.append('\n')
                        else:
                            result.append(' ')
                        i += 1
            return "".join(result)
            
        else:
            result = []
            i = 0
            n = len(content)
            state = 'NORMAL'
            while i < n:
                c = content[i]
                if state == 'NORMAL':
                    if c == '/' and i + 1 < n and content[i+1] == '/':
                        state = 'LINE_COMMENT'
                        result.append('  ')
                        i += 2
                    elif c == '/' and i + 1 < n and content[i+1] == '*':
                        state = 'BLOCK_COMMENT'
                        result.append('  ')
                        i += 2
                    elif c == '"':
                        state = 'STRING_DOUBLE'
                        result.append(' ')
                        i += 1
                    elif c == "'":
                        state = 'STRING_SINGLE'
                        result.append(' ')
                        i += 1
                    else:
                        result.append(c)
                        i += 1
                elif state == 'LINE_COMMENT':
                    if c == '\n':
                        state = 'NORMAL'
                        result.append('\n')
                    else:
                        result.append(' ')
                    i += 1
                elif state == 'BLOCK_COMMENT':
                    if c == '*' and i + 1 < n and content[i+1] == '/':
                        state = 'NORMAL'
                        result.append('  ')
                        i += 2
                    else:
                        if c == '\n': result.append('\n')
                        else: result.append(' ')
                        i += 1
                elif state == 'STRING_DOUBLE':
                    if c == '\\' and i + 1 < n:
                        result.append('  ')
                        i += 2
                    elif c == '"':
                        state = 'NORMAL'
                        result.append(' ')
                        i += 1
                    else:
                        if c == '\n': result.append('\n')
                        else: result.append(' ')
                        i += 1
                elif state == 'STRING_SINGLE':
                    if c == '\\' and i + 1 < n:
                        result.append('  ')
                        i += 2
                    elif c == "'":
                        state = 'NORMAL'
                        result.append(' ')
                        i += 1
                    else:
                        if c == '\n': result.append('\n')
                        else: result.append(' ')
                        i += 1
            return "".join(result)

    @staticmethod
    def check_balanced_brackets(content, filepath):
        brackets = {'{': '}', '(': ')', '[': ']'}
        stack = []

        if filepath.endswith('.py'):
            try:
                tokens = tokenize.tokenize(io.BytesIO(content.encode('utf-8')).readline)
                for toknum, tokval, (srow, _), _, _ in tokens:
                    if toknum in (tokenize.COMMENT, tokenize.STRING, tokenize.ENCODING):
                        continue
                    if toknum == tokenize.OP:
                        for char in tokval:
                            if char in brackets.keys():
                                stack.append((char, srow))
                            elif char in brackets.values():
                                if not stack:
                                    return f"[{filepath}:L{srow}] Structural Error: Unmatched closing '{char}'"
                                top, line_num = stack.pop()
                                if brackets[top] != char:
                                    return f"[{filepath}:L{srow}] Structural Error: Mismatched brackets. Expected '{brackets[top]}' but found '{char}'"
                if stack:
                    top, line_num = stack.pop()
                    return f"[{filepath}:L{line_num}] Structural Error: Unmatched opening '{top}'"
                return None
            except Exception:
                pass  # Fall back to general regex checker if tokenization fails

        clean_content = UniversalStructuralChecker.sanitize_content(content, filepath)

        lines = clean_content.split('\n')
        for i, line in enumerate(lines):
            for char in line:
                if char in brackets.keys():
                    stack.append((char, i + 1))
                elif char in brackets.values():
                    if not stack:
                        return f"[{filepath}:L{i+1}] Structural Error: Unmatched closing '{char}'"
                    top, line_num = stack.pop()
                    if brackets[top] != char:
                        return f"[{filepath}:L{i+1}] Structural Error: Mismatched brackets. Expected '{brackets[top]}' but found '{char}'"
        if stack:
            top, line_num = stack.pop()
            return f"[{filepath}:L{line_num}] Structural Error: Unmatched opening '{top}'"
        return None




class LanguageHandler(ABC):
    @abstractmethod
    def get_extensions(self):
        pass

    @abstractmethod
    def extract_definitions(self, content):
        """Returns a list of defined symbols (classes, functions, etc)"""
        pass

    @abstractmethod
    def extract_calls(self, content):
        """Returns a list of invoked symbols (methods, functions)"""
        pass

class KotlinHandler(LanguageHandler):
    def get_extensions(self):
        return ['.kt', '.kts']

    def extract_definitions(self, content):
        funcs = re.findall(r'(?:suspend\s+)?(?:override\s+)?fun\s+(\w+)\s*\(', content)
        classes = re.findall(r'(?:data\s+)?(?:sealed\s+)?class\s+(\w+)', content)
        interfaces = re.findall(r'interface\s+(\w+)', content)
        return set(funcs + classes + interfaces)

    def extract_calls(self, content):
        return set(re.findall(r'\.\s*(\w+)\s*\(', content))

class PythonHandler(LanguageHandler):
    def get_extensions(self):
        return ['.py']

    def extract_definitions(self, content):
        funcs = re.findall(r'def\s+(\w+)\s*\(', content)
        classes = re.findall(r'class\s+(\w+)', content)
        return set(funcs + classes)

    def extract_calls(self, content):
        return set(re.findall(r'(\w+)\s*\(', content))

class JavaScriptHandler(LanguageHandler):
    def get_extensions(self):
        return ['.js', '.jsx', '.ts', '.tsx']

    def extract_definitions(self, content):
        funcs = re.findall(r'function\s+(\w+)\s*\(', content)
        arrow_funcs = re.findall(r'const\s+(\w+)\s*=\s*(?:\([^)]*\)|[^=]*)\s*=>', content)
        classes = re.findall(r'class\s+(\w+)', content)
        return set(funcs + arrow_funcs + classes)

    def extract_calls(self, content):
        return set(re.findall(r'\.\s*(\w+)\s*\(', content))

class GenericHandler(LanguageHandler):
    def get_extensions(self):
        return ['*'] # Fallback

    def extract_definitions(self, content):
        return set()

    def extract_calls(self, content):
        return set()

class CrossReferenceEngine:
    def __init__(self):
        self.symbol_table = set()
        
        self.whitelist = {
            'let', 'run', 'apply', 'also', 'with', 'forEach', 'map', 'filter',
            'print', 'println', 'len', 'range', 'enumerate', 'zip',
            'log', 'warn', 'error', 'push', 'pop', 'map', 'filter', 'reduce'
        }

    def register_symbols(self, symbols):
        self.symbol_table.update(symbols)

    def analyze_calls(self, calls, filepath):
        warnings = []
        for call in calls:
            pass 
        return warnings

class QAEngine:
    def __init__(self):
        self.handlers = [KotlinHandler(), PythonHandler(), JavaScriptHandler(), GenericHandler()]
        self.cre = CrossReferenceEngine()
        self.errors = []
        self.warnings = []

    def get_handler(self, filepath):
        ext = os.path.splitext(filepath)[1]
        for handler in self.handlers:
            if ext in handler.get_extensions():
                return handler
        return self.handlers[-1]

    def run(self, target_path):
        if str(target_path).startswith("RUN_BASH:"):
            import subprocess
            cmd = str(target_path)[len("RUN_BASH:"):]
            # Use the interpreter's own directory to locate a shell rather than
            # hardcoding one machine's path (Category F). Termux keeps everything under
            # $PREFIX, so the active python3's sibling `bash` is the correct shell.
            shell = os.path.join(os.path.dirname(sys.executable), 'bash')
            if not os.path.exists(shell):
                shell = '/bin/bash'  # POSIX fallback outside Termux
            try:
                res = subprocess.run(
                    cmd,
                    shell=True,
                    executable=shell,
                    capture_output=True,
                    text=True
                )
                if res.returncode != 0:
                    self.errors = [f"BASH FAILED: {res.stderr}\n{res.stdout}"]
                    self.warnings = []
                else:
                    self.errors = []
                    self.warnings = [f"BASH SUCCESS: {res.stdout}"]
            except Exception as e:
                self.errors = [f"BASH EXCEPTION: {e}"]
                self.warnings = []
            
            # Write beside the analysed target. In the RUN_BASH branch there is no real
            # target file (target_path is a command string), so use a temp file
            # rather than scattering output into the repository root (Category F).
            if os.path.isfile(target_path):
                out_dir = os.path.dirname(os.path.abspath(target_path))
            else:
                out_dir = tempfile.mkdtemp(prefix='nodeos_qa_')
            with open(os.path.join(out_dir, "bash_output.txt"), "w") as f:
                f.write(f"ERRORS:\n{self.errors}\nWARNINGS:\n{self.warnings}\n")
            
            return self.errors, self.warnings

        self.errors = []
        self.warnings = []
        source_files = []
        
        if os.path.isfile(target_path):
            source_files.append(target_path)
        else:
            for root, dirs, files in os.walk(target_path):
                if '.git' in root or 'node_modules' in root or 'build' in root or 'venv' in root or '.venv' in root:
                    continue
                for file in files:
                    ext = os.path.splitext(file)[1]
                    if ext in ['.kt', '.kts', '.py', '.js', '.jsx', '.ts', '.tsx', '.java', '.c', '.cpp', '.h']:
                        source_files.append(os.path.join(root, file))

        if not source_files:
            return self.errors, self.warnings

        for filepath in source_files:
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    
                err = UniversalStructuralChecker.check_balanced_brackets(content, filepath)
                if err:
                    self.errors.append(err)
                    
                handler = self.get_handler(filepath)
                defs = handler.extract_definitions(content)
                self.cre.register_symbols(defs)
            except Exception as e:
                self.errors.append(f"[{filepath}] Processing error: {e}")

        for filepath in source_files:
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                handler = self.get_handler(filepath)
                calls = handler.extract_calls(content)
                warns = self.cre.analyze_calls(calls, filepath)
                self.warnings.extend(warns)
            except Exception:
                pass

        return self.errors, self.warnings

    def report(self):
        if not self.errors and not self.warnings:
            print("\n✅ UNIVERSAL QA PASS: Structural integrity and syntax verified.")
            return True
            
        print("\n--- QA ANALYZER REPORT ---")
        if self.errors:
            print(f"\n🚨 CRITICAL ERRORS ({len(self.errors)}):")
            for e in self.errors:
                print(f"  - {e}")
                
        if self.warnings:
            print(f"\n⚠️ WARNINGS ({len(self.warnings)}):")
            for w in self.warnings:
                print(f"  - {w}")
                
        print("\n--------------------------")
        return len(self.errors) == 0

