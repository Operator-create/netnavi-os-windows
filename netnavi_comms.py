#!/usr/bin/env python3
import socket
import threading
import time
import json
import math
import hashlib
import hmac
import base64
import os
import asyncio
import websockets
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding

# Color codes for terminal beauty
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
MAGENTA = "\033[95m"
BOLD = "\033[1m"
RESET = "\033[0m"

# ==========================================
# SECP256K1 & BIP-340 SCHNORR IMPLEMENTATION
# ==========================================

P_curve = 2**256 - 2**32 - 977
N_curve = 115792089237316195423570985008687907852837564279074904382605163141518161494337
Gx = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
Gy = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8

def point_add(P, Q):
    if P is None: return Q
    if Q is None: return P
    x1, y1 = P
    x2, y2 = Q
    if x1 == x2 and y1 != y2:
        return None
    if P == Q:
        if y1 == 0: return None
        m = (3 * x1 * x1 * pow(2 * y1, P_curve - 2, P_curve)) % P_curve
    else:
        m = ((y2 - y1) * pow(x2 - x1, P_curve - 2, P_curve)) % P_curve
    x3 = (m * m - x1 - x2) % P_curve
    y3 = (m * (x1 - x3) - y1) % P_curve
    return (x3, y3)

def point_mul(P, k):
    k = k % N_curve
    R = None
    current = P
    while k > 0:
        if k & 1:
            R = point_add(R, current)
        current = point_add(current, current)
        k >>= 1
    return R

def get_public_key(private_key_int):
    P = point_mul((Gx, Gy), private_key_int)
    if P is None:
        raise ValueError("Invalid private key")
    # For BIP-340, public key is just x-coordinate (32 bytes)
    # The y-coordinate is forced to be even. If it's odd, private key is negated.
    x, y = P
    is_odd = (y % 2) != 0
    actual_priv = private_key_int if not is_odd else (N_curve - private_key_int)
    return x, actual_priv

def tagged_hash(tag, msg):
    tag_hash = hashlib.sha256(tag.encode('utf-8')).digest()
    return hashlib.sha256(tag_hash + tag_hash + msg).digest()

def schnorr_sign(msg_bytes, private_key_int):
    # msg_bytes must be 32 bytes
    x_pub, d = get_public_key(private_key_int)
    pubkey_bytes = x_pub.to_bytes(32, 'big')
    
    # Auxiliary random bytes
    aux = os.urandom(32)
    t = (d ^ int.from_bytes(tagged_hash("BIP-340/aux", aux), 'big')).to_bytes(32, 'big')
    
    # Generate nonce k'
    k_prime = int.from_bytes(tagged_hash("BIP-340/nonce", t + pubkey_bytes + msg_bytes), 'big') % N_curve
    if k_prime == 0:
        raise ValueError("Nonce generated is 0")
        
    R = point_mul((Gx, Gy), k_prime)
    Rx, Ry = R
    k = k_prime if (Ry % 2 == 0) else (N_curve - k_prime)
    
    # Compute challenge e
    e = int.from_bytes(tagged_hash("BIP-340/challenge", Rx.to_bytes(32, 'big') + pubkey_bytes + msg_bytes), 'big') % N_curve
    
    s = (k + e * d) % N_curve
    sig = Rx.to_bytes(32, 'big') + s.to_bytes(32, 'big')
    return sig

