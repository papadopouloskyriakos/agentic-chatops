#!/usr/bin/env python3
"""APC AOS v3.9.4 menu-mode driver (raw socket, IAC refuse-all).

pdu.py list                         -> print outlet list (read-only)
pdu.py {on|off} <outlet> <guard>    -> act only if the outlet screen contains <guard>
Env: PDU_HOST (default 10.0.181.X), PDU_USER, PDU_PASS
"""
import os, re, socket, sys, time

HOST = os.environ.get("PDU_HOST", "10.0.181.X")
USER, PW = os.environ.get("PDU_USER", "operator"), os.environ["PDU_PASS"]
IAC, DONT, DO, WONT, WILL = 255, 254, 253, 252, 251


class T:
    def __init__(self):
        self.s = socket.create_connection((HOST, 23), timeout=10)
        self.buf = b""

    def _pump(self, t=1.0):
        self.s.settimeout(t)
        try:
            data = self.s.recv(4096)
        except socket.timeout:
            return False
        if not data:
            raise EOFError("connection closed")
        out, i = bytearray(), 0
        while i < len(data):
            b = data[i]
            if b == IAC and i + 2 < len(data) + 1 and i + 1 < len(data):
                cmd = data[i + 1]
                if cmd in (DO, DONT, WILL, WONT) and i + 2 < len(data):
                    opt = data[i + 2]
                    self.s.sendall(bytes([IAC, WONT if cmd in (DO, DONT) else DONT, opt]))
                    i += 3
                    continue
                i += 2
                continue
            out.append(b)
            i += 1
        self.buf += bytes(out)
        return True

    def expect(self, pat, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            m = re.search(pat, self.buf.decode("latin1"), re.S)
            if m:
                txt = self.buf.decode("latin1")
                self.buf = b""
                return txt
            self._pump(0.5)
        raise TimeoutError(f"waiting for {pat!r}; got tail: {self.buf.decode('latin1')[-400:]!r}")

    def send(self, s):
        self.s.sendall(s.encode() + b"\r")


def pick(screen, label):
    m = re.search(r"(\d+)\s*-\s*" + label, screen)
    if not m:
        raise SystemExit(f"ABORT: menu option {label!r} not found in:\n{screen[-800:]}")
    return m.group(1)


def main():
    act = sys.argv[1]
    t = T()
    t.expect(r"User Name\s*:")
    t.send(USER)
    t.expect(r"Password\s*:")
    t.send(PW)
    scr = t.expect(r"> ?$")
    t.send(pick(scr, r"Device Manager"))
    scr = t.expect(r"> ?$")
    t.send(pick(scr, r"Outlet Management"))
    scr = t.expect(r"> ?$")
    t.send(pick(scr, r"Outlet Control/Configuration"))
    scr = t.expect(r"> ?$")
    if act == "list":
        print(scr)
        t.s.close()
        return
    outlet, guard = sys.argv[2], sys.argv[3]
    line = re.search(r"^\s*" + re.escape(outlet) + r"-\s+(.*)$", scr, re.M)
    if not line or guard not in line.group(1):
        raise SystemExit(f"ABORT: outlet {outlet} line does not contain guard {guard!r}: {line.group(0) if line else None!r}")
    print("LIST LINE:", line.group(0).strip())
    t.send(outlet)
    scr = t.expect(r"> ?$")
    if guard not in scr:
        raise SystemExit(f"ABORT: outlet screen lacks guard:\n{scr}")
    print("OUTLET SCREEN:", " | ".join(l.strip() for l in scr.splitlines() if l.strip())[-400:])
    t.send(pick(scr, r"Control Outlet"))
    scr = t.expect(r"> ?$")
    t.send(pick(scr, {"on": r"Immediate On", "off": r"Immediate Off"}[act]))
    scr = t.expect(r"(YES|cancel)")
    if guard not in scr and outlet not in scr:
        raise SystemExit(f"ABORT: confirm screen lacks outlet id:\n{scr}")
    t.send("YES")
    scr = t.expect(r"(continue|> ?$)", timeout=20)
    print("RESULT:", " | ".join(l.strip() for l in scr.splitlines() if l.strip())[-300:])
    t.send("")
    time.sleep(1)
    t.s.close()


if __name__ == "__main__":
    main()
