from fastapi import FastAPI, UploadFile, File, HTTPException, status
from pydantic import BaseModel
from bs4 import BeautifulSoup
from typing import List
import re

app = FastAPI(title="Student Academic History API")

students = {}


class HistoryRecord(BaseModel):
    course_code: str
    term: str
    credits_earned: int
    status: str


class HistoryUpdate(BaseModel):
    history: List[HistoryRecord]


class PlannedCourse(BaseModel):
    course_code: str
    term: str


class PlanUpdate(BaseModel):
    planned_courses: List[PlannedCourse]


def grade_rank(grade: str):
    grade = grade.strip()

    if re.fullmatch(r"\d+(\.\d+)?", grade):
        return 3

    if grade and grade.upper() not in ["P", "PASS"]:
        return 2

    if grade.upper() in ["P", "PASS"]:
        return 1

    return 0


def parse_credits(value: str):
    try:
        return int(float(value.strip()))
    except:
        return 0


def parse_transcript_html(html_content: str):
    soup = BeautifulSoup(html_content, "html.parser")
    records = {}

    valid_statuses = {"Completed", "In-Progress", "Attempted"}

    for table in soup.find_all("table"):
        rows = table.find_all("tr")

        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            values = [cell.get_text(" ", strip=True) for cell in cells]

            if len(values) < 6:
                continue

            status_value = values[0]
            course_code = values[1]
            grade = values[3]
            term = values[4]
            credits = parse_credits(values[5])

            if status_value not in valid_statuses:
                continue

            if not term:
                continue

            key = (course_code, term)

            new_record = {
                "course_code": course_code,
                "term": term,
                "credits_earned": credits,
                "status": status_value,
                "_grade_rank": grade_rank(grade),
            }

            if key not in records:
                records[key] = new_record
            else:
                old = records[key]

                if new_record["_grade_rank"] > old["_grade_rank"]:
                    records[key] = new_record
                elif new_record["_grade_rank"] == old["_grade_rank"]:
                    if new_record["credits_earned"] > old["credits_earned"]:
                        records[key] = new_record

    cleaned = []

    for record in records.values():
        record.pop("_grade_rank", None)
        cleaned.append(record)

    return cleaned


def require_student(student_id: str):
    if student_id not in students:
        raise HTTPException(status_code=404, detail="Student not found")


@app.get("/")
def root():
    return {"message": "Student Academic History API is running"}


@app.post("/api/v1/students/{student_id}/history/import", status_code=status.HTTP_201_CREATED)
async def import_history(student_id: str, file: UploadFile = File(...)):
    content = await file.read()
    html_content = content.decode("utf-8", errors="ignore")

    history = parse_transcript_html(html_content)

    students[student_id] = {
        "history": history,
        "plan": []
    }

    return {
        "status": "success",
        "past_courses_imported": len(history)
    }


@app.put("/api/v1/students/{student_id}/history")
def update_history(student_id: str, body: HistoryUpdate):
    require_student(student_id)

    students[student_id]["history"] = [record.dict() for record in body.history]

    return {
        "status": "success",
        "message": "Academic history updated successfully"
    }


@app.delete("/api/v1/students/{student_id}/history")
def delete_history(student_id: str):
    require_student(student_id)

    students[student_id]["history"] = []

    return {
        "status": "success",
        "message": "Academic history cleared successfully"
    }


@app.post("/api/v1/students/{student_id}/plan")
def create_plan(student_id: str, body: PlanUpdate):
    require_student(student_id)

    students[student_id]["plan"] = [course.dict() for course in body.planned_courses]

    return {
        "status": "success",
        "planned_courses_saved": len(body.planned_courses)
    }


@app.put("/api/v1/students/{student_id}/plan")
def update_plan(student_id: str, body: PlanUpdate):
    require_student(student_id)

    students[student_id]["plan"] = [course.dict() for course in body.planned_courses]

    return {
        "status": "success",
        "planned_courses_saved": len(body.planned_courses)
    }


@app.delete("/api/v1/students/{student_id}/plan")
def delete_plan(student_id: str):
    require_student(student_id)

    students[student_id]["plan"] = []

    return {
        "status": "success",
        "message": "Plan cleared successfully"
    }


@app.get("/api/v1/students/{student_id}/profile")
def get_profile(student_id: str):
    require_student(student_id)

    return {
        "student_id": student_id,
        "history": students[student_id]["history"],
        "plan": students[student_id]["plan"]
    }