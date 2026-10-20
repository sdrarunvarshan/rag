from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Image(Base):
    __tablename__ = "images"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    document_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    minio_key: Mapped[str] = mapped_column(String, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    caption: Mapped[str | None] = mapped_column(String, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document: Mapped[Document] = relationship("Document", back_populates="images")
    node: Mapped[Node | None] = relationship("Node", back_populates="images")

    __table_args__ = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "document_id": str(self.document_id),
            "node_id": str(self.node_id) if self.node_id else None,
            "minio_key": self.minio_key,
            "page": self.page,
            "caption": self.caption,
            "mime_type": self.mime_type,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
