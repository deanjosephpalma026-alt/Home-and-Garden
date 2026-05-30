from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from database import get_db_connection, pg_column_exists
import psycopg2.extras
import traceback
import logging

order_bp = Blueprint('order', __name__)

def _load_cart(cur, user_id):
    cur.execute(
        """
        SELECT
            c.id,
            c.product_id,
            c.quantity,
            c.subtotal,
            p.name,
            p.price,
            p.image,
            p.stock,
            p.seller_id
        FROM cart c
        JOIN products p ON c.product_id = p.id
        WHERE c.user_id = %s
        ORDER BY c.id DESC
        """,
        (user_id,),
    )
    rows = cur.fetchall() or []
    for row in rows:
        if row.get('subtotal') is None:
            row['subtotal'] = float(row.get('price') or 0) * int(row.get('quantity') or 0)
    return rows


@order_bp.route('/cart')
def cart():
    if 'id' not in session:
        flash('Please log in to view your cart.', 'error')
        return redirect(url_for('auth.login'))
    
    user_id = session['id']
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cart_items = _load_cart(cur, user_id)
        total = sum(float(item.get('subtotal') or 0) for item in cart_items)
        
        cur.close()
        conn.close()
        return render_template('cart.html', cart_items=cart_items, total=total)
    except Exception as e:
        print(f"Error loading cart: {e}")
        flash('Error loading cart. Please try again.', 'error')
        return redirect(url_for('main.home'))

@order_bp.route('/add_to_cart/<int:product_id>', methods=['POST'])
def add_to_cart(product_id):
    if 'id' not in session:
        flash('Please log in to add items to cart.', 'error')
        return redirect(url_for('auth.login'))
    
    user_id = session['id']
    quantity = int(request.form.get('quantity', 1))
    
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Check if product exists and has enough stock
        cur.execute(
            "SELECT id, price, stock FROM products WHERE id = %s",
            (product_id,),
        )
        product = cur.fetchone()
        
        if not product or product['stock'] < quantity:
            flash('Product out of stock or insufficient quantity.', 'error')
            cur.close()
            conn.close()
            return redirect(url_for('order.cart'))
            
        # Check if item already in cart
        cur.execute("SELECT id, quantity FROM cart WHERE user_id = %s AND product_id = %s", (user_id, product_id))
        item = cur.fetchone()
        price = float(product.get('price') or 0)
        
        if item:
            new_qty = int(item.get('quantity') or 0) + quantity
            new_subtotal = price * new_qty
            cur.execute(
                "UPDATE cart SET quantity=%s, subtotal=%s WHERE id=%s",
                (new_qty, new_subtotal, item['id']),
            )
        else:
            subtotal = price * quantity
            cur.execute(
                "INSERT INTO cart (user_id, product_id, quantity, subtotal) VALUES (%s, %s, %s, %s)",
                (user_id, product_id, quantity, subtotal),
            )
            
        conn.commit()
        cur.close()
        conn.close()
        flash('Item added to cart!', 'success')
    except Exception as e:
        print(f"Error adding to cart: {e}")
        flash('Error adding to cart. Please try again.', 'error')
        
    return redirect(url_for('order.cart'))


@order_bp.route('/update_cart/<int:cart_id>', methods=['POST'])
def update_cart(cart_id):
    if 'id' not in session:
        return jsonify({'success': False, 'message': 'Please log in first.'}), 401

    payload = request.get_json(silent=True) or {}
    try:
        quantity = int(payload.get('quantity') or 1)
    except Exception:
        return jsonify({'success': False, 'message': 'Invalid quantity.'}), 400

    if quantity < 1:
        return jsonify({'success': False, 'message': 'Quantity must be at least 1.'}), 400

    user_id = session['id']
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute(
            """
            SELECT c.id, c.product_id, p.price, p.stock
            FROM cart c
            JOIN products p ON c.product_id = p.id
            WHERE c.id=%s AND c.user_id=%s
            """,
            (cart_id, user_id),
        )
        row = cur.fetchone()
        if not row:
            return jsonify({'success': False, 'message': 'Cart item not found.'}), 404

        if int(row.get('stock') or 0) < quantity:
            return jsonify({'success': False, 'message': 'Insufficient stock.'}), 400

        subtotal = float(row.get('price') or 0) * quantity
        cur.execute(
            "UPDATE cart SET quantity=%s, subtotal=%s WHERE id=%s AND user_id=%s",
            (quantity, subtotal, cart_id, user_id),
        )
        conn.commit()
        return jsonify(
            {
                'success': True,
                'message': 'Cart updated.',
                'cart_id': cart_id,
                'quantity': quantity,
                'subtotal': subtotal,
            }
        )
    except Exception as e:
        conn.rollback()
        print(f"Error updating cart: {e}")
        return jsonify({'success': False, 'message': 'Unable to update cart.'}), 500
    finally:
        cur.close()
        conn.close()


