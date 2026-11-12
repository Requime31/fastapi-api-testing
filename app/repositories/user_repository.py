# app/repositories/user_repository.py
from sqlalchemy import func
from sqlalchemy.orm import Session
from .. import models, schemas
from ..auth.hashing import hash_password


class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_email(self, email: str) -> models.User | None:
        # Emails are compared case-insensitively (FAT-9); lower() on the column also
        # matches accounts stored in mixed case before the fix.
        return self.db.query(models.User).filter(
            func.lower(models.User.email) == email.lower()
        ).first()

    def create(self, user: schemas.UserCreate) -> models.User:
        new_user = models.User(
            email=user.email.lower(),
            password=hash_password(user.password),
            phone=user.phone
        )
        self.db.add(new_user)
        self.db.commit()
        self.db.refresh(new_user)
        return new_user