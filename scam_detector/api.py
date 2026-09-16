"""
HTTP API for the scam detector.

Run locally:
    uvicorn scam_detector.api:app --reload

Then POST a posting:
    curl -X POST http://127.0.0.1:8000/analyze \
      -H 'Content-Type: application/json' \
      -d '{"title":"Remote Data Entry","description":"...","company":"Acme"}'

This is a single service, no Kafka, no GPU, no message broker. At the volumes a
job-scam tool actually sees, one process behind uvicorn handles the load. Add a
worker count and a cache when you have traffic that justifies it, not before.
"""

from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel, Field

from .scorer import score_posting

app = FastAPI(title="Job Scam Detector", version="1.0")


class PostingIn(BaseModel):
    title: str = Field(default="", description="Job title")
    description: str = Field(..., description="Full posting or recruiter message text")
    company: str = Field(default="", description="Claimed employer name, if given")
    run_network: bool = Field(default=True, description="Run live domain/MX lookups")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/analyze")
def analyze(posting: PostingIn) -> dict:
    result = score_posting(
        title=posting.title,
        description=posting.description,
        company=posting.company,
        run_network=posting.run_network,
    )
    return result.as_dict()
