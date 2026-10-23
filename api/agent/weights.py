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


NEAR_MISS_FRACTION = 0.10
BOUND_SUFFIXES = ("_min", "_max")
TERMINAL_KINDS = ("recompute", "panoramas")


def nonzero(vector: Any) -> dict:
    """The numeric, non-zero entries of a stored weight block, whatever the key format."""
    return {k: v for k, v in (vector or {}).items() if _number(v) and v != 0}


def snapshot_unrestorable_reason(stored: Any) -> Optional[str]:
    """Why a snapshot's weights cannot be written back as they are, or ``None`` when they can.

    ``restore_weights`` writes the snapshot dict verbatim over the category's weights. Apply, restore and the
    optimizer store ``*_percent`` keys; a manual ``save_snapshot`` stores the decimal ``get_weights`` output
    (bare names, ``bonus`` included), which would put a non-percent block into the config.
    """
    if not isinstance(stored, dict) or not stored:
        return "the snapshot holds no weights"
    off_format = [k for k in stored if not k.endswith(SUFFIX)]
    if off_format:
        return ("this snapshot was saved in another format by the web UI (keys without _percent: "
                + ", ".join(sorted(off_format)[:5]) + "); restore it from /compare")
    unknown = [k for k in stored if base_key(k) not in VALID_WEIGHT_COLUMNS]
    if unknown:
        return "this snapshot holds keys that are not scored metrics: " + ", ".join(sorted(unknown)[:5])
    if not all(_number(v) for v in stored.values()):
        return "this snapshot holds a non-numeric weight"
    return None


def job_state(body: dict, started_at: Optional[float]) -> dict:
    """The recompute-status route body as a state the model can read without knowing exit codes.

    ``started_at`` is the start time the caller got from ``recompute_scores``; ``matches_started_job`` says
    whether the status describes that job (``None`` when the status carries no start time, as when another
    worker or a command-line run holds the library lock).
    """
    from utils.exit_codes import LIBRARY_LOCK_HELD_EXIT_CODE
    kind, exit_code, reported = body.get("kind"), body.get("exit_code"), body.get("started_at")
    matches = None if started_at is None or not _number(reported) else abs(float(reported) - float(started_at)) < 1e-3
    out: dict[str, Any] = {"kind": kind, "scope": body.get("scope"), "started_at": reported,
                           "progress": body.get("progress"), "exit_code": exit_code,
                           "matches_started_job": matches, "reason": None}
    if body.get("running"):
        out["state"] = "running"
    elif kind not in TERMINAL_KINDS or exit_code is None:
        out.update(state="idle", reason="no_job")
    elif exit_code == 0:
        out.update(state="succeeded", reason="ok")
    elif exit_code == LIBRARY_LOCK_HELD_EXIT_CODE:
        out.update(state="busy", reason="lock_held")
    else:
        out.update(state="failed", reason="failed")
    if out["reason"] != "no_job" and (kind != "recompute" or matches is False):
        out["reason"] = "not_this_job"
    return out


def learned_changes(current: dict, suggested: dict) -> tuple[list[dict], dict]:
    """``(changes, proposal)``: the keys whose suggested value differs from the current one.

    ``proposal`` is the partial ``*_percent`` map to hand to ``preview_weights(weights=...)``.
    """
    changes = [{"key": key, "current": current.get(key, 0), "suggested": suggested.get(key, 0),
                "delta": suggested.get(key, 0) - current.get(key, 0)}
               for key in sorted(set(current) | set(suggested)) if suggested.get(key, 0) != current.get(key, 0)]
    return changes, {c["key"]: c["suggested"] for c in changes}


def near_miss(rejected: list) -> Optional[dict]:
    """The first higher-priority category (in the order given) a photo missed on ONE numeric bound by under 10%.

    ``rejected`` is the critique's ``category_reason.rejected``: ``{category, mismatch: {key, required, actual}}``
    for the first filter each higher-priority category failed. Only a numeric ``*_min`` / ``*_max`` with a
    known value and a non-zero bound counts; a boolean, a tag rule or a missing value never does.
    """
    for entry in rejected or []:
        mismatch = entry.get("mismatch") or {}
        key, required, actual = mismatch.get("key"), mismatch.get("required"), mismatch.get("actual")
        if not isinstance(key, str) or not key.endswith(BOUND_SUFFIXES):
            continue
        if not _number(required) or not _number(actual) or required == 0:
            continue
        gap = abs(actual - required) / abs(required)
        if gap < NEAR_MISS_FRACTION:
            return {"suggested": entry.get("category"),
                    "mismatch": {"key": key, "required": required, "actual": actual, "gap": round(gap, 3)}}
    return None
