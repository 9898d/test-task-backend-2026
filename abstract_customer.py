import json
import logging
from collections import defaultdict
from typing import Optional, Dict, List, Set, Tuple

from sqlalchemy import text

from amocrm import Customer, Lead
from models import AbstractCustomer, db, AbcCustomerEntities

logger = logging.getLogger(__name__)


def update_jsonb_field(entity_id: int,
                       attribute: AbcCustomerEntities,
                       index: int, new_value: Dict,
                       table_name='abstract_customer'):
    """
    Обновление jsonb поля в указанной таблице.
    Оставлено для обратной совместимости (используется другими частями системы).
    В ночном прогоне НЕ используется — там работаем через ORM в памяти.
    """
    if table_name != 'abstract_customer':
        raise Exception("Неизвестная таблица")
    query = text(f"""
        UPDATE {table_name}
        SET {attribute.value} = jsonb_set({attribute.value}, :path, :value)
        WHERE id = :entity_id
    """)
    db.session.execute(query, {'path': f'{{{index}}}', 'value': json.dumps(new_value), 'entity_id': entity_id})


def dict_compare_merge(l_dict1, l_dict2):
    """Сливает два списка dict'ов по general.id. Более свежие данные побеждают."""
    d = defaultdict(dict)
    for i in (l_dict1 or []) + (l_dict2 or []):
        try:
            key = i['general']['id']
        except (KeyError, TypeError):
            logger.warning(f"dict_compare_merge: запись без general.id пропущена: {i}")
            continue
        d[key].update(i)
    return list(d.values())


def get_customer_json(customer: Customer) -> dict:
    return {
        'general': {
            'id': customer.id,
            'login': customer.custom_fields_values.get('Логин', {}).get('value'),
            'billing_type': customer.custom_fields_values.get('Вид оплаты', {}).get('value'),
            'is_robot': bool(customer.custom_fields_values.get('Робот')),
            'is_nds': bool(customer.custom_fields_values.get('Оплата с НДС')),
            'system': customer.custom_fields_values.get('Система', {}).get('value'),
            'host': customer.custom_fields_values.get('Хост', {}).get('value'),
            'name': customer.name,
        },
        'api_value': customer.as_dict()
    }


def get_lead_json(lead: Lead) -> dict:
    return {
        'general': {
            'id': lead.id,
            'login': lead.custom_fields_values.get('Логин', {}).get('value'),
            'name': lead.name,
        },
        'api_value': lead.as_dict()
    }


# ---------- In-memory индексы ----------

class InMemoryIndex:
    """
    Индексы для поиска AbstractCustomer по crm_id и login.
    Направление поиска соответствует бизнес-правилам:
    - покупатель: по id в CRM, иначе по логину среди СДЕЛОК (by_lead_login);
    - сделка: по id в CRM, иначе по логину среди ПОКУПАТЕЛЕЙ (by_customer_login).
    """

    def __init__(self, customers: List[AbstractCustomer]):
        self.customers: Set[AbstractCustomer] = set(customers)
        self.by_customer_crm_id: Dict[int, AbstractCustomer] = {}
        self.by_customer_login: Dict[str, List[AbstractCustomer]] = defaultdict(list)
        self.by_lead_crm_id: Dict[int, AbstractCustomer] = {}
        self.by_lead_login: Dict[str, List[AbstractCustomer]] = defaultdict(list)

        for ac in customers:
            self._index_customer(ac)
            self._index_lead(ac)

    def _index_customer(self, ac: AbstractCustomer):
        for c in (ac.amo_customers or []):
            crm_id = c.get('general', {}).get('id')
            if crm_id is not None:
                self.by_customer_crm_id[crm_id] = ac
            login = c.get('general', {}).get('login')
            if login and ac not in self.by_customer_login[login]:
                self.by_customer_login[login].append(ac)

    def _index_lead(self, ac: AbstractCustomer):
        for l in (ac.amo_leads or []):
            crm_id = l.get('general', {}).get('id')
            if crm_id is not None:
                self.by_lead_crm_id[crm_id] = ac
            login = l.get('general', {}).get('login')
            if login and ac not in self.by_lead_login[login]:
                self.by_lead_login[login].append(ac)

    def reindex(self, ac: AbstractCustomer):
        """
        Переиндексация объекта после слияния (пункт 2.5).
        Вызывается ПОСЛЕ merge_into, ДО remove_from_indexes(by_login).
        Переносит записи by_login на by_crm.
        """
        self._index_customer(ac)
        self._index_lead(ac)

    def remove_from_indexes(self, ac: AbstractCustomer):
        """Удаляет все записи ac из индексов (при слиянии и смене логина)."""
        for c in (ac.amo_customers or []):
            crm_id = c.get('general', {}).get('id')
            if crm_id is not None and self.by_customer_crm_id.get(crm_id) is ac:
                del self.by_customer_crm_id[crm_id]
            login = c.get('general', {}).get('login')
            if login and ac in self.by_customer_login.get(login, []):
                self.by_customer_login[login].remove(ac)
                if not self.by_customer_login[login]:
                    del self.by_customer_login[login]

        for l in (ac.amo_leads or []):
            crm_id = l.get('general', {}).get('id')
            if crm_id is not None and self.by_lead_crm_id.get(crm_id) is ac:
                del self.by_lead_crm_id[crm_id]
            login = l.get('general', {}).get('login')
            if login and ac in self.by_lead_login.get(login, []):
                self.by_lead_login[login].remove(ac)
                if not self.by_lead_login[login]:
                    del self.by_lead_login[login]

        self.customers.discard(ac)

    def find_customer(self, crm_id: int, login: Optional[str]) -> Optional[AbstractCustomer]:
        """Покупатель: по id в CRM, иначе по логину среди СДЕЛОК."""
        if crm_id in self.by_customer_crm_id:
            return self.by_customer_crm_id[crm_id]
        if login:
            candidates = self.by_lead_login.get(login, [])
            if len(candidates) == 1:
                return candidates[0]
            if len(candidates) > 1:
                logger.warning(f"Customer login {login} has more than one abccustomer (by leads)")
        return None

    def find_lead(self, crm_id: int, login: Optional[str]):
        """Сделка: по id в CRM, иначе по логину среди ПОКУПАТЕЛЕЙ."""
        by_crm = self.by_lead_crm_id.get(crm_id)
        by_login = None
        if login:
            candidates = self.by_customer_login.get(login, [])
            if len(candidates) == 1:
                by_login = candidates[0]
            elif len(candidates) > 1:
                logger.warning(f"Lead login {login} has more than one abccustomer (by customers)")
        return by_crm, by_login


