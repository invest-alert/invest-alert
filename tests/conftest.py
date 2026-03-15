import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["ENABLE_CONTEXT_SCHEDULER"] = "false"
os.environ["ENABLE_SUMMARY_WORKER"] = "false"

from app.api.deps import get_db  # noqa: E402
import app.db.session as db_session  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402
import app.models as models  # noqa: E402,F401

engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
db_session.engine = engine
db_session.SessionLocal = TestingSessionLocal


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


fastapi_app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def client():
    with TestClient(fastapi_app) as c:
        yield c
