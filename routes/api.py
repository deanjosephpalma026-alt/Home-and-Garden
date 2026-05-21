from flask import Blueprint, request, jsonify
from database import get_db_connection
from utils import api_success, api_error, _serialize_product_row, _serialize_cart_item_row, _extract_bearer_token, _current_supabase_email_from_bearer, _mobile_user_from_bearer
import psycopg2.extras

api_bp = Blueprint('api', __name__)

@api_bp.route('/products')
def get_products():
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT p.*, s.shop_name, s.name as seller_name
            FROM products p
            JOIN sellers s ON p.seller_id = s.id
            WHERE s.status = 'approved'
        """)
        products = cur.fetchall()
        cur.close()
        conn.close()
        
        serialized = [_serialize_product_row(p) for p in products]
        return api_success('Products fetched successfully.', data={'products': serialized})
    except Exception as e:
        print(f"API Error fetching products: {e}")
        return api_error('Unable to fetch products.', status_code=500)

@api_bp.route('/products/<int:product_id>')
def get_product(product_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT p.*, s.shop_name, s.name as seller_name
            FROM products p
            JOIN sellers s ON p.seller_id = s.id
            WHERE p.id = %s
        """, (product_id,))
        product = cur.fetchone()
        cur.close()
        conn.close()
        
        if not product:
            return api_error('Product not found.', status_code=404)
            
        return api_success('Product fetched successfully.', data={'product': _serialize_product_row(product)})
    except Exception as e:
        print(f"API Error fetching product {product_id}: {e}")
        return api_error('Unable to fetch product.', status_code=500)

@api_bp.route('/user/profile')
def get_user_profile():
    user, error = _mobile_user_from_bearer()
    if error:
        return api_error(error, status_code=401)
        
    return api_success('User profile fetched successfully.', data={'user': user})

@api_bp.route('/cart')
def get_cart():
    user, error = _mobile_user_from_bearer()
    if error:
        return api_error(error, status_code=401)
        
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT c.*, p.name, p.price, p.image, s.shop_name
            FROM cart c
            JOIN products p ON c.product_id = p.id
            JOIN sellers s ON p.seller_id = s.id
            WHERE c.user_id = %s
        """, (user['id'],))
        cart_items = cur.fetchall()
        cur.close()
        conn.close()
        
        serialized = [_serialize_cart_item_row(item) for item in cart_items]
        total = sum(item['subtotal'] for item in serialized)
        
        return api_success('Cart fetched successfully.', data={
            'cart_items': serialized,
            'total_amount': total
        })
    except Exception as e:
        print(f"API Error fetching cart: {e}")
        return api_error('Unable to fetch cart.', status_code=500)

@api_bp.route('/cart/add', methods=['POST'])
def add_to_cart():
    user, error = _mobile_user_from_bearer()
    if error:
        return api_error(error, status_code=401)
        
    data = request.get_json()
    product_id = data.get('product_id')
    quantity = data.get('quantity', 1)
    
    if not product_id:
        return api_error('Product ID is required.')
        
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Check if product exists and has enough stock
        cur.execute("SELECT price, stock FROM products WHERE id = %s", (product_id,))
        product = cur.fetchone()
        if not product:
            cur.close()
            conn.close()
            return api_error('Product not found.', status_code=404)
            
        if product['stock'] < quantity:
            cur.close()
            conn.close()
            return api_error('Insufficient stock.')
            
        subtotal = float(product['price']) * quantity
        
        # Check if item already in cart
        cur.execute("SELECT id, quantity FROM cart WHERE user_id = %s AND product_id = %s", (user['id'], product_id))
        existing = cur.fetchone()
        
        if existing:
            new_qty = existing['quantity'] + quantity
            new_subtotal = float(product['price']) * new_qty
            cur.execute("UPDATE cart SET quantity = %s, subtotal = %s WHERE id = %s", (new_qty, new_subtotal, existing['id']))
        else:
            cur.execute("INSERT INTO cart (user_id, product_id, quantity, subtotal) VALUES (%s, %s, %s, %s)",
                       (user['id'], product_id, quantity, subtotal))
            
        conn.commit()
        cur.close()
        conn.close()
        return api_success('Item added to cart.')
    except Exception as e:
        print(f"API Error adding to cart: {e}")
        return api_error('Unable to add item to cart.', status_code=500)

@api_bp.route('/orders')
def get_orders():
    user, error = _mobile_user_from_bearer()
    if error:
        return api_error(error, status_code=401)
        
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        from utils import _fetch_mobile_orders, _order_group_payload
        orders = _fetch_mobile_orders(cur, user['id'])
        payload = _order_group_payload(orders)
        cur.close()
        conn.close()
        return api_success('Orders fetched successfully.', data=payload)
    except Exception as e:
        print(f"API Error fetching orders: {e}")
        return api_error('Unable to fetch orders.', status_code=500)

@api_bp.route('/notifications')
def get_notifications():
    user, error = _mobile_user_from_bearer()
    if error:
        return api_error(error, status_code=401)
        
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM user_notifications WHERE user_id = %s ORDER BY created_at DESC", (user['id'],))
        notifications = cur.fetchall()
        cur.close()
        conn.close()
        
        # Simple serialization for notifications
        serialized = []
        for n in notifications:
            serialized.append({
                'id': n['id'],
                'message': n['message'],
                'type': n.get('type'),
                'is_read': n.get('is_read', False),
                'created_at': n['created_at'].isoformat() if hasattr(n['created_at'], 'isoformat') else n['created_at']
            })
            
        return api_success('Notifications fetched successfully.', data={'notifications': serialized})
    except Exception as e:
        print(f"API Error fetching notifications: {e}")
        return api_error('Unable to fetch notifications.', status_code=500)
