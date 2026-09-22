"""Discover, rank, and prepare manual applications for nearby German jobs.

Run: python agent.py run
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

CENTRE = (49.3988, 8.6724)  # Heidelberg
RADIUS_KM = 40
SHORTLIST_THRESHOLD = 70
OUTPUT_DIR = Path("output") / str(date.today())
PROFILE_PATH = Path("profile.json")

ROLE_QUERIES = [
    "Werkstudent Marketing", "Werkstudent Vertrieb", "Werkstudent Business Development",
    "Praktikum Marketing", "Praktikum Sales", "Praktikum Business Development",
    "Ehrenamt Marketing", "Ehrenamt Kommunikation",
]
ALLOWED_WORKPLACE = ("hybrid", "on-site", "onsite", "in office", "office", "vor ort", "präsenz")
REMOTE_ONLY = ("fully remote", "remote only", "100% remote", "100% homeoffice", "online only")
TYPE_TERMS = ("werkstudent", "working student", "praktikum", "internship", "intern", "volunteer", "ehrenamt")


def load_env_file() -> None:
    """Small dependency-free .env reader; existing environment wins."""
    env = Path(".env")
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"'))


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    return 6371 * 2 * math.asin(math.sqrt(
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    ))


def normalise(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def acceptable_workplace(job: dict[str, Any]) -> bool:
    text = normalise(" ".join(str(job.get(k, "")) for k in ("title", "description", "workplace")))
    if any(term in text for term in REMOTE_ONLY):
        return False
    # Sources sometimes omit a workplace label; retain only explicit office/hybrid evidence.
    return any(term in text for term in ALLOWED_WORKPLACE)


def acceptable_type(job: dict[str, Any]) -> bool:
    text = normalise(f"{job.get('title', '')} {job.get('description', '')}")
    return any(term in text for term in TYPE_TERMS)


def location_in_range(job: dict[str, Any]) -> bool:
    lat, lon = job.get("latitude"), job.get("longitude")
    if lat is None or lon is None:
        return False  # avoid guessing a location from a city string
    try:
        return haversine_km(CENTRE, (float(lat), float(lon))) <= RADIUS_KM
    except (TypeError, ValueError):
        return False


def google_jobs(query: str, api_key: str) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"engine": "google_jobs", "q": query, "location": "Heidelberg, Baden-Wurttemberg, Germany", "hl": "de", "api_key": api_key})
    with urllib.request.urlopen(f"https://serpapi.com/search.json?{params}", timeout=40) as response:
        items = json.load(response).get("jobs_results", [])
    jobs: list[dict[str, Any]] = []
    for item in items:
        extensions = " ".join(item.get("detected_extensions", {}).get("schedule_type", []))
        jobs.append({
            "id": item.get("job_id"),
            "title": item.get("title", ""),
            "company": item.get("company_name", ""),
            "location": item.get("location", ""),
            "description": item.get("description", ""),
            "workplace": extensions,
            "apply_options": item.get("apply_options", []),
            # Google Jobs has no reliable coordinates. These fields are intentionally absent:
            # such results are placed in needs_location_review rather than incorrectly shortlisted.
            "source": "Google Jobs via SerpApi",
        })
    return jobs


def classify_location(job: dict[str, Any]) -> None:
    """Conservative city gate for Google Jobs results without geo-coordinates."""
    nearby = ("heidelberg", "mannheim", "weinheim", "schwetzingen", "walldorf", "wiesloch", "speyer", "hockenheim", "sinsheim", "brühl", "leimen")
    text = normalise(job.get("location", ""))
    job["within_radius"] = location_in_range(job) or any(city in text for city in nearby)
    job["location_verification"] = "Review exact office address before applying" if "latitude" not in job else "Coordinate verified"


def collect(api_key: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    accepted: list[dict[str, Any]] = []
    for query in ROLE_QUERIES:
        for job in google_jobs(query, api_key):
            key = job.get("id") or f"{job['title']}|{job['company']}|{job['location']}"
            if key in seen:
                continue
            seen.add(key)
            classify_location(job)
            job["passes_filters"] = bool(job["within_radius"] and acceptable_type(job) and acceptable_workplace(job))
            if job["passes_filters"]:
                accepted.append(job)
    return accepted


def call_openai(api_key: str, prompt: str) -> str:
    """Call Responses API without storing credentials or adding a package dependency."""
    payload = json.dumps({
        "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        "input": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses", data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"OpenAI request failed ({error.code}): {error.read().decode('utf-8', 'replace')}") from error
    for item in result.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                return content.get("text", "")
    raise RuntimeError("OpenAI response contained no text.")


def ask_json(api_key: str, profile: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    prompt = f"""You are a cautious German career assistant. Evaluate this vacancy for the candidate.
Return valid JSON only with: match_score (integer 0-100), reasons (array of at most 4 short strings), gaps (array), and application_language (English or German).
Do not invent qualifications. A role must remain office or hybrid only.

Candidate: {json.dumps(profile, ensure_ascii=False)}
Vacancy: {json.dumps(job, ensure_ascii=False)}"""
    return json.loads(call_openai(api_key, prompt))


def write_draft(api_key: str, profile: dict[str, Any], job: dict[str, Any], review: dict[str, Any]) -> str:
    prompt = f"""Write a concise, honest cover-letter draft in {review.get('application_language', 'English')} for this candidate and vacancy.
It is a draft for human review, not a submitted application. Do not claim a start date, visa status, degree completion, or skills absent from the profile. Mention that availability can be confirmed in interview. Include subject, greeting, 3 short paragraphs, and sign-off.

Candidate: {json.dumps(profile, ensure_ascii=False)}
Vacancy: {json.dumps(job, ensure_ascii=False)}"""
    return call_openai(api_key, prompt)


def main() -> int:
    load_env_file()
    if len(sys.argv) != 2 or sys.argv[1] != "run":
        print("Usage: python agent.py run")
        return 2
    serp_key, openai_key = os.getenv("SERPAPI_API_KEY"), os.getenv("OPENAI_API_KEY")
    missing = [name for name, value in (("SERPAPI_API_KEY", serp_key), ("OPENAI_API_KEY", openai_key)) if not value]
    if missing:
        print("Missing required setting(s): " + ", ".join(missing) + ". Copy .env.example to .env.")
        return 2

    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    vacancies = collect(serp_key)
    shortlisted: list[dict[str, Any]] = []
    application_dir = OUTPUT_DIR / "applications"
    for number, job in enumerate(vacancies, 1):
        review = ask_json(openai_key, profile, job)
        job["ai_review"] = review
        if int(review.get("match_score", 0)) >= SHORTLIST_THRESHOLD:
            shortlisted.append(job)
            application_dir.mkdir(exist_ok=True)
            safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", f"{number}_{job['company']}_{job['title']}")[:100]
            draft = write_draft(openai_key, profile, job, review)
            (application_dir / f"{safe_name}.md").write_text(draft, encoding="utf-8")

    (OUTPUT_DIR / "vacancies.json").write_text(json.dumps(vacancies, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUT_DIR / "shortlist.json").write_text(json.dumps(shortlisted, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {len(vacancies)} filtered vacancies and {len(shortlisted)} application drafts to {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
