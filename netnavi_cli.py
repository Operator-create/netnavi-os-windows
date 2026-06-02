#!/usr/bin/env python3
import asyncio
import socket
import threading
import time
import json
import os
import sys
import hashlib
import random
import websockets
from netnavi_comms import (
    get_public_key, schnorr_sign, schnorr_verify,
    encrypt_nostr_dm, decrypt_nostr_dm, UDPDiscovery,
    CYAN, GREEN, YELLOW, RED, MAGENTA, BOLD, RESET, eml, evaluate_eml_rpn
)

KEYS_FILE = os.environ.get("NETNAVI_KEYS_FILE", "netnavi_keys.json")
DEFAULT_RELAY = "wss://relay.damus.io"

# DH Parameters for the EML simulation handshake (same as in simulator)
DH_P = 997
DH_G = 2

class NetNaviNode:
    def __init__(self):
        self.name = ""
        self.private_key = 0
        self.pubkey_hex = ""
        self.ws_port = 8765
        self.discovery = None
        self.active_connections = {}
        self.incoming_queue = asyncio.Queue()
        self.nostr_relay = DEFAULT_RELAY
        self.current_peer = None  # Holds current active chat peer context
        
    def load_keys(self):
        if os.path.exists(KEYS_FILE):
            with open(KEYS_FILE, 'r') as f:
                keys = json.load(f)
                self.name = keys.get("name", "UnknownNavi")
                self.private_key = int(keys["private_key"], 16)
                self.pubkey_hex = keys["public_key"]
        else:
            self.name = input("Enter your NetNavi's name (e.g. MegaMan.EXE): ").strip()
            if not self.name:
                self.name = "NetNavi.EXE"
            self.private_key = random.randint(1, 2**256 - 1)
            x_pub, self.private_key = get_public_key(self.private_key)
            self.pubkey_hex = f"{x_pub:064x}"
            keys = {
                "name": self.name,
                "private_key": f"{self.private_key:064x}",
                "public_key": self.pubkey_hex
            }
            with open(KEYS_FILE, 'w') as f:
                json.dump(keys, f, indent=4)
            print(f"[{GREEN}System{RESET}] Generated new identity for {CYAN}{self.name}{RESET}!")
            print(f"  * Public Key: {YELLOW}{self.pubkey_hex}{RESET}")
            
    # Nostr serialization helper
    def create_nostr_event(self, kind, tags, content):
        created_at = int(time.time())
        serialized = [
            0,
            self.pubkey_hex,
            created_at,
            kind,
            tags,
            content
        ]
        serialized_bytes = json.dumps(serialized, separators=(',', ':')).encode('utf-8')
        event_id = hashlib.sha256(serialized_bytes).hexdigest()
        
        event_id_bytes = bytes.fromhex(event_id)
        sig = schnorr_sign(event_id_bytes, self.private_key)
        
        return {
            "id": event_id,
            "pubkey": self.pubkey_hex,
            "created_at": created_at,
            "kind": kind,
            "tags": tags,
            "content": content,
            "sig": sig.hex()
        }

# Global node instance
node = NetNaviNode()

# Helper for non-blocking input in asyncio
async def async_input(prompt):
    return await asyncio.get_event_loop().run_in_executor(None, input, prompt)

# ==========================================
# LOCAL P2P HANDSHAKE & WEBSOCKET ENGINE
# ==========================================

