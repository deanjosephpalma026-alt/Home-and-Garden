import random
import string
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from urllib import error as urllib_error
from urllib import request as urllib_request
from flask import jsonify, request
from config import Config
from database import get_db_connection, add_column_if_missing
import psycopg2.extras
import os

from werkzeug.security import check_password_hash, generate_password_hash

def supabase_auth_configured():
    return bool(Config.SUPABASE_URL and Config.SUPABASE_ANON_KEY)

def _is_likely_hashed_password(value):
    if not value:
        return False
    text = str(value)
    markers = ('pbkdf2:', 'scrypt:', '$2a$', '$2b$', '$2y$')
    return any(marker in text for marker in markers)

def _rider_email_column_exists():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        from database import pg_column_exists
        return pg_column_exists(cur, 'riders', 'email')
    except Exception:
        return False
    finally:
        cur.close()
        conn.close()

def log_db_error(block_name, error):
    print(f"[DB ERROR] {block_name}: {error}")

def _normalize_static_path(path):
    if not path:
        return None

    normalized = str(path).strip().replace('\\', '/')
    if not normalized:
        return None

    normalized = normalized.lstrip('/')
    if normalized.startswith('static/'):
        normalized = normalized[len('static/') :]

    return normalized

def _split_product_list_field(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        items = value
    else:
        text = str(value).strip()
        if not text:
            return []
        if text.startswith('['):
            try:
                decoded = json.loads(text)
                if isinstance(decoded, list):
                    items = decoded
                else:
                    items = [decoded]
            except Exception:
                items = [text]
        elif '|' in text:
            items = text.split('|')
        elif ',' in text:
            items = text.split(',')
        elif ';' in text:
            items = text.split(';')
        else:
            items = [text]

    cleaned = []
    for item in items:
        text = str(item).strip()
        if text:
            cleaned.append(text)
    return cleaned

def _numeric_count(value):
    try:
        return int(float(value or 0))
    except Exception:
        return 0

def _numeric_average(value):
    try:
        return round(float(value or 0), 2)
    except Exception:
        return 0.0

def ensure_product_reviews_table(conn):
    cur = conn.cursor()
    try:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS product_reviews (
                id SERIAL PRIMARY KEY,
                product_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                rating SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
                title VARCHAR(150) DEFAULT NULL,
                comment TEXT DEFAULT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_product_reviews_product_id
            ON product_reviews(product_id)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_product_reviews_user_id
            ON product_reviews(user_id)
            """
        )
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_product_reviews_unique_user_product
            ON product_reviews(product_id, user_id)
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

def serialize_review_row(review_row):
    if not review_row:
        return None
    created_at = review_row.get('created_at')
    return {
        'id': review_row.get('id'),
        'product_id': review_row.get('product_id'),
        'user_name': review_row.get('user_name') or review_row.get('customer_name') or 'Customer',
        'rating': _numeric_count(review_row.get('rating')),
        'title': review_row.get('title'),
        'comment': review_row.get('comment'),
        'created_at': created_at.isoformat() if hasattr(created_at, 'isoformat') else created_at,
    }

def ensure_default_admin_account():
    admin_email = os.environ.get('DEFAULT_ADMIN_EMAIL')
    admin_password = os.environ.get('DEFAULT_ADMIN_PASSWORD')
    admin_name = os.environ.get('DEFAULT_ADMIN_NAME', 'System Admin')
    if not admin_email or not admin_password:
        return

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("SELECT id FROM users WHERE email=%s", (admin_email,))
        existing = cur.fetchone()
        if not existing:
            cur.execute(
                """
                INSERT INTO users (name, email, password, role, email_verified)
                VALUES (%s, %s, %s, 'admin', 1)
                """,
                (admin_name, admin_email, generate_password_hash(admin_password))
            )
            conn.commit()
    except Exception as e:
        print(f"Error ensuring default admin account: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

def verify_password(stored_password, provided_password):
    if not stored_password:
        return False, False
    try:
        return check_password_hash(stored_password, provided_password), True
    except Exception:
        return stored_password == provided_password, False

def _user_public_payload(user_row):
    if not user_row:
        return None
    return {
        'id': user_row.get('id'),
        'name': user_row.get('name'),
        'email': user_row.get('email'),
        'role': user_row.get('role'),
        'profile_image': user_row.get('profile_image'),
        'address': user_row.get('address'),
        'first_name': user_row.get('first_name'),
        'last_name': user_row.get('last_name'),
        'region': user_row.get('region'),
        'province': user_row.get('province'),
        'city_municipality': user_row.get('city_municipality') or user_row.get('city') or user_row.get('municipality'),
        'barangay': user_row.get('barangay'),
        'house_number': user_row.get('house_number'),
        'street_name': user_row.get('street_name'),
        'postal_code': user_row.get('postal_code'),
        'valid_id': user_row.get('valid_id'),
    }

def _serialize_product_row(product_row):
    if not product_row:
        return None
    return {
        'id': product_row.get('id'),
        'name': product_row.get('name'),
        'description': product_row.get('description'),
        'price': float(product_row.get('price') or 0),
        'stock': int(product_row.get('stock') or 0),
        'category': product_row.get('category'),
        'image': _normalize_static_path(product_row.get('image')),
        'size_options': _split_product_list_field(product_row.get('size_options')),
        'color_options': _split_product_list_field(product_row.get('color_options')),
        'sold_count': _numeric_count(product_row.get('sold_count')),
        'average_rating': _numeric_average(product_row.get('average_rating')),
        'review_count': _numeric_count(product_row.get('review_count')),
        'seller_id': product_row.get('seller_id'),
        'seller_name': product_row.get('seller_name'),
        'shop_name': product_row.get('shop_name'),
        'seller_profile_image': product_row.get('seller_profile_image'),
    }

def _serialize_cart_item_row(cart_row):
    if not cart_row:
        return None
    return {
        'id': cart_row.get('cart_id') or cart_row.get('id'),
        'product_id': cart_row.get('product_id'),
        'name': cart_row.get('name'),
        'image': _normalize_static_path(cart_row.get('image')),
        'price': float(cart_row.get('price') or 0),
        'quantity': int(cart_row.get('quantity') or 0),
        'subtotal': float(cart_row.get('subtotal') or (float(cart_row.get('price') or 0) * int(cart_row.get('quantity') or 0))),
        'seller_id': cart_row.get('seller_id'),
        'shop_name': cart_row.get('shop_name'),
    }

def _compose_address_from_parts(parts):
    address_parts = []
    for value in parts:
        if value:
            address_parts.append(str(value).strip())
    return ', '.join(address_parts) if address_parts else None

def generate_verification_code():
    return ''.join(random.choices(string.digits, k=6))

def generate_otp_code():
    return ''.join(random.choices(string.digits, k=6))

def _extract_bearer_token():
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return None
    return auth_header.replace('Bearer ', '', 1).strip()

def _current_supabase_email_from_bearer():
    token = _extract_bearer_token()
    if not token:
        return None, 'Missing bearer token.'

    status, response = _supabase_get_user(token)
    if status != 200:
        message = response.get('error_description') or response.get('msg') or 'Invalid Supabase session token.'
        return None, message

    email = (response or {}).get('email')
    if not email:
        return None, 'Supabase user email is missing.'
    return email, None

def _mobile_user_from_bearer():
    email, error_message = _current_supabase_email_from_bearer()
    if error_message:
        return None, error_message

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute(
            """
            SELECT id, name, email, role, profile_image, address, first_name, last_name,
                   country, region, province, municipality, city, city_municipality,
                   barangay, house_number, street_name, postal_code, valid_id, refund_account_number
            FROM users
            WHERE email=%s
            """,
            (email,),
        )
        user = cur.fetchone()
    finally:
        cur.close()
        conn.close()

    if not user:
        return None, 'User profile not found in users table.'
    return user, None

def _fetch_mobile_cart_items(cur, user_id):
    cur.execute(
        """
        SELECT
            c.id AS cart_id,
            c.product_id,
            c.quantity,
            c.subtotal,
            p.name,
            p.image,
            p.price,
            p.seller_id,
            s.shop_name
        FROM cart c
        JOIN products p ON c.product_id = p.id
        LEFT JOIN sellers s ON p.seller_id = s.id
        WHERE c.user_id = %s
        ORDER BY c.id DESC
        """,
        (user_id,),
    )
    cart_items = cur.fetchall() or []
    serialized = [_serialize_cart_item_row(row) for row in cart_items]
    total_amount = sum(item['subtotal'] for item in serialized)
    return serialized, total_amount

def _fetch_mobile_orders(cur, user_id):
    try:
        add_column_if_missing(cur.connection, 'orders', 'order_received', 'SMALLINT DEFAULT 0')
        add_column_if_missing(cur.connection, 'orders', 'order_received_at', 'TIMESTAMP NULL')
    except Exception as error:
        print(f'Error ensuring order_received columns for mobile orders: {error}')

    cur.execute(
        """
        SELECT
            o.id,
            o.quantity,
            o.total,
            o.payment_method,
            o.payment_status,
            o.order_date,
            o.delivery_status,
            o.seller_confirmed,
            o.address,
            o.pickup_address,
            o.customer_contact,
            o.assigned_at,
            o.picked_up_at,
            o.delivered_at,
            o.delivery_proof,
            COALESCE(o.order_received, 0) AS order_received,
            o.order_received_at,
            p.name AS product_name,
            p.image AS product_image,
            p.price AS product_price,
            COALESCE(s.shop_name, 'Unknown Shop') AS shop_name,
            rr.status AS refund_status,
            rr.refund_status AS refund_delivery_status
        FROM orders o
        JOIN products p ON o.product_id = p.id
        LEFT JOIN sellers s ON p.seller_id = s.id
        LEFT JOIN refund_requests rr ON o.id = rr.order_id
        WHERE o.user_id = %s
        ORDER BY o.order_date DESC
        """,
        (user_id,),
    )
    orders = cur.fetchall() or []
    return orders

def _order_group_payload(orders):
    to_pay = []
    to_ship = []
    to_receive = []
    completed = []
    refunded = []
    cancelled = []

    for order in orders:
        payment_status = order.get('payment_status', '')
        delivery_status = order.get('delivery_status', '')
        seller_confirmed = order.get('seller_confirmed', 0)
        order_received = order.get('order_received', 0)
        refund_status = order.get('refund_status')

        if payment_status == 'Refunded' or refund_status == 'approved':
            refunded.append(order)
            continue
        if payment_status == 'Cancelled' or delivery_status == 'cancelled':
            cancelled.append(order)
            continue
        if payment_status == 'Pending' and not seller_confirmed:
            to_pay.append(order)
        elif (payment_status in ['Paid', 'Confirmed'] or seller_confirmed) and delivery_status in ['pending', 'assigned', 'picked_up', None, '']:
            to_ship.append(order)
        elif delivery_status in ['in_transit']:
            to_receive.append(order)
        elif delivery_status == 'delivered' and not order_received:
            to_receive.append(order)
        elif order_received:
            completed.append(order)
        else:
            if delivery_status == 'delivered':
                to_receive.append(order)
            else:
                to_ship.append(order)

    return {
        'orders': orders,
        'to_pay': to_pay,
        'to_ship': to_ship,
        'to_receive': to_receive,
        'completed': completed,
        'refunded': refunded,
        'cancelled': cancelled,
    }

def send_verification_email(email, code, name):
    """Send email verification code"""
    subject = "Email Verification - Home And Garden"
    body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333333; margin: 0; padding: 0; background-color: #f5f5f5;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px; background-color: #ffffff;">
            <div style="text-align: center; margin-bottom: 30px;">
                <h1 style="color: #111827; font-size: 28px; font-weight: 300; margin: 0; letter-spacing: -0.5px;">Home And Garden</h1>
            </div>
            
            <h2 style="color: #111827; font-size: 24px; font-weight: 400; margin-top: 0; margin-bottom: 20px;">Email Verification</h2>
            
            <p style="color: #4b5563; font-size: 16px; margin-bottom: 20px;">Hello {name},</p>
            
            <p style="color: #4b5563; font-size: 16px; margin-bottom: 30px;">Thank you for registering with Home And Garden. Please verify your email address by entering the verification code below:</p>
            
            <div style="background-color: #f9fafb; border: 2px solid #e5e7eb; border-radius: 8px; padding: 30px; text-align: center; margin: 30px 0;">
                <p style="color: #6b7280; font-size: 14px; margin: 0 0 10px 0; text-transform: uppercase; letter-spacing: 1px;">Your Verification Code</p>
                <h1 style="color: #111827; font-size: 36px; font-weight: 600; margin: 0; letter-spacing: 8px; font-family: 'Courier New', monospace;">{code}</h1>
            </div>
            
            <p style="color: #6b7280; font-size: 14px; margin-bottom: 20px;">This code will expire in 24 hours.</p>
            
            <p style="color: #6b7280; font-size: 14px; margin-bottom: 0;">If you did not create an account, please ignore this email.</p>
            
            <div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #e5e7eb;">
                <p style="color: #9ca3af; font-size: 12px; margin: 0; text-align: center;">© 2024 Home And Garden. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """
    return send_email(email, subject, body)

def send_congratulatory_email(email, name, host_url=None):
    """Send congratulatory email after successful registration"""
    if not host_url:
        host_url = "http://localhost:5000"  # Default fallback
    
    subject = "Welcome to Home And Garden! 🎉"
    body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333333; margin: 0; padding: 0; background-color: #f5f5f5;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px; background-color: #ffffff;">
            <div style="text-align: center; margin-bottom: 30px;">
                <h1 style="color: #111827; font-size: 28px; font-weight: 300; margin: 0; letter-spacing: -0.5px;">Home And Garden</h1>
            </div>
            
            <div style="text-align: center; margin-bottom: 30px;">
                <div style="font-size: 48px; margin-bottom: 10px;">🎉</div>
                <h2 style="color: #111827; font-size: 24px; font-weight: 400; margin: 0;">Welcome to Home And Garden!</h2>
            </div>
            
            <p style="color: #4b5563; font-size: 16px; margin-bottom: 20px;">Dear {name},</p>
            
            <p style="color: #4b5563; font-size: 16px; margin-bottom: 20px;">Congratulations! Your account has been successfully created and you're now part of the Home And Garden community.</p>
            
            <div style="background-color: #f0f9ff; border-left: 4px solid #0ea5e9; padding: 20px; margin: 30px 0;">
                <h3 style="color: #0c4a6e; font-size: 18px; margin-top: 0; margin-bottom: 15px;">What you can do now:</h3>
                <ul style="color: #374151; font-size: 14px; margin: 0; padding-left: 20px;">
                    <li style="margin-bottom: 8px;">Browse and purchase from our wide selection of home and garden products</li>
                    <li style="margin-bottom: 8px;">Track your orders and delivery status</li>
                    <li style="margin-bottom: 8px;">Manage your shopping cart and wishlist</li>
                    <li style="margin-bottom: 8px;">Leave reviews and ratings for products you've purchased</li>
                    <li style="margin-bottom: 8px;">Receive exclusive offers and updates</li>
                </ul>
            </div>
            
            <div style="text-align: center; margin: 40px 0;">
                <a href="{host_url}" style="background-color: #111827; color: #ffffff; padding: 12px 30px; text-decoration: none; border-radius: 6px; font-weight: 500; display: inline-block;">Start Shopping</a>
            </div>
            
            <p style="color: #6b7280; font-size: 14px; margin-bottom: 20px; text-align: center;">If you have any questions, feel free to contact our support team.</p>
            
            <div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #e5e7eb;">
                <p style="color: #9ca3af; font-size: 12px; margin: 0; text-align: center;">© 2024 Home And Garden. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """
    return send_email(email, subject, body)

def send_congratulatory_email_seller(email, name, host_url=None):
    """Send congratulatory email after seller approval"""
    if not host_url:
        host_url = "http://localhost:5000"  # Default fallback
    
    subject = "Welcome to Home And Garden - Seller Account Approved! 🎉"
    body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333333; margin: 0; padding: 0; background-color: #f5f5f5;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px; background-color: #ffffff;">
            <div style="text-align: center; margin-bottom: 30px;">
                <h1 style="color: #111827; font-size: 28px; font-weight: 300; margin: 0; letter-spacing: -0.5px;">Home And Garden</h1>
            </div>
            
            <div style="text-align: center; margin-bottom: 30px;">
                <div style="font-size: 48px; margin-bottom: 10px;">🎉</div>
                <h2 style="color: #111827; font-size: 24px; font-weight: 400; margin: 0;">Seller Account Approved!</h2>
            </div>
            
            <p style="color: #4b5563; font-size: 16px; margin-bottom: 20px;">Dear {name},</p>
            
            <p style="color: #4b5563; font-size: 16px; margin-bottom: 20px;">Congratulations! Your seller account has been approved. You can now start listing your products and selling on Home And Garden.</p>
            
            <div style="background-color: #f0fdf4; border-left: 4px solid #22c55e; padding: 20px; margin: 30px 0;">
                <h3 style="color: #14532d; font-size: 18px; margin-top: 0; margin-bottom: 15px;">Next steps for you:</h3>
                <ul style="color: #166534; font-size: 14px; margin: 0; padding-left: 20px;">
                    <li style="margin-bottom: 8px;">Log in to your seller dashboard</li>
                    <li style="margin-bottom: 8px;">Complete your shop profile</li>
                    <li style="margin-bottom: 8px;">Start adding your products with high-quality images</li>
                    <li style="margin-bottom: 8px;">Set up your shipping and payment preferences</li>
                </ul>
            </div>
            
            <div style="text-align: center; margin: 40px 0;">
                <a href="{host_url}/seller_login" style="background-color: #111827; color: #ffffff; padding: 12px 30px; text-decoration: none; border-radius: 6px; font-weight: 500; display: inline-block;">Go to Seller Dashboard</a>
            </div>
            
            <p style="color: #6b7280; font-size: 14px; margin-bottom: 20px; text-align: center;">We're excited to have you as a partner. Happy selling!</p>
            
            <div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #e5e7eb;">
                <p style="color: #9ca3af; font-size: 12px; margin: 0; text-align: center;">© 2024 Home And Garden. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """
    return send_email(email, subject, body)

def send_congratulatory_email_rider(email, name, host_url=None):
    """Send congratulatory email after rider approval"""
    if not host_url:
        host_url = "http://localhost:5000"  # Default fallback
    
    subject = "Welcome to Home And Garden - Rider Account Approved! 🎉"
    body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333333; margin: 0; padding: 0; background-color: #f5f5f5;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px; background-color: #ffffff;">
            <div style="text-align: center; margin-bottom: 30px;">
                <h1 style="color: #111827; font-size: 28px; font-weight: 300; margin: 0; letter-spacing: -0.5px;">Home And Garden</h1>
            </div>
            
            <div style="text-align: center; margin-bottom: 30px;">
                <div style="font-size: 48px; margin-bottom: 10px;">🎉</div>
                <h2 style="color: #111827; font-size: 24px; font-weight: 400; margin: 0;">Welcome to Home And Garden!</h2>
            </div>
            
            <p style="color: #4b5563; font-size: 16px; margin-bottom: 20px;">Dear {name},</p>
            
            <p style="color: #4b5563; font-size: 16px; margin-bottom: 20px;">Congratulations! Your rider account has been approved and you're now part of the Home And Garden delivery team.</p>
            
            <div style="background-color: #f0f9ff; border-left: 4px solid #0ea5e9; padding: 20px; margin: 30px 0;">
                <h3 style="color: #0c4a6e; font-size: 18px; margin-top: 0; margin-bottom: 15px;">What you can do now:</h3>
                <ul style="color: #374151; font-size: 14px; margin: 0; padding-left: 20px;">
                    <li style="margin-bottom: 8px;">Accept delivery orders from your rider dashboard</li>
                    <li style="margin-bottom: 8px;">Track delivery routes and update order status</li>
                    <li style="margin-bottom: 8px;">Manage your delivery schedule and earnings</li>
                    <li style="margin-bottom: 8px;">Handle customer communications and feedback</li>
                    <li style="margin-bottom: 8px;">Process refunds and returns for delivered items</li>
                </ul>
            </div>
            
            <div style="text-align: center; margin: 40px 0;">
                <a href="{host_url}/rider_login" style="background-color: #111827; color: #ffffff; padding: 12px 30px; text-decoration: none; border-radius: 6px; font-weight: 500; display: inline-block;">Access Rider Dashboard</a>
            </div>
            
            <p style="color: #6b7280; font-size: 14px; margin-bottom: 20px; text-align: center;">If you have any questions, feel free to contact our support team.</p>
            
            <div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #e5e7eb;">
                <p style="color: #9ca3af; font-size: 12px; margin: 0; text-align: center;">© 2024 Home And Garden. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """
    return send_email(email, subject, body)

def send_password_reset_email(email, name, code):
    """Send password reset OTP code"""
    subject = "Password Reset - Home And Garden"
    body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333333; margin: 0; padding: 0; background-color: #f5f5f5;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px; background-color: #ffffff;">
            <div style="text-align: center; margin-bottom: 30px;">
                <h1 style="color: #111827; font-size: 28px; font-weight: 300; margin: 0; letter-spacing: -0.5px;">Home And Garden</h1>
            </div>
            
            <h2 style="color: #111827; font-size: 24px; font-weight: 400; margin-top: 0; margin-bottom: 20px;">Password Reset</h2>
            
            <p style="color: #4b5563; font-size: 16px; margin-bottom: 20px;">Hello {name},</p>
            
            <p style="color: #4b5563; font-size: 16px; margin-bottom: 30px;">You have requested to reset your password. Please use the OTP code below to proceed:</p>
            
            <div style="background-color: #f9fafb; border: 2px solid #e5e7eb; border-radius: 8px; padding: 30px; text-align: center; margin: 30px 0;">
                <p style="color: #6b7280; font-size: 14px; margin: 0 0 10px 0; text-transform: uppercase; letter-spacing: 1px;">Your OTP Code</p>
                <h1 style="color: #111827; font-size: 36px; font-weight: 600; margin: 0; letter-spacing: 8px; font-family: 'Courier New', monospace;">{code}</h1>
            </div>
            
            <p style="color: #dc2626; font-size: 14px; margin-bottom: 20px; font-weight: 500;">⚠️ This code will expire in 10 minutes.</p>
            
            <p style="color: #6b7280; font-size: 14px; margin-bottom: 0;">If you did not request a password reset, please ignore this email and your password will remain unchanged.</p>
            
            <div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #e5e7eb;">
                <p style="color: #9ca3af; font-size: 12px; margin: 0; text-align: center;">© 2024 Home And Garden. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """
    return send_email(email, subject, body)

def api_success(message, data=None, status_code=200):
    payload = {'success': True, 'message': message}
    if data is not None:
        payload['data'] = data
    return jsonify(payload), status_code

def api_error(message, status_code=400, errors=None):
    payload = {'success': False, 'message': message}
    if errors is not None:
        payload['errors'] = errors
    return jsonify(payload), status_code

def send_email(to_email, subject, body):
    try:
        if not Config.MAIL_USERNAME or not Config.MAIL_PASSWORD:
            print("Email not configured.")
            return False
        msg = MIMEMultipart()
        msg['From'] = Config.MAIL_FROM
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html'))
        server = smtplib.SMTP(Config.MAIL_SERVER, Config.MAIL_PORT)
        server.starttls()
        server.login(Config.MAIL_USERNAME, Config.MAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False

# Supabase Auth Helpers
def _supabase_json_request(method, path_with_query, payload=None, access_token=None):
    if not Config.SUPABASE_URL or not Config.SUPABASE_ANON_KEY:
        return 503, {'error': 'Supabase auth is not configured.'}

    base_url = Config.SUPABASE_URL.rstrip('/')
    url = f"{base_url}{path_with_query}"
    body = json.dumps(payload).encode('utf-8') if payload is not None else None
    headers = {
        'Content-Type': 'application/json',
        'apikey': Config.SUPABASE_ANON_KEY,
    }

    if access_token:
        headers['Authorization'] = f'Bearer {access_token}'

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

def _supabase_sign_in(email, password):
    return _supabase_json_request(
        'POST',
        '/auth/v1/token?grant_type=password',
        {'email': email, 'password': password},
    )

def _supabase_sign_up(email, password, metadata=None):
    payload = {'email': email, 'password': password}
    if metadata:
        payload['data'] = metadata
    return _supabase_json_request('POST', '/auth/v1/signup', payload)

def _supabase_get_user(access_token):
    return _supabase_json_request('GET', '/auth/v1/user', access_token=access_token)

def _supabase_error_message(response_body, fallback):
    if not isinstance(response_body, dict):
        return fallback
    return (
        response_body.get('error_description')
        or response_body.get('msg')
        or response_body.get('error')
        or fallback
    )

def _is_supabase_non_blocking_auth_state(message):
    text = (message or '').strip().lower()
    if not text:
        return False

    non_blocking_markers = (
        'email not confirmed',
        'invalid login credentials',
        'user already registered',
        'already exists',
    )
    return any(marker in text for marker in non_blocking_markers)

def _ensure_supabase_sign_in_from_web(email, password, display_name=None):
    if not Config.SUPABASE_URL or not Config.SUPABASE_ANON_KEY:
        return False, 'Supabase auth is not configured on server.'

    sign_in_status, sign_in_response = _supabase_sign_in(email, password)
    if sign_in_status == 200:
        return True, None

    sign_up_status, sign_up_response = _supabase_sign_up(
        email,
        password,
        {'name': display_name} if display_name else None,
    )

    if sign_up_status in (200, 201):
        second_sign_in_status, second_sign_in_response = _supabase_sign_in(email, password)
        if second_sign_in_status == 200:
            return True, None

        # Account creation can succeed while sign-in is blocked (e.g., email confirmation required).
        follow_up_message = _supabase_error_message(
            second_sign_in_response,
            'Supabase account exists but sign-in is not available yet.',
        )
        if _is_supabase_non_blocking_auth_state(follow_up_message):
            return True, follow_up_message
        return False, follow_up_message

    sign_in_message = _supabase_error_message(sign_in_response, '')
    sign_up_message = _supabase_error_message(sign_up_response, '')

    # Do not block local registration when the Supabase account already exists
    # or requires email confirmation before sign-in.
    if _is_supabase_non_blocking_auth_state(sign_in_message) or _is_supabase_non_blocking_auth_state(sign_up_message):
        return True, sign_in_message or sign_up_message or None

    return False, _supabase_error_message(
        sign_in_response or sign_up_response,
        'Unable to authenticate with Supabase.',
    )

def _supabase_admin_update_password_by_email(email, new_password):
    list_status, list_response = _supabase_admin_json_request(
        'GET',
        '/auth/v1/admin/users?page=1&per_page=1000',
    )

    if list_status != 200:
        return False, _supabase_error_message(
            list_response,
            'Unable to list Supabase users for password sync.',
        )

    users = (list_response or {}).get('users') or []
    target_user = next(
        (item for item in users if (item.get('email') or '').lower() == email.lower()),
        None,
    )

    if not target_user:
        return False, 'Supabase auth user not found for this email.'

    user_id = target_user.get('id')
    if not user_id:
        return False, 'Supabase auth user id is missing.'

    update_status, update_response = _supabase_admin_json_request(
        'PUT',
        f'/auth/v1/admin/users/{user_id}',
        {'password': new_password},
    )

    if update_status not in (200, 204):
        return False, _supabase_error_message(
            update_response,
            'Unable to update Supabase password.',
        )

    return True, None

def _supabase_admin_upsert_user(email, password, display_name=None):
    list_status, list_response = _supabase_admin_json_request(
        'GET',
        '/auth/v1/admin/users?page=1&per_page=1000',
    )

    if list_status != 200:
        return False, _supabase_error_message(
            list_response,
            'Unable to list Supabase users for admin sync.',
        )

    users = (list_response or {}).get('users') or []
    target_user = next(
        (item for item in users if (item.get('email') or '').lower() == email.lower()),
        None,
    )

    payload = {
        'password': password,
        'email_confirm': True,
    }
    if display_name:
        payload['user_metadata'] = {'name': display_name}

    if target_user and target_user.get('id'):
        update_status, update_response = _supabase_admin_json_request(
            'PUT',
            f"/auth/v1/admin/users/{target_user['id']}",
            payload,
        )
        if update_status in (200, 204):
            return True, None
        return False, _supabase_error_message(
            update_response,
            'Unable to update Supabase auth user.',
        )

    create_payload = {
        'email': email,
        **payload,
    }
    create_status, create_response = _supabase_admin_json_request(
        'POST',
        '/auth/v1/admin/users',
        create_payload,
    )
    if create_status in (200, 201):
        return True, None

    return False, _supabase_error_message(
        create_response,
        'Unable to create Supabase auth user.',
    )

def _supabase_admin_json_request(method, path_with_query, payload=None):
    if not Config.SUPABASE_URL or not Config.SUPABASE_SERVICE_ROLE_KEY:
        return 503, {'error': 'Supabase service role is not configured.'}

    base_url = Config.SUPABASE_URL.rstrip('/')
    url = f"{base_url}{path_with_query}"
    body = json.dumps(payload).encode('utf-8') if payload is not None else None

    headers = {
        'Content-Type': 'application/json',
        'apikey': Config.SUPABASE_SERVICE_ROLE_KEY,
        'Authorization': f'Bearer {Config.SUPABASE_SERVICE_ROLE_KEY}',
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
