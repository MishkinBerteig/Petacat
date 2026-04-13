import os


DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://petacat:dev@localhost:5432/petacat",
)
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8000"))
SEED_DATA_DIR = os.environ.get(
    "SEED_DATA_DIR",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "seed_data"),
)
