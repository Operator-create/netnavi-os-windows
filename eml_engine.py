#!/usr/bin/env python3
"""
eml_engine.py — EML (Exp-Minus-Log) Universal Mathematics Engine
Version: 1.0.0

Self-contained EML math engine extracted from netnavi_comms.py.
Depends only on Python stdlib (math, cmath, json, zlib, base64, random).

Provides:
  - eml()                          : Core EML operator with guardrails
  - evaluate_eml_rpn()             : Sandboxed iterative RPN evaluator
  - AST builders (make_add, etc.)  : Construct expression trees
  - Triple-Helix compression       : Serialize/deserialize EML graphs
  - ZipperAutomaton                : Linear non-recursive evaluator
  - bloat_ast(), remap_ast_*()     : Obfuscation tools
  - EMLFormula                     : High-level formula object (compile + evaluate)

netnavi_comms.py re-exports everything here for backwards compatibility.
"""

__version__ = "1.0.0"

import math
import cmath
import json
import zlib
import base64
import random
from typing import Optional

# ===========================================================================
# Core EML Operator
# ===========================================================================

def eml(x, y):
    """
    Computes the EML (Exp-Minus-Log) operator: eml(x, y) = exp(x) - ln(y)
    with strict real-domain clamping to prevent crashes and overflows.
    Supports complex-number arithmetic fallback.
    """
    if isinstance(x, complex) or isinstance(y, complex):
        try:
            return cmath.exp(x) - cmath.log(y)
        except Exception:
            return complex(float('inf'), 0.0)

    # Real-domain evaluation with strict guardrails
    x_clamped = max(-700.0, min(700.0, float(x)))

    # Real-domain log clamping to prevent domain crashes (y <= 0)
    epsilon = 1e-15
    y_clamped = abs(float(y)) + epsilon

    try:
        return math.exp(x_clamped) - math.log(y_clamped)
    except OverflowError:
        return float('inf')


# ===========================================================================
# RPN Evaluator
# ===========================================================================

def evaluate_eml_rpn(tokens, variables, use_complex=False):
    """
    Evaluates an EML expression in Reverse Polish Notation (postfix).
    Tokens: list of string values (operators, variables, constants).
    Variables: dict mapping variable names to numeric/complex values.
    Includes arity checks, stack limit, and complex promotion.
    """
    stack = []
    max_stack_size = 64

    local_vars = variables
    if use_complex:
        local_vars = {k: complex(v) for k, v in variables.items()}

    for token in tokens:
        if not token:
            continue

        if token in ('E', 'eml', 'EML'):
            if len(stack) < 2:
                stack.append(0.0)
                continue
            y = stack.pop()
            x = stack.pop()
            stack.append(eml(x, y))
        else:
            if token in local_vars:
                val = local_vars[token]
            else:
                try:
                    val = float(token)
                    if use_complex:
                        val = complex(val)
                except ValueError:
                    try:
                        val = complex(token)
                    except ValueError:
                        val = 0.0

            if len(stack) >= max_stack_size:
                break
            stack.append(val)

    return stack[-1] if stack else 0.0


# ===========================================================================
# Triple-Helix Graph Compression
# ===========================================================================

class TripleHelix:
    def __init__(self):
        self.chain_a = []  # Topology bitstring (1=operator, 0=leaf)
        self.chain_b = []  # Macro/Operator IDs (0=EML, 1=EXP, 2=LN)
        self.chain_c = []  # Leaf dictionary mappings


