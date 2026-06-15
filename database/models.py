from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Meeting(Base):
    __tablename__ = "meetings"

    id = Column(String, primary_key=True)
    digest = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class SeenEmail(Base):
    __tablename__ = "seen_emails"

    email_id = Column(String, primary_key=True)
    seen_at = Column(DateTime, default=datetime.utcnow)
