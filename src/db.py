"""SQLAlchemy 2.x models and session factory.

One SQLite file (data/uygun.db) holds everything. WAL mode is enabled for
durability and concurrent read+write.

Schema is intentionally Postgres-compatible — no SQLite-specific types — so a
later migration to Postgres is a connection-string swap.

Tables:
  products       — imported from products.xlsx; the agent grounds prices/stock here
  post_drafts    — pre-approval, may have multiple revisions
  posts          — published posts, 1:1 with FB
  post_metrics   — daily reach/reactions/comments snapshot per post
  page_metrics   — daily follower count
  api_spend      — every billable API call, for $20 cap
  settings       — runtime config the founder edits via Telegram

Schema changes during dev: drop data/uygun.db and re-run the importer.
Schema changes in prod: add an Alembic migration (deferred until needed).
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    func,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)


class Base(DeclarativeBase):
    pass


# ─── Tables ──────────────────────────────────────────────────────────────────


class Product(Base):
    __tablename__ = "products"

    # Codes are heterogeneous in the source data: "1", "ც", "7ქ", etc.
    # Keep as TEXT to preserve them verbatim.
    code: Mapped[str] = mapped_column(String, primary_key=True)
    # Natural-sort key: int(code) if code is numeric, NULL otherwise.
    # Queries order by `(code_sort ASC NULLS LAST, code ASC)` for "1, 2, ..., 10, 11, ..., ც".
    code_sort: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # NULL or 0 = "ask for price" — agent must not invent a number.
    price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Default 1 = in stock; toggle to 0 via Telegram /toggle_stock.
    stock_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Coarse category derived from name prefix during import (e.g. "საბურავის").
    category: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # True if data/photos/{code}.jpg exists; updated by photo scanner.
    has_photo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Generator uses this to avoid featuring the same product twice in 7 days.
    last_featured_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )


class PostDraft(Base):
    __tablename__ = "post_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)
    # B2B | B2C | EDU | BTS | LITE | Promo — see brand.WEEKLY_CALENDAR
    calendar_slot: Mapped[str] = mapped_column(String, nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    # JSON-serialized array of hashtag strings.
    hashtags_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cta: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    featured_product_code: Mapped[Optional[str]] = mapped_column(
        String, ForeignKey("products.code"), nullable=True
    )
    # Local filesystem path to the resolved image (real photo, gemini gen, or text card).
    image_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # real | gemini | text_card
    image_source: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # pending | approved | edited | rejected | published
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    # Bumped each regeneration so we can trace edit history.
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    telegram_message_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Free-text the founder typed when tapping ✏️ Edit.
    user_feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    product: Mapped[Optional[Product]] = relationship(Product, lazy="joined")


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    draft_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("post_drafts.id"), nullable=False, unique=True
    )
    # Facebook returns "{page_id}_{post_id}" — unique across all FB.
    fb_post_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    fb_permalink: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)

    draft: Mapped[PostDraft] = relationship(PostDraft)


class PostMetrics(Base):
    __tablename__ = "post_metrics"
    __table_args__ = (UniqueConstraint("post_id", "snapshot_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(Integer, ForeignKey("posts.id"), nullable=False)
    snapshot_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    reach: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    reactions: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    comments: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    shares: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class PageMetrics(Base):
    __tablename__ = "page_metrics"

    snapshot_date: Mapped[datetime] = mapped_column(Date, primary_key=True)
    follower_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    follower_delta: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class ApiSpend(Base):
    __tablename__ = "api_spend"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False, index=True
    )
    # anthropic | google | meta
    provider: Mapped[str] = mapped_column(String, nullable=False)
    # generate_text | generate_image | validate | insights | publish
    operation: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    input_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )


class Memory(Base):
    """Long-term facts about the founder's preferences and brand style.

    Injected into the system prompt of every chat conversation so the bot
    "remembers" things across sessions. Two ways memories get added:
      1. Explicit: founder types `/remember მე არ მიყვარს corporate ტექსტი`
      2. Auto-detect: chat engine notices statements like "always do X" /
         "don't ever Y" and offers to save (Phase 3+)
    """
    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # preference | style | dislike | fact | learned
    category: Mapped[str] = mapped_column(String, nullable=False, default="preference")
    # Optional source tag: "manual" (typed via /remember) or "auto" (detected).
    source: Mapped[str] = mapped_column(String, nullable=False, default="manual")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
        nullable=False,
    )


class Sale(Base):
    """Manual sales log — small built-in bookkeeping.

    Founder enters every sale as `/sale CODE QTY PRICE` or via the FSM-guided
    menu flow. `product_name` is snapshotted at sale time so the historic row
    keeps meaning even if the product is later renamed or removed from xlsx.
    Quantity is REAL to support bulk products (e.g. 0.5 liter chemical).
    """
    __tablename__ = "sales"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_code: Mapped[str] = mapped_column(
        String, ForeignKey("products.code"), nullable=False, index=True
    )
    product_name: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    total_price: Mapped[float] = mapped_column(Float, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sold_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False, index=True
    )


class ConversationMessage(Base):
    """Per-turn log of the founder's chat with the SMM-manager agent.

    Used for two things:
      1. Conversation continuity — last N messages are sent back to Claude as
         context so the conversation flows naturally.
      2. Future analytics — what kinds of things the founder asks about over time.

    Kept lightweight: only role + content + timestamp. No threading.
    """
    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role: Mapped[str] = mapped_column(String, nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Optional token usage so we can show spend per conversation.
    input_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.current_timestamp(), nullable=False, index=True
    )


# Default settings seeded on first run.
DEFAULT_SETTINGS: dict[str, str] = {
    "agent_active": "true",
    "post_gen_time": "11:30",
    "post_publish_time": "12:00",
    "monthly_budget_usd": "20",
    "tone_mode": "default",
}


# ─── Engine & session factory ────────────────────────────────────────────────

_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker[Session]] = None


@event.listens_for(Engine, "connect")
def _enable_sqlite_wal(dbapi_connection, connection_record):
    """Enable WAL mode + foreign keys on SQLite for durability and integrity."""
    # Only applies to sqlite3 connections; no-op for Postgres.
    if not hasattr(dbapi_connection, "cursor"):
        return
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    except Exception:
        # If the driver isn't SQLite, the pragmas just fail silently — that's fine.
        pass


def init_engine(database_url: str) -> Engine:
    """Initialize the global engine. Call once at startup from main.py."""
    global _engine, _SessionLocal
    _engine = create_engine(database_url, echo=False, future=True)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def create_all() -> None:
    """Create all tables if they don't exist. Idempotent."""
    if _engine is None:
        raise RuntimeError("init_engine() must be called first")
    Base.metadata.create_all(_engine)


