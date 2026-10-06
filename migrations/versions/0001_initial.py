"""Initial durable state, identity, import and generation storage."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    j = sa.JSON().with_variant(JSONB(), "postgresql")
    op.create_table(
        "workspace",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("payload", j, nullable=False),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("login", sa.String(100), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("password_hash", sa.String(500), nullable=False),
    )
    op.create_table(
        "login_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(64),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("csrf", sa.String(100), nullable=False),
        sa.Column("expires", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "login_attempts",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("failures", sa.Integer, nullable=False),
        sa.Column("since", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "audit",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("version", sa.Integer, nullable=False, unique=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(200), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot", j, nullable=False),
    )
    op.create_table(
        "import_documents",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("digest", sa.String(64), nullable=False, unique=True),
        sa.Column("filename", sa.String(300), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("preview", j, nullable=False),
    )
    op.create_table(
        "generation_jobs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("source_version", sa.Integer, nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("request", j, nullable=False),
        sa.Column("source", j, nullable=False),
        sa.Column("result", j),
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started", sa.DateTime(timezone=True)),
        sa.Column("finished", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_generation_jobs_status", "generation_jobs", ["status"])


def downgrade():
    for table in [
        "generation_jobs",
        "import_documents",
        "audit",
        "login_attempts",
        "login_sessions",
        "users",
        "workspace",
    ]:
        op.drop_table(table)
