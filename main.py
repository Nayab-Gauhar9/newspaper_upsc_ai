import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.api.issues import router as issues_router
from src.api.articles import router as articles_router
app = FastAPI(
    title="UPSC Polity Living Dossiers API",
    description="Multi-source evolving current affairs graph backend for GS-II Mains",
    version="1.0.0",
)

# Enable CORS for FlutterFlow or frontend dashboards
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routes
app.include_router(issues_router)
app.include_router(articles_router)

@app.get("/health")
def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    # Pass the module import string "src.main:app" so auto-reload works properly
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
