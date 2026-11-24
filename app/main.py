import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select

from app.core.config import INSECURE_SECRET_KEYS, settings
from app.core.database import create_db_and_tables, engine
from app.core.security import hash_password
from app.models import Role, User
from app.routers import (
    admin,
    analytics,
    auth,
    reservations,
    rooms,
    stats,
    waitlist,
)
from app.services import jobs
from app.services.reservation_service import BookingError


# --------------------------------------------------
# LOGGING
# --------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger("studyspot")


# --------------------------------------------------
# ADMIN
# --------------------------------------------------

def ensure_admin() -> None:
    """İlk çalıştırmada .env bilgilerinden admin hesabı oluşturur."""

    with Session(engine) as session:
        email = settings.ADMIN_EMAIL.lower()

        existing_admin = session.exec(
            select(User).where(User.email == email)
        ).first()

        if existing_admin is None:
            session.add(
                User(
                    email=email,
                    full_name=settings.ADMIN_NAME,
                    hashed_password=hash_password(
                        settings.ADMIN_PASSWORD
                    ),
                    role=Role.admin,
                )
            )

            session.commit()


# --------------------------------------------------
# LIFESPAN
# --------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):

    if settings.SECRET_KEY in INSECURE_SECRET_KEYS:
        logger.warning(
            "SECRET_KEY varsayılan değerde: "
            "Bu anahtarı bilen herkes admin token'ı üretebilir. "
            ".env dosyasında rastgele bir değer verin."
        )

    create_db_and_tables()
    ensure_admin()

    task = (
        asyncio.create_task(jobs.scheduler_loop())
        if settings.SCHEDULER_ENABLED
        else None
    )

    try:
        yield

    finally:
        if task:
            task.cancel()

            with suppress(asyncio.CancelledError):
                await task


# --------------------------------------------------
# FASTAPI APPLICATION
# --------------------------------------------------

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description=(
        "Çalışma salonu / oda rezervasyon sistemi. "
        "CEN 3001 Advanced Computer Programming projesi."
    ),
    lifespan=lifespan,
)


# --------------------------------------------------
# STATIC FILES
# --------------------------------------------------

app.mount(
    "/static",
    StaticFiles(directory="app/static"),
    name="static",
)


# --------------------------------------------------
# BOOKING ERROR HANDLER
# --------------------------------------------------

@app.exception_handler(BookingError)
async def booking_error_handler(
    request: Request,
    exc: BookingError,
) -> JSONResponse:

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.message,
            "code": exc.code,
            "params": exc.params,
        },
    )


# --------------------------------------------------
# API ROUTERS
# --------------------------------------------------

for module in (
    auth,
    rooms,
    reservations,
    waitlist,
    analytics,
    admin,
):
    app.include_router(
        module.router,
        prefix=settings.API_PREFIX,
    )


# CHECK-IN ROUTER

app.include_router(
    reservations.checkin_router,
    prefix=settings.API_PREFIX,
)


# STATISTICS ROUTER

app.include_router(
    stats.router,
    prefix=settings.API_PREFIX,
)


# --------------------------------------------------
# ROOT PAGE
# --------------------------------------------------

@app.get(
    "/",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def root():

    return """
    <!DOCTYPE html>
    <html lang="tr">

    <head>
        <meta charset="UTF-8">
        <meta name="viewport"
              content="width=device-width, initial-scale=1.0">

        <title>StudySpot - Kişisel İstatistikler</title>
    </head>

    <body>

        <h1>StudySpot</h1>

        <main data-route="stats">

            <h2>Kişisel İstatistikler</h2>

            <div id="stats-container"></div>

        </main>

        <script src="/static/stats.js"></script>

    </body>

    </html>
    """


# --------------------------------------------------
# HEALTH CHECK
# --------------------------------------------------

@app.get(
    "/health",
    tags=["Genel"],
)
def health() -> dict[str, str]:

    return {
        "status": "ok"
    }