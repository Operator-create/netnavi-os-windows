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


# ===========================================================================
# EML Engine — extracted to eml_engine.py for modularity.
# Full re-export preserved for backwards compatibility.
# ===========================================================================

import sys as _sys
import os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

from eml_engine import (
    eml, evaluate_eml_rpn,
    TripleHelix, serialize_triple_helix, deserialize_triple_helix,
    ZipperAutomaton,
    ASTNode, EMLNode, EMLLeaf,
    make_const, make_var, make_exp, make_ln,
    make_sub, make_add, make_mul, make_div,
    flatten_to_rpn, match_exp, match_ln, decompose_to_triple_helix,
    get_ast_depth, inject_neutral_node, bloat_ast,
    generate_variable_mapping, remap_ast_variables,
    validate_and_normalize_variables,
    EMLFormula,
)


if __name__ == "__main__":
    import random
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--test-crypto":
        run_crypto_tests()
