import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select

from app.core.config import INSECURE_SECRET_KEYS, settings
from app.core.database import create_db_and_tables, engine
from app.core.security import hash_password
from app.models import Role, User
from app.routers import admin, analytics, auth, feedback, reservations, rooms, suggestions, waitlist
from app.services import jobs
from app.services.reservation_service import BookingError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("studyspot")
STATIC_DIR = Path(__file__).parent / "static"


def ensure_admin() -> None:
    """İlk çalıştırmada .env'deki bilgilerle bir admin hesabı oluşturur."""
    with Session(engine) as session:
        email = settings.ADMIN_EMAIL.lower()
        if session.exec(select(User).where(User.email == email)).first() is None:
            session.add(
                User(
                    email=email,
                    full_name=settings.ADMIN_NAME,
                    hashed_password=hash_password(settings.ADMIN_PASSWORD),
                    role=Role.admin,
                )
            )
            session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.SECRET_KEY in INSECURE_SECRET_KEYS:
        logger.warning(
            "SECRET_KEY varsayılan değerde: bu anahtarı bilen herkes admin token'ı üretebilir. "
            ".env dosyasında rastgele bir değer verin (bkz. .env.example)."
        )
    create_db_and_tables()
    ensure_admin()
    task = asyncio.create_task(jobs.scheduler_loop()) if settings.SCHEDULER_ENABLED else None
    yield
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="Çalışma salonu / oda rezervasyon sistemi. CEN 3001 Advanced Computer Programming projesi.",
    lifespan=lifespan,
)


@app.exception_handler(BookingError)
async def booking_error_handler(request: Request, exc: BookingError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code, content={"detail": exc.message, "code": exc.code, **exc.extra}
    )


for module in (auth, rooms, reservations, waitlist, suggestions, analytics, admin, feedback):
    app.include_router(module.router, prefix=settings.API_PREFIX)
app.include_router(reservations.checkin_router, prefix=settings.API_PREFIX)


# Web arayüzü: derleme adımı olmayan HTML/CSS/vanilla JS, aynı /api/v1 endpoint'lerini kullanır
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    """Ana adres web arayüzünü açar; Swagger /docs adresinde."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health", tags=["Genel"])
def health() -> dict[str, str]:
    return {"status": "ok"}
