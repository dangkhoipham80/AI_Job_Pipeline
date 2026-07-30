"""A fictional CV for tests and the demo seeder.

The application never reads this — ``ensure_master`` bootstraps an empty document
(``cv/skeleton.py``) and everything real lives in the database. This exists so
the test suite has a stable, realistic document to assert against without
depending on whoever's machine it runs on, and so ``scripts/seed_demo.py`` can
produce a dashboard worth looking at.

Everyone and everything here is invented.
"""

from __future__ import annotations

from jobpilot.cv.schema import (
    BulletItem,
    BulletsSection,
    CvDocument,
    EducationEntry,
    EducationSection,
    Entry,
    ExperienceSection,
    Header,
    Link,
    ParagraphSection,
    ProjectsSection,
    Theme,
)


def sample_document() -> CvDocument:
    """A backend-flavoured CV with the shape the tailor and guardrails expect."""
    return CvDocument(
        theme=Theme(color="awesome-red"),
        header=Header(
            first_name="ALEX",
            last_name="EXAMPLE",
            position="Fresher Software Engineer",
            mobile="(+84) 900 000 000",
            email="alex@example.com",
            github="alex-example",
            linkedin="alex-example",
            extra_info=Link(label="Portfolio", url="https://alex.example.com/"),
        ),
        sections=[
            ParagraphSection(
                key="summary",
                title="Summary",
                text=(
                    "Software Engineer focused on backend development and distributed "
                    "systems. Experienced with Java Spring Boot, RESTful APIs, and CI/CD "
                    "pipelines in building scalable services. Comfortable working in team "
                    "environments, following clean code practices, and continuously "
                    "improving system quality and reliability."
                ),
            ),
            EducationSection(
                key="education",
                title="Education",
                entries=[
                    EducationEntry(
                        degree="`Bachelor's`, Software Engineering",
                        institution="Example University",
                        location="Ho Chi Minh, Viet Nam",
                        date="Oct. 2022 -- Apr. 2026",
                        items=[
                            "Major in **Java Backend Development**.",
                            "Current GPA: **3.5/4.0**.",
                        ],
                    ),
                    EducationEntry(
                        degree="High School Diploma, Specialized in **Mathematics**",
                        institution="Example High School",
                        location="Example City, Viet Nam",
                        date="2019 -- 2022",
                        items=["Graduated with GPA: **9.0/10.0**."],
                    ),
                ],
            ),
            ExperienceSection(
                key="experience",
                title="Work Experience",
                entries=[
                    Entry(
                        title="Example Software, Junior Software Engineer - Backend",
                        date="Ho Chi Minh City, Dec. 2024 -- Present",
                        items=[
                            "Worked in a **Scrum-based** microservices environment using "
                            "`Java Spring Boot` to develop and maintain backend services.",
                            "Implemented and migrated RESTful APIs for enterprise systems "
                            "following clean architecture principles.",
                            "Wrote **unit tests** with `JUnit`, achieving **over 80% code "
                            "coverage** measured by **JaCoCo**.",
                            "Debugged and fixed production issues by analyzing logs and "
                            "metrics on `Grafana`.",
                            "Deployed services through `Jenkins CI/CD` pipelines and managed "
                            "tasks and sprints using **Jira**.",
                        ],
                        tech_stack=[
                            "Java",
                            "Spring Boot",
                            "Microservices",
                            "JUnit",
                            "JaCoCo",
                            "Grafana",
                            "Jenkins",
                            "Jira",
                        ],
                    )
                ],
            ),
            ProjectsSection(
                key="projects",
                title="Projects",
                entries=[
                    Entry(
                        title="Lumen -- Generative Lesson Platform (5 members, `Java` + `Python`)",
                        url="https://github.com/example/lumen",
                        date="Aug 2025 -- Nov 2025",
                        items=[
                            "Built an AI-powered learning platform that ingests textbooks, "
                            "detects lessons, and serves grounded Q&A using **RAG** and "
                            "vector search.",
                            "Designed a **microservices** system with `Spring Boot`, "
                            "**Spring Cloud Gateway**, **Eureka**, and **JWT**.",
                            "Built an RAG pipeline using **FastAPI**, **LangChain**, "
                            "**FAISS**, **MongoDB**, and OCR.",
                        ],
                        role="Team Lead",
                        tech_stack=[
                            "Spring Boot",
                            "FastAPI",
                            "Kafka",
                            "MongoDB",
                            "React",
                            "Docker",
                        ],
                    ),
                    Entry(
                        title="Pathfinder -- Educational Platform (5 members, `Java`)",
                        url="https://gitlab.com/example/pathfinder",
                        date="Jun 2024 -- Jul 2024",
                        items=[
                            "Built a university exploration platform with an "
                            "**AI-powered chatbot**.",
                            "Developed real-time data visualization with **PostgreSQL** and "
                            "**MongoDB**.",
                        ],
                        role="Team Lead",
                        tech_stack=["Java", "Spring Boot", "PostgreSQL", "MongoDB", "React"],
                    ),
                    Entry(
                        title="Roundtable -- Social Platform (5 members, `Python`)",
                        url="https://gitlab.com/example/roundtable",
                        date="May 2024 -- Jul 2024",
                        items=[
                            "Built a social platform with **FastAPI WebSocket** for "
                            "real-time messaging.",
                            "Implemented secure auth with **Firebase**, **JWT**, and a "
                            "**React** + **TailwindCSS** UI.",
                        ],
                        role="Team Lead",
                        tech_stack=["FastAPI", "Firebase", "JWT", "React", "TailwindCSS"],
                    ),
                ],
            ),
            BulletsSection(
                key="honors",
                title="Honors & Awards",
                items=[
                    BulletItem(
                        text="**Solved 300+ LeetCode Problems** covering Data Structures & "
                        "Algorithms.",
                        date="2024 -- Present",
                    )
                ],
            ),
            BulletsSection(
                key="skills",
                title="Skills",
                items=[
                    BulletItem(
                        label="Languages & Frameworks",
                        text="Java, Spring Boot, Python, FastAPI",
                    ),
                    BulletItem(
                        label="Databases & Testing", text="PostgreSQL, MongoDB, JUnit, JaCoCo"
                    ),
                    BulletItem(
                        label="Cloud, DevOps & Tools",
                        text="AWS, Docker, Kubernetes, Jenkins, Git, Jira",
                    ),
                ],
            ),
        ],
    )
