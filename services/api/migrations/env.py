import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from wasifyai_api.config import get_settings

url = get_settings().database_url


def run_migrations(connection):
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()


async def run_online():
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        await conn.run_sync(run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=url, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(run_online())
