from typing import Annotated

from fastapi import APIRouter, Query, Request, Response

from app.api.v1.resources import Actor, Db, context
from app.core.config import get_settings
from app.search.clients import OpenSearch
from app.search.service import search

router = APIRouter(prefix="/search", tags=["search"])


@router.get("")
async def search_documents(
    request: Request,
    response: Response,
    db: Db,
    user: Actor,
    q: Annotated[str, Query(min_length=2, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return {"data": await search(db, user, OpenSearch(get_settings()), q, limit, context(request))}
