from flask import Blueprint, request
from datetime import datetime
import json
import os
import psycopg2.extras

from database import get_db_connection, add_column_if_missing
from utils import (
    api_success,
    api_error,
    _current_supabase_email_from_bearer,
    _serialize_product_row,
    _serialize_cart_item_row,
    ensure_product_reviews_table,
    serialize_review_row,
)


mobile_api_bp = Blueprint('mobile_api', __name__)


def _join_variant_values(value):
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = [item.strip() for item in value.replace('|', ',').split(',') if item.strip()]
    elif isinstance(value, (list, tuple, set)):
        cleaned = [str(item).strip() for item in value if str(item).strip()]
    else:
        cleaned = [str(value).strip()] if str(value).strip() else []
    return ', '.join(cleaned) if cleaned else None


def _account_by_email(email):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        add_column_if_missing(conn, 'riders', 'email', 'VARCHAR(100) DEFAULT NULL')
        try:
            cur.execute("SELECT * FROM sellers WHERE LOWER(email)=LOWER(%s)", (email,))
            seller = cur.fetchone()
            if seller:
                seller['role'] = 'seller'
                return seller, None
        except Exception:
            pass

        try:
            cur.execute("SELECT * FROM riders WHERE LOWER(email)=LOWER(%s)", (email,))
            rider = cur.fetchone()
            if rider:
                rider['role'] = 'rider'
                return rider, None
        except Exception:
            pass

        cur.execute("SELECT * FROM users WHERE LOWER(email)=LOWER(%s)", (email,))
        user = cur.fetchone()
        if user:
            user['role'] = user.get('role') or 'user'
            return user, None
        return None, 'Account not found.'
    finally:
        cur.close()
        conn.close()


def _public_account_payload(row):
    role = (row.get('role') or 'user') if row else 'user'
    if role == 'seller':
        return {
            'id': row.get('id'),
            'name': row.get('name') or '',
            'email': row.get('email') or '',
            'role': 'seller',
            'profile_image': row.get('profile_image'),
            'address': row.get('address'),
            'first_name': row.get('first_name'),
            'last_name': row.get('last_name'),
            'region': row.get('region'),
            'province': row.get('province'),
            'city_municipality': row.get('city_municipality') or row.get('city') or row.get('municipality'),
            'barangay': row.get('barangay'),
            'house_number': row.get('house_number'),
            'street_name': row.get('street_name'),
            'postal_code': row.get('postal_code'),
            'account_status': row.get('status'),
            'shop_name': row.get('shop_name'),
        }
    if role == 'rider':
        return {
            'id': row.get('id'),
            'name': row.get('name') or '',
            'email': row.get('email') or '',
            'role': 'rider',
            'profile_image': None,
            'address': None,
            'first_name': None,
            'last_name': None,
            'region': None,
            'province': None,
            'city_municipality': None,
            'barangay': None,
            'house_number': None,
            'street_name': None,
            'postal_code': None,
            'account_status': row.get('status'),
            'contact': row.get('contact'),
        }

    return {
        'id': row.get('id'),
        'name': row.get('name') or '',
        'email': row.get('email') or '',
        'role': row.get('role') or 'user',
        'profile_image': row.get('profile_image'),
        'address': row.get('address'),
        'first_name': row.get('first_name'),
        'last_name': row.get('last_name'),
        'region': row.get('region'),
        'province': row.get('province'),
        'city_municipality': row.get('city_municipality') or row.get('city') or row.get('municipality'),
        'barangay': row.get('barangay'),
        'house_number': row.get('house_number'),
        'street_name': row.get('street_name'),
        'postal_code': row.get('postal_code'),
        'account_status': None,
    }


def _require_bearer_email():
    email, error_message = _current_supabase_email_from_bearer()
    if error_message:
        return None, api_error(error_message, status_code=401)
    return email, None


@mobile_api_bp.route('/home')
def home_products():
    try:
        conn = get_db_connection()
        ensure_product_reviews_table(conn)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT
                p.*,
                s.shop_name,
                s.name AS seller_name,
                s.profile_image AS seller_profile_image,
                COALESCE((SELECT COUNT(*) FROM orders o WHERE o.product_id = p.id AND LOWER(COALESCE(o.delivery_status::text,'')) <> 'cancelled'), 0) AS sold_count,
                COALESCE((SELECT COUNT(*) FROM product_reviews r WHERE r.product_id = p.id), 0) AS review_count,
                COALESCE((SELECT AVG(r.rating) FROM product_reviews r WHERE r.product_id = p.id), 0) AS average_rating
            FROM products p
            JOIN sellers s ON p.seller_id = s.id
            WHERE s.status = 'approved'
            ORDER BY p.created_at DESC
            LIMIT 15
            """
        )
        products = cur.fetchall() or []
        serialized = [_serialize_product_row(row) for row in products]
        return api_success(
            'Home products fetched successfully.',
            data={'products': serialized},
        )
    except Exception:
        return api_error('Unable to load home products.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/products')
def list_products():
    search = (request.args.get('search') or '').strip()
    category = (request.args.get('category') or '').strip()
    try:
        conn = get_db_connection()
        ensure_product_reviews_table(conn)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        where = ["s.status = 'approved'"]
        params = []
        if search:
            where.append("(LOWER(p.name) LIKE LOWER(%s) OR LOWER(p.description) LIKE LOWER(%s))")
            params.extend([f"%{search}%", f"%{search}%"])
        if category:
            where.append("p.category = %s")
            params.append(category)

        where_sql = " AND ".join(where)
        cur.execute(
            f"""
            SELECT
                p.*,
                s.shop_name,
                s.name AS seller_name,
                s.profile_image AS seller_profile_image,
                COALESCE((SELECT COUNT(*) FROM orders o WHERE o.product_id = p.id AND LOWER(COALESCE(o.delivery_status::text,'')) <> 'cancelled'), 0) AS sold_count,
                COALESCE((SELECT COUNT(*) FROM product_reviews r WHERE r.product_id = p.id), 0) AS review_count,
                COALESCE((SELECT AVG(r.rating) FROM product_reviews r WHERE r.product_id = p.id), 0) AS average_rating
            FROM products p
            JOIN sellers s ON p.seller_id = s.id
            WHERE {where_sql}
            ORDER BY p.created_at DESC
            """,
            tuple(params),
        )
        products = cur.fetchall() or []
        serialized = [_serialize_product_row(row) for row in products]

        cur.execute(
            """
            SELECT DISTINCT p.category
            FROM products p
            JOIN sellers s ON p.seller_id = s.id
            WHERE s.status = 'approved' AND p.category IS NOT NULL AND p.category <> ''
            ORDER BY p.category
            """
        )
        categories = [row['category'] for row in (cur.fetchall() or [])]

        return api_success(
            'Products fetched successfully.',
            data={'products': serialized, 'categories': categories},
        )
    except Exception:
        return api_error('Unable to fetch products.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/products/<int:product_id>')
def product_detail(product_id):
    try:
        conn = get_db_connection()
        ensure_product_reviews_table(conn)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT
                p.*,
                s.shop_name,
                s.name AS seller_name,
                s.profile_image AS seller_profile_image,
                COALESCE((SELECT COUNT(*) FROM orders o WHERE o.product_id = p.id AND LOWER(COALESCE(o.delivery_status::text,'')) <> 'cancelled'), 0) AS sold_count,
                COALESCE((SELECT COUNT(*) FROM product_reviews r WHERE r.product_id = p.id), 0) AS review_count,
                COALESCE((SELECT AVG(r.rating) FROM product_reviews r WHERE r.product_id = p.id), 0) AS average_rating
            FROM products p
            JOIN sellers s ON p.seller_id = s.id
            WHERE p.id = %s
            """,
            (product_id,),
        )
        product = cur.fetchone()
        if not product:
            return api_error('Product not found.', status_code=404)
        return api_success(
            'Product fetched successfully.',
            data={'product': _serialize_product_row(product)},
        )
    except Exception:
        return api_error('Unable to fetch product.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/products/<int:product_id>/reviews', methods=['GET'])
