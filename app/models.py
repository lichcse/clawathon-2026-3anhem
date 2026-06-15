from sqlalchemy import Column, String, Integer, Boolean, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.database import Base


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id = Column(String(64), primary_key=True)
    created_at = Column(DateTime, default=utcnow)

    repos = relationship("Repository", back_populates="user", cascade="all, delete-orphan")
    messages = relationship("ChatMessage", back_populates="user", cascade="all, delete-orphan")


class Repository(Base):
    __tablename__ = "repositories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), ForeignKey("users.id"), nullable=False)
    name = Column(String(255), nullable=False)
    github_url = Column(String(500), nullable=False)
    main_branch = Column(String(100), nullable=False, default="main")
    is_private = Column(Boolean, default=False)
    interact_with_source = Column(Boolean, default=False)
    github_username = Column(String(100))
    github_token_encrypted = Column(Text)
    auto_update_docs = Column(Boolean, default=False)
    review_on_mr = Column(Boolean, default=False)
    review_on_commit = Column(Boolean, default=False)
    is_shared = Column(Boolean, default=False)
    clone_status = Column(String(50), default="pending")
    clone_error = Column(Text)
    webhook_secret = Column(String(64))
    created_at = Column(DateTime, default=utcnow)

    user = relationship("User", back_populates="repos")
    messages = relationship("ChatMessage", back_populates="repo", cascade="all, delete-orphan")
    webhook_events = relationship("WebhookEvent", back_populates="repo", cascade="all, delete-orphan")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    repo_id = Column(Integer, ForeignKey("repositories.id"), nullable=False)
    user_id = Column(String(64), ForeignKey("users.id"), nullable=False)
    role = Column(String(10), nullable=False)
    content = Column(Text, nullable=False)
    model = Column(String(100))
    created_at = Column(DateTime, default=utcnow)

    repo = relationship("Repository", back_populates="messages")
    user = relationship("User", back_populates="messages")


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    repo_id = Column(Integer, ForeignKey("repositories.id"), nullable=False)
    event_type = Column(String(50))
    event_id = Column(String(200))
    sender_login = Column(String(100))
    processed = Column(Boolean, default=False)
    is_agent_event = Column(Boolean, default=False)
    result = Column(Text)
    created_at = Column(DateTime, default=utcnow)

    repo = relationship("Repository", back_populates="webhook_events")
