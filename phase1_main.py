from fastapi import FastAPI, UploadFile, File, HTTPException
from bs4 import BeautifulSoup
import re

app = FastAPI(title="Course Registration API")

courses = {}


def extract_course_codes(text):
    if not text:
        return []

    pattern = r"\b[A-Z]{3,4}\s?\d{4}\b"
    matches = re.findall(pattern, text)

    cleaned = []
    for match in matches:
        cleaned.append(match.replace(" ", "").upper())

    return list(dict.fromkeys(cleaned))


def parse_credits(text):
    if not text:
        return 0

    match = re.search(r"\d+(\.\d+)?", text)
    if match:
        return float(match.group())

    return 0


def parse_catalog_html(html_content):
    soup = BeautifulSoup(html_content, "html.parser")
    rows = soup.find_all("tr")

    parsed_courses = {}

    for row in rows:
        cells = row.find_all(["td", "th"])

        if len(cells) < 3:
            continue

        cell_texts = [cell.get_text(" ", strip=True) for cell in cells]

        course_code = None
        for text in cell_texts:
            codes = extract_course_codes(text)
            if codes:
                course_code = codes[0]
                break

        if not course_code:
            continue

        title = ""
        credits = 0
        prerequisites = []
        cross_listed = []

        for text in cell_texts:
            lower_text = text.lower()

            if "credit" in lower_text or re.fullmatch(r"\d+(\.\d+)?", text):
                credits = parse_credits(text)

            if "prereq" in lower_text or "requires" in lower_text:
                prerequisites = extract_course_codes(text)

            if "cross" in lower_text:
                cross_listed = extract_course_codes(text)

        for text in cell_texts:
            if course_code not in text and not re.search(r"\d+(\.\d+)?\s*credit", text.lower()):
                if "prereq" not in text.lower() and "cross" not in text.lower():
                    title = text
                    break

        parsed_courses[course_code] = {
            "course_code": course_code,
            "title": title,
            "credits": credits,
            "prerequisites": prerequisites,
            "cross_listed": cross_listed
        }

    return parsed_courses


@app.get("/")
def root():
    return {"message": "Course Registration API is running"}


@app.post("/api/v1/admin/catalog/import")
async def import_catalog(file: UploadFile = File(...)):
    if not file.filename.endswith(".html"):
        raise HTTPException(status_code=400, detail="Only HTML files are allowed")

    content = await file.read()
    html_content = content.decode("utf-8", errors="ignore")

    parsed_courses = parse_catalog_html(html_content)

    if not parsed_courses:
        raise HTTPException(status_code=400, detail="No courses found in uploaded catalog")

    courses.clear()
    courses.update(parsed_courses)

    return {
        "message": "Catalog imported successfully",
        "courses_imported": len(courses)
    }


@app.get("/api/v1/catalog/courses/{course_code}")
def get_course(course_code: str):
    normalized_code = course_code.replace(" ", "").upper()

    if normalized_code not in courses:
        raise HTTPException(status_code=404, detail="Course not found")

    return courses[normalized_code]
