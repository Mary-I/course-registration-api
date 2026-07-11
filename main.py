from typing import List

import re
from bs4 import BeautifulSoup
from fastapi import FastAPI, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel


app = FastAPI(title="Course Registration and Academic Audit API")

# Catalog records are keyed by normalized course code.
catalog = {}

# Student records are isolated by student_id.
students = {}


# -------------------------
# Pydantic request models
# -------------------------

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


# -------------------------
# Shared helper functions
# -------------------------

def normalize_course_code(course_code: str) -> str:
    """Uppercase a course code and remove spaces and hyphens."""
    return re.sub(r"[\s-]+", "", course_code).upper()


def extract_course_codes(text: str) -> List[str]:
    """Extract course codes from prerequisite or cross-list text."""
    if not text:
        return []

    pattern = r"\b[A-Z]{3,4}[\s-]?\d{4}\b"
    matches = re.findall(pattern, text.upper())

    result = []
    seen = set()

    for match in matches:
        cleaned = match.strip()

        if cleaned not in seen:
            result.append(cleaned)
            seen.add(cleaned)

    return result


def parse_credits(value: str) -> int:
    """Convert a credit value to an integer; invalid values become zero."""
    try:
        match = re.search(r"\d+(?:\.\d+)?", value)

        if not match:
            return 0

        return int(float(match.group()))
    except (TypeError, ValueError):
        return 0


def grade_rank(grade: str) -> int:
    """
    Numeric grade > letter grade > P/Pass > blank.

    Used when the same course and term appear in multiple transcript tables.
    """
    grade = grade.strip().upper()

    if re.fullmatch(r"\d+(?:\.\d+)?", grade):
        return 3

    if grade and grade not in {"P", "PASS"}:
        return 2

    if grade in {"P", "PASS"}:
        return 1

    return 0


def term_sort_key(term: str):
    """
    Convert terms such as 23F, 24W, 26SP and 26F into sortable values.

    Required season order:
    W < SP < S < F
    """
    cleaned = term.strip().upper()
    match = re.fullmatch(r"(\d{2})(W|SP|S|F)", cleaned)

    if not match:
        return 9999, 999

    year = int(match.group(1))
    season = match.group(2)
    season_order = {
        "W": 0,
        "SP": 1,
        "S": 2,
        "F": 3,
    }

    return year, season_order[season]


def require_student(student_id: str):
    if student_id not in students:
        raise HTTPException(status_code=404, detail="Student not found")


# -------------------------
# Phase 1: Catalog parsing
# -------------------------

def parse_catalog_html(html_content: str):
    soup = BeautifulSoup(html_content, "html.parser")
    parsed_catalog = {}

    for table in soup.find_all("table"):
        rows = table.find_all("tr")

        for row in rows:
            cells = row.find_all("td")

            if len(cells) < 5:
                continue

            course_code = cells[0].get_text(" ", strip=True)
            title = cells[1].get_text(" ", strip=True)
            credits = parse_credits(cells[2].get_text(" ", strip=True))
            prerequisite_text = cells[3].get_text(" ", strip=True)
            cross_listed_text = cells[4].get_text(" ", strip=True)

            if not re.search(r"[A-Za-z]{3,4}[\s-]?\d{4}", course_code):
                continue

            normalized_code = normalize_course_code(course_code)

            parsed_catalog[normalized_code] = {
                "course_code": normalized_code,
                "title": title,
                "credits": credits,
                "prerequisites": extract_course_codes(prerequisite_text),
                "cross_listed": extract_course_codes(cross_listed_text),
            }

    return parsed_catalog


@app.post("/api/v1/admin/catalog/import")
async def import_catalog(file: UploadFile = File(...)):
    content = await file.read()
    html_content = content.decode("utf-8", errors="ignore")

    parsed_catalog = parse_catalog_html(html_content)

    catalog.clear()
    catalog.update(parsed_catalog)

    return {
        "message": "Catalog imported successfully",
        "courses_imported": len(catalog),
    }


@app.get("/api/v1/catalog/courses/{course_code}")
def get_course(course_code: str):
    normalized_code = normalize_course_code(course_code)

    if normalized_code not in catalog:
        raise HTTPException(status_code=404, detail="Course not found")

    return catalog[normalized_code]


# -------------------------
# Phase 2: Transcript parser
# -------------------------

def parse_transcript_html(html_content: str):
    soup = BeautifulSoup(html_content, "html.parser")
    records = {}

    valid_statuses = {"Completed", "In-Progress", "Attempted"}

    for table in soup.find_all("table"):
        rows = table.find_all("tr")

        for row in rows:
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
                continue

            existing = records[key]

            if new_record["_grade_rank"] > existing["_grade_rank"]:
                records[key] = new_record
            elif (
                new_record["_grade_rank"] == existing["_grade_rank"]
                and new_record["credits_earned"]
                > existing["credits_earned"]
            ):
                records[key] = new_record

    cleaned_records = []

    for record in records.values():
        record.pop("_grade_rank", None)
        cleaned_records.append(record)

    return cleaned_records


@app.post(
    "/api/v1/students/{student_id}/history/import",
    status_code=status.HTTP_201_CREATED,
)
async def import_history(student_id: str, file: UploadFile = File(...)):
    content = await file.read()
    html_content = content.decode("utf-8", errors="ignore")
    history = parse_transcript_html(html_content)

    if student_id not in students:
        students[student_id] = {
            "history": [],
            "plan": [],
        }

    students[student_id]["history"] = history

    return {
        "status": "success",
        "past_courses_imported": len(history),
    }


@app.put("/api/v1/students/{student_id}/history")
def update_history(student_id: str, body: HistoryUpdate):
    require_student(student_id)

    students[student_id]["history"] = [
        record.model_dump() for record in body.history
    ]

    return {
        "status": "success",
        "message": "Academic history updated successfully",
    }


