-- Plain-SQL schema, equivalent to db/models.py, kept for reference / manual
-- inspection and as a lighter alternative to a full Alembic migration chain
-- for a project this size. db/init_db.py (SQLAlchemy's Base.metadata.create_all)
-- is the actual source of truth used at startup.

CREATE TABLE IF NOT EXISTS quality_runs (
    run_id          VARCHAR(16) PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
    dataset_name    VARCHAR(255) NOT NULL DEFAULT 'default',
    source_file     VARCHAR(512) NOT NULL,
    health_score    INTEGER NOT NULL,
    rows_processed  INTEGER NOT NULL,
    rows_flagged    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_quality_runs_dataset_name ON quality_runs(dataset_name);

-- One row per ingested source row, stored as JSON rather than fixed
-- columns — this is what lets the same table hold any dataset's shape
-- without a migration per schema.
CREATE TABLE IF NOT EXISTS dataset_rows (
    id                       SERIAL PRIMARY KEY,
    row_index                INTEGER NOT NULL,
    data                     JSON NOT NULL,
    source_run_id            VARCHAR(16) NOT NULL REFERENCES quality_runs(run_id)
);
CREATE INDEX IF NOT EXISTS ix_dataset_rows_source_run_id ON dataset_rows(source_run_id);

CREATE TABLE IF NOT EXISTS quality_issues (
    id              SERIAL PRIMARY KEY,
    run_id          VARCHAR(16) NOT NULL REFERENCES quality_runs(run_id),
    row_reference   VARCHAR(64) NOT NULL,
    "column"        VARCHAR(64) NOT NULL,
    issue_type      VARCHAR(32) NOT NULL,
    description     TEXT NOT NULL,
    severity        VARCHAR(16) NOT NULL DEFAULT 'medium'
);
CREATE INDEX IF NOT EXISTS ix_quality_issues_run_id ON quality_issues(run_id);
CREATE INDEX IF NOT EXISTS ix_quality_issues_issue_type ON quality_issues(issue_type);

CREATE TABLE IF NOT EXISTS data_lineage (
    id                        SERIAL PRIMARY KEY,
    source_file               VARCHAR(512) NOT NULL,
    ingested_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    transformations_applied   JSON NOT NULL,
    destination_table         VARCHAR(64) NOT NULL,
    run_id                    VARCHAR(16) NOT NULL REFERENCES quality_runs(run_id)
);
