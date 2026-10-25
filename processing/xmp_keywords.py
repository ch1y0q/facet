"""Versioned flat-keyword ownership carried in XMP, never inferred from names.

Names already present before Facet's first write remain foreign, even when a
Facet tag has the same spelling. Tombstones are scoped to this exact packet's
previously claimed names; they are not permission to remove arbitrary tags.
"""
import json
import unicodedata


def keyword_key(value):
    return unicodedata.normalize('NFC', value).casefold()


def parse_keyword_state(raw):
    if raw is None:
        return None
    try:
        state = json.loads(raw)
        if state.get('version') != 1:
            return None
        for key in ('owned', 'deleted', 'ai', 'manual'):
            values = state[key]
            if not isinstance(values, list) or len(values) > 10000:
                return None
            if any(not isinstance(value, str) or not value or len(value) > 1024 for value in values):
                return None
        return state
    except (ValueError, TypeError, KeyError, AttributeError):
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
    present = unique(existing)
    wanted = unique(current)
    deleted = unique(previous['deleted'])
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
    merged = {**present}
    for key, value in wanted.items():
        merged.setdefault(key, value)
    machines = unique([*previous['ai'], *[value for value in ai if keyword_key(value) in owned]])
    return list(merged.values()), {'version': 1, 'owned': list(owned.values()),
                                  'deleted': list(deleted.values()), 'ai': list(machines.values()),
                                  'manual': list(unique(manual).values())}


def serialize_keyword_state(state):
    return json.dumps(state, ensure_ascii=False, separators=(',', ':'))
