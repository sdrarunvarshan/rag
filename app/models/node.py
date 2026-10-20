from __future__ import annotations

from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Node(Base):
    __tablename__ = "nodes"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    document_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    node_type: Mapped[str] = mapped_column(
        String, nullable=False
    )  # 'section', 'subsection', 'table'
    heading: Mapped[str | None] = mapped_column(String, nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    path: Mapped[str | None] = mapped_column(String, nullable=True)
    embedding = Column(Vector(384), nullable=True)
    search_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # embedding column is added via migration (pgvector type)
    # Not included in model to avoid type issues

    document: Mapped[Document] = relationship("Document", back_populates="nodes")
    parent: Mapped[Node | None] = relationship(
        "Node", remote_side=[id], back_populates="children"
    )
    children: Mapped[list[Node]] = relationship(
        "Node", back_populates="parent", cascade="all, delete-orphan"
    )
    images: Mapped[list[Image]] = relationship(
        "Image", back_populates="node", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_nodes_type", "node_type"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "document_id": str(self.document_id),
            "parent_id": str(self.parent_id) if self.parent_id else None,
            "node_type": self.node_type,
            "heading": self.heading,
            "text": self.text,
            "page": self.page,
            "path": self.path,
            "search_text": self.search_text,
        }
