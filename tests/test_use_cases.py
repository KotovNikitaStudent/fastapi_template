from app.core.use_cases import TaskService


def test_create_task(mock_repo):
    service = TaskService(mock_repo)
    task = service.create_task("Test", "Desc")
    assert task.title == "Test"


def test_get_all_tasks(mock_repo):
    setvice = TaskService(mock_repo)
    tasks = setvice.get_all_tasks()
    assert len(tasks) == 1
    assert tasks[0].title == "Test"


def test_mark_task_as_completed(mock_repo):
    service = TaskService(mock_repo)
    task = service.mark_task_as_completed(1)
    assert task.completed is True