def product_reviews(product_id):
    try:
        conn = get_db_connection()
        ensure_product_reviews_table(conn)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT
                r.id,
                r.product_id,
                r.rating,
                r.title,
                r.comment,
                r.created_at,
                COALESCE(u.name, 'Customer') AS user_name
            FROM product_reviews r
            LEFT JOIN users u ON r.user_id = u.id
            WHERE r.product_id = %s
            ORDER BY r.created_at DESC
            LIMIT 50
            """,
            (product_id,),
        )
        rows = cur.fetchall() or []
        return api_success(
            'Product reviews fetched successfully.',
            data={
                'reviews': [serialize_review_row(row) for row in rows],
            },
        )
    except Exception:
        return api_error('Unable to load reviews.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/products/<int:product_id>/reviews', methods=['POST'])
def add_product_review(product_id):
    user, err = _require_mobile_user()
    if err is not None:
        return err

    payload = request.get_json(silent=True) or {}
    try:
        rating = int(payload.get('rating') or 0)
    except Exception:
        rating = 0
    title = (payload.get('title') or '').strip() or None
    comment = (payload.get('comment') or '').strip() or None

    if rating < 1 or rating > 5:
        return api_error('Rating must be between 1 and 5.', status_code=400)

    try:
        conn = get_db_connection()
        ensure_product_reviews_table(conn)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            """
            SELECT 1
            FROM orders
            WHERE user_id=%s AND product_id=%s AND LOWER(COALESCE(delivery_status::text,'')) IN ('delivered', 'in_transit')
            LIMIT 1
            """,
            (user['id'], product_id),
        )
        if not cur.fetchone():
            return api_error('You can only review products from completed purchases.', status_code=403)

        cur.execute(
            """
            INSERT INTO product_reviews (product_id, user_id, rating, title, comment, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (product_id, user_id)
            DO UPDATE SET rating=EXCLUDED.rating, title=EXCLUDED.title, comment=EXCLUDED.comment, updated_at=EXCLUDED.updated_at
            RETURNING id
            """,
            (product_id, user['id'], rating, title, comment, datetime.utcnow()),
        )
        conn.commit()
        return api_success('Review saved successfully.')
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return api_error('Unable to save review.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/profile', methods=['GET'])
def mobile_profile():
    email, err = _require_bearer_email()
    if err is not None:
        return err

    account, error_message = _account_by_email(email)
    if error_message:
        return api_error(error_message, status_code=404)

    return api_success(
        'Profile fetched successfully.',
        data={'user': _public_account_payload(account)},
    )


@mobile_api_bp.route('/profile', methods=['PUT'])
def update_mobile_profile():
    email, err = _require_bearer_email()
    if err is not None:
        return err

    payload = request.get_json(silent=True) or {}
    name = payload.get('name')
    address = payload.get('address')
    shop_name = payload.get('shop_name')

    try:
        conn = get_db_connection()
        ensure_product_reviews_table(conn)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Check if it's a seller
        cur.execute("SELECT * FROM sellers WHERE LOWER(email)=LOWER(%s)", (email,))
        seller = cur.fetchone()
        
        if seller:
            # Update seller profile
            updates = []
            params = []
            if name is not None:
                updates.append("name=%s")
                params.append(name)
            if address is not None:
                updates.append("address=%s")
                params.append(address)
            if shop_name is not None:
                updates.append("shop_name=%s")
                params.append(shop_name)

            if updates:
                params.append(seller['id'])
                cur.execute(
                    f"UPDATE sellers SET {', '.join(updates)} WHERE id=%s RETURNING *",
                    tuple(params),
                )
                seller = cur.fetchone()
                conn.commit()

            seller['role'] = 'seller'
            return api_success(
                'Profile updated successfully.',
                data={'user': _public_account_payload(seller)},
            )
        
        # Check if it's a user (buyer)
        cur.execute("SELECT * FROM users WHERE LOWER(email)=LOWER(%s)", (email,))
        user = cur.fetchone()
        if user:
            updates = []
            params = []
            if name is not None:
                updates.append("name=%s")
                params.append(name)
            if address is not None:
                updates.append("address=%s")
                params.append(address)

            if updates:
                params.append(user['id'])
                cur.execute(
                    f"UPDATE users SET {', '.join(updates)} WHERE id=%s RETURNING *",
                    tuple(params),
                )
                user = cur.fetchone()
                conn.commit()

            user['role'] = user.get('role') or 'user'
            return api_success(
                'Profile updated successfully.',
                data={'user': _public_account_payload(user)},
            )
        
        return api_error('Account not found.', status_code=404)
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return api_error('Unable to update profile.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


def _require_mobile_user():
    email, err = _require_bearer_email()
    if err is not None:
        return None, err
    account, error_message = _account_by_email(email)
    if error_message or not account or account.get('role') not in ('user', 'admin'):
        return None, api_error('This endpoint is only available for buyer accounts.', status_code=403)
    return account, None


@mobile_api_bp.route('/cart', methods=['GET'])
def get_cart():
    user, err = _require_mobile_user()
    if err is not None:
        return err

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT
                c.id,
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
            (user['id'],),
        )
        cart_items = cur.fetchall() or []
        serialized = [_serialize_cart_item_row(row) for row in cart_items]
        total = sum(float(row.get('subtotal') or 0) for row in serialized)
        return api_success(
            'Cart fetched successfully.',
            data={'cart_items': serialized, 'total_amount': total},
        )
    except Exception:
        return api_error('Unable to fetch cart.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/cart', methods=['POST'])
def add_cart_item():
    user, err = _require_mobile_user()
    if err is not None:
        return err

    payload = request.get_json(silent=True) or {}
    product_id = payload.get('product_id')
    quantity = int(payload.get('quantity') or 1)
    if not product_id:
        return api_error('Product ID is required.', status_code=400)

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute("SELECT id, price, stock FROM products WHERE id=%s", (product_id,))
        product = cur.fetchone()
        if not product:
            return api_error('Product not found.', status_code=404)
        if int(product.get('stock') or 0) < quantity:
            return api_error('Insufficient stock.', status_code=400)

        cur.execute(
            "SELECT id, quantity FROM cart WHERE user_id=%s AND product_id=%s",
            (user['id'], product_id),
        )
        existing = cur.fetchone()
        price = float(product.get('price') or 0)

        if existing:
            new_qty = int(existing.get('quantity') or 0) + quantity
            subtotal = price * new_qty
            cur.execute(
                "UPDATE cart SET quantity=%s, subtotal=%s WHERE id=%s",
                (new_qty, subtotal, existing['id']),
            )
        else:
            subtotal = price * quantity
            cur.execute(
                "INSERT INTO cart (user_id, product_id, quantity, subtotal) VALUES (%s, %s, %s, %s)",
                (user['id'], product_id, quantity, subtotal),
            )

        conn.commit()
        return api_success('Added to cart.')
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return api_error('Unable to add to cart.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/cart/<int:cart_id>', methods=['PUT'])
def update_cart_item(cart_id):
    user, err = _require_mobile_user()
    if err is not None:
        return err

    payload = request.get_json(silent=True) or {}
    quantity = int(payload.get('quantity') or 1)
    if quantity < 1:
        return api_error('Quantity must be at least 1.', status_code=400)

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            """
            SELECT c.id, c.product_id, p.price, p.stock
            FROM cart c
            JOIN products p ON c.product_id = p.id
            WHERE c.id=%s AND c.user_id=%s
            """,
            (cart_id, user['id']),
        )
        row = cur.fetchone()
        if not row:
            return api_error('Cart item not found.', status_code=404)

        if int(row.get('stock') or 0) < quantity:
            return api_error('Insufficient stock.', status_code=400)

        subtotal = float(row.get('price') or 0) * quantity
        cur.execute(
            "UPDATE cart SET quantity=%s, subtotal=%s WHERE id=%s",
            (quantity, subtotal, cart_id),
        )
        conn.commit()
        return api_success('Cart updated.')
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return api_error('Unable to update cart.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/cart/<int:cart_id>', methods=['DELETE'])
def delete_cart_item(cart_id):
    user, err = _require_mobile_user()
    if err is not None:
        return err

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("DELETE FROM cart WHERE id=%s AND user_id=%s", (cart_id, user['id']))
        conn.commit()
        return api_success('Cart item removed.')
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return api_error('Unable to remove cart item.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/checkout', methods=['POST'])
def checkout():
    user, err = _require_mobile_user()
    if err is not None:
        return err

    payload = request.get_json(silent=True) or {}
    payment_method = (payload.get('payment_method') or 'Cash on Delivery').strip()

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            """
            SELECT c.id, c.product_id, c.quantity, p.price, p.stock, p.seller_id,
                   u.address AS user_address,
                   s.address AS pickup_address
            FROM cart c
            JOIN products p ON c.product_id = p.id
            JOIN users u ON c.user_id = u.id
            LEFT JOIN sellers s ON p.seller_id = s.id
            WHERE c.user_id = %s
            """,
            (user['id'],),
        )
        items = cur.fetchall() or []
        if not items:
            return api_error('Your cart is empty.', status_code=400)

        for item in items:
            qty = int(item.get('quantity') or 0)
            stock = int(item.get('stock') or 0)
            if stock < qty:
                return api_error('Insufficient stock for one or more items.', status_code=400)

        for item in items:
            qty = int(item.get('quantity') or 0)
            price = float(item.get('price') or 0)
            total = price * qty
            cur.execute(
                """
                INSERT INTO orders (
                    user_id, product_id, quantity, total, payment_method, payment_status,
                    address, seller_id, delivery_status, pickup_address, delivery_address
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s, %s)
                """,
                (
                    user['id'],
                    item['product_id'],
                    qty,
                    total,
                    payment_method,
                    'Pending',
                    item.get('user_address'),
                    item.get('seller_id'),
                    item.get('pickup_address'),
                    item.get('user_address'),
                ),
            )

            cur.execute(
                "UPDATE products SET stock = stock - %s WHERE id=%s",
                (qty, item['product_id']),
            )

        cur.execute("DELETE FROM cart WHERE user_id=%s", (user['id'],))
        conn.commit()
        return api_success('Checkout successful.')
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return api_error('Checkout failed.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/orders', methods=['GET'])
def mobile_orders():
    user, err = _require_mobile_user()
    if err is not None:
        return err

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT
                o.id,
                o.quantity,
                COALESCE(o.total, 0) AS total,
                o.payment_status,
                o.delivery_status,
                COALESCE(o.order_received, 0) AS order_received,
                p.name AS product_name,
                p.image AS product_image,
                COALESCE(s.shop_name, 'Unknown Shop') AS shop_name
            FROM orders o
            JOIN products p ON o.product_id = p.id
            LEFT JOIN sellers s ON o.seller_id = s.id
            WHERE o.user_id = %s
            ORDER BY o.order_date DESC
            """,
            (user['id'],),
        )
        rows = cur.fetchall() or []
        for row in rows:
            try:
                row['total'] = float(row.get('total') or 0)
            except Exception:
                row['total'] = 0

        to_pay = []
        to_ship = []
        to_receive = []
        completed = []
        refunded = []
        cancelled = []

        for row in rows:
            status = (row.get('delivery_status') or '').lower()
            payment_status = (row.get('payment_status') or '').lower()
            received = int(row.get('order_received') or 0)

            if status == 'cancelled' or payment_status == 'cancelled':
                cancelled.append(row)
                continue

            if received == 1:
                completed.append(row)
                continue

            if status in ('delivered', 'in_transit'):
                to_receive.append(row)
                continue

            if status in ('pending', 'assigned', 'picked_up'):
                to_ship.append(row)
                continue

            to_pay.append(row)

        return api_success(
            'Orders fetched successfully.',
            data={
                'to_pay': to_pay,
                'to_ship': to_ship,
                'to_receive': to_receive,
                'completed': completed,
                'refunded': refunded,
                'cancelled': cancelled,
            },
        )
    except Exception:
        return api_error('Unable to load orders.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/orders/<int:order_id>/cancel', methods=['POST'])