# ---------- Применение изменений в памяти (без commit) ----------

def apply_customer(ac: Optional[AbstractCustomer], amo_customer: Customer) -> Tuple[AbstractCustomer, Optional[str]]:
    """Применяет покупателя к AbstractCustomer в памяти. Возвращает (ac, old_login)."""
    new_json = get_customer_json(amo_customer)
    if ac is None:
        return AbstractCustomer(
            amo_customers=[new_json],
            amo_leads=[], amo_companies=[], amo_contacts=[],
        ), None

    ac.amo_customers = ac.amo_customers or []
    old_login = None
    for i, c in enumerate(ac.amo_customers):
        if c.get('general', {}).get('id') == amo_customer.id:
            old_login = c.get('general', {}).get('login')
            ac.amo_customers[i] = new_json
            break
    else:
        ac.amo_customers.append(new_json)
    return ac, old_login


def merge_into(target: AbstractCustomer, source: AbstractCustomer):
    """Сливает source в target."""
    target.amo_customers = dict_compare_merge(target.amo_customers or [], source.amo_customers or [])
    target.amo_leads = dict_compare_merge(target.amo_leads or [], source.amo_leads or [])
    target.amo_contacts = dict_compare_merge(target.amo_contacts or [], source.amo_contacts or [])
    target.amo_companies = dict_compare_merge(target.amo_companies or [], source.amo_companies or [])


def apply_lead(ac: AbstractCustomer, amo_lead: Lead) -> Tuple[AbstractCustomer, Optional[str]]:
    """Применяет сделку к AbstractCustomer в памяти. Возвращает (ac, old_login)."""
    new_json = get_lead_json(amo_lead)
    ac.amo_leads = ac.amo_leads or []
    old_login = None
    for i, l in enumerate(ac.amo_leads):
        if l.get('general', {}).get('id') == amo_lead.id:
            old_login = l.get('general', {}).get('login')
            ac.amo_leads[i] = new_json
            break
    else:
        ac.amo_leads.append(new_json)
    return ac, old_login


# ---------- Чистка вложенных сущностей и «удалить» в имени ----------

def _cleanup_list(entity_list: List[Dict], check_ids: Set[int]) -> List[Dict]:
    """Оставляет записи, у которых id в check_ids и нет «удалить» в name."""
    result = []
    for item in entity_list or []:
        general = item.get('general', {})
        item_id = general.get('id')
        name = (general.get('name') or '').lower()
        if 'удалить' in name:
            continue
        if item_id in check_ids:
            result.append(item)
    return result


def cleanup_entity(ac: AbstractCustomer,
                   customer_ids: Set[int],
                   lead_ids: Set[int],
                   contact_ids: Set[int],
                   company_ids: Set[int]):
    """Чистит вложенные сущности (в памяти, без commit)."""
    if ac.amo_customers:
        ac.amo_customers = _cleanup_list(ac.amo_customers, customer_ids)
    if ac.amo_leads:
        ac.amo_leads = _cleanup_list(ac.amo_leads, lead_ids)
    if ac.amo_contacts:
        ac.amo_contacts = _cleanup_list(ac.amo_contacts, contact_ids)
    if ac.amo_companies:
        ac.amo_companies = _cleanup_list(ac.amo_companies, company_ids)