"""
Тест сценария слияния: ac1 (покупатель login=cust_0, сделка id=100000) + ac2 (покупатель login=cust_1).
Подаём:
  - покупателей id=1 (cust_0) и id=2 (cust_1) — чтобы cleanup_entity не удалил их;
  - сделку id=100000 с login=cust_1 — чтобы сработало merge_into(ac1, ac2).
Проверяем: остался 1 AbstractCustomer (ac1), в нём оба логина и сделка 100000.
"""
import logging
from unittest.mock import patch

from sqlalchemy import text

from config import Config
from models import db, AbstractCustomer
from main import collect_leads_customers
from amocrm import Lead, Customer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def create_app():
    from flask import Flask
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)
    return app


def main():
    app = create_app()
    with app.app_context():
        db.create_all()
        db.session.query(AbstractCustomer).delete()
        db.session.execute(text("ALTER SEQUENCE abstract_customer_id_seq RESTART WITH 1"))
        db.session.commit()

        # ac1: покупатель cust_0 + сделка 100000
        ac1 = AbstractCustomer(
            amo_customers=[{'general': {'id': 1, 'login': 'cust_0', 'name': 'Customer 1'}, 'api_value': {}}],
            amo_leads=[{'general': {'id': 100000, 'login': 'cust_0', 'name': 'Lead 100000'}, 'api_value': {}}],
            amo_companies=[], amo_contacts=[],
        )
        # ac2: покупатель cust_1
        ac2 = AbstractCustomer(
            amo_customers=[{'general': {'id': 2, 'login': 'cust_1', 'name': 'Customer 2'}, 'api_value': {}}],
            amo_leads=[], amo_companies=[], amo_contacts=[],
        )
        db.session.add(ac1)
        db.session.add(ac2)
        db.session.commit()
        ac1_id, ac2_id = ac1.id, ac2.id
        logger.info(f"Добавлены ac1={ac1_id}, ac2={ac2_id}")

        # Выгрузка: оба покупателя (чтобы cleanup не удалил) + сделка с login=cust_1
        customers = [
            Customer(id=1, name="Customer 1", next_price=0, next_date=0, responsible_user_id=1,
                     status_id=1, periodicity=0, created_by=1, updated_by=1, created_at=0,
                     updated_at=0, closest_task_at=0, is_deleted=False, ltv=0, purchases_count=0,
                     average_check=0, account_id=1,
                     custom_fields_values={"Логин": {"value": "cust_0"}},
                     _embedded={"companies": [], "contacts": []}),
            Customer(id=2, name="Customer 2", next_price=0, next_date=0, responsible_user_id=1,
                     status_id=1, periodicity=0, created_by=1, updated_by=1, created_at=0,
                     updated_at=0, closest_task_at=0, is_deleted=False, ltv=0, purchases_count=0,
                     average_check=0, account_id=1,
                     custom_fields_values={"Логин": {"value": "cust_1"}},
                     _embedded={"companies": [], "contacts": []}),
        ]
        leads = [
            Lead(id=100000, name="Lead 100000", price=0, responsible_user_id=1, group_id=0,
                 status_id=1, pipeline_id=1, source_id=1, created_by=1, updated_by=1,
                 created_at=0, updated_at=0, closest_task_at=0, is_deleted=False, score=0,
                 account_id=1, custom_fields_values={"Логин": {"value": "cust_1"}},
                 _embedded={"contacts": []}),
        ]

        def mock_amocrm_get(obj_cls, **kwargs):
            if obj_cls.__name__ == "Customer":
                yield from customers
            elif obj_cls.__name__ == "Lead":
                yield from leads

        with patch("main.amocrm_get", side_effect=mock_amocrm_get):
            collect_leads_customers(is_full=True)

        # Проверки
        remaining = db.session.query(AbstractCustomer).all()
        assert len(remaining) == 1, f"Ожидался 1 AbstractCustomer, получено {len(remaining)}"
        ac = remaining[0]
        assert ac.id == ac1_id, f"Ожидался ac1={ac1_id}, получен {ac.id}"
        logins = {c['general']['login'] for c in ac.amo_customers}
        assert logins == {'cust_0', 'cust_1'}, f"Ожидались логины cust_0, cust_1, получено {logins}"
        lead_ids = {l['general']['id'] for l in ac.amo_leads}
        assert 100000 in lead_ids, f"Ожидалась сделка 100000, получено {lead_ids}"

        logger.info("=" * 60)
        logger.info("ТЕСТ СЛИЯНИЯ ПРОЙДЕН")
        logger.info(f"  Остался 1 AbstractCustomer (id={ac.id})")
        logger.info(f"  Логины покупателей: {logins}")
        logger.info(f"  id сделок: {lead_ids}")
        logger.info("=" * 60)


if __name__ == "__main__":
    main()