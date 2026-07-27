"""Seed a realistic demo dataset so every dashboard page has something to show.

Idempotent — re-running adds nothing. Reads DATABASE_URL from .env like the rest
of the app, so point it at a throwaway database, not one with real applications
in it.

    python scripts/seed_demo.py
"""

import sys
from datetime import timedelta

from jobpilot.cv import store as cv_store
from jobpilot.store.db import get_sessionmaker
from jobpilot.store.models import Application, Job, JobStatus, Run
from jobpilot.tailor import service
from jobpilot.tailor.engine import FixtureEngine
from jobpilot.tailor.schema import Change, EntryPlan, Requirement, SectionPlan, TailorPlan
from jobpilot.timeutil import vn_now

# Windows consoles default to cp1252; the report below prints non-ASCII.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

now = vn_now()
S = JobStatus

JOBS = [
    (
        "itviec:2156537",
        "Backend Engineer (Java, Spring Boot)",
        "ACME Corp",
        "Ho Chi Minh City",
        "1000-2000 USD",
        "fresher",
        S.REVIEW,
        6,
        "itviec",
        "email",
        "hr@acme.example.com",
        0.82,
    ),
    (
        "itviec:2156601",
        "Junior Java Developer",
        "Zalopay",
        "Ho Chi Minh City",
        "Thuong luong",
        "junior",
        S.SHORTLISTED,
        11,
        "itviec",
        "portal",
        "https://zalopay.example.com/apply",
        0.74,
    ),
    (
        "itviec:2156344",
        "Backend Developer (Microservices)",
        "MoMo",
        "Ho Chi Minh City",
        "1200-2500 USD",
        "junior",
        S.APPROVED,
        20,
        "itviec",
        "email",
        "careers@momo.example.com",
        0.79,
    ),
    (
        "topcv:884120",
        "Fresher Backend Engineer",
        "Northwind Software",
        "Ho Chi Minh City",
        "Up to 15 trieu",
        "fresher",
        S.SUBMITTED,
        30,
        "topcv",
        "email",
        "careers@northwind.example.com",
        0.71,
    ),
    (
        "topcv:884233",
        "Java Backend (Spring Cloud)",
        "VNG",
        "Ho Chi Minh City",
        "Canh tranh",
        "junior",
        S.DISCOVERED,
        4,
        "topcv",
        "portal",
        "https://vng.example.com/careers/884233",
        0.68,
    ),
    (
        "topcv:884301",
        "Software Engineer - Backend",
        "Techcombank",
        "Ha Noi",
        "20-35 trieu",
        "junior",
        S.DISCOVERED,
        9,
        "topcv",
        "portal",
        "https://tcb.example.com/apply",
        0.61,
    ),
    (
        "vietnamworks:551002",
        "Backend Engineer (Java/Kotlin)",
        "Shopee",
        "Ho Chi Minh City",
        "Negotiable",
        "junior",
        S.DISCOVERED,
        14,
        "vietnamworks",
        "external",
        "https://shopee.example.com/jobs/551002",
        0.66,
    ),
    (
        "vietnamworks:551188",
        "Java Developer (Fresher accepted)",
        "NashTech",
        "Ho Chi Minh City",
        "12-18 trieu",
        "fresher",
        S.DISCOVERED,
        26,
        "vietnamworks",
        "email",
        "hr@nashtech.example.com",
        0.72,
    ),
    (
        "vietnamworks:551205",
        "Backend Engineer",
        "Katalon",
        "Ho Chi Minh City",
        "1500-2200 USD",
        "junior",
        S.SHORTLISTED,
        40,
        "vietnamworks",
        "portal",
        "https://katalon.example.com/apply",
        0.77,
    ),
    (
        "itviec:2155990",
        "Senior Backend Engineer",
        "Grab",
        "Ho Chi Minh City",
        "3000+ USD",
        "senior",
        S.SKIPPED,
        52,
        "itviec",
        "portal",
        "https://grab.example.com/apply",
        0.31,
    ),
    (
        "topcv:883901",
        "Java Backend Engineer",
        "OneMount",
        "Ha Noi",
        "25-40 trieu",
        "junior",
        S.FAILED,
        60,
        "topcv",
        "email",
        "not-an-email",
        0.64,
    ),
    (
        "itviec:2155770",
        "Backend Developer (Node/Java)",
        "Tiki",
        "Ho Chi Minh City",
        "Thuong luong",
        "junior",
        S.DISCOVERED,
        70,
        "itviec",
        "portal",
        "https://tiki.example.com/apply",
        0.58,
    ),
]

