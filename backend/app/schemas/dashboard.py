from pydantic import BaseModel


class MySummaryResponse(BaseModel):
    total_calls: int
    resolved: int
    unresolved: int
    avg_duration_sec: int | None


class CategoryCount(BaseModel):
    category_major: str
    count: int


class MidCount(BaseModel):
    category_mid: str
    count: int


class MyTodayResponse(BaseModel):
    total: int
    by_major: list[CategoryCount]
    by_mid: list[MidCount]


class KeywordCount(BaseModel):
    keyword: str
    count: int


class MyKeywordsResponse(BaseModel):
    keywords: list[KeywordCount]


class WeeklyTrendItem(BaseModel):
    date: str
    disease_name: str
    count: int


class MyWeeklyTrendResponse(BaseModel):
    data: list[WeeklyTrendItem]


class HourlyCount(BaseModel):
    hour: int
    count: int


class AllSummaryResponse(BaseModel):
    today: int
    this_week: int
    this_month: int
    hourly: list[HourlyCount]


class TrendItem(BaseModel):
    date: str
    disease_name: str | None = None
    category_mid: str | None = None
    count: int


class TrendResponse(BaseModel):
    period: str
    data: list[TrendItem]


class CategoryItem(BaseModel):
    category: str
    major: str
    mid: str


class CategoriesResponse(BaseModel):
    categories: list[CategoryItem]