async def run_local_handshake_server(websocket):
    peer_ip = websocket.remote_address[0]
    print(f"\n[{YELLOW}System{RESET}] Incoming P.E.T. link request from {CYAN}{peer_ip}{RESET}...")
    
    # State 1: Accept Link
    try:
        msg = await asyncio.wait_for(websocket.recv(), timeout=10.0)
        data = json.loads(msg)
        if data.get("action") != "REQUEST_LINK":
            await websocket.close()
            return
            
        print(f"[{GREEN}System{RESET}] Initial link accepted. Initiating EML Handshake.")
        await websocket.send(json.dumps({
            "dialogue": f"Connection accepted. This is {node.name}. Identify yourself.",
            "state": "ACCEPT_LINK"
        }))
        
        # State 2: DH Key Exchange
        msg = await asyncio.wait_for(websocket.recv(), timeout=10.0)
        data = json.loads(msg)
        if data.get("action") != "SEND_DH_PUBLIC_KEY":
            await websocket.close()
            return
            
        A = data["dh_public_key_A"]
        # Choose private key b
        b = random.randint(10, 100)
        B = pow(DH_G, b, DH_P)
        K = float(pow(A, b, DH_P))
        
        await websocket.send(json.dumps({
            "dialogue": "Base key parameter received. Exchanging public parameters.",
            "state": "KEY_EXCHANGE",
            "dh_public_key": B
        }))
        
        # State 3: Challenge Generation
        msg = await asyncio.wait_for(websocket.recv(), timeout=10.0)
        data = json.loads(msg)
        if data.get("action") != "REQUEST_CHALLENGE":
            await websocket.close()
            return
            
        x_val = round(random.uniform(0.5, 2.0), 4)
        rpn = "1 1 x K E E 1 E E"
        
        await websocket.send(json.dumps({
            "dialogue": "Challenge compiled. Solve the bloated EML graph.",
            "state": "CHALLENGE",
            "challenge_x": x_val,
            "challenge_rpn": rpn
        }))
        
        # State 4: Verify Proof
        msg = await asyncio.wait_for(websocket.recv(), timeout=10.0)
        data = json.loads(msg)
        if data.get("action") != "SEND_PROOF":
            await websocket.close()
            return
            
        client_proof = data["proof_value"]
        # Calculate expected locally
        expected = evaluate_eml_rpn(rpn.split(), {"x": x_val, "K": K})
        
        if math.isclose(client_proof, expected, rel_tol=1e-9):
            print(f"[{GREEN}System{RESET}] Handshake {GREEN}SUCCESS{RESET}! Base key K={K}. Proof matches expected value.")
            await websocket.send(json.dumps({
                "dialogue": "Verification successful. Double Soul sync authorized.",
                "state": "VERIFICATION_SUCCESS"
            }))
            
            # Enter active chat loop
            node.active_connections[peer_ip] = websocket
            node.current_peer = {"type": "local", "ip": peer_ip, "websocket": websocket}
            print(f"\n{CYAN}{BOLD}--- SOUL UNION SESSION STARTED WITH {peer_ip} ---{RESET}")
            print(f"Type your messages below. Use '/exit' to close link.\n")
            
            while True:
                chat_msg = await websocket.recv()
                chat_data = json.loads(chat_msg)
                if chat_data.get("action") == "CHAT_EXIT":
                    print(f"\n[{RED}System{RESET}] Peer closed the session.")
                    break
                print(f"\n{MAGENTA}{BOLD}Peer:{RESET} {chat_data.get('content')}")
                print(f"{CYAN}{node.name}>{RESET} ", end="", flush=True)
                
            del node.active_connections[peer_ip]
            node.current_peer = None
        else:
            print(f"[{RED}System{RESET}] Handshake {RED}FAILED{RESET}. Invalid proof: {client_proof} (Expected: {expected})")
            await websocket.send(json.dumps({
                "dialogue": "Verification failed. Link severed.",
                "state": "VERIFICATION_FAILURE"
            }))
            await websocket.close()
            
    except Exception as e:
        print(f"[{RED}Error{RESET}] Handshake error: {e}")
        await websocket.close()

