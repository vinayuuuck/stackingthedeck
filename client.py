#!/usr/bin/env python3
import argparse
import json
import random
import socket
from typing import Any, Dict, List

# -------- Replace these three functions with your own strategy ----------


def arrange_S(S_pool: List[int]) -> List[int]:
    """Return an ordering S' of the multiset S_pool. Placeholder: random permutation."""
    Sprime = S_pool[:]
    random.shuffle(Sprime)
    return Sprime


def insert_V(S_prime: List[int], V: List[int]) -> List[int]:
    """Return a full sequence (len=16) that is a permutation of S' union V, preserves S' order, ends with 1. Placeholder random interleave."""
    seq = S_prime[:]
    bag = V[:]

    # Ensure a 1 at the end; reserve from V if possible
    reserve_one = None
    if 1 in bag:
        bag.remove(1)
        reserve_one = 1

    out: List[int] = []
    for x in seq:
        n_insert = 0 if not bag else random.randint(0, min(2, len(bag)))
        for _ in range(n_insert):
            out.append(bag.pop(random.randrange(len(bag))))
        out.append(x)
    # append leftovers
    random.shuffle(bag)
    out.extend(bag)

    if reserve_one is not None:
        out.append(1)
    else:
        # move a 1 to end if any, else force (should not happen under spec)
        if 1 in out:
            out.remove(1)
        out.append(1)

    return out[:16]


def choose_start(sequence: List[int]) -> int:
    """Return starting number between 1 and 8 inclusive. Placeholder: random choice."""
    return random.randint(1, 8)


# -------- Networking helpers ----------


def send_msg(sock: socket.socket, obj: Dict[str, Any]) -> None:
    # IMPORTANT: real newline, not a backslash-n literal
    data = (json.dumps(obj) + "\n").encode("utf-8")
    sock.sendall(data)


def recv_msg(sock: socket.socket, timeout: float = None) -> Dict[str, Any]:
    sock.settimeout(timeout)
    buf = bytearray()
    while True:
        b = sock.recv(1)
        if not b:
            raise ConnectionError("Server closed")
        if b == b"\n":
            break
        buf.extend(b)
    return json.loads(bytes(buf).decode("utf-8"))


def main():
    parser = argparse.ArgumentParser(
        description="Non-interactive strategy client for Alice/Charles game (localhost only)"
    )
    parser.add_argument("port", type=int, help="Port")
    parser.add_argument("name", type=str, help="Your display name")
    parser.add_argument(
        "role", type=str, choices=["Arranger", "Chooser"], help="Your role"
    )
    parser.add_argument("--seed", type=int, default=None, help="Random seed (optional)")
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    HOST = "127.0.0.1"  # simplified: always localhost
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((HOST, args.port))

    # Introduce ourselves
    print("[CLIENT] Sending HELLO...")
    send_msg(sock, {"type": "HELLO", "name": args.name, "role": args.role})
    print("[CLIENT] HELLO sent. Waiting for WELCOME...")
    welcome = recv_msg(sock, timeout=30.0)
    if welcome.get("type") != "WELCOME":
        print("Failed to join:", welcome)
        return
    print(f"[CLIENT] Joined as {args.role}. Waiting for instructions...")

    while True:
        msg = recv_msg(sock, timeout=None)
        mtype = msg.get("type")
        if mtype == "ERROR":
            print("[SERVER ERROR]", msg.get("reason"))
            break
        if mtype == "ORDER_REQUEST" and args.role == "Chooser":
            S_pool = msg.get("S_pool", [])
            Sprime = arrange_S(S_pool)
            send_msg(sock, {"type": "ORDER_RESPONSE", "S_prime": Sprime})
        elif mtype == "ARRANGE_REQUEST" and args.role == "Arranger":
            S_prime = msg.get("S_prime", [])
            V = msg.get("V", [])
            full_seq = insert_V(S_prime, V)
            send_msg(sock, {"type": "ARRANGE_RESPONSE", "sequence": full_seq})
        elif mtype == "PICK_START_REQUEST" and args.role == "Chooser":
            sequence = msg.get("sequence", [])
            start = choose_start(sequence)
            send_msg(sock, {"type": "PICK_START_RESPONSE", "start": start})
        elif mtype == "RULE_VIOLATED":
            print("[SERVER] Rule violated:", msg.get("reason"))
            break
        elif mtype == "RESULT":
            print("----- GAME RESULT -----")
            print("Winner:", msg.get("winner"))
            print("Annotated sequence:", msg.get("sequence_annotated"))
            print("Start number:", msg.get("start"))
            print("V:", msg.get("V"))
            print("S (pool):", msg.get("S_pool"))
            print("S' (ordered):", msg.get("S_prime"))
            print("-----------------------")
            break
        else:
            pass


if __name__ == "__main__":
    main()
