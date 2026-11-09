from enum import Enum

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Column, func, MetaData, Index, text
from sqlalchemy.dialects.postgresql import JSONB

naming_convention = {
    "ix": 'ix_%(column_0_label)s',
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}
db = SQLAlchemy(metadata=MetaData(naming_convention=naming_convention))


class AbcCustomerEntities(Enum):
    AmoCustomer = 'amo_customers'
    AmoLead = 'amo_leads'
    AmoCompany = 'amo_companies'
    AmoContact = 'amo_contacts'
    SendMethods = 'send_methods'


class AbstractCustomer(db.Model):
    """
    "default" "general" : {
        "id": int
    }

    "amo_customers": [
        {
            "general": {
                "login": str,
                "billing_type": str,
                "is_robot": bool,
                "is_nds": bool,
                "system": str,
                "host": str,
                "name": str
            },
            "api_value": {}
        }
    ]

    "amo_leads": [
        {
            "general": {
                "login": Optional[str],
                "name": str
            }
            "api_value": {}
        }
    ]

    "amo_companies": [
        {
            "general": {
                "id": int,
                "inn": Optional[str],
                "name": str
            }
            "api_value": {}
        }
    ]

    "amo_contacts": [
        {
            "general": {
                "id": int,
                "phone": Optional[str],
                "name": str
            }
            "api_value": {}
        }
    ]

    "send_methods": [
        {
            "type": str (mail,sms,wtsp),
            "value": str,
            "desc": str,
        }
    ]
    """
    __tablename__ = "abstract_customer"
    id = Column(db.BigInteger(), nullable=False, primary_key=True)
    amo_customers = Column(JSONB)
    amo_leads = Column(JSONB)
    amo_companies = Column(JSONB)
    amo_contacts = Column(JSONB)
    send_methods = Column(JSONB)
    created_at = Column(db.DateTime, server_default=func.now())
    updated_at = Column(db.DateTime, onupdate=func.now())

    # GIN-индексы для containment-поиска (@>) — используются внешними частями системы.
    # jsonb_path_ops меньше и быстрее дефолтного jsonb_ops для @>.
    __table_args__ = (
        Index('ix_abstract_customer_amo_customers_gin',
              amo_customers, postgresql_using='gin',
              postgresql_ops={'amo_customers': 'jsonb_path_ops'}),
        Index('ix_abstract_customer_amo_leads_gin',
              amo_leads, postgresql_using='gin',
              postgresql_ops={'amo_leads': 'jsonb_path_ops'}),
        Index('ix_abstract_customer_amo_companies_gin',
              amo_companies, postgresql_using='gin',
              postgresql_ops={'amo_companies': 'jsonb_path_ops'}),
        Index('ix_abstract_customer_amo_contacts_gin',
              amo_contacts, postgresql_using='gin',
              postgresql_ops={'amo_contacts': 'jsonb_path_ops'}),
        # Expression-индексы для внешнего поиска по точному логину и названию.
        # GIN по containment не ускоряет LIKE/«=» по значению внутри массива,
        # поэтому добавляем отдельные индексы на первый элемент массива (general).
        Index('ix_abstract_customer_customer_login',
              text("(amo_customers -> 0 -> 'general' ->> 'login')")),
        Index('ix_abstract_customer_customer_name',
              text("(amo_customers -> 0 -> 'general' ->> 'name')")),
        Index('ix_abstract_customer_lead_login',
              text("(amo_leads -> 0 -> 'general' ->> 'login')")),
        Index('ix_abstract_customer_lead_name',
              text("(amo_leads -> 0 -> 'general' ->> 'name')")),
    )