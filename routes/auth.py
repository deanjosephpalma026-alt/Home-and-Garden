from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, current_app
from datetime import datetime, timedelta
import json
import os
import re
import uuid
import logging
from werkzeug.security import generate_password_hash
from config import Config
from database import get_db_connection, get_db_cursor, add_column_if_missing
from utils import (
    generate_verification_code, api_success, api_error, send_email,
    _supabase_sign_in, _supabase_sign_up, _supabase_admin_upsert_user,
    _supabase_error_message, _is_supabase_non_blocking_auth_state,
    _ensure_supabase_sign_in_from_web, verify_password, _user_public_payload,
    send_password_reset_email, _supabase_admin_update_password_by_email
)

auth_bp = Blueprint('auth', __name__)
logger = logging.getLogger(__name__)
_locations_cache = None

def send_verification_email(email, code, name):
    subject = "Verify your Home and Garden Account"
    body = f"""
    <html>
        <body>
            <h2>Hello {name},</h2>
            <p>Thank you for registering with Home and Garden!</p>
            <p>Your verification code is: <strong>{code}</strong></p>
            <p>This code will expire in 24 hours.</p>
            <p>If you didn't request this, please ignore this email.</p>
        </body>
    </html>
    """
    return send_email(email, subject, body)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=current_app.config['CURSOR_FACTORY']) if hasattr(current_app.config, 'CURSOR_FACTORY') else conn.cursor(cursor_factory=None)
        # Handle cases where cursor_factory might not be RealDictCursor in the original app.py
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        cur.execute("SELECT * FROM users WHERE email=%s", (email,))
        user = cur.fetchone()
        
        if user:
            password_ok, is_hashed = verify_password(user['password'], password)
            if password_ok:
                if int(user.get('email_verified') or 0) == 0:
                    session['verification_email'] = email
                    session['verification_user_type'] = 'user'
                    flash('Please verify your email first.', 'warning')
                    cur.close()
                    conn.close()
                    return redirect(url_for('auth.verify_email'))
                
                session['id'] = user['id']
                session['name'] = user['name']
                session['email'] = user['email']
                session['role'] = user['role']

                session['user_id'] = user['id']
                session['user_name'] = user['name']
                session['user_email'] = user['email']
                session['user_role'] = user['role']
                
                cur.close()
                conn.close()
                
                if user['role'] == 'admin':
                    return redirect(url_for('admin.admin_dashboard'))
                return redirect(url_for('main.home'))
            else:
                flash('Invalid email or password.', 'error')
        else:
            flash('Invalid email or password.', 'error')
        
        cur.close()
        conn.close()
        
    return render_template('login.html')

@auth_bp.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        name = f"{first_name} {last_name}"
        email = request.form['email']
        password = request.form['password']
        
        if len(password) < 8:
            flash('Password must be at least 8 characters long.', 'error')
            return render_template('signup.html')
        if not re.search(r'[A-Z]', password):
            flash('Password must contain at least one uppercase letter (A-Z).', 'error')
            return render_template('signup.html')
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            flash('Password must contain at least one special character (!@#$%^&*(),.?":{}|<>).', 'error')
            return render_template('signup.html')
        
        valid_id_file = request.files.get('valid_id')
        valid_id_path = None
        if valid_id_file and valid_id_file.filename:
            valid_ids_dir = os.path.join(current_app.static_folder, 'uploads', 'valid_ids')
            os.makedirs(valid_ids_dir, exist_ok=True)
            file_ext = os.path.splitext(valid_id_file.filename)[1]
            unique_filename = f"{uuid.uuid4().hex}{file_ext}"
            valid_id_path = os.path.join('uploads', 'valid_ids', unique_filename)
            full_path = os.path.join(current_app.static_folder, valid_id_path)
            valid_id_file.save(full_path)
        
        # Address parts handling...
        region = request.form.get('region', '')
        province = request.form.get('province', '')
        city_municipality = request.form.get('city_municipality', '')
        barangay = request.form.get('barangay', '')
        municipality = request.form.get('municipality', '') or city_municipality
        city = request.form.get('city', '') or city_municipality
        country = 'Philippines'
        house_number = request.form.get('house_number', '')
        street_name = request.form.get('street_name', '')
        postal_code = request.form.get('postal_code', '')
        
        address_parts = [p for p in [house_number, street_name, barangay, city_municipality, province, region, postal_code, country] if p]
        full_address = ', '.join(address_parts) if address_parts else None
        
        with get_db_cursor(commit=True) as cur:
            cur.execute("SELECT id FROM users WHERE email=%s", (email,))
            if cur.fetchone():
                flash('Email already registered! Try logging in.', 'error')
                return redirect(url_for('auth.login'))

            if Config.SUPABASE_URL and Config.SUPABASE_ANON_KEY:
                supabase_ok, supabase_error = _ensure_supabase_sign_in_from_web(email, password, display_name=name)
                if not supabase_ok:
                    flash(f"Unable to create Supabase account: {supabase_error}", 'error')
                    return render_template('signup.html')

            verification_code = generate_verification_code()
            code_expires = datetime.now() + timedelta(hours=24)
            hashed_password = generate_password_hash(password)
            
            cur.execute("""
                INSERT INTO users (name, email, password, role, address, profile_image, first_name, last_name,
                country, region, province, municipality, city, city_municipality, barangay, house_number, street_name, postal_code,
                valid_id, email_verified, verification_code, verification_code_expires)
                VALUES (%s, %s, %s, 'user', %s, 'uploads/profile/default.jpg', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, %s, %s)
                RETURNING id
            """, (name, email, hashed_password, full_address, first_name, last_name,
                  country, region, province, municipality, city, city_municipality, barangay, house_number, street_name, postal_code,
                  valid_id_path, verification_code, code_expires))
            
        session['verification_email'] = email
        session['verification_user_type'] = 'user'
        if send_verification_email(email, verification_code, name):
            flash('Account created successfully! Please check your email for verification code.', 'success')
        else:
            error_msg = 'Account created successfully! However, we could not send the verification email.'
            if Config.FLASK_DEBUG:
                error_msg += f' [DEV MODE] Your code is: {verification_code}'
            flash(error_msg, 'error')
        return redirect(url_for('auth.verify_email'))
        
    return render_template('signup.html')

