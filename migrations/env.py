"""迁移从应用配置读取地址，不在仓库中保存数据库凭据。"""

import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from dialogue_lab.config import Settings
from dialogue_lab.storage.tables import metadata


def migrate(connection):
    context.configure(connection=connection, target_metadata=metadata)
    with context.begin_transaction():
        context.run_migrations()


async def online():
    engine = create_async_engine(Settings().database_url.get_secret_value())
    async with engine.connect() as connection:
        await connection.run_sync(migrate)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=Settings().database_url.get_secret_value(), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(online())