def cancel_order(order_id):
    user, err = _require_mobile_user()
    if err is not None:
        return err

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            """
            SELECT o.*, p.stock
            FROM orders o
            JOIN products p ON o.product_id = p.id
            WHERE o.id = %s AND o.user_id = %s
            """,
            (order_id, user['id']),
        )
        order = cur.fetchone()
        if not order:
            return api_error('Order not found.', status_code=404)

        if (order.get('delivery_status') or '').lower() not in ('pending', 'cancelled'):
            return api_error('Cannot cancel order in this status.', status_code=400)

        if int(order.get('seller_confirmed') or 0) == 0:
            cur.execute(
                "UPDATE products SET stock = stock + %s WHERE id=%s",
                (order['quantity'], order['product_id']),
            )

        cur.execute(
            "UPDATE orders SET delivery_status='cancelled', payment_status='Cancelled' WHERE id=%s",
            (order_id,),
        )
        conn.commit()
        return api_success('Order cancelled.')
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return api_error('Unable to cancel order.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/orders/<int:order_id>/received', methods=['POST'])
def confirm_received(order_id):
    user, err = _require_mobile_user()
    if err is not None:
        return err

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            UPDATE orders
            SET order_received=1, order_received_at=%s
            WHERE id=%s AND user_id=%s
            RETURNING id
            """,
            (datetime.utcnow(), order_id, user['id']),
        )
        updated = cur.fetchone()
        if not updated:
            return api_error('Order not found.', status_code=404)
        conn.commit()
        return api_success('Order marked as received.')
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def _require_role(*roles):
    email, err = _require_bearer_email()
    if err is not None:
        return None, err

    account, error_message = _account_by_email(email)
    if error_message or not account:
        return None, api_error('Account not found.', status_code=404)

    role = (account.get('role') or '').strip().lower()
    if role not in roles:
        return None, api_error('Unauthorized access.', status_code=403)

    return account, None


def _iso(value):
    if not value:
        return None
    try:
        return value.isoformat()
    except Exception:
        return str(value)


def _ensure_order_mobile_columns(conn):
    try:
        add_column_if_missing(conn, 'orders', 'assigned_at', 'TIMESTAMP NULL')
        add_column_if_missing(conn, 'orders', 'picked_up_at', 'TIMESTAMP NULL')
        add_column_if_missing(conn, 'orders', 'delivered_at', 'TIMESTAMP NULL')
        add_column_if_missing(conn, 'orders', 'delivery_proof', 'VARCHAR(500) DEFAULT NULL')
        add_column_if_missing(conn, 'orders', 'delivery_status', "VARCHAR(20) DEFAULT 'pending'")
        add_column_if_missing(conn, 'orders', 'pickup_address', 'VARCHAR(500) DEFAULT NULL')
        add_column_if_missing(conn, 'orders', 'delivery_address', 'VARCHAR(500) DEFAULT NULL')
        add_column_if_missing(conn, 'orders', 'customer_contact', 'VARCHAR(32) DEFAULT NULL')
        add_column_if_missing(conn, 'orders', 'order_received', 'SMALLINT DEFAULT 0')
        add_column_if_missing(conn, 'orders', 'order_received_at', 'TIMESTAMP NULL')
    except Exception:
        pass


def _serialize_seller_order_row(row):
    return {
        'id': row.get('id'),
        'product_id': row.get('product_id'),
        'quantity': int(row.get('quantity') or 0),
        'total': float(row.get('total') or 0),
        'payment_method': row.get('payment_method'),
        'payment_status': row.get('payment_status'),
        'delivery_status': row.get('delivery_status'),
        'order_date': _iso(row.get('order_date')),
        'seller_confirmed': int(row.get('seller_confirmed') or 0),
        'order_received': int(row.get('order_received') or 0),
        'pickup_address': row.get('pickup_address'),
        'delivery_address': row.get('delivery_address') or row.get('address'),
        'customer': {
            'id': row.get('user_id'),
            'name': row.get('user_name'),
            'email': row.get('user_email'),
            'address': row.get('user_address') or row.get('address'),
        },
        'product': {
            'name': row.get('product_name'),
            'image': row.get('product_image'),
        },
    }


def _serialize_rider_order_row(row):
    return {
        'id': row.get('id'),
        'product_id': row.get('product_id'),
        'quantity': int(row.get('quantity') or 0),
        'total': float(row.get('total') or 0),
        'payment_method': row.get('payment_method'),
        'payment_status': row.get('payment_status'),
        'delivery_status': row.get('delivery_status'),
        'order_date': _iso(row.get('order_date')),
        'assigned_at': _iso(row.get('assigned_at')),
        'picked_up_at': _iso(row.get('picked_up_at')),
        'delivered_at': _iso(row.get('delivered_at')),
        'pickup_address': row.get('pickup_address'),
        'delivery_address': row.get('delivery_address') or row.get('address'),
        'shop_name': row.get('shop_name'),
        'seller_name': row.get('seller_name'),
        'seller_contact': row.get('seller_contact'),
        'customer_name': row.get('customer_name'),
        'customer_email': row.get('customer_email'),
        'customer_contact': row.get('customer_contact'),
        'product_name': row.get('product_name'),
        'product_image': row.get('product_image'),
        'delivery_proof': row.get('delivery_proof'),
    }


def _serialize_refund_row(row):
    return {
        'id': row.get('id'),
        'order_id': row.get('order_id'),
        'product_id': row.get('product_id'),
        'reason': row.get('reason'),
        'evidence_file': row.get('evidence_file'),
        'rejection_reason': row.get('rejection_reason'),
        'status': row.get('status'),
        'refund_status': row.get('refund_status'),
        'created_at': _iso(row.get('created_at')),
        'updated_at': _iso(row.get('updated_at')),
        'product_name': row.get('product_name'),
        'product_image': row.get('product_image'),
        'user_name': row.get('user_name'),
        'user_email': row.get('user_email'),
    }


@mobile_api_bp.route('/seller/dashboard', methods=['GET'])
def seller_dashboard_payload():
    seller, err = _require_role('seller')
    if err is not None:
        return err

    seller_id = int(seller.get('id') or 0)
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute("SELECT COUNT(*) AS c FROM products WHERE seller_id=%s", (seller_id,))
        total_products = int((cur.fetchone() or {}).get('c') or 0)

        cur.execute(
            """
            SELECT COUNT(*) AS c
            FROM orders
            WHERE seller_id=%s
            """,
            (seller_id,),
        )
        total_orders = int((cur.fetchone() or {}).get('c') or 0)

        cur.execute(
            """
            SELECT COUNT(*) AS c
            FROM orders
            WHERE seller_id=%s AND LOWER(COALESCE(payment_status,''))='pending'
            """,
            (seller_id,),
        )
        pending_orders = int((cur.fetchone() or {}).get('c') or 0)

        cur.execute(
            """
            SELECT COUNT(*) AS c
            FROM orders
            WHERE seller_id=%s AND LOWER(COALESCE(payment_status,''))='confirmed'
            """,
            (seller_id,),
        )
        completed_orders = int((cur.fetchone() or {}).get('c') or 0)

        cur.execute(
            """
            SELECT COALESCE(SUM(total), 0) AS ts
            FROM orders
            WHERE seller_id=%s
            """,
            (seller_id,),
        )
        total_sales = float((cur.fetchone() or {}).get('ts') or 0)
        total_earnings = total_sales * 0.9
        total_commission = total_sales * 0.1

        refunded_items = 0
        refund_pending = 0
        try:
            cur.execute(
                """
                SELECT status, COUNT(*) AS c
                FROM refund_requests
                WHERE seller_id=%s
                GROUP BY status
                """,
                (seller_id,),
            )
            rows = cur.fetchall() or []
            for r in rows:
                st = (r.get('status') or '').lower()
                if st == 'approved':
                    refunded_items = int(r.get('c') or 0)
                if st == 'pending':
                    refund_pending = int(r.get('c') or 0)
        except Exception:
            pass

        return api_success(
            'Seller dashboard loaded.',
            data={
                'metrics': {
                    'total_products': total_products,
                    'total_orders': total_orders,
                    'pending_orders': pending_orders,
                    'completed_orders': completed_orders,
                    'refunded_items': refunded_items,
                    'pending_refunds': refund_pending,
                    'total_sales': total_sales,
                    'total_earnings': total_earnings,
                    'admin_commission': total_commission,
                }
            },
        )
    except Exception:
        return api_error('Unable to load seller dashboard.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/seller/products', methods=['GET'])
def seller_products():
    seller, err = _require_role('seller')
    if err is not None:
        return err

    seller_id = int(seller.get('id') or 0)
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT p.*, s.shop_name, s.name AS seller_name, s.profile_image AS seller_profile_image
            FROM products p
            JOIN sellers s ON p.seller_id = s.id
            WHERE p.seller_id=%s
            ORDER BY p.created_at DESC
            """,
            (seller_id,),
        )
        rows = cur.fetchall() or []
        serialized = [_serialize_product_row(r) for r in rows]
        return api_success('Seller products fetched.', data={'products': serialized})
    except Exception:
        return api_error('Unable to fetch seller products.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/seller/products', methods=['POST'])