@order_bp.route('/remove_from_cart', methods=['POST'])
def remove_from_cart():
    if 'id' not in session:
        flash('Please log in to edit your cart.', 'error')
        return redirect(url_for('auth.login'))

    cart_id = request.args.get('cart_id', type=int) or request.form.get('cart_id', type=int)
    if not cart_id:
        flash('Cart item not found.', 'error')
        return redirect(url_for('order.cart'))

    user_id = session['id']
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM cart WHERE id=%s AND user_id=%s", (cart_id, user_id))
        if cur.rowcount == 0:
            flash('Cart item not found.', 'error')
        else:
            flash('Item removed from cart.', 'success')
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error removing cart item: {e}")
        flash('Unable to remove item from cart.', 'error')
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('order.cart'))

@order_bp.route('/checkout', methods=['GET', 'POST'])
def checkout():
    if 'id' not in session:
        flash('Please log in to checkout.', 'error')
        return redirect(url_for('auth.login'))
        
    user_id = session['id']
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    if request.method == 'POST':
        payment_method = (request.form.get('payment_method') or 'Cash on Delivery').strip()
        try:
            cur.execute("SELECT address FROM users WHERE id=%s", (user_id,))
            user = cur.fetchone() or {}
            user_address = user.get('address')
            if not user_address:
                flash('No delivery address found. Please update your profile.', 'error')
                return redirect(url_for('user.profile'))

            items = _load_cart(cur, user_id)
            if not items:
                flash('Your cart is empty.', 'error')
                return redirect(url_for('main.home'))

            product_ids = [row['product_id'] for row in items]
            cur.execute(
                """
                SELECT id, stock, seller_id
                FROM products
                WHERE id = ANY(%s)
                """,
                (product_ids,),
            )
            products = {row['id']: row for row in (cur.fetchall() or [])}

            for item in items:
                pid = item['product_id']
                qty = int(item.get('quantity') or 0)
                p = products.get(pid) or {}
                if int(p.get('stock') or 0) < qty:
                    flash('Insufficient stock for one or more items.', 'error')
                    return redirect(url_for('order.cart'))

            seller_ids = list({(products.get(row['product_id']) or {}).get('seller_id') for row in items})
            seller_ids = [sid for sid in seller_ids if sid]
            sellers_by_id = {}
            if seller_ids:
                cur.execute(
                    "SELECT id, address FROM sellers WHERE id = ANY(%s)",
                    (seller_ids,),
                )
                sellers_by_id = {row['id']: row for row in (cur.fetchall() or [])}

            for item in items:
                pid = item['product_id']
                qty = int(item.get('quantity') or 0)
                price = float(item.get('price') or 0)
                total = price * qty
                seller_id = (products.get(pid) or {}).get('seller_id')
                pickup_address = (sellers_by_id.get(seller_id) or {}).get('address')

                cur.execute(
                    """
                    INSERT INTO orders (
                        user_id, product_id, quantity, total, payment_method, payment_status,
                        address, seller_id, delivery_status, pickup_address, delivery_address
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s, %s)
                    """,
                    (
                        user_id,
                        pid,
                        qty,
                        total,
                        payment_method,
                        'Pending',
                        user_address,
                        seller_id,
                        pickup_address,
                        user_address,
                    ),
                )

                cur.execute("UPDATE products SET stock = stock - %s WHERE id=%s", (qty, pid))

            cur.execute("DELETE FROM cart WHERE user_id=%s", (user_id,))
            conn.commit()
            flash('Order placed successfully!', 'success')
            # If this request came from AJAX (fetch), return JSON so client-side JS can handle it
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 'application/json' in (request.headers.get('Accept') or ''):
                return jsonify({'success': True, 'message': 'Order placed successfully.'})
            return redirect(url_for('order.my_orders'))
        except Exception as e:
            conn.rollback()
            logging.exception('Checkout error')
            # If AJAX, return JSON error
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 'application/json' in (request.headers.get('Accept') or ''):
                return jsonify({'success': False, 'message': 'Checkout failed. Please try again.'}), 500
            flash('Checkout failed. Please try again.', 'error')
            return redirect(url_for('order.checkout'))
        
    cart_items = _load_cart(cur, user_id)
    
    if not cart_items:
        flash('Your cart is empty.', 'error')
        cur.close()
        conn.close()
        return redirect(url_for('main.home'))
        
    total = sum(float(item.get('subtotal') or 0) for item in cart_items)

    cur.execute("SELECT address FROM users WHERE id=%s", (user_id,))
    user = cur.fetchone() or {}
    user_address = user.get('address')

    seller_ids = list({row.get('seller_id') for row in cart_items if row.get('seller_id')})
    sellers_payment_info = {}
    if seller_ids:
        cur.execute(
            """
            SELECT id, shop_name, gcash_number, paymaya_number
            FROM sellers
            WHERE id = ANY(%s)
            """,
            (seller_ids,),
        )
        sellers_payment_info = {row['id']: row for row in (cur.fetchall() or [])}
    
    cur.close()
    conn.close()
    return render_template(
        'checkout.html',
        cart_items=cart_items,
        total_amount=total,
        user_address=user_address,
        sellers_payment_info=sellers_payment_info,
    )


