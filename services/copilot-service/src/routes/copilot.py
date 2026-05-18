"""Copilot natural language query routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()


class QueryRequest(BaseModel):
    query: str
    context: dict = {}
    stream: bool = False


def get_engine(request: Request):
    return request.app.state.query_engine


@router.post("/query")
async def query(body: QueryRequest, request: Request):
    engine = get_engine(request)
    result = await engine.query(body.query, body.context)
    return result


@router.post("/query/stream")
async def query_stream(body: QueryRequest, request: Request):
    engine = get_engine(request)
    return StreamingResponse(engine.stream_query(body.query), media_type="text/event-stream")


@router.get("/suggestions")
async def get_suggestions(context: str = "", request: Request = None):
    engine = get_engine(request)
    suggestions = await engine.get_suggestions(context)
    return {"suggestions": suggestions}
