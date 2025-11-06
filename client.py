#!/usr/bin/env python3
import argparse
import json
import random
import socket
from typing import Any, Dict, List, Tuple, Optional


from collections import Counter

NODE_LIMIT = 500000


def simulate_full(sequence: List[int], start: int) -> str:
    n = len(sequence)
    p = -1
    m = start
    while True:
        rem = n - (p + 1)
        if m > rem:
            return "Chooser"
        p = p + m
        m = sequence[p]
        if p == n - 1 and sequence[p] == 1:
            return "Arranger"


def simulate_partial_prefix(prefix: List[int], start: int, total_len: int) -> str:
    n = total_len
    p = -1
    m = start
    while True:
        rem = n - (p + 1)
        if m > rem:
            return "Chooser"
        p = p + m
        if p < len(prefix):
            m = prefix[p]
            if p == n - 1:
                if prefix[p] == 1:
                    return "Arranger"
                else:
                    return "ArrangerFail"
            continue
        else:
            return "Undecided"


def arranger_oracle(
    S_prime: List[int], V: List[int], node_limit: int = NODE_LIMIT
) -> Optional[List[int]]:
    n = 16
    total_len = len(S_prime) + len(V)
    if total_len != n:
        return None
    bag_counter = Counter(V)
    if bag_counter[1] == 0 and S_prime and S_prime[-1] != 1:
        return None
    if bag_counter[1] > 0:
        bag_counter[1] -= 1
        if bag_counter[1] == 0:
            del bag_counter[1]
        reserve_one = True
    else:
        reserve_one = False
    stack = []
    start_state = (0, tuple(sorted(bag_counter.elements())), [])
    stack.append(start_state)
    seen: Dict[Tuple[int, Tuple[int, ...], int], bool] = {}
    nodes = 0
    while stack:
        if nodes > node_limit:
            break
        nodes += 1
        idx_s, vtuple, prefix = stack.pop()
        vbag = list(vtuple)
        key = (idx_s, vtuple, len(prefix))
        if key in seen:
            continue
        seen[key] = True
        prune = False
        for s in range(1, 9):
            status = simulate_partial_prefix(prefix, s, n)
            if status == "Chooser" or status == "ArrangerFail":
                prune = True
                break
        if prune:
            continue
        if len(prefix) == n - 1:
            last_candidates = []
            if idx_s < len(S_prime):
                if S_prime[idx_s] == 1:
                    last_candidates.append(1)
            for v in vbag:
                if v == 1:
                    last_candidates.append(1)
                    break
            if not last_candidates:
                continue
            final_seq = prefix + [1]
            ok = True
            for s in range(1, 9):
                if simulate_full(final_seq, s) != "Arranger":
                    ok = False
                    break
            if ok:
                return final_seq
            else:
                continue
        if idx_s < len(S_prime):
            next_val = S_prime[idx_s]
            new_prefix = prefix + [next_val]
            stack.append((idx_s + 1, vtuple, new_prefix))
        if vbag:
            seen_values = set()
            for i, val in enumerate(vbag):
                if val in seen_values:
                    continue
                seen_values.add(val)
                new_v = vbag[:i] + vbag[i + 1 :]
                new_vtuple = tuple(sorted(new_v))
                new_prefix = prefix + [val]
                stack.append((idx_s, new_vtuple, new_prefix))
    return None


def unique_permutations_multiset(items: List[int]):
    counts = Counter(items)
    keys = sorted(counts.keys())

    def gen(prefix, counts_left, length):
        if len(prefix) == length:
            yield list(prefix)
            return
        for k in keys:
            if counts_left.get(k, 0) > 0:
                counts_left[k] -= 1
                prefix.append(k)
                yield from gen(prefix, counts_left, length)
                prefix.pop()
                counts_left[k] += 1

    yield from gen([], dict(counts), len(items))


def arrange_S(S_pool: List[int]) -> List[int]:
    pool = S_pool[:]
    if not pool:
        return []
    if len(pool) <= 8:
        for perm in unique_permutations_multiset(pool):
            oracle = arranger_oracle(perm, [])
            if oracle is None:
                return perm
        return sorted(pool, reverse=True)
    best_candidate = None
    for perm in unique_permutations_multiset(pool):
        possible = True
        hypothetical_V = [1]
        oracle = arranger_oracle(perm, hypothetical_V)
        if oracle is None:
            return perm
        if best_candidate is None:
            best_candidate = perm
    if best_candidate is not None:
        return best_candidate
    return sorted(pool, reverse=True)


def insert_V(S_prime: List[int], V: List[int]) -> List[int]:
    seq = arranger_oracle(S_prime, V)
    if seq is not None:
        return seq
    n = 16
    seq_out: List[int] = []
    seq_out.extend(S_prime)
    bag = V[:]
    if 1 in bag:
        bag.remove(1)
        bag.append(1)
    while len(seq_out) < n:
        if bag:
            seq_out.append(bag.pop(0))
        else:
            seq_out.append(1)
    if seq_out[-1] != 1:
        for i in range(len(seq_out) - 1):
            if seq_out[i] == 1:
                seq_out[i], seq_out[-1] = seq_out[-1], seq_out[i]
                break
        else:
            seq_out[-1] = 1
    return seq_out[:n]


def choose_start(sequence: List[int]) -> int:
    for s in range(1, 9):
        if simulate_full(sequence, s) == "Chooser":
            return s
    best = 1
    best_revealed = -1
    n = len(sequence)
    for s in range(1, 9):
        p = -1
        m = s
        revealed = 0
        while True:
            rem = n - (p + 1)
            if m > rem:
                break
            p = p + m
            revealed += 1
            m = sequence[p]
            if p == n - 1 and sequence[p] == 1:
                revealed = -1
                break
        if revealed > best_revealed:
            best_revealed = revealed
            best = s
    return best


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