JD = """**Ve cong viec**

Chung toi dang tim Backend Engineer lam viec voi Java va Spring Boot de xay dung
va bao tri cac dich vu microservices.

**Yeu cau**
- Java, Spring Boot
- RESTful API, microservices
- PostgreSQL hoac MySQL
- Kinh nghiem voi CI/CD (Jenkins, GitLab CI)
- Uu tien: Apache Kafka, Kubernetes

**Quyen loi**
- Luong thuong canh tranh, review 2 lan/nam
- Laptop, bao hiem suc khoe
"""

db = get_sessionmaker()()
cv_store.ensure_master(db)

for jid, title, company, loc, salary, level, status, hours, source, channel, target, score in JOBS:
    if db.get(Job, jid):
        continue
    db.add(
        Job(
            id=jid,
            source=source,
            title=title,
            company=company,
            location=loc,
            salary=salary,
            level=level,
            status=status,
            match_score=score,
            apply_channel=channel,
            apply_target=target,
            url=f"https://{source}.com/jobs/{jid.split(':')[1]}",
            posted_at=now - timedelta(hours=hours),
            crawled_at=now - timedelta(hours=max(0, hours - 2)),
            payload={
                "skills": ["Java", "Spring Boot", "PostgreSQL", "Docker", "Kafka"][
                    : 3 + (hours % 3)
                ],
                "description_md": JD,
                "is_fresh": hours < 48,
            },
        )
    )
db.commit()
print(f"seeded {len(JOBS)} jobs")

PLAN = TailorPlan(
    match_score=0.82,
    requirements=[
        Requirement(
            text="Java, Spring Boot",
            kind="must_have",
            status="HAVE",
            evidence="experience: Example Software",
        ),
        Requirement(
            text="RESTful API, microservices",
            kind="must_have",
            status="HAVE",
            evidence="experience + projects: Slide AI",
        ),
        Requirement(
            text="PostgreSQL or MySQL",
            kind="must_have",
            status="HAVE",
            evidence="skills: Databases & Testing",
        ),
        Requirement(
            text="CI/CD (Jenkins, GitLab CI)",
            kind="must_have",
            status="PARTIAL",
            evidence="experience: Jenkins CI/CD pipelines",
        ),
        Requirement(
            text="Apache Kafka",
            kind="nice_to_have",
            status="PARTIAL",
            evidence="projects: Slide AI tech stack",
        ),
        Requirement(
            text="Kubernetes",
            kind="nice_to_have",
            status="PARTIAL",
            evidence="skills: Cloud, DevOps & Tools",
        ),
        Requirement(text="GitLab CI", kind="nice_to_have", status="MISSING"),
        Requirement(text="5+ years of experience", kind="must_have", status="MISSING"),
    ],
    summary=(
        "Backend engineer building **RESTful APIs** and `microservices` with `Java Spring Boot`, "
        "with **unit testing** in `JUnit` and `Jenkins CI/CD` pipelines in production."
    ),
    section_order=["summary", "skills", "experience", "projects", "education", "honors"],
    sections=[
        SectionPlan(key="honors", enabled=False),
        SectionPlan(key="projects", entry_order=[0, 1]),
    ],
    entries=[EntryPlan(section_key="experience", entry_index=0, tech_stack_order=[1, 0, 2, 3, 6])],
    changes=[
        Change(
            section="summary",
            what="Summary rewritten around Spring Boot microservices",
            reason="must_have Java, Spring Boot",
        ),
        Change(
            section="skills",
            what="Skills promoted above Work Experience",
            reason="ATS reads the top of the page first",
        ),
        Change(
            section="experience",
            what="Tech stack reordered, Spring Boot first",
            reason="must_have Java, Spring Boot",
        ),
        Change(
            section="projects",
            what="Food Forum dropped",
            reason="one-page budget, least relevant to backend",
        ),
        Change(section="honors", what="Honors hidden", reason="one-page budget"),
    ],
)

