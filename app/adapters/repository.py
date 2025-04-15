from abc import ABC, abstractmethod
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.orm import Session

from app.core.entities import Task
from app.database import Base


class AbstractRepository(ABC):
    @abstractmethod
    def add(self, title: str, description: str) -> Task:
        pass

    @abstractmethod
    def get_all(self) -> list[Task]:
        pass

    @abstractmethod
    def update(self, task_id: int, completed: bool) -> Task:
        pass


class TaskModel(Base):
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(String, nullable=False)
    completed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class SqlAlchemyRepository(AbstractRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, title: str, description: str) -> Task:
        db_task = TaskModel(title=title, description=description)
        self.session.add(db_task)
        self.session.commit()
        self.session.refresh(db_task)
        return Task(
            id=db_task.id,
            title=db_task.title,
            description=db_task.description,
            completed=db_task.completed,
            created_at=db_task.created_at,
        )

    def get_all(self) -> list[Task]:
        db_tasks = self.session.query(TaskModel).all()
        return [
            Task(
                id=t.id,
                title=t.title,
                description=t.description,
                completed=t.completed,
                created_at=t.created_at,
            )
            for t in db_tasks
        ]

    def update(self, task_id: int, completed: bool) -> Task:
        db_task = self.session.query(TaskModel).filter(TaskModel.id == task_id).first()
        if not db_task:
            return None
        db_task.completed = completed
        self.session.commit()
        self.session.refresh(db_task)
        return Task(
            id=db_task.id,
            title=db_task.title,
            description=db_task.description,
            completed=db_task.completed,
            created_at=db_task.created_at,
        )
