from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(str(settings.SQLALCHEMY_DATABASE_URI))
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
