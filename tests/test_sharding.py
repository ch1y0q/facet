"""The CI slices cover every test file exactly once."""

import pytest

from tests._sharding import files_for_shard, parse_shard

NODEIDS = (
    [f"tests/test_big.py::test_{i}" for i in range(9)]
    + [f"tests/test_mid.py::TestX::test_{i}" for i in range(5)]
    + [f"tests/test_small_{n}.py::test_one" for n in range(7)]
)


@pytest.mark.parametrize("total", [1, 2, 4, 5])
def test_slices_are_disjoint_and_complete(total):
    slices = [files_for_shard(NODEIDS, index, total) for index in range(1, total + 1)]
    every_file = {nodeid.split("::")[0] for nodeid in NODEIDS}
    assert set().union(*slices) == every_file
    assert sum(len(s) for s in slices) == len(every_file)


def test_slices_are_balanced_by_test_count():
    sizes = []
    for index in range(1, 4):
        files = files_for_shard(NODEIDS, index, 3)
        sizes.append(sum(1 for nodeid in NODEIDS if nodeid.split("::")[0] in files))
    assert sorted(sizes) == [6, 6, 9]


def test_assignment_ignores_collection_order():
    assert files_for_shard(NODEIDS, 2, 4) == files_for_shard(list(reversed(NODEIDS)), 2, 4)


@pytest.mark.parametrize("value", ["0/4", "5/4", "4", "a/b"])
def test_malformed_shard_is_refused(value):
    with pytest.raises(ValueError):
        parse_shard(value)