async def run_local_handshake_client(ip, port):
    uri = f"ws://{ip}:{port}"
    print(f"[{YELLOW}System{RESET}] Connecting to {uri}...")
    try:
        async with websockets.connect(uri) as websocket:
            # Step 1: Initial link request
            await websocket.send(json.dumps({
                "action": "REQUEST_LINK"
            }))
            
            msg = await websocket.recv()
            data = json.loads(msg)
            print(f"\n{MAGENTA}Peer:{RESET} \"{data['dialogue']}\"")
            
            # Step 2: DH Key Exchange
            a = random.randint(10, 100)
            A = pow(DH_G, a, DH_P)
            await websocket.send(json.dumps({
                "action": "SEND_DH_PUBLIC_KEY",
                "dh_public_key_A": A
            }))
            
            msg = await websocket.recv()
            data = json.loads(msg)
            B = data["dh_public_key"]
            K = float(pow(B, a, DH_P))
            print(f"[{GREEN}System{RESET}] Established EML Base Key K = {K}")
            
            # Step 3: Request Challenge
            await websocket.send(json.dumps({
                "action": "REQUEST_CHALLENGE"
            }))
            
            msg = await websocket.recv()
            data = json.loads(msg)
            x_val = data["challenge_x"]
            rpn_tokens = data["challenge_rpn"].split()
            print(f"[{GREEN}System{RESET}] Received Challenge Input x = {x_val}")
            print(f"[{GREEN}System{RESET}] Received Bloated EML Graph: {' '.join(rpn_tokens)}")
            
            # Evaluate proof
            proof = evaluate_eml_rpn(rpn_tokens, {"x": x_val, "K": K})
            print(f"[{GREEN}System{RESET}] Generated proof value: {proof:.8f}")
            
            # Step 4: Send Proof
            await websocket.send(json.dumps({
                "action": "SEND_PROOF",
                "proof_value": proof
            }))
            
            msg = await websocket.recv()
            data = json.loads(msg)
            print(f"{MAGENTA}Peer:{RESET} \"{data['dialogue']}\"")
            
            if "SUCCESS" in data["state"]:
                print(f"{GREEN}{BOLD}✔ HANDSHAKE GRANTED! Soul Unison established successfully!{RESET}")
                node.current_peer = {"type": "local", "ip": ip, "websocket": websocket}
                print(f"\n{CYAN}{BOLD}--- SOUL UNION SESSION STARTED WITH {ip} ---{RESET}")
                print(f"Type your messages below. Use '/exit' to close link.\n")
                
                # Run receiver listener in background
                async def receive_loop():
                    try:
                        while True:
                            chat_msg = await websocket.recv()
                            chat_data = json.loads(chat_msg)
                            if chat_data.get("action") == "CHAT_EXIT":
                                print(f"\n[{RED}System{RESET}] Peer closed the session.")
                                break
                            print(f"\n{MAGENTA}{BOLD}Peer:{RESET} {chat_data.get('content')}")
                            print(f"{CYAN}{node.name}>{RESET} ", end="", flush=True)
                    except websockets.exceptions.ConnectionClosed:
                        pass
                
                recv_task = asyncio.create_task(receive_loop())
                
                # Run sender loop
                while True:
                    text = await async_input("")
                    if text.strip() == "/exit":
                        await websocket.send(json.dumps({"action": "CHAT_EXIT"}))
                        break
                    await websocket.send(json.dumps({
                        "action": "CHAT_MESSAGE",
                        "content": text
                    }))
                    print(f"{CYAN}{node.name}>{RESET} ", end="", flush=True)
                
                recv_task.cancel()
            else:
                print(f"{RED}{BOLD}✘ HANDSHAKE DENIED! Link severed.{RESET}")
                
    except Exception as e:
        print(f"[{RED}Error{RESET}] P2P Connection error: {e}")

# ==========================================
# WIDE-AREA NOSTR PROTOCOL ENGINE
# ==========================================