@app.delete("/api/v1/students/{student_id}/history")
def delete_history(student_id: str):
    require_student(student_id)
    students[student_id]["history"] = []

    return {
        "status": "success",
        "message": "Academic history cleared successfully",
    }


@app.post("/api/v1/students/{student_id}/plan")
def create_plan(student_id: str, body: PlanUpdate):
    require_student(student_id)

    students[student_id]["plan"] = [
        course.model_dump() for course in body.planned_courses
    ]

    return {
        "status": "success",
        "planned_courses_saved": len(body.planned_courses),
    }


@app.put("/api/v1/students/{student_id}/plan")
def update_plan(student_id: str, body: PlanUpdate):
    require_student(student_id)

    students[student_id]["plan"] = [
        course.model_dump() for course in body.planned_courses
    ]

    return {
        "status": "success",
        "planned_courses_saved": len(body.planned_courses),
    }


@app.delete("/api/v1/students/{student_id}/plan")
def delete_plan(student_id: str):
    require_student(student_id)
    students[student_id]["plan"] = []

    return {
        "status": "success",
        "message": "Plan cleared successfully",
    }


@app.get("/api/v1/students/{student_id}/profile")
def get_profile(student_id: str):
    require_student(student_id)

    return {
        "student_id": student_id,
        "history": students[student_id]["history"],
        "plan": students[student_id]["plan"],
    }


# -------------------------
# Phase 3: Audit engine
# -------------------------

def completed_course_records(history):
    """
    Return one completed record per normalized course code.

    If a course was taken more than once, use the latest completed record.
    Failed or in-progress attempts do not contribute earned credits.
    """
    completed = {}

    for record in history:
        if record["status"] != "Completed":
            continue

        normalized_code = normalize_course_code(record["course_code"])

        if normalized_code not in completed:
            completed[normalized_code] = record
            continue

        existing = completed[normalized_code]

        if term_sort_key(record["term"]) > term_sort_key(existing["term"]):
            completed[normalized_code] = record
        elif (
            term_sort_key(record["term"]) == term_sort_key(existing["term"])
            and record["credits_earned"] > existing["credits_earned"]
        ):
            completed[normalized_code] = record

    return completed


@app.get("/api/v1/students/{student_id}/audit-report")
def get_audit_report(
    student_id: str,
    strict: bool = Query(default=False),
):
    require_student(student_id)

    history = students[student_id]["history"]
    plan = students[student_id]["plan"]

    completed = completed_course_records(history)

    # Missing-prerequisite errors grouped by planned term.
    errors_by_term = {}

    for planned_course in plan:
        planned_code = normalize_course_code(
            planned_course["course_code"]
        )
        planned_term = planned_course["term"]
        catalog_course = catalog.get(planned_code)

        if not catalog_course:
            continue

        for prerequisite in catalog_course["prerequisites"]:
            prerequisite_code = normalize_course_code(prerequisite)
            completed_prerequisite = completed.get(prerequisite_code)

            prerequisite_is_valid = (
                completed_prerequisite is not None
                and term_sort_key(completed_prerequisite["term"])
                < term_sort_key(planned_term)
            )

            if not prerequisite_is_valid:
                errors_by_term.setdefault(planned_term, []).append(
                    {
                        "course_code": planned_course["course_code"],
                        "type": "MISSING_PREREQUISITE",
                        "message": (
                            f"Missing prerequisite: {prerequisite}"
                        ),
                    }
                )

    timeline_validation = [
        {
            "term": term,
            "errors": errors_by_term[term],
        }
        for term in sorted(errors_by_term, key=term_sort_key)
    ]

    # Cross-list conflicts.
    cross_list_violations = []
    seen_cross_list_conflicts = set()

    for planned_course in plan:
        planned_code = normalize_course_code(
            planned_course["course_code"]
        )
        catalog_course = catalog.get(planned_code)

        if not catalog_course:
            continue

        for cross_listed_code in catalog_course["cross_listed"]:
            normalized_cross_code = normalize_course_code(
                cross_listed_code
            )

            if normalized_cross_code not in completed:
                continue

            conflict_key = (planned_code, normalized_cross_code)

            if conflict_key in seen_cross_list_conflicts:
                continue

            seen_cross_list_conflicts.add(conflict_key)

            completed_display_code = completed[
                normalized_cross_code
            ]["course_code"]

            cross_list_violations.append(
                {
                    "course_code": planned_course["course_code"],
                    "type": "CROSS_LIST_CONFLICT",
                    "message": (
                        "Cross-listed with completed course "
                        f"{completed_display_code}"
                    ),
                }
            )

    # Credit calculations.
    total_earned = sum(
        record["credits_earned"] for record in completed.values()
    )

    total_planned = 0

    for planned_course in plan:
        normalized_code = normalize_course_code(
            planned_course["course_code"]
        )
        catalog_course = catalog.get(normalized_code)

        if catalog_course:
            total_planned += catalog_course["credits"]

    total_remaining = max(
        0,
        120 - total_earned - total_planned,
    )

    has_issues = bool(
        timeline_validation or cross_list_violations
    )

    if not has_issues:
        audit_status = "ok"
    elif strict:
        audit_status = "failed"
    else:
        audit_status = "warning"

    return {
        "student_id": student_id,
        "status": audit_status,
        "timeline_validation": timeline_validation,
        "cross_list_violations": cross_list_violations,
        "credit_summary": {
            "total_earned": total_earned,
            "total_planned": total_planned,
            "total_remaining_for_graduation": total_remaining,
        },
    }


@app.get("/")
def root():
    return {
        "message": (
            "Course Registration and Academic Audit API is running"
        )
    }