def seller_add_product():
    seller, err = _require_role('seller')
    if err is not None:
        return err

    payload = request.get_json(silent=True) or {}
    name = (payload.get('name') or '').strip()
    description = (payload.get('description') or '').strip()
    category = (payload.get('category') or '').strip()
    image = (payload.get('image') or '').strip()
    size_options = _join_variant_values(payload.get('size_options'))
    color_options = _join_variant_values(payload.get('color_options'))
    try:
        price = float(payload.get('price') or 0)
        stock = int(payload.get('stock') or 0)
    except Exception:
        return api_error('Invalid price or stock.', status_code=400)

    if not name:
        return api_error('Product name is required.', status_code=400)

    seller_id = int(seller.get('id') or 0)
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        add_column_if_missing(conn, 'products', 'size_options', 'TEXT DEFAULT NULL')
        add_column_if_missing(conn, 'products', 'color_options', 'TEXT DEFAULT NULL')
        cur.execute(
            """
            INSERT INTO products (name, description, price, stock, category, image, seller_id, size_options, color_options)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                name,
                description or None,
                price,
                stock,
                category or None,
                image or None,
                seller_id,
                size_options,
                color_options,
            ),
        )
        row = cur.fetchone() or {}
        conn.commit()
        product_id = int(row.get('id') or 0)

        cur.execute(
            """
            SELECT p.*, s.shop_name, s.name AS seller_name, s.profile_image AS seller_profile_image
            FROM products p
            JOIN sellers s ON p.seller_id = s.id
            WHERE p.id=%s AND p.seller_id=%s
            """,
            (product_id, seller_id),
        )
        product = cur.fetchone()
        return api_success(
            'Product created.',
            data={'product': _serialize_product_row(product)},
        )
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return api_error('Unable to create product.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/seller/products/<int:product_id>', methods=['PUT'])
def seller_update_product(product_id):
    seller, err = _require_role('seller')
    if err is not None:
        return err

    payload = request.get_json(silent=True) or {}
    seller_id = int(seller.get('id') or 0)
    size_options = _join_variant_values(payload.get('size_options')) if 'size_options' in payload else None
    color_options = _join_variant_values(payload.get('color_options')) if 'color_options' in payload else None

    fields = []
    params = []
    for key in ('name', 'description', 'category', 'image'):
        if key in payload:
            fields.append(f"{key}=%s")
            params.append(payload.get(key))
    if 'price' in payload:
        fields.append("price=%s")
        params.append(float(payload.get('price') or 0))
    if 'stock' in payload:
        fields.append("stock=%s")
        params.append(int(payload.get('stock') or 0))
    if 'size_options' in payload:
        fields.append("size_options=%s")
        params.append(size_options)
    if 'color_options' in payload:
        fields.append("color_options=%s")
        params.append(color_options)

    if not fields:
        return api_error('No updates provided.', status_code=400)

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        params.extend([product_id, seller_id])
        cur.execute(
            f"""
            UPDATE products
            SET {', '.join(fields)}
            WHERE id=%s AND seller_id=%s
            RETURNING id
            """,
            tuple(params),
        )
        updated = cur.fetchone()
        if not updated:
            return api_error('Product not found.', status_code=404)
        conn.commit()

        cur.execute(
            """
            SELECT p.*, s.shop_name, s.name AS seller_name, s.profile_image AS seller_profile_image
            FROM products p
            JOIN sellers s ON p.seller_id = s.id
            WHERE p.id=%s AND p.seller_id=%s
            """,
            (product_id, seller_id),
        )
        product = cur.fetchone()
        return api_success(
            'Product updated.',
            data={'product': _serialize_product_row(product)},
        )
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return api_error('Unable to update product.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/seller/products/<int:product_id>', methods=['DELETE'])
def seller_delete_product(product_id):
    seller, err = _require_role('seller')
    if err is not None:
        return err

    seller_id = int(seller.get('id') or 0)
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM products WHERE id=%s AND seller_id=%s",
            (product_id, seller_id),
        )
        if cur.rowcount == 0:
            return api_error('Product not found.', status_code=404)
        conn.commit()
        return api_success('Product deleted.')
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return api_error('Unable to delete product.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/seller/orders', methods=['GET'])
def seller_orders():
    seller, err = _require_role('seller')
    if err is not None:
        return err

    seller_id = int(seller.get('id') or 0)
    try:
        conn = get_db_connection()
        _ensure_order_mobile_columns(conn)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT
                o.*,
                u.name AS user_name,
                u.email AS user_email,
                u.address AS user_address,
                p.name AS product_name,
                p.image AS product_image
            FROM orders o
            JOIN users u ON o.user_id = u.id
            JOIN products p ON o.product_id = p.id
            WHERE o.seller_id = %s OR p.seller_id = %s
            ORDER BY o.order_date DESC
            """,
            (seller_id, seller_id),
        )
        rows = cur.fetchall() or []
        serialized = [_serialize_seller_order_row(r) for r in rows]
        return api_success('Seller orders fetched.', data={'orders': serialized})
    except Exception:
        return api_error('Unable to fetch seller orders.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/seller/orders/<int:order_id>/confirm', methods=['POST'])