async def run_nostr_client(relay_url, target_pubkey_hex=None):
    print(f"[{YELLOW}System{RESET}] Connecting to Nostr relay: {relay_url}...")
    try:
        async with websockets.connect(relay_url) as ws:
            print(f"[{GREEN}System{RESET}] Connected to relay! Subscribing to direct messages...")
            
            # Subscribe to events of kind 4 addressed to our public key
            sub_id = "navi_inbox"
            subscription = [
                "REQ",
                sub_id,
                {
                    "kinds": [4],
                    "#p": [node.pubkey_hex]
                }
            ]
            await ws.send(json.dumps(subscription))
            
            # If target key is provided, start the handshake over Nostr!
            if target_pubkey_hex:
                print(f"[{YELLOW}System{RESET}] Starting Nostr-based EML Handshake with {CYAN}{target_pubkey_hex[:12]}...{RESET}")
                
                # 1. Generate DH parameters
                a = random.randint(10, 100)
                A = pow(DH_G, a, DH_P)
                
                payload = {
                    "action": "NOSTR_DH_REQUEST",
                    "dh_public_key_A": A,
                    "name": node.name
                }
                
                # Encrypt
                encrypted_payload = encrypt_nostr_dm(
                    node.private_key, 
                    bytes.fromhex(target_pubkey_hex), 
                    json.dumps(payload)
                )
                
                # Send kind 4 event
                event = node.create_nostr_event(
                    kind=4,
                    tags=[["p", target_pubkey_hex]],
                    content=encrypted_payload
                )
                await ws.send(json.dumps(["EVENT", event]))
                print(f"  * Diffie-Hellman request sent over relay. Waiting for response...")
                
            # Listen loop
            while True:
                msg = await ws.recv()
                resp = json.loads(msg)
                
                if resp[0] == "EVENT" and resp[1] == sub_id:
                    # Received a subscription event
                    event_data = resp[2]
                    sender_pubkey = event_data["pubkey"]
                    encrypted_content = event_data["content"]
                    
                    # Decrypt DM
                    try:
                        decrypted = decrypt_nostr_dm(
                            node.private_key, 
                            bytes.fromhex(sender_pubkey), 
                            encrypted_content
                        )
                        payload = json.loads(decrypted)
                    except Exception:
                        continue # Ignore messages that fail to decrypt
                        
                    action = payload.get("action")
                    
                    if action == "NOSTR_DH_REQUEST":
                        print(f"\n[{YELLOW}System{RESET}] Incoming Nostr DH Handshake request from {CYAN}{payload['name']}{RESET}!")
                        A = payload["dh_public_key_A"]
                        b = random.randint(10, 100)
                        B = pow(DH_G, b, DH_P)
                        K = float(pow(A, b, DH_P))
                        
                        # Store session EML key mapped to sender pubkey
                        node.active_connections[sender_pubkey] = {"K": K, "b": b}
                        
                        # Respond with B
                        reply = {
                            "action": "NOSTR_DH_RESPONSE",
                            "dh_public_key_B": B,
                            "name": node.name
                        }
                        encrypted = encrypt_nostr_dm(node.private_key, bytes.fromhex(sender_pubkey), json.dumps(reply))
                        evt = node.create_nostr_event(4, [["p", sender_pubkey]], encrypted)
                        await ws.send(json.dumps(["EVENT", evt]))
                        print(f"  * Responded with public key B. Calculated EML Base Key.")
                        
                    elif action == "NOSTR_DH_RESPONSE":
                        B = payload["dh_public_key_B"]
                        K = float(pow(B, a, DH_P))
                        node.active_connections[sender_pubkey] = {"K": K, "a": a}
                        print(f"[{GREEN}System{RESET}] Received DH Public key from relay. Derived Base Key K = {K}")
                        
                        # Generate EML Challenge
                        x_val = round(random.uniform(0.5, 2.0), 4)
                        rpn = "1 1 x K E E 1 E E"
                        node.active_connections[sender_pubkey]["x"] = x_val
                        node.active_connections[sender_pubkey]["rpn"] = rpn
                        
                        challenge = {
                            "action": "NOSTR_CHALLENGE",
                            "challenge_x": x_val,
                            "challenge_rpn": rpn
                        }
                        encrypted = encrypt_nostr_dm(node.private_key, bytes.fromhex(sender_pubkey), json.dumps(challenge))
                        evt = node.create_nostr_event(4, [["p", sender_pubkey]], encrypted)
                        await ws.send(json.dumps(["EVENT", evt]))
                        print(f"  * Sent EML Challenge: {rpn} (x={x_val}) over relay. Waiting for proof...")
                        
                    elif action == "NOSTR_CHALLENGE":
                        x_val = payload["challenge_x"]
                        rpn_tokens = payload["challenge_rpn"].split()
                        K = node.active_connections[sender_pubkey]["K"]
                        
                        # Solve proof
                        proof = evaluate_eml_rpn(rpn_tokens, {"x": x_val, "K": K})
                        print(f"[{GREEN}System{RESET}] Received challenge over relay. Evaluated proof: {proof:.8f}")
                        
                        reply = {
                            "action": "NOSTR_PROOF",
                            "proof_value": proof
                        }
                        encrypted = encrypt_nostr_dm(node.private_key, bytes.fromhex(sender_pubkey), json.dumps(reply))
                        evt = node.create_nostr_event(4, [["p", sender_pubkey]], encrypted)
                        await ws.send(json.dumps(["EVENT", evt]))
                        print(f"  * Sent proof to relay. Waiting for confirmation...")
                        
                    elif action == "NOSTR_PROOF":
                        client_proof = payload["proof_value"]
                        K = node.active_connections[sender_pubkey]["K"]
                        x_val = node.active_connections[sender_pubkey]["x"]
                        rpn = node.active_connections[sender_pubkey]["rpn"]
                        
                        expected = evaluate_eml_rpn(rpn.split(), {"x": x_val, "K": K})
                        
                        if math.isclose(client_proof, expected, rel_tol=1e-9):
                            print(f"\n{GREEN}{BOLD}✔ Nostr Handshake SUCCESS! Double Soul sync authorized.{RESET}")
                            node.current_peer = {"type": "nostr", "pubkey": sender_pubkey, "ws": ws}
                            
                            reply = {
                                "action": "NOSTR_VERIFY_SUCCESS",
                                "dialogue": "Clearance Granted."
                            }
                            encrypted = encrypt_nostr_dm(node.private_key, bytes.fromhex(sender_pubkey), json.dumps(reply))
                            evt = node.create_nostr_event(4, [["p", sender_pubkey]], encrypted)
                            await ws.send(json.dumps(["EVENT", evt]))
                            print(f"Type your messages. Use '/exit' to close link.\n")
                        else:
                            print(f"\n{RED}{BOLD}✘ Nostr Handshake FAILED! Invalid proof.{RESET}")
                            reply = {
                                "action": "NOSTR_VERIFY_FAILURE",
                                "dialogue": "Access Denied."
                            }
                            encrypted = encrypt_nostr_dm(node.private_key, bytes.fromhex(sender_pubkey), json.dumps(reply))
                            evt = node.create_nostr_event(4, [["p", sender_pubkey]], encrypted)
                            await ws.send(json.dumps(["EVENT", evt]))
                            
                    elif action == "NOSTR_VERIFY_SUCCESS":
                        print(f"\n{GREEN}{BOLD}✔ Nostr Handshake SUCCESS! Double Soul sync authorized.{RESET}")
                        print(f"{MAGENTA}Peer:{RESET} \"{payload['dialogue']}\"")
                        node.current_peer = {"type": "nostr", "pubkey": sender_pubkey, "ws": ws}
                        print(f"Type your messages. Use '/exit' to close link.\n")
                        print(f"{CYAN}{node.name}>{RESET} ", end="", flush=True)
                        
                    elif action == "NOSTR_VERIFY_FAILURE":
                        print(f"\n{RED}{BOLD}✘ Nostr Handshake FAILED! Access Denied.{RESET}")
                        
                    elif action == "CHAT_MESSAGE":
                        print(f"\n{MAGENTA}{BOLD}Peer (Nostr):{RESET} {payload['content']}")
                        print(f"{CYAN}{node.name}>{RESET} ", end="", flush=True)
                        
                    elif action == "CHAT_EXIT":
                        print(f"\n[{RED}System{RESET}] Peer closed the session.")
                        node.current_peer = None
                        print(f"{CYAN}{node.name}>{RESET} ", end="", flush=True)
                        
    except Exception as e:
        print(f"[{RED}Error{RESET}] Nostr connection error: {e}")

