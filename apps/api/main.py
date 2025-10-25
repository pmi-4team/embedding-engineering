# apps/api/main.py
from fastapi import FastAPI

app = FastAPI(title="Feedback API")

@app.get("/health")
def health():
    return {"ok": True}

try:
    from apps.api.routers.search import router as search_router
    from apps.api.routers.insights import router as insights_router
    app.include_router(search_router, prefix="/search", tags=["search"])
    app.include_router(insights_router, prefix="/insights", tags=["insights"])
except Exception:
    pass
