"""将客户端播放回执与模型生成终态分开保存。"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = depends_on = None


def upgrade():
    op.execute("ALTER TABLE session_messages ADD COLUMN playback_state TEXT")
    op.execute("""ALTER TABLE session_messages ADD CONSTRAINT message_playback
        CHECK (playback_state IS NULL OR
            (message_kind = 'assistant_message'
             AND playback_state IN ('unconfirmed', 'completed', 'interrupted')))""")
    op.execute("""UPDATE session_messages SET playback_state = 'unconfirmed'
        WHERE message_kind = 'assistant_message'""")


def downgrade():
    op.drop_column("session_messages", "playback_state")
