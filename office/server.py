"""FastAPI server for the hosted office dashboard."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from stats.office.models import SECTION_NAMES, SectionName
from stats.office.service import OfficeMonitorService

WEB_DIR = Path(__file__).parent / "web"
NO_CACHE_HEADERS = {
  "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
  "Pragma": "no-cache",
}


def create_app(service: OfficeMonitorService | None = None) -> FastAPI:
  office_service = service or OfficeMonitorService()

  @asynccontextmanager
  async def lifespan(_: FastAPI):
    office_service.start()
    try:
      yield
    finally:
      office_service.stop()

  app = FastAPI(
    title="Easysort Office Dashboard",
    version="2.0.0",
    description="LAN-hosted monitoring dashboard for Easysort devices and runners.",
    lifespan=lifespan,
  )
  app.state.office_service = office_service

  app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
  )

  if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="office-static")

  @app.get("/health")
  def health() -> JSONResponse:
    snapshot = office_service.get_snapshot()
    return JSONResponse(
      {
        "status": "ok",
        "service": "office-dashboard",
        "snapshot_status": snapshot.status,
        "generated_at": snapshot.to_dict(include_history=False)["generated_at"],
      },
      headers=NO_CACHE_HEADERS,
    )

  @app.get("/api/status")
  def api_status() -> JSONResponse:
    return JSONResponse(office_service.get_snapshot_dict(), headers=NO_CACHE_HEADERS)

  @app.get("/api/{section_name}")
  def api_section(section_name: str) -> JSONResponse:
    if section_name not in SECTION_NAMES:
      raise HTTPException(status_code=404, detail="Unknown section. Try /api/status")
    return JSONResponse(
      office_service.get_section_response(section_name=section_name),  # type: ignore[arg-type]
      headers=NO_CACHE_HEADERS,
    )

  @app.get("/")
  def dashboard() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html", headers=NO_CACHE_HEADERS)

  @app.get("/dashboard")
  def dashboard_alias() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html", headers=NO_CACHE_HEADERS)

  return app
