"""Print printable strings in the exe with their RAM addresses."""
import re
import sys

data = open(sys.argv[1], "rb").read()
pat = re.compile(sys.argv[2].encode(), re.I) if len(sys.argv) > 2 else None
for m in re.finditer(rb"[\x20-\x7e]{5,}", data):
    if pat and not pat.search(m.group()):
        continue
    ram = m.start() - 0x800 + 0x80010000
    print(f"0x{ram:08X}  {m.group().decode()}")
