from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def sessions(url):
    if not url.startswith("postgresql+psycopg://"):
        raise ValueError("PostgreSQL with psycopg is required")
    engine = create_engine(url, pool_pre_ping=True, hide_parameters=True)
    return sessionmaker(engine, expire_on_commit=False)