@order_bp.route('/place_order', methods=['POST'])
def place_order():
    return checkout()

@order_bp.route('/my_orders')
def my_orders():
    if 'id' not in session:
        flash('Please log in to view your orders.', 'error')
        return redirect(url_for('auth.login'))
        
    user_id = session['id']
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT o.*, p.name as product_name, p.image as product_image, s.shop_name
            FROM orders o
            JOIN products p ON o.product_id = p.id
            JOIN sellers s ON p.seller_id = s.id
            WHERE o.user_id = %s
            ORDER BY o.order_date DESC
        """, (user_id,))
        orders = cur.fetchall() or []
        cur.close()
        conn.close()
        
        # Categorize orders by status
        to_pay = []
        to_ship = []
        to_receive = []
        completed = []
        refunded = []
        cancelled = []
        
        for order in orders:
            payment_status = (order.get('payment_status') or '').lower()
            delivery_status = (order.get('delivery_status') or '').lower()
            
            if delivery_status == 'cancelled':
                cancelled.append(order)
            elif payment_status == 'refunded' or delivery_status == 'refunded':
                refunded.append(order)
            elif payment_status == 'pending' or (payment_status == 'confirmed' and delivery_status in ['pending', 'assigned']):
                to_pay.append(order)
            elif delivery_status in ['pending', 'assigned', 'picked_up']:
                to_ship.append(order)
            elif delivery_status == 'in_transit':
                to_receive.append(order)
            elif delivery_status == 'delivered':
                completed.append(order)
            else:
                to_pay.append(order)  # default category
        
        return render_template('my_orders.html', 
                             orders=orders,
                             to_pay=to_pay,
                             to_ship=to_ship,
                             to_receive=to_receive,
                             completed=completed,
                             refunded=refunded,
                             cancelled=cancelled)
    except Exception as e:
        print(f"Error loading orders: {e}")
        flash('Error loading orders.', 'error')
        return redirect(url_for('main.home'))

@order_bp.route('/delete_order/<int:order_id>', methods=['POST'])
def delete_order(order_id):
    if 'id' not in session:
        flash('Please log in first!', 'error')
        return redirect(url_for('auth.login'))
        
    user_id = session['id']
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    try:
        cur.execute("""
            SELECT o.*, p.stock
            FROM orders o
            JOIN products p ON o.product_id = p.id
            WHERE o.id = %s AND o.user_id = %s
        """, (order_id, user_id))
        order = cur.fetchone()
        
        if not order:
            flash('Order not found or unauthorized.', 'error')
            return redirect(url_for('order.my_orders'))
            
        if order['delivery_status'] not in ['pending', 'cancelled']:
            flash('Cannot cancel order in this status.', 'error')
            return redirect(url_for('order.my_orders'))
            
        # Restore stock if not confirmed
        if not order.get('seller_confirmed'):
            cur.execute("UPDATE products SET stock = stock + %s WHERE id = %s", (order['quantity'], order['product_id']))
            
        cur.execute("UPDATE orders SET delivery_status = 'cancelled', payment_status = 'Cancelled' WHERE id = %s", (order_id,))
        conn.commit()
        flash('Order cancelled successfully.', 'success')
    except Exception as e:
        print(f"Error cancelling order: {e}")
        conn.rollback()
        flash('Error cancelling order.', 'error')
    finally:
        cur.close()
        conn.close()
        
    return redirect(url_for('order.my_orders'))