def schnorr_verify(msg_bytes, pubkey_bytes, sig_bytes):
    # Verify Schnorr signature according to BIP-340
    if len(pubkey_bytes) != 32 or len(sig_bytes) != 64 or len(msg_bytes) != 32:
        return False
    px = int.from_bytes(pubkey_bytes, 'big')
    rx = int.from_bytes(sig_bytes[:32], 'big')
    s = int.from_bytes(sig_bytes[32:], 'big')
    
    if px >= P_curve or rx >= P_curve or s >= N_curve:
        return False
        
    # Reconstruct public key point P (y is even)
    y_sq = (pow(px, 3, P_curve) + 7) % P_curve
    py = pow(y_sq, (P_curve + 1) // 4, P_curve)
    if pow(py, 2, P_curve) != y_sq:
        return False # No square root exists
    if py % 2 != 0:
        py = P_curve - py
        
    P = (px, py)
    e = int.from_bytes(tagged_hash("BIP-340/challenge", rx.to_bytes(32, 'big') + pubkey_bytes + msg_bytes), 'big') % N_curve
    
    # Compute R = s*G - e*P
    sG = point_mul((Gx, Gy), s)
    eP = point_mul(P, e)
    # negate eP
    if eP is None: return False
    ePx, ePy = eP
    neg_eP = (ePx, (P_curve - ePy) % P_curve)
    
    R = point_add(sG, neg_eP)
    if R is None or (R[1] % 2 != 0) or R[0] != rx:
        return False
    return True

# ==========================================
# NOSTR ENCRYPTED DIRECT MESSAGES (KIND 4)
# ==========================================

def get_shared_secret(priv_key_int, pub_key_bytes):
    px = int.from_bytes(pub_key_bytes, 'big')
    # Reconstruct public key point
    y_sq = (pow(px, 3, P_curve) + 7) % P_curve
    py = pow(y_sq, (P_curve + 1) // 4, P_curve)
    if py % 2 != 0:
        py = P_curve - py
    P = (px, py)
    S = point_mul(P, priv_key_int)
    if S is None:
        raise ValueError("Invalid shared secret calculation")
    return S[0].to_bytes(32, 'big')

def encrypt_nostr_dm(priv_key_int, receiver_pubkey_bytes, plain_text):
    shared_secret = get_shared_secret(priv_key_int, receiver_pubkey_bytes)
    iv = os.urandom(16)
    cipher = Cipher(algorithms.AES(shared_secret), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    
    padder = padding.PKCS7(128).padder()
    padded_data = padder.update(plain_text.encode('utf-8')) + padder.finalize()
    ciphertext = encryptor.update(padded_data) + encryptor.finalize()
    
    ciphertext_b64 = base64.b64encode(ciphertext).decode('utf-8')
    iv_b64 = base64.b64encode(iv).decode('utf-8')
    return f"{ciphertext_b64}?iv={iv_b64}"

def decrypt_nostr_dm(priv_key_int, sender_pubkey_bytes, encrypted_content):
    shared_secret = get_shared_secret(priv_key_int, sender_pubkey_bytes)
    try:
        ciphertext_b64, iv_b64 = encrypted_content.split("?iv=")
        ciphertext = base64.b64decode(ciphertext_b64)
        iv = base64.b64decode(iv_b64)
        
        cipher = Cipher(algorithms.AES(shared_secret), modes.CBC(iv), backend=default_backend())
        decryptor = cipher.decryptor()
        
        decrypted_padded = decryptor.update(ciphertext) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        plain_bytes = unpadder.update(decrypted_padded) + unpadder.finalize()
        return plain_bytes.decode('utf-8')
    except Exception as e:
        raise ValueError(f"Decryption failed: {e}")

# ==========================================
# LOCAL NET DISCOVERY (UDP BROADCAST)
# ==========================================

class UDPDiscovery:
    def __init__(self, navi_name, pubkey_hex, ws_port=8765, discovery_port=5555):
        self.navi_name = navi_name
        self.pubkey_hex = pubkey_hex
        self.ws_port = ws_port
        self.discovery_port = discovery_port
        self.discovered_navis = {}
        self.running = False
        self.lock = threading.Lock()
        
    def start(self):
        self.running = True
        self.listen_thread = threading.Thread(target=self._listen, daemon=True)
        self.broadcast_thread = threading.Thread(target=self._broadcast, daemon=True)
        self.listen_thread.start()
        self.broadcast_thread.start()
        
    def stop(self):
        self.running = False
        
    def _broadcast(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        
        beacon = {
            "type": "NETNAVI_BEACON",
            "name": self.navi_name,
            "pubkey": self.pubkey_hex,
            "ws_port": self.ws_port
        }
        data = json.dumps(beacon).encode('utf-8')
        
        while self.running:
            try:
                sock.sendto(data, ('<broadcast>', self.discovery_port))
            except Exception:
                pass
            time.sleep(3.0)
        sock.close()
        
    def _listen(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Bind to broadcast port
        try:
            sock.bind(('', self.discovery_port))
        except Exception as e:
            # Fallback if port bound
            return
            
        sock.settimeout(1.0)
        
        while self.running:
            try:
                data, addr = sock.recvfrom(1024)
                sender_ip = addr[0]
                payload = json.loads(data.decode('utf-8'))
                if payload.get("type") == "NETNAVI_BEACON":
                    name = payload["name"]
                    pubkey = payload["pubkey"]
                    ws_port = payload["ws_port"]
                    
                    if pubkey != self.pubkey_hex:
                        with self.lock:
                            self.discovered_navis[pubkey] = {
                                "name": name,
                                "ip": sender_ip,
                                "port": ws_port,
                                "last_seen": time.time()
                            }
            except socket.timeout:
                continue
            except Exception:
                continue
        sock.close()
        
    def get_discovered(self):
        # Prune stales (> 10s)
        now = time.time()
        with self.lock:
            stale = [k for k, v in self.discovered_navis.items() if now - v["last_seen"] > 10.0]
            for k in stale:
                del self.discovered_navis[k]
            return self.discovered_navis.copy()

# ==========================================
# UNIT TESTS RUNNER
# ==========================================

def run_crypto_tests():
    print(f"[{YELLOW}Test{RESET}] Initiating Cryptographic verification...")
    # 1. Test key gen & pubkey derivation
    priv = random.randint(1, N_curve - 1)
    px, d = get_public_key(priv)
    print(f"  * Key generation: OK (Private: {priv:x}... -> Public: {px:x}...)")
    
    # 2. Test Schnorr signature
    msg = hashlib.sha256(b"NetNavi Identity").digest()
    sig = schnorr_sign(msg, d)
    pub_bytes = px.to_bytes(32, 'big')
    is_valid = schnorr_verify(msg, pub_bytes, sig)
    assert is_valid, "Schnorr Signature Verification Failed!"
    print(f"  * Schnorr Sign & Verify: {GREEN}SUCCESS{RESET}")
    
    # 3. Test Nostr Encrypted DMs
    priv2 = random.randint(1, N_curve - 1)
    px2, d2 = get_public_key(priv2)
    pub2_bytes = px2.to_bytes(32, 'big')
    
    message = "MegaMan, Chaud's Navi has located the virus."
    encrypted = encrypt_nostr_dm(d, pub2_bytes, message)
    print(f"  * Encrypted payload: {encrypted[:40]}...")
    
    decrypted = decrypt_nostr_dm(d2, pub_bytes, encrypted)
    assert decrypted == message, "Nostr DM Encryption/Decryption Failed!"
    print(f"  * Nostr DM Decrypt: {GREEN}SUCCESS (Result: '{decrypted}'){RESET}")
    print(f"{GREEN}✔ All Cryptographic Verification Tests Passed!{RESET}\n")

# ==========================================
# EML UNIVERSAL MATHEMATICS & TRIPLE HELIX ENGINE
# ==========================================

import cmath
import zlib

def eml(x, y):
    """
    Computes the EML (Exp-Minus-Log) operator: eml(x, y) = exp(x) - ln(y)
    with strict real-domain clamping to prevent crashes and overflows.
    Supports complex-number arithmetic fallback.
    """
    # Check if either input is a complex number
    if isinstance(x, complex) or isinstance(y, complex):
        try:
            return cmath.exp(x) - cmath.log(y)
        except Exception:
            return complex(float('inf'), 0.0)

    # Real-domain evaluation with strict guardrails
    # 1. Clamping the exponent to prevent double-exponential overflow/underflow
    x_clamped = max(-700.0, min(700.0, float(x)))

    # 2. Real-domain log clamping to prevent domain crashes (y <= 0)
    epsilon = 1e-15
    y_clamped = abs(float(y)) + epsilon

    try:
        val = math.exp(x_clamped) - math.log(y_clamped)
        return val
    except OverflowError:
        return float('inf')

def evaluate_eml_rpn(tokens, variables, use_complex=False):
    """
    Evaluates an EML mathematical expression in Reverse Polish Notation (postfix).
    Tokens: list of string values (operators, variables, constants).
    Variables: dict mapping variable names to their numeric/complex values.
    Supports arity checks, stack limit checks, and unified complex promotion.
    """
    stack = []
    max_stack_size = 64

    # Promote variables to complex if use_complex is True
    local_vars = variables
    if use_complex:
        local_vars = {k: complex(v) for k, v in variables.items()}

    for token in tokens:
        if not token:
            continue

        # Check for EML operators: 'E', 'eml', or 'EML'
        if token in ('E', 'eml', 'EML'):
            if len(stack) < 2:
                # Arity underflow protection: default to 0.0
                stack.append(0.0)
                continue
            
            y = stack.pop()
            x = stack.pop()
            
            res = eml(x, y)
            stack.append(res)
        else:
            # Operand: Variable or Constant
            if token in local_vars:
                val = local_vars[token]
            else:
                try:
                    # Parse as float constant
                    val = float(token)
                    if use_complex:
                        val = complex(val)
                except ValueError:
                    # Try parsing as complex constant (e.g. 1+2j)
                    try:
                        val = complex(token)
                    except ValueError:
                        # Fallback for unknown variables/constants
                        val = 0.0
            
            if len(stack) >= max_stack_size:
                # Stack overflow protection
                break
            stack.append(val)

    if not stack:
        return 0.0
    return stack[-1]

# --- Triple-Helix Graph Compression Engine ---

class TripleHelix:
    def __init__(self):
        self.chain_a = []  # Topology (1 for operator, 0 for leaf)
        self.chain_b = []  # Macro/Operator IDs (0 = EML, 1 = EXP, 2 = LN)
        self.chain_c = []  # Leaf dictionary mappings

def serialize_triple_helix(helix):
    """
    Packs and compresses the TripleHelix chains using zlib.
    """
    # Chain A: Pack bitstring into bytes
    bitstring = "".join(map(str, helix.chain_a))
    if not bitstring:
        byte_a = b""
    else:
        # Pad bitstring length to a multiple of 8
        padded_len = (len(bitstring) + 7) // 8 * 8
        bitstring_padded = bitstring.zfill(padded_len)
        val = int(bitstring_padded, 2)
        byte_a = val.to_bytes(padded_len // 8, byteorder='big')

    # Chain B: Operators list to raw bytes
    byte_b = bytes(helix.chain_b)

    # Chain C: JSON representation
    json_c = json.dumps(helix.chain_c).encode('utf-8')

    # Apply zlib compression
    comp_a = zlib.compress(byte_a, level=9)
    comp_b = zlib.compress(byte_b, level=9)
    comp_c = zlib.compress(json_c, level=9)

    return {
        'comp_a': base64.b64encode(comp_a).decode('utf-8'),
        'comp_b': base64.b64encode(comp_b).decode('utf-8'),
        'comp_c': base64.b64encode(comp_c).decode('utf-8'),
        'bitstring_len': len(bitstring)
    }

def deserialize_triple_helix(compressed_data):
    """
    Decompresses and reconstructs the TripleHelix chains from serialized data.
    """
    comp_a = base64.b64decode(compressed_data['comp_a'])
    comp_b = base64.b64decode(compressed_data['comp_b'])
    comp_c = base64.b64decode(compressed_data['comp_c'])
    bitstring_len = compressed_data['bitstring_len']

    byte_a = zlib.decompress(comp_a)
    byte_b = zlib.decompress(comp_b)
    json_c = zlib.decompress(comp_c)

    # Reconstruct Chain A
    if not byte_a:
        chain_a = []
    else:
        val = int.from_bytes(byte_a, byteorder='big')
        padded_len = len(byte_a) * 8
        bitstring = bin(val)[2:].zfill(padded_len)
        if len(bitstring) > bitstring_len:
            # Remove leading zeros added during padding
            bitstring = bitstring[-bitstring_len:]
        chain_a = [int(b) for b in bitstring]

    # Reconstruct Chain B
    chain_b = list(byte_b)

    # Reconstruct Chain C
    chain_c = json.loads(json_c.decode('utf-8'))

    return chain_a, chain_b, chain_c

class ZipperAutomaton:
    """
    Linear, non-recursive evaluator that 'zips' the Triple-Helix streams
    on-the-fly directly to execute the formula without tree construction.
    """
    def __init__(self, chain_a, chain_b, chain_c):
        self.chain_a = list(chain_a)
        self.chain_b = list(chain_b)
        self.chain_c = list(chain_c)
        self.pos_a = 0
        self.pos_b = 0
        self.pos_c = 0

    def zip_and_evaluate(self, variables, use_complex=False):
        self.pos_a = 0
        self.pos_b = 0
        self.pos_c = 0
        local_vars = variables
        if use_complex:
            local_vars = {k: complex(v) for k, v in variables.items()}
        return self._eval_recursive(local_vars, use_complex)

    def _eval_recursive(self, variables, use_complex):
        if self.pos_a >= len(self.chain_a):
            return 0.0

        is_node = self.chain_a[self.pos_a]
        self.pos_a += 1

        if not is_node:
            leaf = self.chain_c[self.pos_c]
            self.pos_c += 1
            if leaf['t'] == 'var':
                return variables[leaf['v']]
            val = leaf['v']
            if use_complex:
                return complex(val)
            return val
        else:
            op = self.chain_b[self.pos_b]
            self.pos_b += 1

            if op == 0:  # Raw EML
                left = self._eval_recursive(variables, use_complex)
                right = self._eval_recursive(variables, use_complex)
                return eml(left, right)
            elif op == 1:  # EXP Macro
                val = self._eval_recursive(variables, use_complex)
                # Apply same guardrails to EXP macro
                if isinstance(val, complex):
                    try:
                        return cmath.exp(val)
                    except Exception:
                        return complex(float('inf'), 0.0)
                else:
                    val_clamped = max(-700.0, min(700.0, float(val)))
                    try:
                        return math.exp(val_clamped)
                    except OverflowError:
                        return float('inf')
            elif op == 2:  # LN Macro
                val = self._eval_recursive(variables, use_complex)
                # Apply same guardrails to LN macro
                if isinstance(val, complex):
                    try:
                        return cmath.log(val)
                    except Exception:
                        return complex(float('-inf'), 0.0)
                else:
                    epsilon = 1e-15
                    val_clamped = abs(float(val)) + epsilon
                    return math.log(val_clamped)
            else:
                raise ValueError(f"Unknown Operator/Macro ID: {op}")

# --- AST Compiler, Bloating, and Remapping Engine ---

class ASTNode:
    def is_leaf(self):
        raise NotImplementedError

class EMLNode(ASTNode):
    def __init__(self, left, right):
        self.left = left
        self.right = right

    def is_leaf(self):
        return False

    def __str__(self):
        return f"eml({self.left}, {self.right})"

class EMLLeaf(ASTNode):
    def __init__(self, leaf_type, value):
        self.leaf_type = leaf_type  # 'var' or 'const'
        self.value = value          # name (str) or float

    def is_leaf(self):
        return True

    def __str__(self):
        if self.leaf_type == 'var':
            return str(self.value)
        else:
            if self.value == int(self.value):
                return str(int(self.value))
            return str(self.value)

def make_const(val):
    return EMLLeaf('const', float(val))

def make_var(name):
    return EMLLeaf('var', name)

def make_exp(u):
    return EMLNode(u, make_const(1.0))

def make_ln(u):
    return EMLNode(
        make_const(1.0),
        EMLNode(
            EMLNode(make_const(1.0), u),
            make_const(1.0)
        )
    )

def make_sub(u, v):
    return EMLNode(make_ln(u), make_exp(v))

def make_add(u, v):
    neg_v = make_sub(make_const(0.0), v)
    return EMLNode(make_ln(u), make_exp(neg_v))

def make_mul(u, v):
    return make_exp(make_add(make_ln(u), make_ln(v)))

def make_div(u, v):
    return make_exp(make_sub(make_ln(u), make_ln(v)))

def flatten_to_rpn(node):
    tokens = []
    _flatten_recursive(node, tokens)
    return tokens

def _flatten_recursive(node, tokens):
    if node.is_leaf():
        if node.leaf_type == 'var':
            tokens.append(str(node.value))
        else:
            if node.value == int(node.value):
                tokens.append(str(int(node.value)))
            else:
                tokens.append(str(node.value))
    else:
        _flatten_recursive(node.left, tokens)
        _flatten_recursive(node.right, tokens)
        tokens.append('E')

def match_exp(node):
    if isinstance(node, EMLNode) and node.right.is_leaf() and node.right.leaf_type == 'const' and node.right.value == 1.0:
        return node.left
    return None

def match_ln(node):
    if not isinstance(node, EMLNode):
        return None
    if not (node.left.is_leaf() and node.left.leaf_type == 'const' and node.left.value == 1.0):
        return None
    right = node.right
    if not isinstance(right, EMLNode):
        return None
    if not isinstance(right.left, EMLNode):
        return None
    r_l = right.left
    if not (r_l.left.is_leaf() and r_l.left.leaf_type == 'const' and r_l.left.value == 1.0):
        return None
    u = r_l.right
    if not (right.right.is_leaf() and right.right.leaf_type == 'const' and right.right.value == 1.0):
        return None
    return u

def decompose_to_triple_helix(node, helix, use_macros=True):
    if use_macros:
        inner = match_ln(node)
        if inner is not None:
            helix.chain_a.append(1)
            helix.chain_b.append(2)  # Macro ID 2 = LN
            decompose_to_triple_helix(inner, helix, use_macros)
            return
        
        inner = match_exp(node)
        if inner is not None:
            helix.chain_a.append(1)
            helix.chain_b.append(1)  # Macro ID 1 = EXP
            decompose_to_triple_helix(inner, helix, use_macros)
            return

    if node.is_leaf():
        helix.chain_a.append(0)
        helix.chain_c.append({
            't': node.leaf_type,
            'v': node.value
        })
    else:
        helix.chain_a.append(1)
        helix.chain_b.append(0)  # Operator ID 0 = Raw EML
        decompose_to_triple_helix(node.left, helix, use_macros)
        decompose_to_triple_helix(node.right, helix, use_macros)

def get_ast_depth(node):
    if node.is_leaf():
        return 1
    return 1 + max(get_ast_depth(node.left), get_ast_depth(node.right))

def inject_neutral_node(node):
    """
    Wraps a node with a mathematically neutral operation:
    - node + 0
    - node - 0
    - node * 1
    - node / 1
    """
    import random
    op = random.choice(['add_zero', 'sub_zero', 'mul_one', 'div_one'])
    if op == 'add_zero':
        return make_add(node, make_const(0.0))
    elif op == 'sub_zero':
        return make_sub(node, make_const(0.0))
    elif op == 'mul_one':
        return make_mul(node, make_const(1.0))
    else:
        return make_div(node, make_const(1.0))

def bloat_ast(node, target_depth, current_depth=1):
    """
    Recursively traverses the AST, injecting mathematically neutral nodes
    to increase the tree depth to target_depth.
    """
    if target_depth <= current_depth:
        return node
        
    if node.is_leaf():
        new_node = inject_neutral_node(node)
        new_depth = get_ast_depth(new_node)
        return bloat_ast(new_node, target_depth, current_depth + new_depth - 1)
    else:
        import random
        choice = random.choice(['left', 'right', 'both', 'wrap'])
        if choice == 'left':
            new_left = bloat_ast(node.left, target_depth, current_depth + 1)
            return EMLNode(new_left, node.right)
        elif choice == 'right':
            new_right = bloat_ast(node.right, target_depth, current_depth + 1)
            return EMLNode(node.left, new_right)
        elif choice == 'both':
            new_left = bloat_ast(node.left, target_depth - 1, current_depth + 1)
            new_right = bloat_ast(node.right, target_depth - 1, current_depth + 1)
            return EMLNode(new_left, new_right)
        else:
            new_node = inject_neutral_node(node)
            new_depth = get_ast_depth(new_node)
            return bloat_ast(new_node, target_depth, current_depth + new_depth - 1)

def generate_variable_mapping(variables):
    """
    Generates a randomized mapping from original variable names to obfuscated names (v0, v1, ...).
    Returns:
        remapped_vars: dict with keys like 'v0', 'v1' mapping to original values
        key_map: dict mapping original variable names to new names (e.g., {'x': 'v0'})
    """
    import random
    orig_names = list(variables.keys())
    obf_names = [f"v{i}" for i in range(len(orig_names))]
    random.shuffle(obf_names)
    key_map = dict(zip(orig_names, obf_names))
    remapped_vars = {key_map[k]: v for k, v in variables.items()}
    return remapped_vars, key_map

def remap_ast_variables(node, key_map):
    """
    Replaces variable names in an AST node using the key_map.
    """
    if node.is_leaf():
        if node.leaf_type == 'var' and node.value in key_map:
            return EMLLeaf('var', key_map[node.value])
        return node
    else:
        return EMLNode(
            remap_ast_variables(node.left, key_map),
            remap_ast_variables(node.right, key_map)
        )

def validate_and_normalize_variables(variables, clamp_range=(-1.0, 1.0)):
    """
    Validates and clamps input variable values to clamp_range.
    """
    normalized = {}
    min_val, max_val = clamp_range
    for k, v in variables.items():
        if isinstance(v, (int, float)):
            clamped_v = max(min_val, min(max_val, float(v)))
            normalized[k] = clamped_v
        elif isinstance(v, complex):
            clamped_real = max(min_val, min(max_val, v.real))
            clamped_imag = max(min_val, min(max_val, v.imag))
            normalized[k] = complex(clamped_real, clamped_imag)
        else:
            normalized[k] = v
    return normalized

if __name__ == "__main__":
    import random
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--test-crypto":
        run_crypto_tests()
