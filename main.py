from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI

from app.database import Base, engine
from app.interfaces.api import router as api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


def get_app() -> FastAPI:
    app = FastAPI(
        lifespan=lifespan,
    )
    app.include_router(api_router)
    return app


app = get_app()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
