"""Private, durable stack links and per-operation remote write receipts."""


def init_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS immich_stack_links (
        scope TEXT NOT NULL, local_stack_id TEXT NOT NULL, remote_stack_id TEXT NOT NULL,
        local_fingerprint TEXT NOT NULL, remote_fingerprint TEXT NOT NULL,
        PRIMARY KEY(scope,local_stack_id), UNIQUE(scope,remote_stack_id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS immich_stack_receipts (
        scope TEXT NOT NULL, admission_scope TEXT NOT NULL, operation_id TEXT NOT NULL, status TEXT NOT NULL,
        local_stack_id TEXT, remote_stack_id TEXT, asset_ids TEXT NOT NULL DEFAULT '[]', updated_at TEXT NOT NULL,
        PRIMARY KEY(scope,operation_id))""")
    conn.execute('CREATE INDEX IF NOT EXISTS immich_stack_receipts_state ON immich_stack_receipts(admission_scope,status)')
    # Lifetime send claims normalize asset admission so completion cannot reopen
    # a stale preflight, and lookup cost is indexed rather than scanning receipts.
    conn.execute("""CREATE TABLE IF NOT EXISTS immich_stack_send_claims (
        admission_scope TEXT NOT NULL, asset_id TEXT NOT NULL, operation_id TEXT NOT NULL,
        PRIMARY KEY(admission_scope,asset_id))""")
