"""Split the suite into N disjoint slices for parallel CI jobs.

CI runs one job per slice with ``FACET_TEST_SHARD=<index>/<total>`` (1-based).
Slices are whole files, so module- and class-scoped fixtures still run once
per file, and files are dealt largest-first onto the lightest slice so the
jobs finish close together. The assignment depends only on the collected
node ids, so every xdist worker of one job computes the same slice.
"""

from collections import Counter

SHARD_ENV = "FACET_TEST_SHARD"


def parse_shard(value):
    """Return ``(index, total)`` from ``"<index>/<total>"``, 1-based."""
    index, _, total = value.partition("/")
    index, total = int(index), int(total)
    if not 1 <= index <= total:
        raise ValueError(f"{SHARD_ENV}={value!r}: expected <index>/<total> with 1 <= index <= total")
    return index, total


def files_for_shard(nodeids, index, total):
    """Return the set of test files slice ``index`` of ``total`` runs."""
    counts = Counter(nodeid.split("::", 1)[0] for nodeid in nodeids)
    loads = [0] * total
    owned = [set() for _ in range(total)]
    for path, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        lightest = loads.index(min(loads))
        loads[lightest] += count
        owned[lightest].add(path)
    return owned[index - 1]
