"""Compare the face-test reports from several machines and apply the README's must-stay gates.

    python testdb/ci_compare.py linux.txt docker.txt windows.txt

Fails if any report differs from the first one, or if the first report breaks a gate:
no known face under a wrong name, and with 3 references at T = 0.35 no primary face named
wrongly and no bystander named.
"""

import argparse
import difflib
import re
import sys
from pathlib import Path


def gates(lines):
    """Failed gate descriptions for one report."""
    failed = []
    known = next((line for line in lines if line.startswith("known faces ")), "")
    match = re.search(r"wrong (\d+)", known)
    if not match or int(match.group(1)):
        failed.append(f"known faces under a wrong name: {known or 'line missing'}")
    in_three = False
    row = None
    for line in lines:
        if re.match(r"^\d+ reference photo", line):
            in_three = line.startswith("3 ")
        elif in_three and re.match(r"^\s+0\.35 \|", line):
            row = line
    numbers = [int(n) for n in re.findall(r"\d+", row.split("|", 1)[1])] if row else []
    if len(numbers) != 5:
        failed.append(f"3-reference T=0.35 row missing or unreadable: {row!r}")
    else:
        p_right, p_wrong, p_unknown, b_unknown, b_named = numbers
        if p_wrong:
            failed.append(f"open set, 3 references, T=0.35: {p_wrong} primary faces named wrongly")
        if b_named:
            failed.append(f"open set, 3 references, T=0.35: {b_named} bystanders named")
    return failed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("reports", nargs="+", type=Path)
    args = parser.parse_args()

    texts = {r.stem: r.read_text(encoding="utf8").splitlines() for r in args.reports}
    first, *rest = texts
    print(f"--- {first} (reference)")
    print("\n".join(texts[first]))
    ok = True
    for name in rest:
        if texts[name] == texts[first]:
            print(f"--- {name}: identical to {first}")
        else:
            ok = False
            print(f"--- {name}: DIFFERS from {first}")
            print("\n".join(difflib.unified_diff(texts[first], texts[name], first, name, lineterm="")))
    for failure in gates(texts[first]):
        ok = False
        print(f"GATE FAILED: {failure}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
