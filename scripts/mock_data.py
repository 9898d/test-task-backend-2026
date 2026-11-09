"""
Генератор тестовых данных, имитирующий ответы AmoCRM.
Используется только для локального тестирования.
Логины генерируются как f"cust_{i}" и f"lead_{i}" — гарантированно уникальны.
"""
import random
import string
from typing import Iterator

from amocrm import Customer, Lead


def random_login(prefix="user"):
    """Оставлено для обратной совместимости, но в бенчмарке не используется."""
    return f"{prefix}_{''.join(random.choices(string.ascii_lowercase + string.digits, k=8))}"


def generate_customers(count: int, start_id: int = 1) -> Iterator[Customer]:
    for i in range(count):
        crm_id = start_id + i
        login = f"cust_{i}"
        yield Customer(
            id=crm_id,
            name=f"Customer {crm_id}",
            next_price=0, next_date=0, responsible_user_id=1, status_id=1,
            periodicity=0, created_by=1, updated_by=1, created_at=0, updated_at=0,
            closest_task_at=0, is_deleted=False, ltv=0, purchases_count=0,
            average_check=0, account_id=1,
            custom_fields_values={
                "Логин": {"value": login},
                "Вид оплаты": {"value": "cash"},
                "Система": {"value": "test"},
                "Хост": {"value": "localhost"},
            },
            _embedded={"companies": [], "contacts": []},
        )


def generate_leads(count: int, customer_logins: list[str], start_id: int = 100000) -> Iterator[Lead]:
    for i in range(count):
        crm_id = start_id + i
        if random.random() < 0.7 and customer_logins:
            login = random.choice(customer_logins)
        else:
            login = f"lead_{i}"
        yield Lead(
            id=crm_id,
            name=f"Lead {crm_id}",
            price=0, responsible_user_id=1, group_id=0, status_id=1,
            pipeline_id=1, source_id=1, created_by=1, updated_by=1,
            created_at=0, updated_at=0, closest_task_at=0, is_deleted=False,
            score=0, account_id=1,
            custom_fields_values={"Логин": {"value": login}},
            _embedded={"contacts": []},
        )