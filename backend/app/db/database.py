import aiosqlite
from app.config import settings


async def get_db() -> aiosqlite.Connection:
    """Get a database connection."""
    db = await aiosqlite.connect(settings.db_path)
    db.row_factory = aiosqlite.Row
    return db


async def init_db() -> None:
    """Initialize database tables."""
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                project_path TEXT NOT NULL,
                task TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'setup',
                role_configs TEXT NOT NULL,  -- JSON
                started_at REAL NOT NULL,
                completed_at REAL,
                token_usage TEXT DEFAULT '{}'  -- JSON
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                agent_role TEXT,
                content TEXT NOT NULL,
                tool_calls TEXT DEFAULT '[]',  -- JSON
                created_at REAL NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
        """)
        await db.commit()