def seed_default_settings() -> None:
    """Insert default rows into `settings` if they don't already exist.

    Idempotent — preserves any value the founder has already changed.
    """
    with session_scope() as s:
        existing = {row.key for row in s.query(Setting).all()}
        for key, value in DEFAULT_SETTINGS.items():
            if key not in existing:
                s.add(Setting(key=key, value=value))


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Yield a session; commit on success, rollback on error."""
    if _SessionLocal is None:
        raise RuntimeError("init_engine() must be called first")
    s = _SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    """Read a runtime setting. Returns `default` if missing."""
    with session_scope() as s:
        row = s.get(Setting, key)
        return row.value if row else default


def set_setting(key: str, value: str) -> None:
    """Upsert a runtime setting. Updated_at refreshes automatically."""
    with session_scope() as s:
        row = s.get(Setting, key)
        if row is None:
            s.add(Setting(key=key, value=value))
        else:
            row.value = value


# ─── Memory helpers ──────────────────────────────────────────────────────────


def add_memory(content: str, category: str = "preference", source: str = "manual") -> int:
    """Add a memory. Returns the new row's id."""
    with session_scope() as s:
        row = Memory(content=content.strip(), category=category, source=source)
        s.add(row)
        s.flush()  # populate row.id before the context exits
        return row.id


