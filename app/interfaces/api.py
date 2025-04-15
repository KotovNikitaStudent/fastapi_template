from typing import List
from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.orm import Session

from app.adapters.repository import SqlAlchemyRepository
from app.adapters.schemas import TaskResponse, TaskCreate
from app.core.use_cases import TaskService
from app.database import get_db


router = APIRouter()


@router.post("/tasks", response_model=TaskResponse)
def create_task(task_data: TaskCreate, db: Session = Depends(get_db)):
    repo = SqlAlchemyRepository(db)
    service = TaskService(repo)
    return service.create_task(**task_data.model_dump())


@router.get("/tasks", response_model=List[TaskResponse])
def get_all_tasks(db: Session = Depends(get_db)):
    repo = SqlAlchemyRepository(db)
    service = TaskService(repo)
    return service.get_all_tasks()


@router.put("/tasks/{task_id}/complete", response_model=TaskResponse)
def complete_task(task_id: int, db: Session = Depends(get_db)):
    repo = SqlAlchemyRepository(db)
    service = TaskService(repo)
    task = service.mark_task_as_completed(task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Task not found"
        )
    return task
