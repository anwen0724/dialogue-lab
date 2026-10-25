"""创建会话、消息、路径和压缩记录。"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE sessions (
        session_id BIGINT GENERATED ALWAYS AS IDENTITY,
        title TEXT NOT NULL,
        status TEXT DEFAULT 'active' NOT NULL,
        active_entry_id BIGINT,
        model_selection JSONB,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        archived_at TIMESTAMP WITH TIME ZONE,
        PRIMARY KEY (session_id),
        CONSTRAINT session_status CHECK ((status = 'active' AND archived_at IS NULL) OR (status
        = 'archived' AND archived_at IS NOT NULL))
        )
    """)
    op.execute("""
        CREATE TABLE session_messages (
        message_id BIGINT GENERATED ALWAYS AS IDENTITY,
        session_id BIGINT NOT NULL,
        request_id UUID NOT NULL,
        message_kind TEXT NOT NULL,
        message_json JSONB NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        completed_at TIMESTAMP WITH TIME ZONE,
        PRIMARY KEY (message_id),
        CONSTRAINT message_kind CHECK (message_kind IN ('user_message', 'assistant_message')),
        CONSTRAINT message_request UNIQUE (session_id, message_kind, request_id),
        CONSTRAINT message_session_id UNIQUE (session_id, message_id)
        )
    """)
    op.execute("""
        CREATE TABLE session_entries (
        entry_id BIGINT GENERATED ALWAYS AS IDENTITY,
        session_id BIGINT NOT NULL,
        parent_entry_id BIGINT,
        entry_type TEXT NOT NULL,
        message_id BIGINT,
        compaction_id BIGINT,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        PRIMARY KEY (entry_id),
        CONSTRAINT entry_session_id UNIQUE (session_id, entry_id),
        CONSTRAINT entry_not_self CHECK (parent_entry_id IS NULL OR parent_entry_id <>
        entry_id),
        CONSTRAINT entry_content CHECK ((entry_type = 'message' AND message_id IS NOT NULL AND
        compaction_id IS NULL) OR (entry_type = 'compaction' AND compaction_id IS NOT NULL AND
        message_id IS NULL)),
        UNIQUE (message_id),
        UNIQUE (compaction_id)
        )
    """)
    op.execute("""
        CREATE TABLE session_compactions (
        compaction_id BIGINT GENERATED ALWAYS AS IDENTITY,
        session_id BIGINT NOT NULL,
        anchor_entry_id BIGINT NOT NULL,
        trigger TEXT NOT NULL,
        status TEXT NOT NULL,
        summary_text TEXT,
        covered_until_entry_id BIGINT,
        first_kept_entry_id BIGINT,
        usage JSONB,
        error_code TEXT,
        error_message TEXT,
        started_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
        completed_at TIMESTAMP WITH TIME ZONE,
        PRIMARY KEY (compaction_id),
        CONSTRAINT compaction_session_id UNIQUE (session_id, compaction_id),
        CONSTRAINT compaction_status CHECK (status IN
        ('running','completed','failed','cancelled','interrupted')),
        CONSTRAINT compaction_completion CHECK ((status = 'running' AND completed_at IS NULL) OR
        (status <> 'running' AND completed_at IS NOT NULL)),
        CONSTRAINT compaction_summary CHECK (status <> 'completed' OR (summary_text IS NOT NULL
        AND length(trim(summary_text)) > 0 AND covered_until_entry_id IS NOT NULL))
        )
    """)
    op.execute("""
        ALTER TABLE sessions ADD CONSTRAINT session_active_entry FOREIGN KEY(session_id,
        active_entry_id) REFERENCES session_entries (session_id, entry_id)
    """)
    op.execute("""
        ALTER TABLE session_messages ADD CONSTRAINT message_session FOREIGN KEY(session_id)
        REFERENCES sessions (session_id)
    """)
    op.execute("""
        ALTER TABLE session_entries ADD CONSTRAINT entry_compaction FOREIGN KEY(session_id,
        compaction_id) REFERENCES session_compactions (session_id, compaction_id)
    """)
    op.execute("""
        ALTER TABLE session_entries ADD CONSTRAINT entry_message FOREIGN KEY(session_id,
        message_id) REFERENCES session_messages (session_id, message_id)
    """)
    op.execute("""
        ALTER TABLE session_entries ADD CONSTRAINT entry_parent FOREIGN KEY(session_id,
        parent_entry_id) REFERENCES session_entries (session_id, entry_id)
    """)
    op.execute("""
        ALTER TABLE session_entries ADD CONSTRAINT entry_session FOREIGN KEY(session_id)
        REFERENCES sessions (session_id)
    """)
    op.execute("""
        ALTER TABLE session_compactions ADD CONSTRAINT compaction_anchor_entry_id FOREIGN
        KEY(session_id, anchor_entry_id) REFERENCES session_entries (session_id, entry_id)
    """)
    op.execute("""
        ALTER TABLE session_compactions ADD CONSTRAINT compaction_covered_until_entry_id FOREIGN
        KEY(session_id, covered_until_entry_id) REFERENCES session_entries (session_id,
        entry_id)
    """)
    op.execute("""
        ALTER TABLE session_compactions ADD CONSTRAINT compaction_first_kept_entry_id FOREIGN
        KEY(session_id, first_kept_entry_id) REFERENCES session_entries (session_id, entry_id)
    """)
    op.execute("""
        ALTER TABLE session_compactions ADD CONSTRAINT compaction_session FOREIGN
        KEY(session_id) REFERENCES sessions (session_id)
    """)


def downgrade():
    op.execute("DROP TABLE session_compactions, session_entries, session_messages, sessions")
