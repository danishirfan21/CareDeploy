import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Clinic(Base):
    __tablename__ = "clinics"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    specialty: Mapped[str] = mapped_column(String(100), default="", server_default="")
    location: Mapped[str] = mapped_column(String(200), default="", server_default="")
    timezone: Mapped[str] = mapped_column(String(64), default="", server_default="")
    phone: Mapped[str] = mapped_column(String(40), default="", server_default="")
    email: Mapped[str] = mapped_column(String(200), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