# ==========================================
# INTERACTIVE TERMINAL LOOP
# ==========================================

async def main_cli():
    node.load_keys()
    
    # Initialize and start UDP discovery
    node.discovery = UDPDiscovery(node.name, node.pubkey_hex)
    node.discovery.start()
    
    # Start local WebSocket server in background
    async def start_server():
        try:
            async with websockets.serve(run_local_handshake_server, "0.0.0.0", node.ws_port):
                await asyncio.Future() # run forever
        except Exception as e:
            print(f"[{RED}Error{RESET}] Could not start local P2P server: {e}")
            
    server_task = asyncio.create_task(start_server())
    
    # Print welcome status
    print(f"\n{CYAN}{BOLD}--- P.E.T. COGNITIVE TERMINAL ONLINE ---{RESET}")
    print(f"  * Local Discoverer: {GREEN}ACTIVE{RESET} (UDP Port 5555)")
    print(f"  * P2P Server: {GREEN}ONLINE{RESET} (Port {node.ws_port})")
    print(f"  * Public Relay: {YELLOW}{node.nostr_relay}{RESET}")
    print(f"Type '/help' for a list of available command operations.\n")
    
    # Command loop
    while True:
        try:
            if node.current_peer:
                # Active chat mode
                text = await async_input("")
                if text.strip() == "/exit":
                    if node.current_peer["type"] == "local":
                        await node.current_peer["websocket"].send(json.dumps({"action": "CHAT_EXIT"}))
                    else:
                        ws = node.current_peer["ws"]
                        peer_key = node.current_peer["pubkey"]
                        payload = {"action": "CHAT_EXIT"}
                        enc = encrypt_nostr_dm(node.private_key, bytes.fromhex(peer_key), json.dumps(payload))
                        evt = node.create_nostr_event(4, [["p", peer_key]], enc)
                        await ws.send(json.dumps(["EVENT", evt]))
                    
                    print(f"[{YELLOW}System{RESET}] Session terminated.")
                    node.current_peer = None
                else:
                    if node.current_peer["type"] == "local":
                        await node.current_peer["websocket"].send(json.dumps({
                            "action": "CHAT_MESSAGE",
                            "content": text
                        }))
                    else:
                        ws = node.current_peer["ws"]
                        peer_key = node.current_peer["pubkey"]
                        payload = {
                            "action": "CHAT_MESSAGE",
                            "content": text
                        }
                        enc = encrypt_nostr_dm(node.private_key, bytes.fromhex(peer_key), json.dumps(payload))
                        evt = node.create_nostr_event(4, [["p", peer_key]], enc)
                        await ws.send(json.dumps(["EVENT", evt]))
                    print(f"{CYAN}{node.name}>{RESET} ", end="", flush=True)
                continue
                
            line = await async_input(f"{CYAN}{node.name}>{RESET} ")
            tokens = line.strip().split()
            if not tokens: continue
            
            cmd = tokens[0]
            
            if cmd == "/help":
                print("Available P.E.T. Commands:")
                print("  /list                 - Scan and show discovered local NetNavis")
                print("  /connect <ip> [port]  - Connect to local Navi via IP & start EML handshake")
                print("  /connect-nostr <key>  - Connect to remote Navi via Nostr pubkey hex")
                print("  /status               - Show your identity pubkey and ports")
                print("  /exit                 - Exit P.E.T. terminal")
                
            elif cmd == "/list":
                peers = node.discovery.get_discovered()
                if not peers:
                    print(f"[{YELLOW}System{RESET}] No local NetNavis found on network.")
                else:
                    print(f"\nDiscovered Local NetNavis:")
                    for k, v in peers.items():
                        print(f"  * {GREEN}{v['name']}{RESET} at {v['ip']}:{v['port']} (Key: {k[:16]}...)")
                    print()
                    
            elif cmd == "/connect":
                if len(tokens) < 2:
                    print(f"Usage: /connect <ip> [port]")
                    continue
                ip = tokens[1]
                port = int(tokens[2]) if len(tokens) > 2 else node.ws_port
                await run_local_handshake_client(ip, port)
                
            elif cmd == "/connect-nostr":
                if len(tokens) < 2:
                    print(f"Usage: /connect-nostr <pubkey_hex>")
                    continue
                target = tokens[1]
                # Start Nostr connection in task
                asyncio.create_task(run_nostr_client(node.nostr_relay, target))
                # Pause a little to print
                await asyncio.sleep(1.0)
                
            elif cmd == "/status":
                print(f"Your NetNavi Identity Profile:")
                print(f"  * Name: {CYAN}{node.name}{RESET}")
                print(f"  * Public Identity Pubkey: {YELLOW}{node.pubkey_hex}{RESET}")
                print(f"  * Local P2P Port: {node.ws_port}")
                print(f"  * UDP Discovery Port: {node.discovery.discovery_port}")
                
            elif cmd == "/exit":
                print(f"[{YELLOW}System{RESET}] Shutting down P.E.T. terminal...")
                node.discovery.stop()
                server_task.cancel()
                break
            else:
                print(f"Unknown command: '{cmd}'. Type '/help' for options.")
                
        except (KeyboardInterrupt, EOFError):
            print(f"\n[{YELLOW}System{RESET}] Shutting down P.E.T. terminal...")
            node.discovery.stop()
            server_task.cancel()
            break
        except Exception as e:
            print(f"[{RED}Error{RESET}] Command loop error: {e}")

if __name__ == "__main__":
    try:
        # Start command loop
        asyncio.run(main_cli())
    except KeyboardInterrupt:
        pass
