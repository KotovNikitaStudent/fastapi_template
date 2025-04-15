from app.adapters.repository import AbstractRepository
from app.core.entities import Task


class TaskService:
    def __init__(self, repo: AbstractRepository) -> None:
        self.repo = repo

    def create_task(self, title: str, description: str) -> Task:
        return self.repo.add(title=title, description=description)

    def get_all_tasks(self) -> list[Task]:
        return self.repo.get_all()

    def mark_task_as_completed(self, task_id: int) -> Task:
        return self.repo.update(task_id=task_id, completed=True)