def seller_confirm_order_api(order_id):
    seller, err = _require_role('seller')
    if err is not None:
        return err

    seller_id = int(seller.get('id') or 0)
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE orders
            SET payment_status='Confirmed', seller_confirmed=1
            WHERE id=%s AND seller_id=%s
            """,
            (order_id, seller_id),
        )
        if cur.rowcount == 0:
            return api_error('Order not found.', status_code=404)
        conn.commit()
        return api_success('Order confirmed.')
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return api_error('Unable to confirm order.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/seller/refunds', methods=['GET'])
def seller_refunds():
    seller, err = _require_role('seller')
    if err is not None:
        return err

    seller_id = int(seller.get('id') or 0)
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT rr.*, p.name AS product_name, p.image AS product_image,
                   u.name AS user_name, u.email AS user_email,
                   o.id AS order_id
            FROM refund_requests rr
            JOIN orders o ON rr.order_id = o.id
            JOIN products p ON o.product_id = p.id
            JOIN users u ON o.user_id = u.id
            WHERE o.seller_id = %s OR rr.seller_id=%s
            ORDER BY rr.created_at DESC
            """,
            (seller_id, seller_id),
        )
        rows = cur.fetchall() or []
        return api_success(
            'Refund requests fetched.',
            data={'refund_requests': [_serialize_refund_row(r) for r in rows]},
        )
    except Exception:
        return api_error('Unable to fetch refund requests.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/seller/refunds/<int:refund_id>/approve', methods=['POST'])
