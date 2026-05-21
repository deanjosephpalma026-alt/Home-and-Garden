import json
import os
from urllib import error as urllib_error
from urllib import request as urllib_request

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get('DATABASE_URL')
SUPABASE_DB_HOST = os.environ.get('SUPABASE_DB_HOST')
SUPABASE_DB_NAME = os.environ.get('SUPABASE_DB_NAME')
SUPABASE_DB_USER = os.environ.get('SUPABASE_DB_USER')
SUPABASE_DB_PASSWORD = os.environ.get('SUPABASE_DB_PASSWORD')
SUPABASE_DB_PORT = os.environ.get('SUPABASE_DB_PORT', '5432')

SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_ANON_KEY = os.environ.get('SUPABASE_ANON_KEY')

if not SUPABASE_URL and SUPABASE_DB_HOST and SUPABASE_DB_HOST.startswith('http'):
    SUPABASE_URL = SUPABASE_DB_HOST


def get_db_connection():
    if DATABASE_URL:
        return psycopg2.connect(DATABASE_URL)

    return psycopg2.connect(
        host=SUPABASE_DB_HOST,
        database=SUPABASE_DB_NAME,
        user=SUPABASE_DB_USER,
        password=SUPABASE_DB_PASSWORD,
        port=SUPABASE_DB_PORT,
    )


def supabase_auth_configured():
    return bool(SUPABASE_URL and SUPABASE_ANON_KEY)


def supabase_json_request(method, path_with_query, payload=None):
    base_url = SUPABASE_URL.rstrip('/')
    url = f"{base_url}{path_with_query}"

    body = json.dumps(payload).encode('utf-8') if payload is not None else None
    headers = {
        'Content-Type': 'application/json',
        'apikey': SUPABASE_ANON_KEY,
    }

    req = urllib_request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib_request.urlopen(req, timeout=15) as response:
            raw = response.read().decode('utf-8').strip()
            data = json.loads(raw) if raw else {}
            return response.status, data
    except urllib_error.HTTPError as err:
        raw = err.read().decode('utf-8').strip()
        data = json.loads(raw) if raw else {}
        return err.code, data
    except Exception as err:
        return 500, {'error': str(err)}


def supabase_sign_in(email, password):
    return supabase_json_request(
        'POST',
        '/auth/v1/token?grant_type=password',
        {'email': email, 'password': password},
    )


def supabase_sign_up(email, password, metadata=None):
    payload = {'email': email, 'password': password}
    if metadata:
        payload['data'] = metadata
    return supabase_json_request('POST', '/auth/v1/signup', payload)


def ensure_supabase_sign_in(email, password, display_name=None):
    sign_in_status, sign_in_response = supabase_sign_in(email, password)
    if sign_in_status == 200:
        return True, None

    sign_up_status, sign_up_response = supabase_sign_up(
        email,
        password,
        {'name': display_name} if display_name else None,
    )
    if sign_up_status not in (200, 201):
        return False, sign_up_response

    sign_in_status, sign_in_response = supabase_sign_in(email, password)
    if sign_in_status == 200:
        return True, None

    return False, sign_in_response


def is_likely_hashed_password(value):
    if not value:
        return False
    text = str(value)
    markers = ('pbkdf2:', 'scrypt:', '$2a$', '$2b$', '$2y$')
    return any(marker in text for marker in markers)


def rider_email_column_exists(cur):
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'riders'
              AND column_name = 'email'
        ) AS exists
        """
    )
    row = cur.fetchone()
    return bool(row and row['exists'])


def sync_table(cur, table_name, include_email_column=True):
    if include_email_column:
        cur.execute(f"SELECT id, name, email, password FROM {table_name} WHERE email IS NOT NULL")
    else:
        return [], [{'table': table_name, 'reason': 'email_column_not_available'}], []

    rows = cur.fetchall() or []

    synced = []
    skipped = []
    failed = []

    for row in rows:
        email = (row.get('email') or '').strip().lower()
        password_value = row.get('password')
        display_name = row.get('name')

        if not email:
            skipped.append({'table': table_name, 'id': row.get('id'), 'reason': 'missing_email'})
            continue

        if is_likely_hashed_password(password_value):
            skipped.append(
                {
                    'table': table_name,
                    'id': row.get('id'),
                    'email': email,
                    'reason': 'hashed_password_requires_login_sync',
                }
            )
            continue

        ok, error = ensure_supabase_sign_in(email, str(password_value), display_name=display_name)
        if ok:
            synced.append({'table': table_name, 'id': row.get('id'), 'email': email})
        else:
            failed.append({'table': table_name, 'id': row.get('id'), 'email': email, 'error': error})

    return synced, skipped, failed


def main():
    if not supabase_auth_configured():
        raise RuntimeError('SUPABASE_URL and SUPABASE_ANON_KEY are required in environment.')

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        all_synced = []
        all_skipped = []
        all_failed = []

        synced, skipped, failed = sync_table(cur, 'users', include_email_column=True)
        all_synced.extend(synced)
        all_skipped.extend(skipped)
        all_failed.extend(failed)

        synced, skipped, failed = sync_table(cur, 'sellers', include_email_column=True)
        all_synced.extend(synced)
        all_skipped.extend(skipped)
        all_failed.extend(failed)

        rider_has_email = rider_email_column_exists(cur)
        synced, skipped, failed = sync_table(cur, 'riders', include_email_column=rider_has_email)
        all_synced.extend(synced)
        all_skipped.extend(skipped)
        all_failed.extend(failed)

        report = {
            'synced_count': len(all_synced),
            'skipped_count': len(all_skipped),
            'failed_count': len(all_failed),
            'synced': all_synced,
            'skipped': all_skipped,
            'failed': all_failed,
        }

        print(json.dumps(report, indent=2))
    finally:
        cur.close()
        conn.close()


if __name__ == '__main__':
    main()
