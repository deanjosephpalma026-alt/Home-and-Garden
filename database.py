import psycopg2
import psycopg2.extras
from config import Config
from contextlib import contextmanager

def get_db_connection():
    """Create and return a PostgreSQL database connection"""
    if Config.DATABASE_URL:
        connection_args = {}
        if 'supabase.co' in Config.DATABASE_URL.lower() and 'sslmode=' not in Config.DATABASE_URL.lower():
            connection_args['sslmode'] = 'require'
        conn = psycopg2.connect(Config.DATABASE_URL, **connection_args)
    else:
        conn_args = {
            'host': Config.SUPABASE_DB_HOST,
            'database': Config.SUPABASE_DB_NAME,
            'user': Config.SUPABASE_DB_USER,
            'password': Config.SUPABASE_DB_PASSWORD,
            'port': Config.SUPABASE_DB_PORT,
        }
        if Config.SUPABASE_DB_HOST and '.supabase.co' in Config.SUPABASE_DB_HOST.lower():
            conn_args['sslmode'] = 'require'
        conn = psycopg2.connect(**conn_args)
    return conn

@contextmanager
def get_db_cursor(commit=False):
    """Context manager for database cursor"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        yield cur
        if commit:
            conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cur.close()
        conn.close()

def pg_table_exists(cur, table_name):
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = %s
        ) AS exists
        """,
        (table_name,)
    )
    return cur.fetchone()['exists']

def pg_column_exists(cur, table_name, column_name):
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = %s
              AND column_name = %s
        ) AS exists
        """,
        (table_name, column_name)
    )
    return cur.fetchone()['exists']

def add_column_if_missing(conn, table_name, column_name, column_def):
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        if not pg_column_exists(cur, table_name, column_name):
            from psycopg2 import sql
            cur.execute(
                sql.SQL("ALTER TABLE {} ADD COLUMN {} {}")
                .format(
                    sql.Identifier(table_name),
                    sql.Identifier(column_name),
                    sql.SQL(column_def),
                )
            )
            conn.commit()
    finally:
        cur.close()
