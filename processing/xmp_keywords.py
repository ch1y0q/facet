"""Versioned flat-keyword ownership carried in XMP, never inferred from names.

Names already present before Facet's first write remain foreign, even when a
Facet tag has the same spelling. Tombstones are scoped to this exact packet's
previously claimed names; they are not permission to remove arbitrary tags.
"""
import json
import unicodedata


def keyword_key(value):
    return unicodedata.normalize('NFC', value).casefold()


MAX_STATE_NAMES = 10000
MAX_STATE_NAME_LENGTH = 1024


def _valid_keyword_state(state):
    if not isinstance(state, dict) or type(state.get('version')) is not int or state['version'] != 1:
        return False
    for key in ('owned', 'deleted', 'ai', 'manual'):
        values = state.get(key)
        if not isinstance(values, list) or len(values) > MAX_STATE_NAMES:
            return False
        if any(not isinstance(value, str) or not value or len(value) > MAX_STATE_NAME_LENGTH for value in values):
            return False
    return True


def parse_keyword_state(raw):
    try:
        state = json.loads(raw)
        return state if _valid_keyword_state(state) else None
    except (ValueError, TypeError):
        return None


def reconcile_keywords(existing, current, previous=None, *, reconcile=False, ai=(), manual=()):
    """Return merged flat names and the next ownership marker.

    Additive writes retain previous ownership so a later explicit reconcile can
    remove old names. AI provenance also survives retagging in additive mode,
    preventing an old machine label becoming a manual tag on import.
    """
    previous = previous or {'owned': [], 'deleted': [], 'ai': [], 'manual': []}
    def unique(values):
        result = {}
        for value in values:
            result.setdefault(keyword_key(value), value)
        return result
    old = unique(previous['owned'])
    existing = list(dict.fromkeys(existing))
    present = unique(existing)
    wanted = unique(current)
    # A name present after our deletion is an external re-add. The old marker
    # no longer grants deletion authority over that new occurrence.
    deleted = {key: value for key, value in unique(previous['deleted']).items() if key not in present}
    if reconcile:
        deleted.update({key: value for key, value in old.items() if key not in wanted})
        present = {key: value for key, value in present.items() if key not in deleted or key in wanted}
        owned = {key: value for key, value in old.items() if key in wanted}
    else:
        owned = old.copy()
    # A pre-existing foreign name is never claimed merely because names match.
    owned.update({key: value for key, value in wanted.items() if key not in present or key in deleted})
    for key in wanted:
        deleted.pop(key, None)
    # Preserve foreign display variants even when they normalize to one key.
    merged = [value for value in existing if keyword_key(value) in present]
    seen = {keyword_key(value) for value in merged}
    for key, value in wanted.items():
        if key not in seen:
            merged.append(value)
            seen.add(key)
    machines = unique([*previous['ai'], *[value for value in ai if keyword_key(value) in owned]])
    return merged, {'version': 1, 'owned': list(owned.values()),
                                  'deleted': list(deleted.values()), 'ai': list(machines.values()),
                                  'manual': list(unique(manual).values())}


def serialize_keyword_state(state):
    if not _valid_keyword_state(state):
        raise RuntimeError(
            'Facet keyword ownership exceeds its safe packet bounds '
            f'({MAX_STATE_NAMES} names per list, {MAX_STATE_NAME_LENGTH} characters per name); '
            'export refused before writing. Reduce the exported name set, or manually '
            'reconcile/archive the existing packet before establishing new ownership. '
            'Deletion markers were not discarded.')
    return json.dumps(state, ensure_ascii=False, separators=(',', ':'))