def list_memories(limit: int = 100) -> list[Memory]:
    """Return memories ordered by most-recent first."""
    with session_scope() as s:
        return s.query(Memory).order_by(Memory.created_at.desc()).limit(limit).all()


def delete_memory(memory_id: int) -> bool:
    """Delete a memory by id. Returns True if a row was deleted."""
    with session_scope() as s:
        row = s.get(Memory, memory_id)
        if row is None:
            return False
        s.delete(row)
        return True


# ─── Conversation helpers ────────────────────────────────────────────────────


def append_conversation_message(
    role: str,
    content: str,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    cost_usd: Optional[float] = None,
) -> None:
    """Append one turn (user or assistant) to conversation history."""
    with session_scope() as s:
        s.add(
            ConversationMessage(
                role=role,
                content=content,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost_usd,
            )
        )


def recent_conversation(limit: int = 20) -> list[ConversationMessage]:
    """Return the last N conversation turns in chronological order (oldest first)."""
    with session_scope() as s:
        rows = (
            s.query(ConversationMessage)
            .order_by(ConversationMessage.id.desc())
            .limit(limit)
            .all()
        )
    # Reverse to chronological order for Claude.
    return list(reversed(rows))


def clear_conversation() -> int:
    """Wipe all conversation history. Returns count deleted."""
    with session_scope() as s:
        count = s.query(ConversationMessage).count()
        s.query(ConversationMessage).delete()
        return count


# ─── Sales helpers ───────────────────────────────────────────────────────────


def add_sale(
    product_code: str,
    quantity: float,
    unit_price: float,
    notes: Optional[str] = None,
) -> tuple[int, str, float]:
    """Record a sale. Snapshots product name.

    Returns (sale_id, product_name, total_price).
    Raises ValueError if product code not found.
    """
    with session_scope() as s:
        product = s.get(Product, product_code)
        if product is None:
            raise ValueError(f"Product '{product_code}' not found")
        total = round(quantity * unit_price, 2)
        sale = Sale(
            product_code=product_code,
            product_name=product.name,
            quantity=quantity,
            unit_price=unit_price,
            total_price=total,
            notes=notes,
        )
        s.add(sale)
        s.flush()
        return sale.id, product.name, total


def list_sales(limit: int = 20) -> list[Sale]:
    """Return recent sales (newest first)."""
    with session_scope() as s:
        return s.query(Sale).order_by(Sale.sold_at.desc()).limit(limit).all()


def get_sale(sale_id: int) -> Optional[Sale]:
    """Fetch a single sale by id, or None if not found."""
    with session_scope() as s:
        return s.get(Sale, sale_id)


def update_sale(
    sale_id: int,
    *,
    quantity: Optional[float] = None,
    unit_price: Optional[float] = None,
    notes: Optional[str] = None,
) -> Optional[Sale]:
    """Update one or more fields of a sale. Recomputes total_price.

    Pass None for fields you don't want to change. To clear notes pass "".
    Returns the updated sale, or None if not found.
    """
    with session_scope() as s:
        row = s.get(Sale, sale_id)
        if row is None:
            return None
        if quantity is not None:
            row.quantity = quantity
        if unit_price is not None:
            row.unit_price = unit_price
        if notes is not None:
            row.notes = notes if notes else None
        row.total_price = round(row.quantity * row.unit_price, 2)
        s.flush()
        # Detach so caller can read attributes safely.
        s.expunge(row)
        return row


def delete_sale(sale_id: int) -> bool:
    """Delete a sale by id. Returns True if a row was deleted."""
    with session_scope() as s:
        row = s.get(Sale, sale_id)
        if row is None:
            return False
        s.delete(row)
        return True


# ─── Website read helpers (Phase 10) ─────────────────────────────────────────


