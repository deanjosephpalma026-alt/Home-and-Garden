from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from database import get_db_connection, add_column_if_missing
from utils import verify_password
import psycopg2.extras
import os
import uuid
from werkzeug.utils import secure_filename

seller_bp = Blueprint('seller', __name__)

@seller_bp.route('/seller_login', methods=['GET', 'POST'])
def seller_login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM sellers WHERE email=%s", (email,))
        seller = cur.fetchone()
        cur.close()
        conn.close()
        
        if seller:
            password_ok, _ = verify_password(seller['password'], password)
            if password_ok:
                if seller['status'] != 'approved':
                    flash('Your seller account is pending approval.', 'warning')
                    return render_template('seller_login.html')
                
                session['seller_id'] = seller['id']
                session['seller_name'] = seller['name']
                session['role'] = 'seller'
                return redirect(url_for('seller.seller_dashboard'))
            else:
                flash('Invalid email or password.', 'error')
        else:
            flash('Invalid email or password.', 'error')
            
    return render_template('seller_login.html')

@seller_bp.route('/seller_dashboard')
def seller_dashboard():
    if 'seller_id' not in session:
        return redirect(url_for('seller.seller_login'))
        
    seller_id = session['seller_id']
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    cur.execute("SELECT * FROM products WHERE seller_id = %s", (seller_id,))
    products = cur.fetchall()
    
    cur.execute("""
        SELECT
            o.*,
            p.name AS product_name,
            p.image AS product_image,
            u.name AS user_name,
            u.email AS user_email,
            u.address AS address
        FROM orders o
        JOIN products p ON o.product_id = p.id
        JOIN users u ON o.user_id = u.id
        WHERE p.seller_id = %s
        ORDER BY o.order_date DESC
    """, (seller_id,))
    orders = cur.fetchall() or []

    pending_count = 0
    for o in orders:
        if (o.get('payment_status') or '').lower() == 'pending':
            pending_count += 1

    refund_requests = []
    try:
        cur.execute(
            """
            SELECT rr.*, p.name AS product_name, p.image AS product_image,
                   u.name AS user_name, u.email AS user_email,
                   o.id AS order_id
            FROM refund_requests rr
            JOIN orders o ON rr.order_id = o.id
            JOIN products p ON o.product_id = p.id
            JOIN users u ON o.user_id = u.id
            WHERE o.seller_id = %s
            ORDER BY rr.created_at DESC
            """,
            (seller_id,),
        )
        refund_requests = cur.fetchall() or []
    except Exception:
        refund_requests = []
    
    cur.close()
    conn.close()
    return render_template(
        'seller_dashboard.html',
        products=products,
        orders=orders,
        pending_count=pending_count,
        refund_requests=refund_requests,
    )

