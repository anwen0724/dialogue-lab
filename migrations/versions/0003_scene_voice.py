"""场景保存自己的音色；原有场景沿用迁移时的语音配置。"""

import sqlalchemy as sa
from alembic import op

from dialogue_lab.config import Settings

revision = "0003"
down_revision = "0002"
branch_labels = depends_on = None


def upgrade():
    op.add_column("scenes", sa.Column("tts_voice", sa.Text(), nullable=True))
    # 仅回填迁移前存在的记录，不设置默认值，不改变后续新场景的显式选择。
    voice = Settings().tts_voice.strip() or None
    op.execute(
        sa.table("scenes", sa.column("tts_voice", sa.Text())).update().values(tts_voice=voice)
    )


def downgrade():
    op.drop_column("scenes", "tts_voice")
