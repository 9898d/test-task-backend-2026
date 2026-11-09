import os


class Config:
    # В продакшене — только через переменные окружения, не хардкодить.
    # Для тестового задания дефолт оставлен для удобства локального запуска.
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://postgres:12345678@localhost:5432/test_task_db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False