def seller_approve_refund_api(refund_id):
    seller, err = _require_role('seller')
    if err is not None:
        return err

    seller_id = int(seller.get('id') or 0)
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE refund_requests
            SET status='approved'
            WHERE id=%s AND seller_id=%s
            """,
            (refund_id, seller_id),
        )
        if cur.rowcount == 0:
            return api_error('Refund not found.', status_code=404)
        conn.commit()
        return api_success('Refund approved.')
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return api_error('Unable to approve refund.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/seller/refunds/<int:refund_id>/reject', methods=['POST'])
def seller_reject_refund_api(refund_id):
    seller, err = _require_role('seller')
    if err is not None:
        return err

    payload = request.get_json(silent=True) or {}
    reason = (payload.get('rejection_reason') or '').strip()
    seller_id = int(seller.get('id') or 0)
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE refund_requests
            SET status='rejected', rejection_reason=%s
            WHERE id=%s AND seller_id=%s
            """,
            (reason, refund_id, seller_id),
        )
        if cur.rowcount == 0:
            return api_error('Refund not found.', status_code=404)
        conn.commit()
        return api_success('Refund rejected.')
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return api_error('Unable to reject refund.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/seller/sales', methods=['GET'])
def seller_sales_api():
    seller, err = _require_role('seller')
    if err is not None:
        return err

    seller_id = int(seller.get('id') or 0)
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        where = ["o.seller_id = %s"]
        params = [seller_id]
        if start_date:
            where.append("o.order_date::date >= %s::date")
            params.append(start_date)
        if end_date:
            where.append("o.order_date::date <= %s::date")
            params.append(end_date)

        where_sql = " AND ".join(where)
        cur.execute(
            f"""
            SELECT
                DATE(o.order_date) AS date,
                COUNT(*) AS order_count,
                COALESCE(SUM(o.total), 0) AS total_sales
            FROM orders o
            WHERE {where_sql}
            GROUP BY DATE(o.order_date)
            ORDER BY DATE(o.order_date) DESC
            """,
            tuple(params),
        )
        rows = cur.fetchall() or []
        sales_data = []
        total_orders = 0
        total_sales = 0.0
        for row in rows:
            ts = float(row.get('total_sales') or 0)
            oc = int(row.get('order_count') or 0)
            total_orders += oc
            total_sales += ts
            sales_data.append(
                {
                    'date': _iso(row.get('date')),
                    'order_count': oc,
                    'total_sales': ts,
                    'seller_earnings': ts * 0.9,
                    'admin_commission': ts * 0.1,
                }
            )

        return api_success(
            'Sales fetched.',
            data={
                'sales_data': sales_data,
                'total_orders': total_orders,
                'total_sales': total_sales,
                'total_earnings': total_sales * 0.9,
                'total_commission': total_sales * 0.1,
            },
        )
    except Exception:
        return api_error('Unable to fetch sales.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/rider/dashboard', methods=['GET'])
def rider_dashboard_payload():
    rider, err = _require_role('rider')
    if err is not None:
        return err

    rider_id = int(rider.get('id') or 0)
    try:
        conn = get_db_connection()
        _ensure_order_mobile_columns(conn)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT delivery_status, COUNT(*) AS c
            FROM orders
            WHERE rider_id=%s
            GROUP BY delivery_status
            """,
            (rider_id,),
        )
        rows = cur.fetchall() or []

        pending = 0
        in_progress = 0
        delivered = 0
        for r in rows:
            st = (r.get('delivery_status') or '').lower()
            c = int(r.get('c') or 0)
            if st == 'delivered':
                delivered += c
            elif st in ('assigned', 'picked_up', 'in_transit'):
                in_progress += c
            else:
                pending += c

        # Get commission metrics
        cur.execute(
            """
            SELECT
                COALESCE(SUM(o.total * 0.05), 0) AS total_commission
            FROM orders o
            WHERE o.rider_id=%s AND LOWER(COALESCE(o.delivery_status::text,'')) = 'delivered'
            """,
            (rider_id,),
        )
        commission_data = cur.fetchone() or {}
        total_commission = float(commission_data.get('total_commission') or 0)

        return api_success(
            'Rider dashboard loaded.',
            data={
                'metrics': {
                    'total_orders': pending + in_progress + delivered,
                    'pending': pending,
                    'in_progress': in_progress,
                    'delivered': delivered,
                    'total_commission': total_commission,
                }
            },
        )
    except Exception:
        return api_error('Unable to load rider dashboard.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/rider/available-orders', methods=['GET'])
def rider_available_orders():
    rider, err = _require_role('rider')
    if err is not None:
        return err

    try:
        conn = get_db_connection()
        _ensure_order_mobile_columns(conn)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT
                o.*,
                p.name AS product_name,
                p.image AS product_image,
                s.shop_name,
                s.name AS seller_name,
                s.email AS seller_contact,
                u.name AS customer_name,
                u.email AS customer_email,
                u.address AS delivery_address
            FROM orders o
            JOIN products p ON o.product_id = p.id
            JOIN sellers s ON p.seller_id = s.id
            JOIN users u ON o.user_id = u.id
            WHERE (o.rider_id IS NULL) AND LOWER(COALESCE(o.delivery_status::text,''))='pending'
            ORDER BY o.order_date DESC
            """,
        )
        rows = cur.fetchall() or []
        serialized = [_serialize_rider_order_row(r) for r in rows]
        return api_success('Available orders fetched.', data={'orders': serialized})
    except Exception:
        return api_error('Unable to fetch available orders.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/rider/orders/<int:order_id>/accept', methods=['POST'])