def list_featured_products(limit: int = 6) -> list[Product]:
    """Products to showcase on the landing page.

    In-stock first, then ones we have a photo for (real or web-found ranks
    higher than text-card), then natural-sort by code.
    """

    from src.config import DATA_DIR

    with session_scope() as s:
        rows = (
            s.query(Product)
            .filter(Product.stock_qty > 0)
            .order_by(
                Product.has_photo.desc(),
                Product.code_sort.asc().nullslast(),
                Product.code.asc(),
            )
            .all()
        )

    # Re-rank: prefer codes that have a cached found_photo so the grid never has gaps.
    found_dir = DATA_DIR / "found_photos"
    photos_dir = DATA_DIR / "photos"
    with_photo: list[Product] = []
    without_photo: list[Product] = []
    for p in rows:
        if (photos_dir / f"{p.code}.jpg").exists() or (found_dir / f"{p.code}.jpg").exists():
            with_photo.append(p)
        else:
            without_photo.append(p)
        if len(with_photo) >= limit:
            break

    return (with_photo + without_photo)[:limit]


def list_published_posts(limit: int = 12, offset: int = 0) -> list[Post]:
    """Published posts, newest first. Joined with draft for body_text + image_path."""
    with session_scope() as s:
        rows = (
            s.query(Post)
            .order_by(Post.published_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )
        # Force-load joined draft so templates can access post.draft.body_text.
        for r in rows:
            _ = r.draft.body_text if r.draft else None
        return rows


def get_published_post(post_id: int) -> Optional[Post]:
    """Single published post by id, with joined draft eagerly loaded."""
    with session_scope() as s:
        row = s.get(Post, post_id)
        if row is not None and row.draft is not None:
            _ = row.draft.body_text  # force load
        return row


def count_published_posts() -> int:
    """Total count of published posts — for pagination."""
    with session_scope() as s:
        return s.query(Post).count()


def list_products_paginated(
    *,
    category: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    per_page: int = 24,
) -> tuple[list[Product], int]:
    """Catalog browse for /products page. Returns (rows, total_count)."""
    with session_scope() as s:
        q = s.query(Product)
        if category:
            q = q.filter(Product.category == category)
        if search:
            like = f"%{search.strip()}%"
            q = q.filter(Product.name.ilike(like))
        total = q.count()
        rows = (
            q.order_by(Product.code_sort.asc().nullslast(), Product.code.asc())
            .limit(per_page)
            .offset((page - 1) * per_page)
            .all()
        )
        return rows, total


def get_product(code: str) -> Optional[Product]:
    """Single product by code."""
    with session_scope() as s:
        return s.get(Product, code)


def list_categories() -> list[str]:
    """Distinct non-null categories, alphabetically."""
    with session_scope() as s:
        rows = (
            s.query(Product.category)
            .filter(Product.category.is_not(None))
            .distinct()
            .order_by(Product.category.asc())
            .all()
        )
        return [r[0] for r in rows if r[0]]


def sales_summary(start: datetime, end: Optional[datetime] = None) -> dict:
    """Aggregate sales between start and end (default now).

    Returns:
        {
          "count": int,
          "total_revenue": float,
          "total_units": float,
          "top_products": [(code, name, qty, revenue), ...]  # up to 5
        }
    """
    from sqlalchemy import func as sqlf

    if end is None:
        end = datetime.utcnow()

    with session_scope() as s:
        rows = (
            s.query(Sale)
            .filter(Sale.sold_at >= start, Sale.sold_at <= end)
            .all()
        )
        count = len(rows)
        total_revenue = round(sum(r.total_price for r in rows), 2)
        total_units = round(sum(r.quantity for r in rows), 2)

        # Top 5 products by revenue.
        top_rows = (
            s.query(
                Sale.product_code,
                Sale.product_name,
                sqlf.sum(Sale.quantity).label("qty"),
                sqlf.sum(Sale.total_price).label("revenue"),
            )
            .filter(Sale.sold_at >= start, Sale.sold_at <= end)
            .group_by(Sale.product_code, Sale.product_name)
            .order_by(sqlf.sum(Sale.total_price).desc())
            .limit(5)
            .all()
        )
        top_products = [
            (r.product_code, r.product_name, float(r.qty), float(r.revenue))
            for r in top_rows
        ]

    return {
        "count": count,
        "total_revenue": total_revenue,
        "total_units": total_units,
        "top_products": top_products,
    }