@auth_bp.route('/logout')
def logout():
    session.clear()
    response = redirect(url_for('auth.login'))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    flash('You have been logged out.', 'info')
    return response

@auth_bp.route('/verify_email', methods=['GET', 'POST'])
def verify_email():
    email = session.get('verification_email')
    if not email:
        return redirect(url_for('auth.login'))
        
    if request.method == 'POST':
        code = request.form.get('verification_code')
        with get_db_cursor(commit=True) as cur:
            cur.execute("SELECT * FROM users WHERE email=%s", (email,))
            user = cur.fetchone()
            
            if user and user['verification_code'] == code:
                if datetime.now() < user['verification_code_expires']:
                    cur.execute("UPDATE users SET email_verified=1, verification_code=NULL, verification_code_expires=NULL WHERE id=%s", (user['id'],))
                    flash('Email verified successfully! You can now login.', 'success')
                    return redirect(url_for('auth.login'))
                else:
                    flash('Verification code expired. Please request a new one.', 'error')
            else:
                flash('Invalid verification code.', 'error')
                
    return render_template(
        'verify_email.html',
        email=email,
        user_type=session.get('verification_user_type', 'user'),
    )


def _normalize_user_type(user_type):
    t = (user_type or '').strip().lower()
    if t in ('seller', 'rider'):
        return t
    return 'user'


def _password_reset_account_by_email(email, user_type):
    t = _normalize_user_type(user_type)
    email = (email or '').strip().lower()
    if not email:
        return None, None

    try:
        with get_db_cursor(commit=False) as cur:
            if t == 'seller':
                cur.execute("SELECT id, name, email FROM sellers WHERE LOWER(email)=LOWER(%s)", (email,))
            elif t == 'rider':
                add_column_if_missing(cur.connection, 'riders', 'email', 'VARCHAR(100) DEFAULT NULL')
                cur.execute("SELECT id, name, email FROM riders WHERE LOWER(email)=LOWER(%s)", (email,))
            else:
                cur.execute("SELECT id, name, email FROM users WHERE LOWER(email)=LOWER(%s)", (email,))
            row = cur.fetchone()
            return row, t
    except Exception:
        return None, t