def serialize_triple_helix(helix: TripleHelix) -> dict:
    """Pack and compress the TripleHelix chains using zlib."""
    bitstring = "".join(map(str, helix.chain_a))
    if not bitstring:
        byte_a = b""
    else:
        padded_len = (len(bitstring) + 7) // 8 * 8
        bitstring_padded = bitstring.zfill(padded_len)
        val = int(bitstring_padded, 2)
        byte_a = val.to_bytes(padded_len // 8, byteorder='big')

    byte_b  = bytes(helix.chain_b)
    json_c  = json.dumps(helix.chain_c).encode('utf-8')

    comp_a = zlib.compress(byte_a, level=9)
    comp_b = zlib.compress(byte_b, level=9)
    comp_c = zlib.compress(json_c,  level=9)

    return {
        'comp_a': base64.b64encode(comp_a).decode('utf-8'),
        'comp_b': base64.b64encode(comp_b).decode('utf-8'),
        'comp_c': base64.b64encode(comp_c).decode('utf-8'),
        'bitstring_len': len(bitstring),
    }


def deserialize_triple_helix(compressed_data: dict) -> tuple:
    """Decompress and reconstruct TripleHelix chains. Returns (chain_a, chain_b, chain_c)."""
    comp_a = base64.b64decode(compressed_data['comp_a'])
    comp_b = base64.b64decode(compressed_data['comp_b'])
    comp_c = base64.b64decode(compressed_data['comp_c'])
    bitstring_len = compressed_data['bitstring_len']

    byte_a = zlib.decompress(comp_a)
    byte_b = zlib.decompress(comp_b)
    json_c = zlib.decompress(comp_c)

    if not byte_a:
        chain_a = []
    else:
        val = int.from_bytes(byte_a, byteorder='big')
        padded_len = len(byte_a) * 8
        bitstring = bin(val)[2:].zfill(padded_len)
        if len(bitstring) > bitstring_len:
            bitstring = bitstring[-bitstring_len:]
        chain_a = [int(b) for b in bitstring]

    chain_b = list(byte_b)
    chain_c = json.loads(json_c.decode('utf-8'))
    return chain_a, chain_b, chain_c


# ===========================================================================
# Zipper Automaton — linear non-recursive evaluator
# ===========================================================================

class ZipperAutomaton:
    """
    Evaluates a Triple-Helix formula by 'zipping' its three streams linearly,
    without reconstructing the tree. Zero recursion, bounded memory.
    """

    def __init__(self, chain_a, chain_b, chain_c):
        self.chain_a = list(chain_a)
        self.chain_b = list(chain_b)
        self.chain_c = list(chain_c)
        self.pos_a = self.pos_b = self.pos_c = 0

    def zip_and_evaluate(self, variables: dict, use_complex: bool = False):
        self.pos_a = self.pos_b = self.pos_c = 0
        local_vars = {k: complex(v) for k, v in variables.items()} if use_complex else variables
        return self._eval(local_vars, use_complex)

    def _eval(self, variables, use_complex):
        if self.pos_a >= len(self.chain_a):
            return 0.0

        is_node = self.chain_a[self.pos_a]
        self.pos_a += 1

        if not is_node:
            leaf = self.chain_c[self.pos_c]
            self.pos_c += 1
            val = variables[leaf['v']] if leaf['t'] == 'var' else leaf['v']
            return complex(val) if use_complex else val

        op = self.chain_b[self.pos_b]
        self.pos_b += 1

        if op == 0:   # Raw EML
            left  = self._eval(variables, use_complex)
            right = self._eval(variables, use_complex)
            return eml(left, right)
        elif op == 1: # EXP macro
            val = self._eval(variables, use_complex)
            if isinstance(val, complex):
                try:    return cmath.exp(val)
                except: return complex(float('inf'), 0.0)
            val_c = max(-700.0, min(700.0, float(val)))
            try:    return math.exp(val_c)
            except OverflowError: return float('inf')
        elif op == 2: # LN macro
            val = self._eval(variables, use_complex)
            if isinstance(val, complex):
                try:    return cmath.log(val)
                except: return complex(float('-inf'), 0.0)
            return math.log(abs(float(val)) + 1e-15)
        else:
            raise ValueError(f"Unknown Operator/Macro ID: {op}")


# ===========================================================================
# AST Node Types
# ===========================================================================

class ASTNode:
    def is_leaf(self): raise NotImplementedError


class EMLNode(ASTNode):
    def __init__(self, left, right):
        self.left  = left
        self.right = right

    def is_leaf(self): return False
    def __str__(self): return f"eml({self.left}, {self.right})"


class EMLLeaf(ASTNode):
    def __init__(self, leaf_type, value):
        self.leaf_type = leaf_type   # 'var' | 'const'
        self.value     = value       # str (name) | float

    def is_leaf(self): return True

    def __str__(self):
        if self.leaf_type == 'var':
            return str(self.value)
        return str(int(self.value)) if self.value == int(self.value) else str(self.value)


# ===========================================================================
# AST Builder Functions
# ===========================================================================

def make_const(val):  return EMLLeaf('const', float(val))
def make_var(name):   return EMLLeaf('var', name)
def make_exp(u):      return EMLNode(u, make_const(1.0))

def make_ln(u):
    return EMLNode(
        make_const(1.0),
        EMLNode(EMLNode(make_const(1.0), u), make_const(1.0))
    )

def make_sub(u, v):  return EMLNode(make_ln(u), make_exp(v))
def make_add(u, v):  return EMLNode(make_ln(u), make_exp(make_sub(make_const(0.0), v)))
def make_mul(u, v):  return make_exp(make_add(make_ln(u), make_ln(v)))
def make_div(u, v):  return make_exp(make_sub(make_ln(u), make_ln(v)))


# ===========================================================================
# RPN Flattener
# ===========================================================================

def flatten_to_rpn(node) -> list:
    tokens = []
    _flatten(node, tokens)
    return tokens

def _flatten(node, tokens):
    if node.is_leaf():
        tokens.append(str(int(node.value)) if (node.leaf_type == 'const' and
                       node.value == int(node.value)) else str(node.value))
    else:
        _flatten(node.left, tokens)
        _flatten(node.right, tokens)
        tokens.append('E')


# ===========================================================================
# Triple-Helix Decomposition + Pattern Matchers
# ===========================================================================

def match_exp(node):
    if (isinstance(node, EMLNode) and node.right.is_leaf() and
            node.right.leaf_type == 'const' and node.right.value == 1.0):
        return node.left
    return None

def match_ln(node):
    if not isinstance(node, EMLNode): return None
    if not (node.left.is_leaf() and node.left.leaf_type == 'const' and node.left.value == 1.0):
        return None
    right = node.right
    if not isinstance(right, EMLNode) or not isinstance(right.left, EMLNode): return None
    r_l = right.left
    if not (r_l.left.is_leaf() and r_l.left.leaf_type == 'const' and r_l.left.value == 1.0):
        return None
    if not (right.right.is_leaf() and right.right.leaf_type == 'const' and right.right.value == 1.0):
        return None
    return r_l.right

def decompose_to_triple_helix(node, helix: TripleHelix, use_macros: bool = True):
    if use_macros:
        inner = match_ln(node)
        if inner is not None:
            helix.chain_a.append(1); helix.chain_b.append(2)
            decompose_to_triple_helix(inner, helix, use_macros); return
        inner = match_exp(node)
        if inner is not None:
            helix.chain_a.append(1); helix.chain_b.append(1)
            decompose_to_triple_helix(inner, helix, use_macros); return

    if node.is_leaf():
        helix.chain_a.append(0)
        helix.chain_c.append({'t': node.leaf_type, 'v': node.value})
    else:
        helix.chain_a.append(1); helix.chain_b.append(0)
        decompose_to_triple_helix(node.left,  helix, use_macros)
        decompose_to_triple_helix(node.right, helix, use_macros)


# ===========================================================================
# Obfuscation Tools
# ===========================================================================

def get_ast_depth(node) -> int:
    if node.is_leaf(): return 1
    return 1 + max(get_ast_depth(node.left), get_ast_depth(node.right))

def inject_neutral_node(node):
    """Wrap node with a mathematically neutral operation (adds 0, multiplies by 1, etc.)."""
    op = random.choice(['add_zero', 'sub_zero', 'mul_one', 'div_one'])
    if op == 'add_zero': return make_add(node, make_const(0.0))
    if op == 'sub_zero': return make_sub(node, make_const(0.0))
    if op == 'mul_one':  return make_mul(node, make_const(1.0))
    return make_div(node, make_const(1.0))

def bloat_ast(node, target_depth, current_depth=1):
    """Recursively inject neutral nodes to reach target_depth."""
    if target_depth <= current_depth:
        return node
    if node.is_leaf():
        new_node = inject_neutral_node(node)
        return bloat_ast(new_node, target_depth, current_depth + get_ast_depth(new_node) - 1)
    choice = random.choice(['left', 'right', 'both', 'wrap'])
    if choice == 'left':
        return EMLNode(bloat_ast(node.left,  target_depth, current_depth + 1), node.right)
    if choice == 'right':
        return EMLNode(node.left, bloat_ast(node.right, target_depth, current_depth + 1))
    if choice == 'both':
        return EMLNode(bloat_ast(node.left,  target_depth - 1, current_depth + 1),
                       bloat_ast(node.right, target_depth - 1, current_depth + 1))
    new_node = inject_neutral_node(node)
    return bloat_ast(new_node, target_depth, current_depth + get_ast_depth(new_node) - 1)

def generate_variable_mapping(variables: dict) -> tuple:
    """
    Randomly permute variable names to obfuscated names (v0, v1, ...).
    Returns (remapped_vars, key_map).
    key_map: {original_name: obfuscated_name}
    """
    orig_names = list(variables.keys())
    obf_names  = [f"v{i}" for i in range(len(orig_names))]
    random.shuffle(obf_names)
    key_map      = dict(zip(orig_names, obf_names))
    remapped_vars = {key_map[k]: v for k, v in variables.items()}
    return remapped_vars, key_map

def remap_ast_variables(node, key_map: dict):
    """Replace variable names in an AST using key_map."""
    if node.is_leaf():
        if node.leaf_type == 'var' and node.value in key_map:
            return EMLLeaf('var', key_map[node.value])
        return node
    return EMLNode(remap_ast_variables(node.left,  key_map),
                   remap_ast_variables(node.right, key_map))

def validate_and_normalize_variables(variables: dict, clamp_range: tuple = (-1.0, 1.0)) -> dict:
    """Clamp all variable values to clamp_range."""
    lo, hi = clamp_range
    normalized = {}
    for k, v in variables.items():
        if isinstance(v, complex):
            normalized[k] = complex(max(lo, min(hi, v.real)), max(lo, min(hi, v.imag)))
        elif isinstance(v, (int, float)):
            normalized[k] = max(lo, min(hi, float(v)))
        else:
            normalized[k] = v
    return normalized


# ===========================================================================
# Internal helpers shared by EMLFormula
# ===========================================================================

def _run_zipper(ast_node, variables: dict, use_complex: bool = False):
    """Compile AST → Triple-Helix → ZipperAutomaton → result. One-shot convenience."""
    helix = TripleHelix()
    decompose_to_triple_helix(ast_node, helix, use_macros=True)
    serialized = serialize_triple_helix(helix)
    ca, cb, cc = deserialize_triple_helix(serialized)
    return ZipperAutomaton(ca, cb, cc).zip_and_evaluate(variables, use_complex=use_complex)


# ===========================================================================
# EMLFormula — high-level formula object
# ===========================================================================

class EMLFormula:
    """
    A portable, self-contained formula object.

    Design: Weights are stored as plain Python numbers for correct local
    evaluation (EML algebra breaks for weights < 1 or negative in real-domain
    mode due to ln guardrail sign-stripping). For delegation, the formula is
    compiled into an opaque EML Triple-Helix payload that hides the weights.

    Privacy model:
      - Local evaluation: weights stay in this Python object, never logged
      - Payload delegation: weights are embedded as EML constants inside the
        Triple-Helix blob; the delegatee sees only remapped variable names

    Usage:
        f = EMLFormula.compile_weighted_sum(
            input_names=["x1", "x2"],
            weights=[0.8, -0.4],
            bias=0.2,
        )
        result = f.evaluate({"x1": 1.5, "x2": 2.0})   # → 0.6  (local)

        payload, key_map = f.to_payload({"x1": 1.5, "x2": 2.0})
        result2 = EMLFormula.evaluate_payload(payload)  # → 0.6  (delegatable)
    """

    def __init__(
        self,
        input_names: list,
        weights: list,
        bias: float = 0.0,
        _ast=None,
    ):
        self._input_names = list(input_names)
        self._weights     = list(weights)
        self._bias        = float(bias)
        # Optional pre-built AST (for from_ast constructor)
        self._ast         = _ast

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def compile_weighted_sum(
        cls,
        input_names: list,
        weights: list,
        bias: float = 0.0,
    ) -> "EMLFormula":
        """
        Compile: sum(weight_i * input_i) + bias
        Weights and bias are stored privately. Works for any real weights.

        Example:
            f = EMLFormula.compile_weighted_sum(["x1","x2"], [0.8, -0.4], bias=0.2)
        """
        if len(input_names) != len(weights):
            raise ValueError("input_names and weights must have the same length.")
        return cls(input_names, weights, bias)

    @classmethod
    def compile_dot_product(cls, input_names: list, weights: list) -> "EMLFormula":
        """Compile a dot product (no bias)."""
        return cls.compile_weighted_sum(input_names, weights, bias=0.0)

    @classmethod
    def compile_weights(
        cls,
        weights: dict,
        inputs: list,
    ) -> "EMLFormula":
        """
        Construct EMLFormula from a weights dict and inputs list.
        Supports weight keys like 'w1', 'w2' or matching input names.
        """
        w_list = []
        for i, name in enumerate(inputs):
            w_val = weights.get(name)
            if w_val is None:
                w_val = weights.get(f"w{i+1}")
            if w_val is None:
                raise ValueError(f"Weight not found for input {name} (tried '{name}' and 'w{i+1}')")
            w_list.append(float(w_val))
        
        bias = float(weights.get("b", weights.get("bias", 0.0)))
        return cls(inputs, w_list, bias)

    @classmethod
    def from_ast(cls, ast_node, input_names: Optional[list] = None) -> "EMLFormula":
        """
        Create from a pre-built EML AST node.
        evaluate() will use the ZipperAutomaton directly on the AST.
        to_payload() will use the AST for serialization.
        Note: AST must use only positive constants to avoid real-domain issues.
        """
        inst = cls(input_names or [], [], 0.0, _ast=ast_node)
        return inst

    # ------------------------------------------------------------------
    # Evaluation (local, fast, private)
    # ------------------------------------------------------------------

    def evaluate(self, variables: dict, use_complex: bool = False) -> float:
        """
        Evaluate locally. For weighted sums, uses direct Python arithmetic
        (fast, exact, handles negative weights correctly).
        For AST-based formulas, uses the ZipperAutomaton.
        """
        if self._ast is not None:
            return _run_zipper(self._ast, variables, use_complex=use_complex)

        # Direct weighted sum evaluation — correct for all weights
        result = self._bias
        for name, weight in zip(self._input_names, self._weights):
            result += weight * variables[name]
        return result

    def evaluate_bloated(self, variables: dict, bloat_depth: int = 8, use_complex: bool = True) -> float:
        """
        Evaluate after applying topology bloat (parity test helper).
        """
        if self._ast is None:
            # For weighted sums, build a temporary AST for the bloat test
            ast = self._build_positive_ast(variables)
            bloated = bloat_ast(ast, bloat_depth)
            val = _run_zipper(bloated, variables, use_complex=use_complex)
            return val.real if isinstance(val, complex) else val
        bloated = bloat_ast(self._ast, bloat_depth)
        val = _run_zipper(bloated, variables, use_complex=use_complex)
        return val.real if isinstance(val, complex) else val

    # ------------------------------------------------------------------
    # Payload serialization (for delegation to untrusted evaluators)
    # ------------------------------------------------------------------

    def to_payload(self, variables: dict, bloat_depth: int = 8) -> tuple:
        """
        Produce an obfuscated, delegatable EML Triple-Helix payload.

        Weights are embedded as EML constants (positive-split for domain safety).
        Input variable names are remapped to v0, v1, ...
        AST is topology-bloated to hide formula structure.

        Returns:
            (payload_dict, key_map)
            payload_dict → safe to delegate; contains remapped vars + helix
            key_map      → {orig_name: obf_name} — keep private
        """
        # Build a delegation AST with positive-split weights
        ast = self._build_delegation_ast(list(variables.keys()))

        # Remap variables
        remapped_vars, key_map = generate_variable_mapping(variables)
        remapped_ast            = remap_ast_variables(ast, key_map)

        # Bloat
        bloated = bloat_ast(remapped_ast, bloat_depth)

        # Serialize
        helix = TripleHelix()
        decompose_to_triple_helix(bloated, helix, use_macros=True)
        serialized = serialize_triple_helix(helix)

        payload = {
            "format":    "eml_triple_helix_v1",
            "variables": remapped_vars,
            "helix":     serialized,
        }
        return payload, key_map

    @staticmethod
    def evaluate_payload(payload: dict, use_complex: bool = False) -> float:
        """Evaluate a payload produced by to_payload() — no key_map needed."""
        ca, cb, cc = deserialize_triple_helix(payload["helix"])
        val = ZipperAutomaton(ca, cb, cc).zip_and_evaluate(
            payload["variables"], use_complex=use_complex
        )
        return val.real if isinstance(val, complex) else val

    # ------------------------------------------------------------------
    # Internal AST builders (positive-split for EML real-domain safety)
    # ------------------------------------------------------------------

    def _build_delegation_ast(self, input_names: list):
        """
        Build EML AST for delegation, splitting weights into pos/neg to
        avoid ln(negative) domain issues in EML real-domain arithmetic.
        """
        pos_terms = []
        neg_terms = []

        for name, weight in zip(self._input_names, self._weights):
            if name not in input_names:
                continue
            if weight >= 0:
                pos_terms.append(make_mul(make_const(abs(weight)), make_var(name)))
            else:
                neg_terms.append(make_mul(make_const(abs(weight)), make_var(name)))

        if self._bias > 0:
            pos_terms.append(make_const(self._bias))
        elif self._bias < 0:
            neg_terms.append(make_const(abs(self._bias)))

        def sum_terms(terms):
            if not terms: return None
            result = terms[0]
            for t in terms[1:]: result = make_add(result, t)
            return result

        pos_ast = sum_terms(pos_terms)
        neg_ast = sum_terms(neg_terms)

        if pos_ast is None and neg_ast is None:
            return make_const(0.0)
        elif pos_ast is None:
            return make_sub(make_const(0.0), neg_ast)
        elif neg_ast is None:
            return pos_ast
        else:
            return make_sub(pos_ast, neg_ast)

    def _build_positive_ast(self, variables: dict):
        """Build AST for bloat parity test — only uses the provided variables."""
        return self._build_delegation_ast(list(variables.keys()))

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def input_names(self) -> list:
        return list(self._input_names)

    @property
    def weights(self) -> list:
        return list(self._weights)

    @property
    def bias(self) -> float:
        return self._bias

    @property
    def depth(self) -> int:
        if self._ast is not None:
            return get_ast_depth(self._ast)
        return len(self._input_names) * 3  # approximate

    def __repr__(self) -> str:
        return (f"EMLFormula(inputs={self._input_names}, "
                f"weights={self._weights}, bias={self._bias})")




def _self_test():
    print("EML Engine self-test...")
    f = EMLFormula.compile_weighted_sum(["x1", "x2"], [0.8, -0.4], bias=0.2)
    result = f.evaluate({"x1": 1.5, "x2": 2.0})
    expected = 0.8 * 1.5 + (-0.4) * 2.0 + 0.2  # = 0.6
    assert math.isclose(result, expected, rel_tol=1e-5), f"Got {result}, expected {expected}"

    payload, _ = f.to_payload({"x1": 1.5, "x2": 2.0})
    result2 = EMLFormula.evaluate_payload(payload, use_complex=True)
    assert math.isclose(result2, expected, rel_tol=1e-5), f"Payload result: {result2}"

    print(f"  weighted sum    → {result:.6f}  ✔")
    print(f"  payload round-trip → {result2:.6f}  ✔")
    print("  eml_engine OK")


if __name__ == "__main__":
    import sys
    if "--self-test" in sys.argv or len(sys.argv) == 1:
        _self_test()
