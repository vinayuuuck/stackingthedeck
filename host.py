#!/usr/bin/env python3
import argparse
import json
import socket
import threading
import time
import random
from typing import List, Tuple, Dict, Any
from collections import Counter


# --- Simple JSON-lines socket helpers ---
def send_msg(sock: socket.socket, obj: Dict[str, Any]) -> None:
    # IMPORTANT: real newline, not a backslash-n literal
    data = (json.dumps(obj) + "\n").encode("utf-8")
    sock.sendall(data)


def recv_line(sock: socket.socket, timeout: float = None) -> bytes:
    sock.settimeout(timeout)
    buf = bytearray()
    while True:
        b = sock.recv(1)
        if not b:
            raise ConnectionError("peer closed")
        if b == b"\n":
            break
        buf.extend(b)
    return bytes(buf)


def recv_msg(sock: socket.socket, timeout: float = None) -> Dict[str, Any]:
    raw = recv_line(sock, timeout=timeout)
    return json.loads(raw.decode("utf-8"))


# --- Game mechanics ---

VALUES = list(range(1, 9))  # 1..8


def make_deck_values() -> List[int]:
    return VALUES * 2  # two of each (two suits)


def choose_V(k: int) -> Tuple[List[int], List[int]]:
    """Return (V, S_pool) where V has size k and includes at least one 1."""
    if k < 1 or k > 16:
        raise ValueError("k must be between 1 and 16")
    deck = make_deck_values()
    # Ensure at least one 1 in V
    V = [1]
    deck.remove(1)
    for _ in range(k - 1):
        choice = random.choice(deck)
        V.append(choice)
        deck.remove(choice)
    S_pool = deck[:]
    random.shuffle(S_pool)
    return V, S_pool


def is_subsequence_with_multiplicity(seq: List[int], superseq: List[int]) -> bool:
    i = 0
    for x in superseq:
        if i < len(seq) and x == seq[i]:
            i += 1
    return i == len(seq)


def simulate(sequence: List[int], start: int):
    n = len(sequence)
    assert n == 16, "Sequence must be length 16"
    if not (1 <= start <= 8):
        return ("", "InvalidStart")
    revealed = [False] * n
    annotated = [str(x) for x in sequence]
    p = -1
    m = start
    while True:
        rem = n - (p + 1)
        if m > rem:
            for idx, flag in enumerate(revealed):
                if flag:
                    annotated[idx] = f"({annotated[idx]})"
            return (" ".join(annotated), "Chooser")
        p = p + m
        revealed[p] = True
        annotated[p] = f"({sequence[p]})"
        m = sequence[p]
        if p == n - 1 and sequence[p] == 1:
            return (" ".join(annotated), "Arranger")