def _ensure_password_reset_otp_table(conn):
    cur = conn.cursor()
    try:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS password_reset_otp (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) NOT NULL,
                user_type VARCHAR(20) NOT NULL,
                otp_code VARCHAR(20) NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                used BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_password_reset_otp_email_usertype
            ON password_reset_otp(email, user_type)
            """
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        cur.close()


@auth_bp.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'GET':
        user_type = _normalize_user_type(request.args.get('user_type') or 'user')
        return render_template('forgot_password.html', user_type=user_type)

    user_type = _normalize_user_type(request.form.get('user_type') or 'user')
    email = (request.form.get('email') or '').strip().lower()
    if not email:
        flash('Please enter your email.', 'error')
        return render_template('forgot_password.html', user_type=user_type)

    account, t = _password_reset_account_by_email(email, user_type)
    if not account:
        flash('Email not found.', 'error')
        return render_template('forgot_password.html', user_type=user_type)

    otp = generate_verification_code()
    expires_at = datetime.now() + timedelta(minutes=15)

    try:
        conn = get_db_connection()
        _ensure_password_reset_otp_table(conn)
        cur = conn.cursor()
        cur.execute(
            "UPDATE password_reset_otp SET used=TRUE WHERE LOWER(email)=LOWER(%s) AND user_type=%s AND used=FALSE",
            (email, t),
        )
        cur.execute(
            """
            INSERT INTO password_reset_otp (email, user_type, otp_code, expires_at, used)
            VALUES (%s, %s, %s, %s, FALSE)
            """,
            (email, t, otp, expires_at),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        try:
            cur.close()
            conn.close()
        except Exception:
            pass
        flash('Unable to generate OTP. Please try again.', 'error')
        return render_template('forgot_password.html', user_type=user_type)

    name = (account.get('name') or '').strip() or email.split('@')[0]
    sent = False
    try:
        sent = bool(send_password_reset_email(email, name, otp))
    except Exception:
        sent = False

    if sent:
        flash('OTP has been sent to your email.', 'success')
    else:
        msg = 'OTP generated. Unable to send email at the moment.'
        if Config.FLASK_DEBUG:
            msg += f' [DEV MODE] Your OTP is: {otp}'
        flash(msg, 'warning')

    return redirect(url_for('auth.reset_password', email=email, user_type=t))


@auth_bp.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    if request.method == 'GET':
        email = (request.args.get('email') or '').strip().lower()
        user_type = _normalize_user_type(request.args.get('user_type') or 'user')
        if not email:
            return redirect(url_for('auth.forgot_password', user_type=user_type))
        return render_template('reset_password.html', email=email, user_type=user_type)

    email = (request.form.get('email') or '').strip().lower()
    user_type = _normalize_user_type(request.form.get('user_type') or 'user')
    otp_code = (request.form.get('otp_code') or '').strip()
    new_password = request.form.get('new_password') or ''
    confirm_password = request.form.get('confirm_password') or ''

    if not (email and otp_code and new_password and confirm_password):
        flash('Please fill in all required fields.', 'error')
        return render_template('reset_password.html', email=email, user_type=user_type)
    if new_password != confirm_password:
        flash('Passwords do not match.', 'error')
        return render_template('reset_password.html', email=email, user_type=user_type)
    if not _password_meets_rules(new_password):
        flash('Password does not meet requirements.', 'error')
        return render_template('reset_password.html', email=email, user_type=user_type)

    t = _normalize_user_type(user_type)

    try:
        conn = get_db_connection()
        _ensure_password_reset_otp_table(conn)
        cur = conn.cursor(cursor_factory=current_app.config['CURSOR_FACTORY']) if hasattr(current_app.config, 'CURSOR_FACTORY') else conn.cursor()
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            """
            SELECT id, expires_at, used
            FROM password_reset_otp
            WHERE LOWER(email)=LOWER(%s) AND user_type=%s AND otp_code=%s AND used=FALSE
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (email, t, otp_code),
        )
        otp_row = cur.fetchone()
        if not otp_row:
            flash('Invalid OTP code.', 'error')
            cur.close()
            conn.close()
            return render_template('reset_password.html', email=email, user_type=user_type)

        if datetime.now() > otp_row.get('expires_at'):
            flash('OTP code expired. Please request a new one.', 'error')
            cur.close()
            conn.close()
            return render_template('reset_password.html', email=email, user_type=user_type)

        hashed_password = generate_password_hash(new_password)
        if t == 'seller':
            cur.execute("UPDATE sellers SET password=%s WHERE LOWER(email)=LOWER(%s)", (hashed_password, email))
        elif t == 'rider':
            add_column_if_missing(conn, 'riders', 'email', 'VARCHAR(100) DEFAULT NULL')
            cur.execute("UPDATE riders SET password=%s WHERE LOWER(email)=LOWER(%s)", (hashed_password, email))
        else:
            cur.execute("UPDATE users SET password=%s WHERE LOWER(email)=LOWER(%s)", (hashed_password, email))

        cur.execute("UPDATE password_reset_otp SET used=TRUE WHERE id=%s", (otp_row.get('id'),))
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        try:
            cur.close()
            conn.close()
        except Exception:
            pass
        flash('Password reset failed. Please try again.', 'error')
        return render_template('reset_password.html', email=email, user_type=user_type)

    if Config.SUPABASE_SERVICE_ROLE_KEY:
        try:
            ok, err = _supabase_admin_update_password_by_email(email, new_password)
            if not ok:
                flash(f'Password updated, but Supabase sync failed: {err}', 'warning')
        except Exception:
            flash('Password updated, but Supabase sync failed.', 'warning')

    flash('Password reset successfully.', 'success')
    if t == 'seller':
        return redirect(url_for('seller.seller_login'))
    if t == 'rider':
        return redirect(url_for('rider.rider_login'))
    return redirect(url_for('auth.login'))

