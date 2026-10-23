"""Manual rows are durable annotations, never recognition training examples."""
from db.person_carry_over import box_iou


def source_identity(path):
    from utils.manual_face_frame import source_identity as frame_identity
    return frame_identity(path)


def region_response(row, current_source):
    changed = current_source is None or current_source != row['manual_source']
    w, h = row['manual_width'], row['manual_height']
    return {'id': row['id'], 'manual_key': row['manual_key'],
            'bbox': [row['bbox_x1'] / w, row['bbox_y1'] / h, row['bbox_x2'] / w, row['bbox_y2'] / h],
            'person_id': row['person_id'], 'person_name': row['person_name'], 'source_changed': changed}


def get_region(conn, path, face_id=None, manual_key=None):
    column, value = ('f.id', face_id) if face_id is not None else ('f.manual_key', manual_key)
    return conn.execute(
        'SELECT f.*,p.name AS person_name FROM faces f LEFT JOIN persons p ON p.id=f.person_id '
        f'WHERE f.photo_path=? AND f.is_manual=1 AND {column}=?', (path, value)).fetchone()


def export_dimensions(row, width, height, disk_path=None):
    """Manual geometry keeps its own frame; stale marks need review, not export."""
    if row['is_manual']:
        try:
            if source_identity(disk_path or row['photo_path']) != row['manual_source']:
                return None
        except OSError:
            return None
        width, height = row['manual_width'], row['manual_height']
    return (width, height) if width and height and width > 0 and height > 0 else None


def detected_overlap(conn, path, box):
    return any(box_iou(box, tuple(row)[1:5]) >= 0.5 for row in conn.execute(
        'SELECT id,bbox_x1,bbox_y1,bbox_x2,bbox_y2 FROM faces '
        'WHERE photo_path=? AND is_manual=0 AND bbox_x1 IS NOT NULL', (path,))
        if None not in tuple(row)[1:5])


def prune_deleted_manual_faces(conn):
    """Explicit UUID deletion wins; return owners whose counts need refreshing."""
    affected = {r[0] for r in conn.execute(
        'SELECT DISTINCT person_id FROM faces WHERE is_manual=1 AND person_id IS NOT NULL '
        'AND manual_key IN (SELECT manual_key FROM manual_face_deletions)')}
    conn.execute('DELETE FROM faces WHERE is_manual=1 '
                 'AND manual_key IN (SELECT manual_key FROM manual_face_deletions)')
    return affected


def without_manual_overlaps(conn, path, records):
    """Filter detector insert tuples (canonical FACES_UPSERT_SQL column order).

    A stale manual frame is retained for review but cannot suppress detections
    in the replacement image's unrelated coordinate space.
    """
    manual = conn.execute(
        'SELECT bbox_x1,bbox_y1,bbox_x2,bbox_y2,manual_source FROM faces '
        'WHERE photo_path=? AND is_manual=1', (path,)).fetchall()
    if not manual:
        return list(records)
    try:
        identity = source_identity(path)
    except OSError:
        return list(records)
    boxes = [tuple(row)[:4] for row in manual if row[4] == identity]
    return [r for r in records if not any(box_iou(r[3:7], box) >= 0.5 for box in boxes)]