@seller_bp.route('/add_product', methods=['GET', 'POST'])
def add_product():
    if 'seller_id' not in session:
        return redirect(url_for('seller.seller_login'))
        
    if request.method == 'POST':
        name = request.form['name']
        description = request.form['description']
        price = float(request.form['price'])
        stock = int(request.form['stock'])
        category = request.form['category']
        size_options = (request.form.get('size_options') or '').strip() or None
        color_options = (request.form.get('color_options') or '').strip() or None
        
        image_file = request.files.get('image')
        image_path = 'uploads/products/default.jpg'
        
        if image_file and image_file.filename:
            filename = secure_filename(f"{uuid.uuid4().hex}_{image_file.filename}")
            image_dir = os.path.join(current_app.static_folder, 'uploads', 'products')
            os.makedirs(image_dir, exist_ok=True)
            image_file.save(os.path.join(image_dir, filename))
            image_path = f"uploads/products/{filename}"
            
        conn = get_db_connection()
        cur = conn.cursor()
        add_column_if_missing(conn, 'products', 'size_options', 'TEXT DEFAULT NULL')
        add_column_if_missing(conn, 'products', 'color_options', 'TEXT DEFAULT NULL')
        cur.execute("""
            INSERT INTO products (name, description, price, stock, category, image, seller_id, size_options, color_options)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (name, description, price, stock, category, image_path, session['seller_id'], size_options, color_options))
        conn.commit()
        cur.close()
        conn.close()
        
        flash('Product added successfully!', 'success')
        return redirect(url_for('seller.seller_dashboard'))
        
    return render_template('add_product.html')


@seller_bp.route('/seller_sales')
def seller_sales():
    if 'seller_id' not in session:
        return redirect(url_for('seller.seller_login'))

    seller_id = session['seller_id']
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        where = ["o.seller_id = %s"]
        params = [seller_id]
        period = 'day'
        period_label = 'Daily'

        if start_date:
            where.append("o.order_date::date >= %s::date")
            params.append(start_date)
            period = 'custom'
            period_label = 'Custom'
        if end_date:
            where.append("o.order_date::date <= %s::date")
            params.append(end_date)
            period = 'custom'
            period_label = 'Custom'

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
                    'date': row.get('date'),
                    'order_count': oc,
                    'total_sales': ts,
                    'seller_earnings': ts * 0.9,
                    'admin_commission': ts * 0.1,
                }
            )

        total_earnings = total_sales * 0.9
        total_commission = total_sales * 0.1

        return render_template(
            'seller_sales.html',
            sales_data=sales_data,
            total_orders=total_orders,
            total_sales=total_sales,
            total_earnings=total_earnings,
            total_commission=total_commission,
            start_date=start_date,
            end_date=end_date,
            period=period,
            period_label=period_label,
        )
    finally:
        cur.close()
        conn.close()


@seller_bp.route('/seller_profile', methods=['GET', 'POST'])
def seller_profile():
    if 'seller_id' not in session:
        return redirect(url_for('seller.seller_login'))

    seller_id = session['seller_id']
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    if request.method == 'POST':
        name = request.form.get('name', '')
        shop_name = request.form.get('shop_name', '')
        address = request.form.get('address', '')
        cur.execute(
            "UPDATE sellers SET name=%s, shop_name=%s, address=%s WHERE id=%s",
            (name, shop_name, address, seller_id),
        )
        conn.commit()
        session['seller_name'] = name or session.get('seller_name')
        flash('Profile updated successfully!', 'success')

    cur.execute("SELECT * FROM sellers WHERE id=%s", (seller_id,))
    seller = cur.fetchone()
    cur.close()
    conn.close()

    return render_template('seller_profile.html', seller=seller)


@seller_bp.route('/edit_product')
def edit_product():
    if 'seller_id' not in session:
        return redirect(url_for('seller.seller_login'))

    product_id = request.args.get('product_id', type=int)
    if not product_id:
        flash('Product not found.', 'error')
        return redirect(url_for('seller.seller_dashboard'))

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT * FROM products WHERE id=%s AND seller_id=%s",
        (product_id, session['seller_id']),
    )
    product = cur.fetchone()
    cur.close()
    conn.close()

    if not product:
        flash('Product not found.', 'error')
        return redirect(url_for('seller.seller_dashboard'))

    return render_template('edit_product.html', product=product)


@seller_bp.route('/update_product', methods=['POST'])
def update_product():
    if 'seller_id' not in session:
        return redirect(url_for('seller.seller_login'))

    product_id = request.args.get('product_id', type=int)
    if not product_id:
        flash('Product not found.', 'error')
        return redirect(url_for('seller.seller_dashboard'))

    name = request.form.get('name', '')
    description = request.form.get('description', '')
    price = float(request.form.get('price') or 0)
    stock = int(request.form.get('stock') or 0)
    category = request.form.get('category', '')
    size_options = (request.form.get('size_options') or '').strip() or None
    color_options = (request.form.get('color_options') or '').strip() or None

    image_file = request.files.get('image')
    image_path = None
    if image_file and image_file.filename:
        filename = secure_filename(f"{uuid.uuid4().hex}_{image_file.filename}")
        image_dir = os.path.join(current_app.static_folder, 'uploads', 'products')
        os.makedirs(image_dir, exist_ok=True)
        image_file.save(os.path.join(image_dir, filename))
        image_path = f"uploads/products/{filename}"

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        add_column_if_missing(conn, 'products', 'size_options', 'TEXT DEFAULT NULL')
        add_column_if_missing(conn, 'products', 'color_options', 'TEXT DEFAULT NULL')
        if image_path:
            cur.execute(
                """
                UPDATE products
                SET name=%s, description=%s, price=%s, stock=%s, category=%s, image=%s, size_options=%s, color_options=%s
                WHERE id=%s AND seller_id=%s
                """,
                (name, description, price, stock, category, image_path, size_options, color_options, product_id, session['seller_id']),
            )
        else:
            cur.execute(
                """
                UPDATE products
                SET name=%s, description=%s, price=%s, stock=%s, category=%s, size_options=%s, color_options=%s
                WHERE id=%s AND seller_id=%s
                """,
                (name, description, price, stock, category, size_options, color_options, product_id, session['seller_id']),
            )
        conn.commit()
        flash('Product updated successfully!', 'success')
    except Exception:
        conn.rollback()
        flash('Unable to update product.', 'error')
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('seller.edit_product', product_id=product_id))


@seller_bp.route('/delete_product', methods=['POST'])
def delete_product():
    if 'seller_id' not in session:
        return redirect(url_for('seller.seller_login'))

    product_id = request.args.get('product_id', type=int)
    if not product_id:
        flash('Product not found.', 'error')
        return redirect(url_for('seller.seller_dashboard'))

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "DELETE FROM products WHERE id=%s AND seller_id=%s",
            (product_id, session['seller_id']),
        )
        conn.commit()
        flash('Product deleted.', 'success')
    except Exception:
        conn.rollback()
        flash('Unable to delete product.', 'error')
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('seller.seller_dashboard'))


@seller_bp.route('/confirm_order', methods=['POST'])
def confirm_order():
    if 'seller_id' not in session:
        return redirect(url_for('seller.seller_login'))

    order_id = request.args.get('order_id', type=int)
    if not order_id:
        flash('Order not found.', 'error')
        return redirect(url_for('seller.seller_dashboard'))

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            UPDATE orders
            SET payment_status='Confirmed', seller_confirmed=1
            WHERE id=%s AND seller_id=%s
            """,
            (order_id, session['seller_id']),
        )
        conn.commit()
        flash('Order confirmed.', 'success')
    except Exception:
        conn.rollback()
        flash('Unable to confirm order.', 'error')
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('seller.seller_dashboard'))