@auth_bp.route('/api/auth/bridge-login', methods=['POST'])
def api_auth_bridge_login():
    payload = request.get_json(silent=True) or {}
    email = (payload.get('email') or '').strip().lower()
    contact = (payload.get('contact') or '').strip()
    password = payload.get('password') or ''

    if not password or (not email and not contact):
        return api_error('Email/contact and password are required.', status_code=400)

    if not (Config.SUPABASE_URL and Config.SUPABASE_ANON_KEY):
        return api_error('Supabase auth configuration is missing.', status_code=503)

    account_type = None
    account = None
    if contact and not email:
        raw_digits = re.sub(r'[^0-9]', '', contact or '')
        contact_candidates = []
        if raw_digits:
            contact_candidates.append(raw_digits)
            if raw_digits.startswith('0') and len(raw_digits) >= 11:
                contact_candidates.append(f"63{raw_digits[1:]}")
            if raw_digits.startswith('63') and len(raw_digits) >= 12:
                contact_candidates.append(f"0{raw_digits[2:]}")

        with get_db_cursor() as cur:
            try:
                add_column_if_missing(cur.connection, 'riders', 'email', 'VARCHAR(100) DEFAULT NULL')
                if contact_candidates:
                    where = " OR ".join(
                        ["regexp_replace(COALESCE(contact,''), '\\\\D', '', 'g')=%s"]
                        * len(contact_candidates)
                    )
                    cur.execute(f"SELECT * FROM riders WHERE {where}", tuple(contact_candidates))
                else:
                    cur.execute("SELECT * FROM riders WHERE contact=%s", (contact,))
                rider_by_contact = cur.fetchone()
            except Exception:
                rider_by_contact = None

        if not rider_by_contact:
            return api_error('Incorrect mobile number or password.', status_code=401)

        password_ok, _ = verify_password(rider_by_contact.get('password'), password)
        if not password_ok:
            return api_error('Incorrect mobile number or password.', status_code=401)

        email = (rider_by_contact.get('email') or '').strip().lower()
        if not email:
            digits = raw_digits or re.sub(r'[^0-9]', '', contact)
            base_email = f"rider{digits}@hg.local" if digits else f"rider{uuid.uuid4().hex[:8]}@hg.local"
            email_candidate = base_email

            with get_db_cursor(commit=True) as cur:
                add_column_if_missing(cur.connection, 'riders', 'email', 'VARCHAR(100) DEFAULT NULL')
                suffix = 1
                while True:
                    cur.execute("SELECT 1 FROM users WHERE LOWER(email)=LOWER(%s)", (email_candidate,))
                    if cur.fetchone():
                        suffix += 1
                        email_candidate = f"rider{digits}_{suffix}@hg.local"
                        continue
                    cur.execute("SELECT 1 FROM sellers WHERE LOWER(email)=LOWER(%s)", (email_candidate,))
                    if cur.fetchone():
                        suffix += 1
                        email_candidate = f"rider{digits}_{suffix}@hg.local"
                        continue
                    cur.execute("SELECT 1 FROM riders WHERE LOWER(email)=LOWER(%s)", (email_candidate,))
                    if cur.fetchone():
                        suffix += 1
                        email_candidate = f"rider{digits}_{suffix}@hg.local"
                        continue
                    break

                cur.execute(
                    "UPDATE riders SET email=%s WHERE id=%s",
                    (email_candidate, rider_by_contact.get('id')),
                )
            email = email_candidate
            rider_by_contact['email'] = email

        account_type = 'rider'
        account = rider_by_contact

    # 1. Check local database first (seller/rider/user-admin)
    if account is None:
        with get_db_cursor() as cur:
            try:
                cur.execute("SELECT * FROM sellers WHERE LOWER(email)=LOWER(%s)", (email,))
                seller = cur.fetchone()
            except Exception:
                seller = None

            try:
                add_column_if_missing(cur.connection, 'riders', 'email', 'VARCHAR(100) DEFAULT NULL')
                cur.execute("SELECT * FROM riders WHERE LOWER(email)=LOWER(%s)", (email,))
                rider = cur.fetchone()
            except Exception:
                rider = None

            cur.execute("SELECT * FROM users WHERE LOWER(email)=LOWER(%s)", (email,))
            user = cur.fetchone()

        if user and (user.get('role') == 'admin'):
            account_type = 'admin'
            account = user
        elif seller:
            account_type = 'seller'
            account = seller
        elif rider:
            account_type = 'rider'
            account = rider
        elif user:
            account_type = 'user'
            account = user

    if account is not None:
        password_ok, _ = verify_password(account.get('password'), password)
        if not password_ok:
            if account_type == 'rider' and contact:
                return api_error('Incorrect mobile number or password.', status_code=401)
            return api_error('Incorrect email or password.', status_code=401)

        if account_type in ('user', 'admin') and int(account.get('email_verified') or 0) == 0:
            return api_error('Please verify your email address on the website first.', status_code=403)

    # 2. Try to sign in to Supabase
    sign_in_status, sign_in_response = _supabase_sign_in(email, password)

    # 3. If Supabase sign-in fails but we have a service role, try to sync/upsert
    if sign_in_status != 200 and Config.SUPABASE_SERVICE_ROLE_KEY:
        display_name = (
            (account.get('name') if account else None) or email.split('@')[0]
        )
        admin_ok, admin_error = _supabase_admin_upsert_user(email, password, display_name)
        if admin_ok:
            # Try signing in again after upsert
            sign_in_status, sign_in_response = _supabase_sign_in(email, password)
        else:
            return api_error(f"Supabase sync failed: {admin_error}", status_code=500)

    if sign_in_status != 200:
        ok, error = _ensure_supabase_sign_in_from_web(
            email,
            password,
            display_name=(account.get('name') if account else None),
        )
        if ok:
            sign_in_status, sign_in_response = _supabase_sign_in(email, password)
        else:
            return api_error(f"Supabase sync failed: {error}", status_code=500)

    # 4. Final check
    if sign_in_status == 200:
        # Sync local user if it didn't exist in any local table (e.g., created directly in Supabase)
        if account is None:
            supabase_user = sign_in_response.get('user', {})
            display_name = supabase_user.get('user_metadata', {}).get('name') or email.split('@')[0]
            with get_db_cursor(commit=True) as cur:
                cur.execute("""
                    INSERT INTO users (name, email, password, role, profile_image, email_verified)
                    VALUES (%s, %s, %s, 'user', 'uploads/profile/default.jpg', 1)
                    RETURNING *
                """, (display_name, email, generate_password_hash(password)))
                account_type = 'user'
                account = cur.fetchone()

        def _bridge_public_payload(kind, row):
            if kind in ('user', 'admin'):
                return _user_public_payload(row)
            if kind == 'seller':
                return {
                    'id': row.get('id'),
                    'name': row.get('name'),
                    'email': row.get('email'),
                    'role': 'seller',
                    'account_status': row.get('status'),
                    'shop_name': row.get('shop_name'),
                }
            if kind == 'rider':
                return {
                    'id': row.get('id'),
                    'name': row.get('name'),
                    'email': row.get('email'),
                    'role': 'rider',
                    'account_status': row.get('status'),
                    'contact': row.get('contact'),
                }
            return {'email': email, 'role': 'user'}
        
        try:
            # Log keys present in the Supabase sign-in response for debugging.
            current_app.logger.info(
                'Bridge login: sign_in_response keys=%s',
                list(sign_in_response.keys()) if isinstance(sign_in_response, dict) else str(type(sign_in_response)),
            )
        except Exception:
            pass

        return api_success('Login successful.', data={
            'user': _bridge_public_payload(account_type, account or {}),
            'session': sign_in_response
        })

    return api_error(_supabase_error_message(sign_in_response, 'Invalid Supabase credentials.'), status_code=401)

