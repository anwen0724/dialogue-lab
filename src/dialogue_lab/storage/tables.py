"""已确认的四张表；消息内容和路径分开保存，不保存系统指令。"""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Identity,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData()


def identity(name):
    return Column(name, BigInteger, Identity(always=True), primary_key=True)


def timestamp(name, *, nullable=False, default=False):
    return Column(
        name,
        DateTime(timezone=True),
        nullable=nullable,
        server_default=func.now() if default else None,
    )


sessions = Table(
    "sessions",
    metadata,
    identity("session_id"),
    Column("title", Text, nullable=False),
    Column("status", Text, nullable=False, server_default="active"),
    Column("active_entry_id", BigInteger),
    Column("model_selection", JSONB),
    timestamp("created_at", default=True),
    timestamp("updated_at", default=True),
    timestamp("archived_at", nullable=True),
    CheckConstraint(
        "(status = 'active' AND archived_at IS NULL) OR "
        "(status = 'archived' AND archived_at IS NOT NULL)",
        name="session_status",
    ),
)

messages = Table(
    "session_messages",
    metadata,
    identity("message_id"),
    Column("session_id", BigInteger, nullable=False),
    Column("request_id", UUID(as_uuid=True), nullable=False),
    Column("message_kind", Text, nullable=False),
    Column("message_json", JSONB, nullable=False),
    timestamp("created_at", default=True),
    timestamp("completed_at", nullable=True),
    CheckConstraint("message_kind IN ('user_message', 'assistant_message')", name="message_kind"),
    UniqueConstraint("session_id", "message_kind", "request_id", name="message_request"),
    UniqueConstraint("session_id", "message_id", name="message_session_id"),
    ForeignKeyConstraint(["session_id"], ["sessions.session_id"], name="message_session"),
)

entries = Table(
    "session_entries",
    metadata,
    identity("entry_id"),
    Column("session_id", BigInteger, nullable=False),
    Column("parent_entry_id", BigInteger),
    Column("entry_type", Text, nullable=False),
    Column("message_id", BigInteger, unique=True),
    Column("compaction_id", BigInteger, unique=True),
    timestamp("created_at", default=True),
    UniqueConstraint("session_id", "entry_id", name="entry_session_id"),
    CheckConstraint(
        "parent_entry_id IS NULL OR parent_entry_id <> entry_id", name="entry_not_self"
    ),
    CheckConstraint(
        "(entry_type = 'message' AND message_id IS NOT NULL AND compaction_id IS NULL) "
        "OR (entry_type = 'compaction' AND compaction_id IS NOT NULL AND message_id IS NULL)",
        name="entry_content",
    ),
    ForeignKeyConstraint(["session_id"], ["sessions.session_id"], name="entry_session"),
    ForeignKeyConstraint(
        ["session_id", "parent_entry_id"],
        ["session_entries.session_id", "session_entries.entry_id"],
        name="entry_parent",
    ),
    ForeignKeyConstraint(
        ["session_id", "message_id"],
        ["session_messages.session_id", "session_messages.message_id"],
        name="entry_message",
    ),
)

compactions = Table(
    "session_compactions",
    metadata,
    identity("compaction_id"),
    Column("session_id", BigInteger, nullable=False),
    Column("anchor_entry_id", BigInteger, nullable=False),
    Column("trigger", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("summary_text", Text),
    Column("covered_until_entry_id", BigInteger),
    Column("first_kept_entry_id", BigInteger),
    Column("usage", JSONB),
    Column("error_code", Text),
    Column("error_message", Text),
    timestamp("started_at", default=True),
    timestamp("completed_at", nullable=True),
    UniqueConstraint("session_id", "compaction_id", name="compaction_session_id"),
    CheckConstraint(
        "status IN ('running','completed','failed','cancelled','interrupted')",
        name="compaction_status",
    ),
    CheckConstraint(
        "(status = 'running' AND completed_at IS NULL) OR "
        "(status <> 'running' AND completed_at IS NOT NULL)",
        name="compaction_completion",
    ),
    CheckConstraint(
        "status <> 'completed' OR (summary_text IS NOT NULL AND length(trim(summary_text)) > 0 "
        "AND covered_until_entry_id IS NOT NULL)",
        name="compaction_summary",
    ),
    ForeignKeyConstraint(["session_id"], ["sessions.session_id"], name="compaction_session"),
)

for field in ("anchor_entry_id", "covered_until_entry_id", "first_kept_entry_id"):
    compactions.append_constraint(
        ForeignKeyConstraint(
            ["session_id", field],
            ["session_entries.session_id", "session_entries.entry_id"],
            name=f"compaction_{field}",
        )
    )
entries.append_constraint(
    ForeignKeyConstraint(
        ["session_id", "compaction_id"],
        ["session_compactions.session_id", "session_compactions.compaction_id"],
        name="entry_compaction",
        use_alter=True,
    )
)
sessions.append_constraint(
    ForeignKeyConstraint(
        ["session_id", "active_entry_id"],
        ["session_entries.session_id", "session_entries.entry_id"],
        name="session_active_entry",
        use_alter=True,
    )
)