def rider_accept_order(order_id):
    rider, err = _require_role('rider')
    if err is not None:
        return err

    rider_id = int(rider.get('id') or 0)
    try:
        conn = get_db_connection()
        _ensure_order_mobile_columns(conn)
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE orders
            SET rider_id=%s, delivery_status='assigned', assigned_at=%s
            WHERE id=%s AND rider_id IS NULL AND LOWER(COALESCE(delivery_status::text,''))='pending'
            """,
            (rider_id, datetime.utcnow(), order_id),
        )
        if cur.rowcount == 0:
            return api_error('Order not available.', status_code=400)
        conn.commit()
        return api_success('Order accepted.')
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return api_error('Unable to accept order.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/rider/deliveries', methods=['GET'])
def rider_deliveries():
    rider, err = _require_role('rider')
    if err is not None:
        return err

    rider_id = int(rider.get('id') or 0)
    try:
        conn = get_db_connection()
        _ensure_order_mobile_columns(conn)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT
                o.*,
                p.name AS product_name,
                p.image AS product_image,
                s.shop_name,
                s.name AS seller_name,
                s.email AS seller_contact,
                u.name AS customer_name,
                u.email AS customer_email,
                u.address AS delivery_address
            FROM orders o
            JOIN products p ON o.product_id = p.id
            JOIN sellers s ON p.seller_id = s.id
            JOIN users u ON o.user_id = u.id
            WHERE o.rider_id = %s
            ORDER BY o.order_date DESC
            """,
            (rider_id,),
        )
        rows = cur.fetchall() or []
        pending = []
        in_progress = []
        delivered = []
        for r in rows:
            st = (r.get('delivery_status') or '').lower()
            if st == 'delivered':
                delivered.append(r)
            elif st in ('assigned', 'picked_up', 'in_transit'):
                in_progress.append(r)
            else:
                pending.append(r)

        return api_success(
            'Deliveries fetched.',
            data={
                'pending': [_serialize_rider_order_row(r) for r in pending],
                'in_progress': [_serialize_rider_order_row(r) for r in in_progress],
                'delivered': [_serialize_rider_order_row(r) for r in delivered],
            },
        )
    except Exception:
        return api_error('Unable to fetch deliveries.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/rider/orders/<int:order_id>/status', methods=['POST'])
