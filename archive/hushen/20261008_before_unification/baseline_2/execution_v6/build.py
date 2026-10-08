"""Reproducibly build a standalone platform file from user-uploaded v5."""
from pathlib import Path
import ast
import hashlib
import json

HERE = Path(__file__).resolve().parent
ENTRY = HERE / 'supermind_baseline2_execution_v6_minute.py'

def main():
    source = (HERE / 'source_v5.py').read_text(encoding='utf-8-sig')
    replacement = (HERE / 'execution_functions.py').read_text(encoding='utf-8')
    tree = ast.parse(replacement)
    parts = {node.name: ast.get_source_segment(replacement, node)
             for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    lines = source.splitlines(keepends=True)
    for node in reversed(ast.parse(source).body):
        if isinstance(node, ast.FunctionDef) and node.name in parts:
            lines[node.lineno - 1:node.end_lineno] = [parts.pop(node.name) + '\n']
    text = ''.join(lines)
    text = text.replace("VERSION = '2026-10-03-D11-fast-v5'", "VERSION = '2026-10-08-baseline2-execution-v6'\nEXEC_END = 1000\nREPRICE_MINUTES = 5\nMAX_ATTEMPTS = 6\nMAX_CHASE = 0.01")
    text = text.replace('SuperMind stock DAILY strategy.', 'SuperMind stock MINUTE execution; daily signals.')
    text += '\n\n' + '\n\n'.join(parts.values()) + '\n'
    ast.parse(text)
    ENTRY.write_text(text, encoding='utf-8')
    manifest = dict(source_sha256=hashlib.sha256((HERE/'source_v5.py').read_bytes()).hexdigest(),
                    platform_sha256=hashlib.sha256(ENTRY.read_bytes()).hexdigest(),
                    note='Original factors unchanged. Minute execution variant, not old return reproduction.')
    (HERE/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(ENTRY)

if __name__ == '__main__':
    main()