@auth_bp.route('/api/mobile/locations', methods=['GET'])
def api_mobile_locations():
    global _locations_cache
    if _locations_cache is not None:
        return api_success('Locations fetched successfully.', data=_locations_cache)

    static_dir = current_app.static_folder
    try:
        with open(os.path.join(static_dir, 'regions.json'), 'r', encoding='utf-8') as f:
            regions_doc = json.load(f) or {}
        with open(os.path.join(static_dir, 'provinces.json'), 'r', encoding='utf-8') as f:
            provinces_doc = json.load(f) or {}
        with open(
            os.path.join(static_dir, 'cities_municipalities.json'),
            'r',
            encoding='utf-8',
        ) as f:
            cities_doc = json.load(f) or {}
        with open(os.path.join(static_dir, 'barangays.json'), 'r', encoding='utf-8') as f:
            barangays_doc = json.load(f) or {}

        payload = {
            'regions': regions_doc.get('regions') or [],
            'provinces': provinces_doc,
            'cities_municipalities': cities_doc,
            'barangays': barangays_doc,
        }
        _locations_cache = payload
        return api_success('Locations fetched successfully.', data=payload)
    except Exception:
        return api_error('Unable to load locations.', status_code=500)

@auth_bp.route('/api/mobile/signup', methods=['POST'])
def api_mobile_signup():
    # Similar to web signup but returns JSON and skips CSRF
    first_name = request.form.get('first_name')
    last_name = request.form.get('last_name')
    name = f"{first_name} {last_name}"
    email = request.form.get('email')
    password = request.form.get('password')
    
    if not email or not password:
        return api_error('Email and password are required.')
        
    region = request.form.get('region', '')
    province = request.form.get('province', '')
    city_municipality = request.form.get('city_municipality', '')
    barangay = request.form.get('barangay', '')
    house_number = request.form.get('house_number', '')
    street_name = request.form.get('street_name', '')
    postal_code = request.form.get('postal_code', '')
    
    address_parts = [p for p in [house_number, street_name, barangay, city_municipality, province, region, postal_code, 'Philippines'] if p]
    full_address = ', '.join(address_parts) if address_parts else None
    
    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute("SELECT id FROM users WHERE email=%s", (email,))
            if cur.fetchone():
                return api_error('Email already registered.')

            if Config.SUPABASE_SERVICE_ROLE_KEY:
                supabase_ok, supabase_error = _supabase_admin_upsert_user(email, password, display_name=name)
                if not supabase_ok:
                    return api_error(f"Supabase error: {supabase_error}", status_code=500)
            elif Config.SUPABASE_URL and Config.SUPABASE_ANON_KEY:
                supabase_ok, supabase_error = _ensure_supabase_sign_in_from_web(email, password, display_name=name)
                if not supabase_ok:
                    return api_error(f"Supabase error: {supabase_error}")
            hashed_password = generate_password_hash(password)
            
            cur.execute("""
                INSERT INTO users (name, email, password, role, address, profile_image, first_name, last_name,
                region, province, city_municipality, barangay, house_number, street_name, postal_code,
                email_verified, verification_code, verification_code_expires)
                VALUES (%s, %s, %s, 'user', %s, 'uploads/profile/default.jpg', %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, NULL, NULL)
                RETURNING id
            """, (
                name,
                email,
                hashed_password,
                full_address,
                first_name,
                last_name,
                region,
                province,
                city_municipality,
                barangay,
                house_number,
                street_name,
                postal_code,
            ))
            
        return api_success('Account created successfully.')
    except Exception as e:
        print(f"Mobile Signup Error: {e}")
        return api_error('Internal server error during signup.')


