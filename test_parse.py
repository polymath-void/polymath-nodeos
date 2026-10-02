import ast
import copy

def test_parse(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        source = f.read()
    tree = ast.parse(source)
    nodes = []
    for node in ast.walk(tree):
        node_name = None
        node_type = None
        
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            node_name = node.name
            node_type = type(node).__name__
        elif isinstance(node, ast.arg):
            node_name = node.arg
            node_type = "Parameter"
        elif isinstance(node, ast.Assign):
            if node.targets and isinstance(node.targets[0], ast.Name):
                node_name = node.targets[0].id
                node_type = "Variable"
            else:
                continue
        else:
            continue

        lineno = getattr(node, 'lineno', 0)
        nodes.append(f"[{node_type}] {node_name} at line {lineno}")
    return nodes

print(test_parse('polymath_nodeos/scripts/qa_engine.py')[:20])
