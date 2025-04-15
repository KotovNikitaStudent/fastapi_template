from .conftest import client


def test_create_task(setup_database):
    response = client.post("/tasks", json={"title": "Test", "description": "Desc"})
    assert response.status_code == 200
    assert response.json()["title"] == "Test"


def test_get_all_tasks(setup_database):
    response = client.get("/tasks")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_complete_task(setup_database):
    response = client.put("/tasks/1/complete")
    assert response.status_code == 200
    assert response.json()["completed"] is True
