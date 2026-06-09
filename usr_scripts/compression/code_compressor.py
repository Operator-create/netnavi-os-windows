"""Code AST compressor.

Prunes method and function bodies from Python code while preserving imports,
class definitions, method signatures, decorators, and docstrings.
Also provides a basic block-collapsing regex pruner for curly-brace languages (JS/TS, Go, Rust).
"""

import ast
import re

def compress_python_code(code_text: str) -> str:
    """Compress Python code by pruning function and method bodies."""
    try:
        tree = ast.parse(code_text)
    except SyntaxError:
        return code_text

    class CodePruner(ast.NodeTransformer):
        def visit_FunctionDef(self, node):
            # Check if there is a docstring in the body
            new_body = []
            if node.body:
                first = node.body[0]
                if (isinstance(first, ast.Expr) and 
                    isinstance(first.value, ast.Constant) and 
                    isinstance(first.value.value, str)):
                    new_body.append(first)
            
            # Append a placeholder statement
            placeholder = ast.Expr(value=ast.Constant(value="... body collapsed ..."))
            new_body.append(placeholder)
            
            node.body = new_body
            return node

        def visit_AsyncFunctionDef(self, node):
            return self.visit_FunctionDef(node)

    pruned_tree = CodePruner().visit(tree)
    try:
        return ast.unparse(pruned_tree)
    except Exception:
        return code_text


# Regex to match function blocks in JS/TS, Go, Rust:
# E.g. "function foo(...) { ... }" or "func foo(...) { ... }" or "fn foo(...) { ... }"
_BRACE_FUNC_RE = re.compile(
    r"((?:function|func|fn)\s+[a-zA-Z0-9_]+\s*\([^)]*\)\s*(?::\s*[^{]+)?\s*)\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}",
    re.MULTILINE
)

def compress_brace_code(code_text: str) -> str:
    """Prune function bodies in curly-brace languages using regex."""
    def replacer(match):
        header = match.group(1)
        body = match.group(2)
        lines = len(body.splitlines())
        if lines > 3:
            return f"{header}{{ // ... {lines} lines collapsed }}"
        return match.group(0)

    # Apply a few times to handle nested braces (up to 2 levels)
    result = code_text
    for _ in range(2):
        result = _BRACE_FUNC_RE.sub(replacer, result)
    return result


def compress_code_input(code_text: str, filename_hint: str = None) -> tuple[str, bool]:
    """Compress code based on filename hint or syntax detection.

    Returns (compressed_code, was_compressed).
    """
    if not code_text.strip():
        return code_text, False

    # Detection via filename hint
    ext = ""
    if filename_hint:
        _, ext = filename_hint.lower().rsplit(".", 1) if "." in filename_hint else ("", "")

    if ext == "py" or (not ext and "def " in code_text and "class " in code_text):
        # Try Python AST compression
        compressed = compress_python_code(code_text)
        if len(compressed) < len(code_text) * 0.95:
            return compressed, True

    if ext in ("js", "ts", "go", "rs") or (not ext and ("function " in code_text or "func " in code_text or "fn " in code_text)):
        compressed = compress_brace_code(code_text)
        if len(compressed) < len(code_text) * 0.95:
            return compressed, True

    return code_text, False
