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
    match = re.search(r"\d+(\.\d+)?", text)
    if match:
        return float(match.group())
    return 0

def parse_catalog_html(html_content):
    soup = BeautifulSoup(html_content, "html.parser")

    rows = soup.find_all("tr")
    parsed_courses = {}

    for row in rows[1:]:
        cells = row.find_all("td")

        if len(cells) < 5:
            continue

        course_code = cells[0].get_text(strip=True).replace(" ", "")
        title = cells[1].get_text(strip=True)

        try:
            credits = int(cells[2].get_text(strip=True))
        except:
            credits = 0

        prereq_text = cells[3].get_text(strip=True)
        cross_text = cells[4].get_text(strip=True)

        prerequisites = extract_course_codes(prereq_text)
        cross_listed = extract_course_codes(cross_text)

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
    content = await file.read()

    html_content = content.decode("utf-8", errors="ignore")

    parsed_courses = parse_catalog_html(html_content)

    courses.clear()
    courses.update(parsed_courses)

    return {
        "message": "Catalog imported successfully",
        "courses_imported": len(courses)
    }

@app.get("/api/v1/catalog/courses/{course_code}")
def get_course(course_code: str):

    code = course_code.replace(" ", "").upper()

    if code not in courses:
        raise HTTPException(status_code=404, detail="Course not found")

    return courses[code]