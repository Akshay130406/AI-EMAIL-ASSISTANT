from sqlalchemy.orm import Session, sessionmaker

from app.models import User


def get_development_user(factory: sessionmaker[Session]) -> User:
    with factory() as session:
        user = session.query(User).filter_by(email="developer@example.test").one()
        session.expunge(user)
        return user
