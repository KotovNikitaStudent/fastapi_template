import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlalchemy.orm import sessionmaker

from main import app
from app.core.entities import Task
from app.database import get_db, Base


TEST_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    TEST_DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)


@pytest.fixture(scope="module")
def setup_database():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    repo.add.return_value = Task(
        id=1, title="Test", description="Desc", completed=False, created_at="2023-01-01"
    )
    repo.get_all.return_value = [
        Task(
            id=1,
            title="Test",
            description="Desc",
            completed=False,
            created_at="2023-01-01",
        )
    ]
    repo.update.return_value = Task(
        id=1, title="Test", description="Desc", completed=True, created_at="2023-01-01"
    )
    return repo