def _password_meets_rules(password):
    if not password or len(password) < 8:
        return False
    if not re.search(r'[A-Z]', password):
        return False
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False
    return True


@auth_bp.route('/api/mobile/seller/signup', methods=['POST'])
def api_mobile_seller_signup():
    first_name = (request.form.get('first_name') or '').strip()
    last_name = (request.form.get('last_name') or '').strip()
    shop_name = (request.form.get('shop_name') or '').strip()
    name = f"{first_name} {last_name}".strip() or (request.form.get('name') or '').strip()
    email = (request.form.get('email') or '').strip().lower()
    password = request.form.get('password') or ''

    if not (name and shop_name and email and password):
        return api_error('Missing required fields.')
    if not _password_meets_rules(password):
        return api_error('Password does not meet security requirements.')

    if not (first_name and last_name):
        parts = [p for p in name.split(' ') if p]
        first_name = parts[0] if parts else name
        last_name = ' '.join(parts[1:]).strip() if len(parts) > 1 else 'Seller'

    region = request.form.get('region', '')
    province = request.form.get('province', '')
    city_municipality = request.form.get('city_municipality', '')
    barangay = request.form.get('barangay', '')
    house_number = request.form.get('house_number', '')
    street_name = request.form.get('street_name', '')
    postal_code = request.form.get('postal_code', '')
    address_parts = [p for p in [house_number, street_name, barangay, city_municipality, province, region, postal_code, 'Philippines'] if p]
    full_address = ', '.join(address_parts) if address_parts else None

    valid_id_file = request.files.get('valid_id')
    valid_id_path = None
    if valid_id_file and valid_id_file.filename:
        valid_ids_dir = os.path.join(current_app.static_folder, 'uploads', 'valid_ids')
        os.makedirs(valid_ids_dir, exist_ok=True)
        file_ext = os.path.splitext(valid_id_file.filename)[1]
        unique_filename = f"{uuid.uuid4().hex}{file_ext}"
        valid_id_path = os.path.join('uploads', 'valid_ids', unique_filename)
        full_path = os.path.join(current_app.static_folder, valid_id_path)
        valid_id_file.save(full_path)

    try:
        with get_db_cursor(commit=True) as cur:
            cur.execute("SELECT id FROM sellers WHERE LOWER(email)=LOWER(%s)", (email,))
            if cur.fetchone():
                return api_error('Email already registered as seller.')
            cur.execute("SELECT id FROM users WHERE LOWER(email)=LOWER(%s)", (email,))
            if cur.fetchone():
                return api_error('Email already registered as buyer/admin.')

            if Config.SUPABASE_SERVICE_ROLE_KEY:
                supabase_ok, supabase_error = _supabase_admin_upsert_user(email, password, display_name=name)
                if not supabase_ok:
                    return api_error(f"Supabase error: {supabase_error}", status_code=500)

            hashed_password = generate_password_hash(password)
            cur.execute(
                """
                INSERT INTO sellers (
                    name, email, shop_name, password, status,
                    first_name, last_name, address, region, province,
                    city_municipality, barangay, house_number, street_name,
                    postal_code, valid_id, email_verified
                )
                VALUES (%s, %s, %s, %s, 'pending', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
                RETURNING id, name, email, shop_name, status
                """,
                (
                    name,
                    email,
                    shop_name,
                    hashed_password,
                    first_name,
                    last_name,
                    full_address,
                    region,
                    province,
                    city_municipality,
                    barangay,
                    house_number,
                    street_name,
                    postal_code,
                    valid_id_path,
                ),
            )
            seller = cur.fetchone()

        return api_success(
            'Seller registration submitted.',
            data={
                'seller': seller,
                'role': 'seller',
                'account_status': seller.get('status') if seller else 'pending',
            },
        )
    except Exception as e:
        print(f"Mobile Seller Signup Error: {e}")
        return api_error('Internal server error during seller signup.', status_code=500)