def rider_update_status(order_id):
    rider, err = _require_role('rider')
    if err is not None:
        return err

    payload = request.get_json(silent=True) or {}
    status = (payload.get('delivery_status') or '').strip().lower()
    allowed = {'assigned', 'picked_up', 'in_transit', 'delivered', 'cancelled'}
    if status not in allowed:
        return api_error('Invalid delivery status.', status_code=400)

    rider_id = int(rider.get('id') or 0)
    try:
        conn = get_db_connection()
        _ensure_order_mobile_columns(conn)
        cur = conn.cursor()

        fields = ["delivery_status=%s"]
        params = [status]
        if status == 'picked_up':
            fields.append("picked_up_at=%s")
            params.append(datetime.utcnow())
        if status == 'delivered':
            fields.append("delivered_at=%s")
            params.append(datetime.utcnow())

        params.extend([order_id, rider_id])
        cur.execute(
            f"UPDATE orders SET {', '.join(fields)} WHERE id=%s AND rider_id=%s",
            tuple(params),
        )
        if cur.rowcount == 0:
            return api_error('Order not found.', status_code=404)
        conn.commit()
        return api_success('Delivery status updated.')
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return api_error('Unable to update delivery status.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/rider/orders/<int:order_id>/proof', methods=['POST'])
def rider_upload_proof_of_delivery(order_id):
    rider, err = _require_role('rider')
    if err is not None:
        return err

    if 'image' not in request.files:
        return api_error('No image file provided.', status_code=400)

    file = request.files['image']
    if not file or file.filename == '':
        return api_error('Invalid image file.', status_code=400)

    rider_id = int(rider.get('id') or 0)
    try:
        # Validate order belongs to rider
        conn = get_db_connection()
        _ensure_order_mobile_columns(conn)
        cur = conn.cursor()

        cur.execute(
            "SELECT id FROM orders WHERE id=%s AND rider_id=%s",
            (order_id, rider_id),
        )
        if cur.fetchone() is None:
            return api_error('Order not found or does not belong to rider.', status_code=404)

        # Create uploads directory if it doesn't exist
        upload_dir = os.path.join('static', 'uploads', 'delivery_proof')
        os.makedirs(upload_dir, exist_ok=True)

        # Generate unique filename
        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        ext = os.path.splitext(file.filename)[1] or '.jpg'
        filename = f"proof_{order_id}_{rider_id}_{timestamp}{ext}"
        filepath = os.path.join(upload_dir, filename)

        # Save file
        file.save(filepath)

        # Update orders table with proof of delivery path
        relative_path = f"/uploads/delivery_proof/{filename}"
        cur.execute(
            "UPDATE orders SET delivery_proof=%s WHERE id=%s",
            (relative_path, order_id),
        )
        conn.commit()

        return api_success(
            'Proof of delivery uploaded successfully.',
            data={'proof_path': relative_path},
        )
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return api_error(f'Unable to upload proof of delivery: {str(e)}', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/rider/commissions', methods=['GET'])
def rider_commissions_api():
    rider, err = _require_role('rider')
    if err is not None:
        return err

    rider_id = int(rider.get('id') or 0)
    try:
        conn = get_db_connection()
        _ensure_order_mobile_columns(conn)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Get total commission from all delivered orders
        cur.execute(
            """
            SELECT
                COALESCE(SUM(o.total * 0.05), 0) AS total_commission,
                COUNT(o.id) AS total_delivered_orders,
                COALESCE(SUM(o.quantity), 0) AS total_items_delivered
            FROM orders o
            WHERE o.rider_id=%s AND LOWER(COALESCE(o.delivery_status::text,'')) = 'delivered'
            """,
            (rider_id,),
        )
        totals = cur.fetchone() or {}
        total_commission = float(totals.get('total_commission') or 0)
        total_delivered_orders = int(totals.get('total_delivered_orders') or 0)
        total_items_delivered = int(totals.get('total_items_delivered') or 0)

        # Get commission breakdown by delivery
        cur.execute(
            """
            SELECT
                o.id AS order_id,
                o.quantity,
                o.total,
                o.delivered_at,
                o.delivery_status,
                p.name AS product_name,
                s.shop_name,
                u.name AS customer_name
            FROM orders o
            JOIN products p ON o.product_id = p.id
            JOIN sellers s ON p.seller_id = s.id
            JOIN users u ON o.user_id = u.id
            WHERE o.rider_id=%s AND LOWER(COALESCE(o.delivery_status::text,'')) = 'delivered'
            ORDER BY o.delivered_at DESC
            LIMIT 100
            """,
            (rider_id,),
        )
        deliveries = cur.fetchall() or []
        deliveries_list = []
        for d in deliveries:
            total = float(d.get('total') or 0)
            commission = total * 0.05
            deliveries_list.append({
                'order_id': d.get('order_id'),
                'product_name': d.get('product_name'),
                'shop_name': d.get('shop_name'),
                'customer_name': d.get('customer_name'),
                'quantity': int(d.get('quantity') or 0),
                'order_total': total,
                'commission': commission,
                'commission_per_item': commission / max(int(d.get('quantity') or 1), 1),
                'delivered_at': _iso(d.get('delivered_at')),
            })

        return api_success(
            'Rider commissions fetched.',
            data={
                'total_commission': total_commission,
                'total_delivered_orders': total_delivered_orders,
                'total_items_delivered': total_items_delivered,
                'average_commission_per_delivery': total_commission / max(total_delivered_orders, 1),
                'commissions': deliveries_list,
            },
        )
    except Exception:
        return api_error('Unable to fetch rider commissions.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/admin/dashboard', methods=['GET'])
def admin_dashboard_payload():
    admin, err = _require_role('admin')
    if err is not None:
        return err

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute("SELECT COUNT(*) AS c FROM sellers")
        total_sellers = int((cur.fetchone() or {}).get('c') or 0)
        cur.execute("SELECT COUNT(*) AS c FROM sellers WHERE status='pending'")
        pending_sellers = int((cur.fetchone() or {}).get('c') or 0)

        cur.execute("SELECT COUNT(*) AS c FROM riders")
        total_riders = int((cur.fetchone() or {}).get('c') or 0)
        cur.execute("SELECT COUNT(*) AS c FROM riders WHERE status='pending'")
        pending_riders = int((cur.fetchone() or {}).get('c') or 0)

        cur.execute("SELECT COUNT(*) AS c FROM users")
        total_users = int((cur.fetchone() or {}).get('c') or 0)

        cur.execute(
            """
            SELECT COALESCE(SUM(total), 0) AS total_sales
            FROM orders
            WHERE LOWER(COALESCE(delivery_status::text,'')) <> 'cancelled'
            """,
        )
        total_sales = float((cur.fetchone() or {}).get('total_sales') or 0)
        total_commission = total_sales * 0.1

        return api_success(
            'Admin dashboard loaded.',
            data={
                'metrics': {
                    'total_sellers': total_sellers,
                    'pending_sellers': pending_sellers,
                    'total_riders': total_riders,
                    'pending_riders': pending_riders,
                    'total_users': total_users,
                    'total_commission': total_commission,
                }
            },
        )
    except Exception:
        return api_error('Unable to load admin dashboard.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/admin/sellers', methods=['GET'])
def admin_list_sellers():
    admin, err = _require_role('admin')
    if err is not None:
        return err

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM sellers ORDER BY id DESC")
        rows = cur.fetchall() or []
        for r in rows:
            if 'password' in r:
                r.pop('password', None)
        return api_success('Sellers fetched.', data={'sellers': rows})
    except Exception:
        return api_error('Unable to fetch sellers.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/admin/riders', methods=['GET'])
def admin_list_riders():
    admin, err = _require_role('admin')
    if err is not None:
        return err

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM riders ORDER BY id DESC")
        rows = cur.fetchall() or []
        for r in rows:
            if 'password' in r:
                r.pop('password', None)
        return api_success('Riders fetched.', data={'riders': rows})
    except Exception:
        return api_error('Unable to fetch riders.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/admin/users', methods=['GET'])
def admin_list_users():
    admin, err = _require_role('admin')
    if err is not None:
        return err

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id, name, email, role, address, created_at FROM users ORDER BY id DESC")
        rows = cur.fetchall() or []
        for r in rows:
            r['created_at'] = _iso(r.get('created_at'))
        return api_success('Users fetched.', data={'users': rows})
    except Exception:
        return api_error('Unable to fetch users.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/admin/sellers/<int:seller_id>/approve', methods=['POST'])
def admin_approve_seller_api(seller_id):
    admin, err = _require_role('admin')
    if err is not None:
        return err

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE sellers SET status='approved' WHERE id=%s", (seller_id,))
        if cur.rowcount == 0:
            return api_error('Seller not found.', status_code=404)
        conn.commit()
        return api_success('Seller approved.')
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return api_error('Unable to approve seller.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/admin/sellers/<int:seller_id>/reject', methods=['POST'])
def admin_reject_seller_api(seller_id):
    admin, err = _require_role('admin')
    if err is not None:
        return err

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE sellers SET status='rejected' WHERE id=%s", (seller_id,))
        if cur.rowcount == 0:
            return api_error('Seller not found.', status_code=404)
        conn.commit()
        return api_success('Seller rejected.')
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return api_error('Unable to reject seller.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/admin/riders/<int:rider_id>/approve', methods=['POST'])
def admin_approve_rider_api(rider_id):
    admin, err = _require_role('admin')
    if err is not None:
        return err

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE riders SET status='approved' WHERE id=%s", (rider_id,))
        if cur.rowcount == 0:
            return api_error('Rider not found.', status_code=404)
        conn.commit()
        return api_success('Rider approved.')
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return api_error('Unable to approve rider.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/admin/riders/<int:rider_id>/reject', methods=['POST'])
def admin_reject_rider_api(rider_id):
    admin, err = _require_role('admin')
    if err is not None:
        return err

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE riders SET status='rejected' WHERE id=%s", (rider_id,))
        if cur.rowcount == 0:
            return api_error('Rider not found.', status_code=404)
        conn.commit()
        return api_success('Rider rejected.')
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return api_error('Unable to reject rider.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass


@mobile_api_bp.route('/admin/commissions', methods=['GET'])
def admin_commissions_api():
    admin, err = _require_role('admin')
    if err is not None:
        return err

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            """
            SELECT
                COALESCE(SUM(o.total), 0) AS total_sales
            FROM orders o
            WHERE LOWER(COALESCE(o.delivery_status::text,'')) <> 'cancelled'
            """,
        )
        total_sales = float((cur.fetchone() or {}).get('total_sales') or 0)
        total_commission = total_sales * 0.1

        cur.execute(
            """
            SELECT
                s.id AS seller_id,
                s.name AS seller_name,
                s.shop_name,
                COUNT(o.id) AS order_count,
                COALESCE(SUM(o.total), 0) AS total_sales
            FROM orders o
            LEFT JOIN sellers s ON o.seller_id = s.id
            WHERE LOWER(COALESCE(o.delivery_status::text,'')) <> 'cancelled'
            GROUP BY s.id, s.name, s.shop_name
            ORDER BY total_sales DESC
            """,
        )
        by_seller = cur.fetchall() or []
        for r in by_seller:
            ts = float(r.get('total_sales') or 0)
            r['total_sales'] = ts
            r['total_commission'] = ts * 0.1

        cur.execute(
            """
            SELECT
                o.id AS order_id,
                o.seller_id,
                COALESCE(o.total, 0) AS total,
                o.order_date,
                o.delivery_status
            FROM orders o
            WHERE LOWER(COALESCE(o.delivery_status::text,'')) <> 'cancelled'
            ORDER BY o.order_date DESC
            LIMIT 300
            """,
        )
        by_order = cur.fetchall() or []
        for r in by_order:
            t = float(r.get('total') or 0)
            r['total'] = t
            r['commission'] = t * 0.1
            r['order_date'] = _iso(r.get('order_date'))

        return api_success(
            'Commissions fetched.',
            data={
                'total_commission': total_commission,
                'by_seller': by_seller,
                'by_order': by_order,
            },
        )
    except Exception:
        return api_error('Unable to fetch commissions.', status_code=500)
    finally:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass
