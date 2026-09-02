from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base. Every model in app.db.models maps onto
    this; Base.metadata is what Alembic autogenerate and the test suite's
    create_all() both target."""