def main():
    parser = argparse.ArgumentParser(description="Host for Alice vs Charles card game")
    parser.add_argument("port", type=int, help="Port to listen on (localhost only)")
    parser.add_argument("k", type=int, help="Size of V (must include at least one 1)")
    args = parser.parse_args()

    HOST = "127.0.0.1"  # simplified: localhost only
    PORT = args.port
    K = args.k

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen(8)
    print(
        f"[HOST] Listening on {HOST}:{PORT} ... waiting for Arranger and Chooser clients"
    )

    roles: Dict[str, Tuple[socket.socket, str]] = {}
    lock = threading.Lock()
    ready_evt = threading.Event()

    def handle_handshake(sock: socket.socket, addr):
        print(f"[HOST] Client connected from {addr}")
        try:
            hello = recv_msg(sock, timeout=30.0)
            print(f"[HOST] Received HELLO from {addr}: {hello}")
        except Exception as e:
            print(f"[HOST] Failed to receive hello from {addr}: {e}")
            try:
                send_msg(sock, {"type": "ERROR", "reason": "HELLO not received"})
            except Exception:
                pass
            sock.close()
            return
        if hello.get("type") != "HELLO":
            try:
                send_msg(sock, {"type": "ERROR", "reason": "Expected HELLO"})
            except Exception:
                pass
            sock.close()
            return
        name = hello.get("name", "Unknown")
        role = hello.get("role", "")
        if role not in ("Arranger", "Chooser"):
            try:
                send_msg(
                    sock,
                    {"type": "ERROR", "reason": "Role must be Arranger or Chooser"},
                )
            except Exception:
                pass
            sock.close()
            return
        with lock:
            if role in roles:
                try:
                    send_msg(
                        sock, {"type": "ERROR", "reason": f"Role {role} already taken"}
                    )
                except Exception:
                    pass
                sock.close()
                return
            roles[role] = (sock, name)
            print(f"[HOST] {role} is {name}")
            try:
                send_msg(sock, {"type": "WELCOME", "you_are": role})
            except Exception:
                pass
            if "Arranger" in roles and "Chooser" in roles:
                ready_evt.set()

    def accept_loop():
        while True:
            try:
                sock, addr = srv.accept()
            except OSError:
                break
            threading.Thread(
                target=handle_handshake, args=(sock, addr), daemon=True
            ).start()

    threading.Thread(target=accept_loop, daemon=True).start()

    # Wait until both roles present
    ready_evt.wait()
    arranger_sock, arranger_name = roles["Arranger"]
    chooser_sock, chooser_name = roles["Chooser"]

    # Create V and S_pool
    try:
        V, S_pool = choose_V(K)
    except Exception as e:
        for role in ("Arranger", "Chooser"):
            if role in roles:
                try:
                    send_msg(roles[role][0], {"type": "ERROR", "reason": str(e)})
                except Exception:
                    pass
        print(f"[HOST] Error choosing V: {e}")
        return

    # Send S_pool to Chooser and ask for an ordering S'
    send_msg(chooser_sock, {"type": "ORDER_REQUEST", "S_pool": S_pool})
    print(
        f"[HOST] Sent S_pool to Chooser ({chooser_name}). Waiting up to 120s for S'..."
    )
    t0 = time.time()
    try:
        msg = recv_msg(chooser_sock, timeout=120.0)
    except socket.timeout:
        print("[HOST] Chooser did not respond in time. Arranger wins by timeout.")
        try:
            send_msg(
                chooser_sock,
                {
                    "type": "RESULT",
                    "winner": "Arranger",
                    "reason": "Chooser timeout on ordering S'",
                },
            )
        except Exception:
            pass
        try:
            send_msg(
                arranger_sock,
                {
                    "type": "RESULT",
                    "winner": "Arranger",
                    "reason": "Chooser timeout on ordering S'",
                },
            )
        except Exception:
            pass
        return
    except Exception as e:
        print(f"[HOST] Chooser connection error: {e}")
        try:
            send_msg(
                arranger_sock,
                {
                    "type": "RESULT",
                    "winner": "Arranger",
                    "reason": "Chooser connection error",
                },
            )
        except Exception:
            pass
        return
    elapsed = time.time() - t0
    if msg.get("type") != "ORDER_RESPONSE":
        print("[HOST] Invalid response from Chooser.")
        try:
            send_msg(
                chooser_sock, {"type": "ERROR", "reason": "Expected ORDER_RESPONSE"}
            )
        except Exception:
            pass
        return
    S_prime = msg.get("S_prime", [])
    if not isinstance(S_prime, list) or sorted(S_prime) != sorted(S_pool):
        try:
            send_msg(
                chooser_sock,
                {"type": "ERROR", "reason": "S_prime must be a reordering of S_pool"},
            )
        except Exception:
            pass
        return
    print(
        f"[HOST] Received S' in {elapsed:.2f}s from Chooser. Forwarding to Arranger..."
    )

    # Ask Arranger to insert V into S' and end with 1
    send_msg(arranger_sock, {"type": "ARRANGE_REQUEST", "S_prime": S_prime, "V": V})
    try:
        msg2 = recv_msg(arranger_sock, timeout=120.0)
    except Exception as e:
        print(f"[HOST] Arranger connection error: {e}")
        try:
            send_msg(
                chooser_sock,
                {
                    "type": "RESULT",
                    "winner": "Chooser",
                    "reason": "Arranger connection error",
                },
            )
        except Exception:
            pass
        return
    if msg2.get("type") != "ARRANGE_RESPONSE":
        try:
            send_msg(
                arranger_sock, {"type": "ERROR", "reason": "Expected ARRANGE_RESPONSE"}
            )
        except Exception:
            pass
        return
    final_seq = msg2.get("sequence", [])
    if not isinstance(final_seq, list) or len(final_seq) != 16:
        try:
            send_msg(
                arranger_sock,
                {"type": "ERROR", "reason": "Sequence must be list of 16 ints"},
            )
        except Exception:
            pass
        return
    if sorted(final_seq) != sorted(S_prime + V):
        reason = "Rule violated: final sequence is not a permutation of S' ∪ V"
        print(f"[HOST] {reason}")
        try:
            send_msg(arranger_sock, {"type": "RULE_VIOLATED", "reason": reason})
            send_msg(chooser_sock, {"type": "RULE_VIOLATED", "reason": reason})
        except Exception:
            pass
        return
    # Check ends with 1
    if final_seq[-1] != 1:
        reason = "Rule violated: final sequence must end with 1"
        print(f"[HOST] {reason}")
        try:
            send_msg(arranger_sock, {"type": "RULE_VIOLATED", "reason": reason})
            send_msg(chooser_sock, {"type": "RULE_VIOLATED", "reason": reason})
        except Exception:
            pass
        return
    # Check preserves S' order
    it = iter(final_seq)
    for val in S_prime:
        for x in it:
            if x == val:
                break
        else:
            reason = "Rule violated: Arranger changed the relative order of S'"
            print(f"[HOST] {reason}")
            try:
                send_msg(arranger_sock, {"type": "RULE_VIOLATED", "reason": reason})
                send_msg(chooser_sock, {"type": "RULE_VIOLATED", "reason": reason})
            except Exception:
                pass
            return

    print(f"[HOST] Final sequence accepted: {' '.join(map(str, final_seq))}")

    # Ask Chooser to pick a start number
    send_msg(chooser_sock, {"type": "PICK_START_REQUEST", "sequence": final_seq})
    try:
        pick_msg = recv_msg(chooser_sock, timeout=60.0)
    except Exception as e:
        print(f"[HOST] Chooser connection error when picking start: {e}")
        try:
            send_msg(
                arranger_sock,
                {
                    "type": "RESULT",
                    "winner": "Arranger",
                    "reason": "Chooser disconnected before picking",
                },
            )
        except Exception:
            pass
        return
    if pick_msg.get("type") != "PICK_START_RESPONSE":
        try:
            send_msg(
                chooser_sock,
                {"type": "ERROR", "reason": "Expected PICK_START_RESPONSE"},
            )
        except Exception:
            pass
        return
    start_num = pick_msg.get("start", None)
    if not isinstance(start_num, int) or not (1 <= start_num <= 8):
        try:
            send_msg(
                chooser_sock, {"type": "ERROR", "reason": "Start must be integer 1..8"}
            )
        except Exception:
            pass
        return

    annotated, winner = simulate(final_seq, start_num)

    print("[HOST] -------- RESULT --------")
    print(f"Sequence: {annotated}")
    print(f"Winner: {winner}")
    print("------------------------------")

    result_payload = {
        "type": "RESULT",
        "winner": winner,
        "sequence_annotated": annotated,
        "final_sequence": final_seq,
        "start": start_num,
        "V": V,
        "S_pool": S_pool,
        "S_prime": S_prime,
    }
    for role in ("Chooser", "Arranger"):
        try:
            send_msg(roles[role][0], result_payload)
        except Exception:
            pass


if __name__ == "__main__":
    main()