@auth_bp.route('/api/mobile/rider/signup', methods=['POST'])
def api_mobile_rider_signup():
    name = (request.form.get('name') or '').strip()
    email = (request.form.get('email') or '').strip().lower()
    contact = (request.form.get('contact') or '').strip()
    password = request.form.get('password') or ''

    if not (name and email and contact and password):
        return api_error('Missing required fields.')
    if not _password_meets_rules(password):
        return api_error('Password does not meet security requirements.')

    drivers_license_file = request.files.get('drivers_license')
    drivers_license_path = None
    if drivers_license_file and drivers_license_file.filename:
        dl_dir = os.path.join(current_app.static_folder, 'uploads', 'delivery_proof')
        os.makedirs(dl_dir, exist_ok=True)
        file_ext = os.path.splitext(drivers_license_file.filename)[1]
        unique_filename = f"{uuid.uuid4().hex}{file_ext}"
        drivers_license_path = os.path.join('uploads', 'delivery_proof', unique_filename)
        full_path = os.path.join(current_app.static_folder, drivers_license_path)
        drivers_license_file.save(full_path)

    try:
        with get_db_cursor(commit=True) as cur:
            add_column_if_missing(cur.connection, 'riders', 'email', 'VARCHAR(100) DEFAULT NULL')
            cur.execute("SELECT id FROM riders WHERE LOWER(email)=LOWER(%s)", (email,))
            if cur.fetchone():
                return api_error('Email already registered as rider.')
            cur.execute("SELECT id FROM users WHERE LOWER(email)=LOWER(%s)", (email,))
            if cur.fetchone():
                return api_error('Email already registered as buyer/admin.')
            cur.execute("SELECT id FROM sellers WHERE LOWER(email)=LOWER(%s)", (email,))
            if cur.fetchone():
                return api_error('Email already registered as seller.')

            if Config.SUPABASE_SERVICE_ROLE_KEY:
                supabase_ok, supabase_error = _supabase_admin_upsert_user(email, password, display_name=name)
                if not supabase_ok:
                    return api_error(f"Supabase error: {supabase_error}", status_code=500)

            hashed_password = generate_password_hash(password)
            cur.execute(
                """
                INSERT INTO riders (name, contact, password, drivers_license, status, email)
                VALUES (%s, %s, %s, %s, 'pending', %s)
                RETURNING id, name, email, contact, status
                """,
                (name, contact, hashed_password, drivers_license_path, email),
            )
            rider = cur.fetchone()

        return api_success(
            'Rider registration submitted.',
            data={
                'rider': rider,
                'role': 'rider',
                'account_status': rider.get('status') if rider else 'pending',
            },
        )
    except Exception as e:
        print(f"Mobile Rider Signup Error: {e}")
        return api_error('Internal server error during rider signup.', status_code=500)


@auth_bp.route('/seller_register', methods=['GET', 'POST'])
def seller_register():
    if request.method == 'POST':
        first_name = (request.form.get('first_name') or '').strip()
        last_name = (request.form.get('last_name') or '').strip()
        shop_name = (request.form.get('shop_name') or '').strip()
        name = f"{first_name} {last_name}".strip()
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''

        if not (first_name and last_name and shop_name and email and password):
            flash('Please fill in all required fields.', 'error')
            return render_template('seller_register.html')
        if not _password_meets_rules(password):
            flash('Password does not meet requirements.', 'error')
            return render_template('seller_register.html')

        region = request.form.get('region', '')
        province = request.form.get('province', '')
        city_municipality = request.form.get('city_municipality', '')
        barangay = request.form.get('barangay', '')
        house_number = request.form.get('house_number', '')
        street_name = request.form.get('street_name', '')
        postal_code = request.form.get('postal_code', '')
        address_parts = [p for p in [house_number, street_name, barangay, city_municipality, province, region, postal_code, 'Philippines'] if p]
        full_address = ', '.join(address_parts) if address_parts else None

        valid_id_file = request.files.get('valid_id')
        valid_id_path = None
        if valid_id_file and valid_id_file.filename:
            valid_ids_dir = os.path.join(current_app.static_folder, 'uploads', 'valid_ids')
            os.makedirs(valid_ids_dir, exist_ok=True)
            file_ext = os.path.splitext(valid_id_file.filename)[1]
            unique_filename = f"{uuid.uuid4().hex}{file_ext}"
            valid_id_path = os.path.join('uploads', 'valid_ids', unique_filename)
            full_path = os.path.join(current_app.static_folder, valid_id_path)
            valid_id_file.save(full_path)

        try:
            with get_db_cursor(commit=True) as cur:
                cur.execute("SELECT id FROM sellers WHERE LOWER(email)=LOWER(%s)", (email,))
                if cur.fetchone():
                    flash('Email already registered as seller.', 'error')
                    return render_template('seller_register.html')
                cur.execute("SELECT id FROM users WHERE LOWER(email)=LOWER(%s)", (email,))
                if cur.fetchone():
                    flash('Email already registered as buyer/admin.', 'error')
                    return render_template('seller_register.html')
                cur.execute("SELECT id FROM riders WHERE LOWER(email)=LOWER(%s)", (email,))
                if cur.fetchone():
                    flash('Email already registered as rider.', 'error')
                    return render_template('seller_register.html')

                if Config.SUPABASE_SERVICE_ROLE_KEY:
                    supabase_ok, supabase_error = _supabase_admin_upsert_user(email, password, display_name=name)
                    if not supabase_ok:
                        flash(f"Supabase error: {supabase_error}", 'error')
                        return render_template('seller_register.html')
                elif Config.SUPABASE_URL and Config.SUPABASE_ANON_KEY:
                    supabase_ok, supabase_error = _ensure_supabase_sign_in_from_web(
                        email,
                        password,
                        display_name=name,
                    )
                    if not supabase_ok:
                        flash(f"Unable to create Supabase account: {supabase_error}", 'error')
                        return render_template('seller_register.html')

                hashed_password = generate_password_hash(password)
                cur.execute(
                    """
                    INSERT INTO sellers (
                        name, email, shop_name, password, status,
                        first_name, last_name, address, region, province,
                        city_municipality, barangay, house_number, street_name,
                        postal_code, valid_id, email_verified
                    )
                    VALUES (%s, %s, %s, %s, 'pending', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
                    """,
                    (
                        name,
                        email,
                        shop_name,
                        hashed_password,
                        first_name,
                        last_name,
                        full_address,
                        region,
                        province,
                        city_municipality,
                        barangay,
                        house_number,
                        street_name,
                        postal_code,
                        valid_id_path,
                    ),
                )

            flash('Seller registration submitted. Your account is pending approval.', 'success')
            return redirect(url_for('seller.seller_login'))
        except Exception as e:
            print(f"Seller Register Error: {e}")
            flash('Unable to submit seller registration.', 'error')
            return render_template('seller_register.html')

    return render_template('seller_register.html')


