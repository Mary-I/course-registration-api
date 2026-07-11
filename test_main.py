import pytest
from fastapi.testclient import TestClient

import main


client = TestClient(main.app)


@pytest.fixture(autouse=True)
def clear_data():
    main.catalog.clear()
    main.students.clear()
    yield
    main.catalog.clear()
    main.students.clear()


CATALOG_HTML = """
<html>
<body>
<table>
<tr>
  <th>Course Code</th><th>Title</th><th>Credits</th>
  <th>Prerequisites</th><th>Cross-listed</th>
</tr>
<tr>
  <td>COSC 2007</td><td>Data Structures II</td><td>3</td>
  <td>None</td><td></td>
</tr>
<tr>
  <td>COSC 3506</td><td>Software Engineering</td><td>3</td>
  <td>COSC 2007</td><td>ITEC 3506</td>
</tr>
<tr>
  <td>ITEC 3506</td><td>Software Engineering</td><td>3</td>
  <td>COSC 2007</td><td>COSC 3506</td>
</tr>
</table>
</body>
</html>
"""


TRANSCRIPT_HTML = """
<html>
<body>
<table>
<tr>
  <th>Status</th><th>Course</th><th>Title</th>
  <th>Grade</th><th>Term</th><th>Credits</th>
</tr>
<tr>
  <td>Completed</td><td>COSC-2007</td><td>Data Structures II</td>
  <td>75</td><td>24F</td><td>3</td>
</tr>
<tr>
  <td>Attempted</td><td>COSC-3506</td><td>Software Engineering</td>
  <td>45</td><td>25F</td><td>0</td>
</tr>
<tr>
  <td>Completed</td><td>COSC-3506</td><td>Software Engineering</td>
  <td>72</td><td>26W</td><td>3</td>
</tr>
</table>
</body>
</html>
"""


def import_catalog():
    response = client.post(
        "/api/v1/admin/catalog/import",
        files={"file": ("catalog.html", CATALOG_HTML, "text/html")},
    )
    assert response.status_code == 200
    return response


def import_history(student_id="111"):
    response = client.post(
        f"/api/v1/students/{student_id}/history/import",
        files={"file": ("student.html", TRANSCRIPT_HTML, "text/html")},
    )
    assert response.status_code == 201
    return response


def test_root_and_catalog():
    response = client.get("/")
    assert response.status_code == 200

    response = import_catalog()
    assert response.json()["courses_imported"] == 3

    response = client.get("/api/v1/catalog/courses/cosc-3506")
    assert response.status_code == 200
    assert response.json()["credits"] == 3

    response = client.get("/api/v1/catalog/courses/unknown")
    assert response.status_code == 404


def test_history_import_profile_update_and_delete():
    response = import_history()
    assert response.json()["past_courses_imported"] == 3

    response = client.get("/api/v1/students/111/profile")
    assert response.status_code == 200
    assert response.json()["student_id"] == "111"
    assert len(response.json()["history"]) == 3
    assert response.json()["plan"] == []

    replacement = {
        "history": [
            {
                "course_code": "COSC-2007",
                "term": "24F",
                "credits_earned": 3,
                "status": "Completed",
            }
        ]
    }

    response = client.put(
        "/api/v1/students/111/history",
        json=replacement,
    )
    assert response.status_code == 200

    response = client.delete("/api/v1/students/111/history")
    assert response.status_code == 200

    response = client.get("/api/v1/students/111/profile")
    assert response.json()["history"] == []


def test_plan_lifecycle_and_unknown_student():
    import_history()

    plan = {
        "planned_courses": [
            {"course_code": "COSC-3506", "term": "26F"}
        ]
    }

    response = client.post("/api/v1/students/111/plan", json=plan)
    assert response.status_code == 200
    assert response.json()["planned_courses_saved"] == 1

    replacement = {
        "planned_courses": [
            {"course_code": "ITEC-3506", "term": "27W"}
        ]
    }

    response = client.put(
        "/api/v1/students/111/plan",
        json=replacement,
    )
    assert response.status_code == 200

    response = client.get("/api/v1/students/111/profile")
    assert response.json()["plan"][0]["course_code"] == "ITEC-3506"

    response = client.delete("/api/v1/students/111/plan")
    assert response.status_code == 200

    assert client.get("/api/v1/students/missing/profile").status_code == 404
    assert client.post(
        "/api/v1/students/missing/plan",
        json=plan,
    ).status_code == 404


def test_audit_ok_and_credit_summary():
    import_catalog()
    import_history()

    plan = {
        "planned_courses": [
            {"course_code": "COSC-3506", "term": "26F"}
        ]
    }
    client.post("/api/v1/students/111/plan", json=plan)

    response = client.get(
        "/api/v1/students/111/audit-report"
    )
    assert response.status_code == 200

    data = response.json()
    assert data["student_id"] == "111"
    assert data["status"] == "ok"
    assert data["credit_summary"]["total_earned"] == 6
    assert data["credit_summary"]["total_planned"] == 3
    assert data["credit_summary"]["total_remaining_for_graduation"] == 111


def test_missing_prerequisite_and_strict_status():
    import_catalog()
    import_history("222")

    main.students["222"]["history"] = []

    plan = {
        "planned_courses": [
            {"course_code": "COSC-3506", "term": "26F"}
        ]
    }
    client.post("/api/v1/students/222/plan", json=plan)

    response = client.get(
        "/api/v1/students/222/audit-report"
    )
    assert response.status_code == 200
    assert response.json()["status"] == "warning"
    assert response.json()["timeline_validation"][0]["errors"][0][
        "type"
    ] == "MISSING_PREREQUISITE"

    response = client.get(
        "/api/v1/students/222/audit-report?strict=true"
    )
    assert response.status_code == 200
    assert response.json()["status"] == "failed"


def test_cross_list_conflict():
    import_catalog()
    import_history()

    plan = {
        "planned_courses": [
            {"course_code": "ITEC-3506", "term": "26F"}
        ]
    }
    client.post("/api/v1/students/111/plan", json=plan)

    response = client.get(
        "/api/v1/students/111/audit-report"
    )
    assert response.status_code == 200

    violations = response.json()["cross_list_violations"]
    assert len(violations) == 1
    assert violations[0]["type"] == "CROSS_LIST_CONFLICT"
