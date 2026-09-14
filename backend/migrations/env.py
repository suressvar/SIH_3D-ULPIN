from alembic import context
from sqlalchemy import create_engine, pool

import app.governance_models  # noqa: F401
import app.pipeline_models  # noqa: F401
from app.config import get_settings
from app.models import Base


def run():
    url = get_settings().database_url
    if context.is_offline_mode():
        context.configure(
            url=url,
            target_metadata=Base.metadata,
            literal_binds=True,
            include_schemas=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    else:
        engine = create_engine(url, poolclass=pool.NullPool)
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=Base.metadata,
                include_schemas=True,
            )
            with context.begin_transaction():
                context.run_migrations()


run()
