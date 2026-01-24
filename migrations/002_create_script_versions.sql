-- Create script_versions table for version history
-- Migration: 002_create_script_versions
-- Created: 2026-01-24

CREATE TABLE script_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    script_id INTEGER NOT NULL,
    version_number INTEGER NOT NULL,
    
    -- Snapshot of script content
    content TEXT NOT NULL,
    dependencies TEXT NOT NULL DEFAULT '',
    python_version VARCHAR(20) NOT NULL DEFAULT '3.11',
    cron_expression VARCHAR(100) NOT NULL DEFAULT '0 * * * *',
    timeout INTEGER NOT NULL DEFAULT 3600,
    environment_vars TEXT NOT NULL DEFAULT '',
    
    -- Version metadata
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(50) NOT NULL DEFAULT 'manual',
    change_summary TEXT,
    
    -- Foreign key
    FOREIGN KEY (script_id) REFERENCES scripts(id) ON DELETE CASCADE,
    
    -- Ensure unique version numbers per script
    UNIQUE (script_id, version_number)
);

-- Indexes for performance
CREATE INDEX idx_script_versions_script_created ON script_versions(script_id, created_at);
CREATE INDEX idx_script_versions_script_version ON script_versions(script_id, version_number);
