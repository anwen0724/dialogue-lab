"""管理数据库连接；业务操作分别使用短事务。"""

from sqlalchemy.ext.asyncio import create_async_engine


class Database:
    def __init__(self, url: str):
        self.engine = create_async_engine(url, pool_pre_ping=True, hide_parameters=True)

    async def close(self) -> None:
        await self.engine.dispose()
