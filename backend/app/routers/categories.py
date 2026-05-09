from fastapi import APIRouter, Depends
import asyncpg

from app.core.database import get_conn
from app.schemas.dashboard import CategoriesResponse, CategoryItem

router = APIRouter(prefix="/api/categories", tags=["categories"])


@router.get("", response_model=CategoriesResponse)
async def get_categories(conn: asyncpg.Connection = Depends(get_conn)):
    rows = await conn.fetch(
        "SELECT category, major, mid FROM category_master ORDER BY category, major, mid"
    )
    return CategoriesResponse(categories=[CategoryItem(**dict(r)) for r in rows])
