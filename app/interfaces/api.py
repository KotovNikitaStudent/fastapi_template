from typing import List
from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.adapters.notifier import NotificationClient
from app.adapters.repository import SqlAlchemyRepository
from app.adapters.schemas import TaskResponse, TaskCreate
from app.core.use_cases import TaskService
from app.database import get_db
from app.dependencies import get_notifier
from app.interfaces.rate_limit import rate_limit


router = APIRouter(dependencies=[Depends(rate_limit)])


@router.post("/tasks", response_model=TaskResponse)
async def create_task(
    task_data: TaskCreate,
    db: Session = Depends(get_db),
    notifier: NotificationClient = Depends(get_notifier),
):
    repo = SqlAlchemyRepository(db)
    service = TaskService(repo)
    # Синхронная работа с БД уходит в пул потоков, чтобы не блокировать event loop.
    task = await run_in_threadpool(service.create_task, **task_data.model_dump())
    # Побочный эффект: недоступность сервиса уведомлений не ломает создание задачи.
    await notifier.notify_task_created(task)
    return task


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


@router.get("/resilience/status")
def resilience_status(notifier: NotificationClient = Depends(get_notifier)):
    """Состояние защит: удобно для отладки и мониторинга."""
    return {
        "notification_service": {
            "enabled": notifier.enabled,
            "circuit": notifier.breaker.state.value,
        }
    }
