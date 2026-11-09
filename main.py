import logging
from typing import Iterator, Set

from sqlalchemy import delete, select

from abstract_customer import (
    InMemoryIndex, apply_customer, apply_lead, merge_into, cleanup_entity,
)
from amocrm import Customer, COMPANIES, CONTACTS, Lead, amocrm_get
from models import db, AbstractCustomer

logger = logging.getLogger(__name__)


def collect_leads_customers(is_full=True):
    """
    Ночная синхронизация:
    1. Загружаем все существующие AbstractCustomer одним SELECT.
    2. Строим in-memory индексы.
    3. Применяем покупателей и сделки в памяти.
    4. Один flush + один commit.
    5. При is_full — чистим вложенные и удаляем лишние AbstractCustomer.
    При исключении — rollback, удаление не запускается.
    """
    session = db.session

    existing = session.scalars(select(AbstractCustomer)).all()
    index = InMemoryIndex(existing)
    logger.info(f"Загружено существующих AbstractCustomer: {len(existing)}")

    new_objects: Set[AbstractCustomer] = set()
    customer_ids: Set[int] = set()
    lead_ids: Set[int] = set()
    contact_ids: Set[int] = set()
    company_ids: Set[int] = set()

    def ensure_in_session(ac: AbstractCustomer):
        if ac.id is None and ac not in new_objects:
            new_objects.add(ac)
            session.add(ac)

    try:
        # 2. Покупатели
        customers: Iterator[Customer] = amocrm_get(Customer, _with=f"{COMPANIES},{CONTACTS}")
        logger.info(f"Collected customers {is_full=}")

        for customer in customers:
            if is_full is False and customer.status_id == 111349:
                continue
            customer_login = customer.get_field('Логин')
            if not customer_login:
                continue

            customer_ids.add(customer.id)
            for c in customer.contacts or []:
                if c.get('id') is not None:
                    contact_ids.add(c.get('id'))
            for c in customer.companies or []:
                if c.get('id') is not None:
                    company_ids.add(c.get('id'))

            ac = index.find_customer(crm_id=customer.id, login=customer_login)
            if ac is None:
                ac, _ = apply_customer(None, customer)
                ensure_in_session(ac)
                index.customers.add(ac)
                index.by_customer_crm_id[customer.id] = ac
                if ac not in index.by_customer_login[customer_login]:
                    index.by_customer_login[customer_login].append(ac)
            else:
                ac, old_login = apply_customer(ac, customer)
                if old_login and old_login != customer_login:
                    if ac in index.by_customer_login.get(old_login, []):
                        index.by_customer_login[old_login].remove(ac)
                        if not index.by_customer_login[old_login]:
                            del index.by_customer_login[old_login]
                index.by_customer_crm_id[customer.id] = ac
                if ac not in index.by_customer_login[customer_login]:
                    index.by_customer_login[customer_login].append(ac)

        # 3. Сделки
        amo_leads: Iterator[Lead] = amocrm_get(Lead, _with=f"{CONTACTS}")
        logger.info(f"Collected leads {is_full=}")

        for amo_lead in amo_leads:
            if is_full is False and amo_lead.status_id == 143:
                continue
            lead_ids.add(amo_lead.id)
            for c in amo_lead.contacts or []:
                if c.get('id') is not None:
                    contact_ids.add(c.get('id'))

            lead_login = amo_lead.get_field('Логин')

            by_crm, by_login = index.find_lead(crm_id=amo_lead.id, login=lead_login)

            if by_crm is not None and by_login is not None and by_crm is not by_login:
                # слияние: в by_crm, вторую удаляем
                merge_into(by_crm, by_login)
                # Переиндексация by_crm ДО удаления by_login (пункт 2.5)
                index.reindex(by_crm)
                index.remove_from_indexes(by_login)
                if by_login in new_objects:
                    # by_login — новый объект, ещё не в БД (pending insert).
                    # Убираем из new_objects и из сессии, иначе flush вставит дубль (пункт 2.2).
                    new_objects.discard(by_login)
                    session.expunge(by_login)
                else:
                    session.delete(by_login)
                target = by_crm
            elif by_crm is not None:
                target = by_crm
            elif by_login is not None:
                target = by_login
            else:
                target = None

            if target is None:
                target = AbstractCustomer(
                    amo_customers=[], amo_leads=[], amo_companies=[], amo_contacts=[],
                )
                apply_lead(target, amo_lead)
                ensure_in_session(target)
                index.customers.add(target)
            else:
                target, old_login = apply_lead(target, amo_lead)
                if old_login and old_login != lead_login:
                    if target in index.by_lead_login.get(old_login, []):
                        index.by_lead_login[old_login].remove(target)
                        if not index.by_lead_login[old_login]:
                            del index.by_lead_login[old_login]

            index.by_lead_crm_id[amo_lead.id] = target
            if lead_login:
                if target not in index.by_lead_login[lead_login]:
                    index.by_lead_login[lead_login].append(target)

        # 4. Flush
        session.flush()
        logger.info(f"Flush выполнен. Новых объектов: {len(new_objects)}")

        # 5. Чистка вложенных и удаление
        if is_full:
            logger.info("Чистка вложенных сущностей")
            for ac in list(index.customers):
                cleanup_entity(
                    ac,
                    customer_ids=customer_ids,
                    lead_ids=lead_ids,
                    contact_ids=contact_ids,
                    company_ids=company_ids,
                )

            logger.info("Чистка покупателей")
            actual_db_ids = {ac.id for ac in index.customers if ac.id is not None}

            if actual_db_ids:
                # Для 20k+50k параметров много; альтернатива — = ANY(:array) или temp table (см. README).
                stmt = delete(AbstractCustomer).where(AbstractCustomer.id.not_in(actual_db_ids))
                session.execute(stmt)
            session.commit()
            logger.info("Чистка выполнена")
        else:
            session.commit()

    except Exception as e:
        session.rollback()
        logger.exception(f"Сбор прерван, откат: {e}")
        raise