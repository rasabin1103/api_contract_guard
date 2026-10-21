from sqlalchemy import create_engine, pool

from alembic import context
from app.core.config import Settings, ensure_sqlite_directory
from app.db.models import Base

url = Settings().database_url
ensure_sqlite_directory(url)

if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            render_as_batch=url.startswith("sqlite"),
        )
        with context.begin_transaction():
            context.run_migrations()