target_job = "itviec:2156537"
if not cv_store.list_versions(db, target_job):
    db.get(Job, target_job).status = JobStatus.SHORTLISTED
    db.commit()
    out = service.tailor_job(db, target_job, FixtureEngine(plan=PLAN))
    print(f"tailored {target_job}: v{out.version}, {out.pages} page(s)")

if not db.query(Application).count():
    db.add_all(
        [
            Application(
                job_id="topcv:884120",
                channel="email",
                result="success",
                submitted_at=now - timedelta(hours=26),
                cv_pdf_path="out/cv/topcv_884120/cv.pdf",
                meta={
                    "email": {
                        "to": "alex.test@example.com",
                        "intended_to": "careers@northwind.example.com",
                        "redirected": True,
                        "subject": "Application for Fresher Backend Engineer - Alex Example",
                        "from": "alex@example.com",
                        "attachments": ["cv.pdf"],
                        "dry_run": False,
                        "body_preview": "Dear Hiring Team at Northwind Software,",
                    }
                },
            ),
            Application(
                job_id="itviec:2156344",
                channel="email",
                result="dry_run",
                cv_pdf_path="out/cv/itviec_2156344/cv.pdf",
                meta={
                    "email": {
                        "to": "careers@momo.example.com",
                        "intended_to": "careers@momo.example.com",
                        "redirected": False,
                        "subject": "Application for Backend Developer - Alex Example",
                        "from": "alex@example.com",
                        "attachments": ["cv.pdf"],
                        "dry_run": True,
                        "body_preview": "Dear Hiring Team at MoMo,",
                    }
                },
            ),
            Application(
                job_id="vietnamworks:551205",
                channel="portal",
                result="awaiting_user",
                cv_pdf_path="out/cv/vietnamworks_551205/cv.pdf",
                meta={
                    "handoff": {
                        "url": "https://katalon.example.com/apply",
                        "prefilled": False,
                        "note": "Nothing was submitted. Open the link, paste the fields, attach the CV.",
                        "fields": {
                            "full_name": "Alex Example",
                            "email": "alex@example.com",
                            "phone": "(+84) 900 000 000",
                        },
                    }
                },
            ),
            Application(
                job_id="topcv:883901",
                channel="email",
                result="failed",
                error_msg="no usable email address for this job (apply_target='not-an-email')",
                cv_pdf_path="out/cv/topcv_883901/cv.pdf",
                meta={},
            ),
        ]
    )
    db.commit()
    print("seeded 4 applications")

if db.query(Run).count() < 3:
    db.add_all(
        [
            Run(
                kind="crawl",
                started_at=now - timedelta(hours=6),
                finished_at=now - timedelta(hours=6) + timedelta(minutes=3),
                stats={
                    "query": "Java Spring Boot Backend",
                    "inserted": 7,
                    "updated": 3,
                    "duplicates": 1,
                    "fresh": 4,
                },
            ),
            Run(
                kind="crawl",
                started_at=now - timedelta(hours=30),
                finished_at=now - timedelta(hours=30) + timedelta(minutes=4),
                stats={
                    "query": "Java Spring Boot Backend",
                    "inserted": 5,
                    "updated": 1,
                    "duplicates": 2,
                    "fresh": 3,
                },
            ),
            Run(
                kind="apply",
                started_at=now - timedelta(hours=26),
                finished_at=now - timedelta(hours=26),
                stats={"job_id": "topcv:884120", "channel": "email", "result": "success"},
            ),
            Run(
                kind="apply",
                started_at=now - timedelta(hours=2),
                finished_at=now - timedelta(hours=2),
                stats={
                    "job_id": "topcv:883901",
                    "channel": "email",
                    "result": "failed",
                    "ok": False,
                    "error": "no usable email address for this job",
                },
            ),
        ]
    )
    db.commit()
    print("seeded runs")

print("done")
