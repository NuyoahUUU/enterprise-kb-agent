from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, scoped_session, sessionmaker

from app.config import settings


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    pool_pre_ping=True,
)
SessionFactory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
# 使用 scoped_session 确保每个线程获得独立的 session，避免并发写入冲突
SessionLocal = scoped_session(SessionFactory)
Base = declarative_base()


def init_db() -> None:
    from app.models import chat_session  # noqa: F401

    Base.metadata.create_all(bind=engine)
    # SQLite WAL 模式：允许多读单写，大幅提升并发性能
    if settings.database_url.startswith("sqlite"):
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        SessionLocal.remove()


@contextmanager
def session_scope():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
        SessionLocal.remove()
