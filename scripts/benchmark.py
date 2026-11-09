"""
Бенчмарк для замера производительности collect_leads_customers.
Запуск: python -m scripts.benchmark
...
"""
import logging
import random
import time
import tracemalloc
from unittest.mock import patch

from sqlalchemy import event, text

from config import Config
from models import db, AbstractCustomer
from main import collect_leads_customers
from scripts.mock_data import generate_customers, generate_leads

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

query_count = {"select": 0, "insert": 0, "update": 0, "delete": 0}


def count_queries(conn, cursor, statement, parameters, context, executemany):
    stmt = statement.strip().upper()
    if stmt.startswith("SELECT"):
        query_count["select"] += 1
    elif stmt.startswith("INSERT"):
        query_count["insert"] += 1
    elif stmt.startswith("UPDATE"):
        query_count["update"] += 1
    elif stmt.startswith("DELETE"):
        query_count["delete"] += 1


def create_app():
    from flask import Flask
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)
    return app


def main(n_customers: int = 2000, n_leads: int = 5000):
    random.seed(42)
    app = create_app()

    with app.app_context():
        db.create_all()
        # Очистка таблицы для чистого замера "с нуля".
        # Для проверки идемпотентности закомментируйте эти 2 строки.
        db.session.query(AbstractCustomer).delete()
        db.session.execute(text("ALTER SEQUENCE abstract_customer_id_seq RESTART WITH 1"))
        db.session.commit()
        logger.info("Таблица очищена")

        customers = list(generate_customers(n_customers))
        customer_logins = [c.get_field("Логин") for c in customers]
        leads = list(generate_leads(n_leads, customer_logins))
        logger.info(f"Сгенерировано: {len(customers)} покупателей, {len(leads)} сделок")

        def mock_amocrm_get(obj_cls, **kwargs):
            if obj_cls.__name__ == "Customer":
                yield from customers
            elif obj_cls.__name__ == "Lead":
                yield from leads

        event.listen(db.engine, "before_cursor_execute", count_queries)
        tracemalloc.start()

        start = time.time()
        with patch("main.amocrm_get", side_effect=mock_amocrm_get):
            collect_leads_customers(is_full=True)
        elapsed = time.time() - start

        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        event.remove(db.engine, "before_cursor_execute", count_queries)

        total = db.session.query(AbstractCustomer).count()
        logger.info("=" * 60)
        logger.info(f"ВРЕМЯ: {elapsed:.2f} сек")
        logger.info(f"Запросов: SELECT={query_count['select']}, INSERT={query_count['insert']}, "
                    f"UPDATE={query_count['update']}, DELETE={query_count['delete']}")
        logger.info(f"Память (tracemalloc): peak={peak / 1024 / 1024:.1f} МБ, current={current / 1024 / 1024:.1f} МБ")
        logger.info(f"Всего записей в БД: {total}")
        logger.info("Примечание: INSERT батчится через insertmanyvalues — "
                    "4 statement'а на ~3500 записей, а не 3500.")
        logger.info("=" * 60)


if __name__ == "__main__":
    main()