@seller_bp.route('/approve_refund', methods=['POST'])
def approve_refund():
    if 'seller_id' not in session:
        return redirect(url_for('seller.seller_login'))

    refund_id = request.args.get('refund_id', type=int)
    if not refund_id:
        flash('Refund not found.', 'error')
        return redirect(url_for('seller.seller_dashboard'))

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE refund_requests SET status='approved' WHERE id=%s",
            (refund_id,),
        )
        conn.commit()
        flash('Refund approved.', 'success')
    except Exception:
        conn.rollback()
        flash('Unable to approve refund.', 'error')
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('seller.seller_dashboard'))


@seller_bp.route('/reject_refund', methods=['POST'])
def reject_refund():
    if 'seller_id' not in session:
        return redirect(url_for('seller.seller_login'))

    refund_id = request.args.get('refund_id', type=int)
    if not refund_id:
        flash('Refund not found.', 'error')
        return redirect(url_for('seller.seller_dashboard'))

    reason = (request.form.get('rejection_reason') or '').strip()

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE refund_requests SET status='rejected', rejection_reason=%s WHERE id=%s",
            (reason, refund_id),
        )
        conn.commit()
        flash('Refund rejected.', 'success')
    except Exception:
        conn.rollback()
        flash('Unable to reject refund.', 'error')
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('seller.seller_dashboard'))
