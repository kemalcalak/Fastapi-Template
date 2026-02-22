from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(str(settings.SQLALCHEMY_DATABASE_URI))
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
