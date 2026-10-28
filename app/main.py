"""Fábrica da aplicação FastAPI.

``create_app()`` recebe opcionalmente o caminho do banco — é assim que os
testes sobem uma instância isolada em arquivo temporário.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import config, db
from .web.routes_api import router as api_router
from .web.routes_pages import router as pages_router

WEB_DIR = Path(__file__).resolve().parent / "web"


def create_app(db_path: str | Path | None = None, seed_demo: bool = False) -> FastAPI:
    caminho = Path(db_path) if db_path else config.DB_PATH
    config.ensure_dirs()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db.init_db(app.state.db_path).close()
        if seed_demo:
            from .seed import populate_demo

            with db.session(app.state.db_path) as conn:
                if db.scalar(conn, "SELECT COUNT(*) FROM transactions") == 0:
                    populate_demo(conn)
        yield

    app = FastAPI(
        title=f"{config.APP_NAME} — {config.APP_TAGLINE}",
        description=(
            "Sistema local de registro de entradas e saídas de dinheiro, com previsão de "
            "salário, aportes extras durante o mês, catálogo de itens e comparativo com "
            "planilhas/meses anteriores."
        ),
        version=config.APP_VERSION,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )
    app.state.db_path = caminho
    # cria o esquema já na construção do app: assim o primeiro request (e os
    # testes que não usam o lifespan) encontram o banco pronto.
    db.init_db(caminho).close()

    templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))
    templates.env.globals.update(
        app_name=config.APP_NAME,
        app_version=config.APP_VERSION,
        tagline=config.APP_TAGLINE,
    )
    templates.env.filters["brl"] = _filtro_brl
    templates.env.filters["pct"] = _filtro_pct
    app.state.templates = templates

    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")
    app.include_router(pages_router)
    app.include_router(api_router)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> PlainTextResponse:
        return PlainTextResponse("ok")

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        if request.url.path.startswith("/api"):
            return JSONResponse({"detail": str(exc)}, status_code=500)
        raise exc

    return app


def _filtro_brl(valor) -> str:
    from .money import format_brl

    return format_brl(valor)


def _filtro_pct(valor) -> str:
    from .money import format_percent

    return format_percent(valor)


# instância padrão usada por `uvicorn app.main:app`
app = create_app()
