"""Pure helpers (no I/O) for the scoring-weight tools: validation, the resulting vector, rank shifts.

The validation is EXACTLY the server's ``update_weights`` rule (``comparison._validate_weight_dict``): each
value numeric and 0..100. The server has no sum rule and no key-set rule, so neither refuses here; both
come back as warnings. The one extra refusal is a modifier (``bonus`` ...): the preview route divides every
value by 100 and ``update_weights`` would store it under ``weights``, not ``modifiers``.
"""

import math
from typing import Any, Optional

from config.category_filter import VALID_WEIGHT_COLUMNS
from config.scoring_config import NORMALIZATION_TOLERANCE, normalise_percent_weights

SUFFIX = "_percent"
BIGGEST_SHOWN = 5
MODIFIER_NAMES = frozenset({"bonus", "noise_tolerance_multiplier"})
NO_CHANGE = "no change: the proposal equals the current weights"


def base_key(key: str) -> str:
    return key[:-len(SUFFIX)] if key.endswith(SUFFIX) else key


def percent_key(key: str) -> str:
    return base_key(key) + SUFFIX


def is_modifier(key: str) -> bool:
    name = base_key(key)
    return name in MODIFIER_NAMES or name.startswith("_") or name.endswith("_multiplier")


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def resulting_vector(current: dict, proposal: Optional[dict], deltas: Optional[dict]) -> tuple[list[str], dict]:
    """``(issues, vector)``: the ``*_percent`` vector the proposal produces over ``current``.

    ``proposal`` is a partial map merged over the current values; ``deltas`` are signed percentage points
    added to them. Exactly one is given. Every issue is listed; the vector is only meaningful when none is.
    """
    if (proposal is None) == (deltas is None):
        return ["give exactly one of `weights` or `deltas`"], dict(current)
    given = proposal if proposal is not None else deltas
    if not given:
        return ["the proposal is empty"], dict(current)
    issues: list[str] = []
    vector = dict(current)
    for raw_key, value in given.items():
        key = percent_key(raw_key)
        if is_modifier(raw_key):
            issues.append(f"`{raw_key}`: bonus and modifiers are not editable through the assistant")
            continue
        if not _number(value):
            issues.append(f"`{raw_key}` must be numeric, got {value!r}")
            continue
        final = value if proposal is not None else current.get(key, 0) + value
        if not 0 <= final <= 100:
            issues.append(f"`{raw_key}` would be {final:g}; a weight must be between 0 and 100")
            continue
        vector[key] = final
    if not issues and not changed_keys(current, vector):
        issues.append(NO_CHANGE)
    return issues, vector


def changed_keys(before: dict, after: dict) -> dict:
    """``{key: {"from", "to"}}`` for every key whose value differs; a missing key counts as 0."""
    return {key: {"from": before.get(key, 0), "to": after.get(key, 0)}
            for key in sorted(set(before) | set(after)) if before.get(key, 0) != after.get(key, 0)}


def weights_sum(vector: dict) -> float:
    return round(sum(v for v in vector.values() if _number(v)), 4)


def warnings_for(vector: dict) -> list[dict]:
    """The non-blocking findings: keys the config loader would drop, and a sum it would rescale."""
    found = [{"code": "unknown_key", "key": key,
              "message": f"`{key}` is not a scored metric; it is stored as typed and a validating load drops it"}
             for key in vector if base_key(key) not in VALID_WEIGHT_COLUMNS]
    total = weights_sum(vector)
    if abs(total - 100) > NORMALIZATION_TOLERANCE:
        found.append({"code": "sum_outside_95_105", "sum": total,
                      "message": f"the sum is {total:g}; the config loader rescales weights to 100 when it is "
                                 "outside 95..105"})
    return found


def route_vector(vector: dict) -> dict:
    """What ``preview_score`` must be sent for ``vector``: the scorer's own normalisation, back in percent.

    The route divides each value by 100 and multiplies it into the metric, so sending
    ``normalise_percent_weights(vector) * 100`` makes it use exactly the decimals ``get_weights`` gives.
    """
    return {key: value * 100 for key, value in normalise_percent_weights(vector).items()}


def route_vectors(first: dict, second: dict) -> tuple[dict, dict]:
    """Both vectors as route bodies over the same keys, so a key set to 0 in one is sent as 0, not left to the config."""
    one, two = route_vector(first), route_vector(second)
    keys = sorted(set(one) | set(two))
    return {k: one.get(k, 0) for k in keys}, {k: two.get(k, 0) for k in keys}


def _ranks(scores: dict) -> dict:
    ordered = sorted(scores, key=lambda path: (-scores[path], path))
    return {path: rank for rank, path in enumerate(ordered, start=1)}


def rank_changes(before: dict, after: dict) -> dict:
    """Rank movement within the sample: rank 1 is the best score, ties keep path order. ``delta`` > 0 is up."""
    old, new = _ranks(before), _ranks(after)
    moves = [{"path": p, "from_rank": old[p], "to_rank": new[p], "delta": old[p] - new[p]} for p in old]
    biggest = sorted((m for m in moves if m["delta"]), key=lambda m: (-abs(m["delta"]), m["path"]))
    return {"moved_up": sum(1 for m in moves if m["delta"] > 0),
            "moved_down": sum(1 for m in moves if m["delta"] < 0),
            "unchanged": sum(1 for m in moves if m["delta"] == 0),
            "biggest": biggest[:BIGGEST_SHOWN]}


def evenly_spaced(items: list, count: int) -> list:
    """``count`` items at evenly spaced positions (deterministic: a repeat is comparable); all when fewer."""
    if len(items) <= count:
        return list(items)
    return [items[i * len(items) // count] for i in range(count)]


def digest_options(category: str, current: dict, resulting: dict) -> dict:
    """What a preview digest is bound to: the category, the weights it started from and the ones it proposes."""
    return {"category": category, "current": dict(sorted(current.items())),
            "resulting": dict(sorted(resulting.items()))}
