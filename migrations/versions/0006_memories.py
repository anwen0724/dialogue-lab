"""角色记忆及可核对的来源；来源版本用于撤回旧模型投影。"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = depends_on = None


def upgrade():
    op.execute("ALTER TABLE characters ADD COLUMN memory_revision INTEGER NOT NULL DEFAULT 0")
    op.execute(
        "ALTER TABLE session_compactions ADD COLUMN memory_revision INTEGER NOT NULL DEFAULT 0"
    )
    op.execute("""
        CREATE TABLE memories (
            memory_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            character_id BIGINT NOT NULL REFERENCES characters(character_id),
            content TEXT,
            is_core BOOLEAN NOT NULL DEFAULT false,
            revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
            status TEXT NOT NULL DEFAULT 'active',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT memory_content CHECK (
                (status = 'active' AND content IS NOT NULL AND length(trim(content)) > 0)
                OR (status = 'forgotten' AND content IS NULL AND NOT is_core)
            )
        )
    """)
    op.execute("CREATE INDEX memory_character ON memories(character_id, status, is_core)")
    op.execute("""
        CREATE TABLE memory_sources (
            memory_id BIGINT NOT NULL REFERENCES memories(memory_id),
            revision INTEGER NOT NULL CHECK (revision > 0),
            message_id BIGINT NOT NULL REFERENCES session_messages(message_id),
            PRIMARY KEY (memory_id, revision, message_id)
        )
    """)


def downgrade():
    op.drop_table("memory_sources")
    op.drop_table("memories")
    op.drop_column("session_compactions", "memory_revision")
    op.drop_column("characters", "memory_revision")