@auth_bp.route('/rider_register', methods=['GET', 'POST'])
def rider_register():
    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        contact = (request.form.get('contact') or '').strip()
        password = request.form.get('password') or ''

        if not (name and email and contact and password):
            flash('Please fill in all required fields.', 'error')
            return render_template('rider_register.html')
        if not _password_meets_rules(password):
            flash('Password does not meet requirements.', 'error')
            return render_template('rider_register.html')

        drivers_license_file = request.files.get('drivers_license')
        drivers_license_path = None
        if drivers_license_file and drivers_license_file.filename:
            dl_dir = os.path.join(current_app.static_folder, 'uploads', 'delivery_proof')
            os.makedirs(dl_dir, exist_ok=True)
            file_ext = os.path.splitext(drivers_license_file.filename)[1]
            unique_filename = f"{uuid.uuid4().hex}{file_ext}"
            drivers_license_path = os.path.join('uploads', 'delivery_proof', unique_filename)
            full_path = os.path.join(current_app.static_folder, drivers_license_path)
            drivers_license_file.save(full_path)

        try:
            with get_db_cursor(commit=True) as cur:
                add_column_if_missing(cur.connection, 'riders', 'email', 'VARCHAR(100) DEFAULT NULL')
                cur.execute("SELECT id FROM riders WHERE LOWER(email)=LOWER(%s)", (email,))
                if cur.fetchone():
                    flash('Email already registered as rider.', 'error')
                    return render_template('rider_register.html')
                cur.execute("SELECT id FROM users WHERE LOWER(email)=LOWER(%s)", (email,))
                if cur.fetchone():
                    flash('Email already registered as buyer/admin.', 'error')
                    return render_template('rider_register.html')
                cur.execute("SELECT id FROM sellers WHERE LOWER(email)=LOWER(%s)", (email,))
                if cur.fetchone():
                    flash('Email already registered as seller.', 'error')
                    return render_template('rider_register.html')

                if Config.SUPABASE_SERVICE_ROLE_KEY:
                    supabase_ok, supabase_error = _supabase_admin_upsert_user(email, password, display_name=name)
                    if not supabase_ok:
                        flash(f"Supabase error: {supabase_error}", 'error')
                        return render_template('rider_register.html')
                elif Config.SUPABASE_URL and Config.SUPABASE_ANON_KEY:
                    supabase_ok, supabase_error = _ensure_supabase_sign_in_from_web(
                        email,
                        password,
                        display_name=name,
                    )
                    if not supabase_ok:
                        flash(f"Unable to create Supabase account: {supabase_error}", 'error')
                        return render_template('rider_register.html')

                hashed_password = generate_password_hash(password)
                cur.execute(
                    """
                    INSERT INTO riders (name, contact, password, drivers_license, status, email)
                    VALUES (%s, %s, %s, %s, 'pending', %s)
                    """,
                    (name, contact, hashed_password, drivers_license_path, email),
                )

            flash('Rider registration submitted. Your account is pending approval.', 'success')
            return redirect(url_for('rider.rider_login'))
        except Exception as e:
            print(f"Rider Register Error: {e}")
            flash('Unable to submit rider registration.', 'error')
            return render_template('rider_register.html')

    return render_template('rider_register.html')
