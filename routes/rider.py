from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from database import get_db_connection
from utils import verify_password
import psycopg2.extras
from datetime import datetime
import os
from werkzeug.utils import secure_filename

rider_bp = Blueprint('rider', __name__)

@rider_bp.route('/rider_login', methods=['GET', 'POST'])
def rider_login():
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip()
        contact = (request.form.get('contact') or '').strip()
        password = request.form.get('password') or ''
        
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute("ALTER TABLE riders ADD COLUMN IF NOT EXISTS email VARCHAR(100) DEFAULT NULL")
            conn.commit()
        except Exception:
            conn.rollback()

        if contact:
            cur.execute("SELECT * FROM riders WHERE contact=%s", (contact,))
        else:
            cur.execute("SELECT * FROM riders WHERE LOWER(email)=LOWER(%s)", (email,))
        rider = cur.fetchone()
        cur.close()
        conn.close()
        
        if rider:
            password_ok, _ = verify_password(rider['password'], password)
            if password_ok:
                if rider['status'] != 'approved':
                    flash('Your rider account is pending approval.', 'warning')
                    return render_template('rider_login.html')
                
                session['rider_id'] = rider['id']
                session['rider_name'] = rider['name']
                session['role'] = 'rider'
                return redirect(url_for('rider.rider_dashboard'))
            else:
                flash('Invalid email or password.', 'error')
        else:
            flash('Invalid email or password.', 'error')
            
    return render_template('rider_login.html')

@rider_bp.route('/rider_dashboard')
def rider_dashboard():
    if 'rider_id' not in session:
        return redirect(url_for('rider.rider_login'))
        
    rider_id = session['rider_id']
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        cur.execute("ALTER TABLE sellers ADD COLUMN IF NOT EXISTS contact VARCHAR(20) DEFAULT NULL")
        conn.commit()
    except Exception:
        conn.rollback()

    cur.execute(
        """
        SELECT
            o.*,
            p.name AS product_name,
            p.image AS product_image,
            s.shop_name,
            s.name AS seller_name,
            COALESCE(s.contact, s.email) AS seller_contact,
            COALESCE(o.pickup_address, s.address) AS pickup_address,
            u.name AS customer_name,
            u.email AS customer_email,
            COALESCE(o.customer_contact, NULL) AS customer_contact,
            COALESCE(o.delivery_address, u.address) AS delivery_address
        FROM orders o
        JOIN products p ON o.product_id = p.id
        JOIN sellers s ON p.seller_id = s.id
        JOIN users u ON o.user_id = u.id
        WHERE (o.rider_id IS NULL) AND (LOWER(COALESCE(o.delivery_status::text,'')) = 'pending')
        ORDER BY o.order_date DESC
        """,
    )
    pending_orders = cur.fetchall() or []

    cur.execute(
        """
        SELECT
            o.*,
            p.name AS product_name,
            p.image AS product_image,
            s.shop_name,
            s.name AS seller_name,
            COALESCE(s.contact, s.email) AS seller_contact,
            COALESCE(o.pickup_address, s.address) AS pickup_address,
            u.name AS customer_name,
            u.email AS customer_email,
            COALESCE(o.customer_contact, NULL) AS customer_contact,
            COALESCE(o.delivery_address, u.address) AS delivery_address
        FROM orders o
        JOIN products p ON o.product_id = p.id
        JOIN sellers s ON p.seller_id = s.id
        JOIN users u ON o.user_id = u.id
        WHERE o.rider_id = %s
        ORDER BY o.order_date DESC
        """,
        (rider_id,),
    )
    rider_orders = cur.fetchall() or []

    deliveries_pending = []
    deliveries_in_progress = []
    deliveries_delivered = []
    for d in rider_orders:
        status = (d.get('delivery_status') or '').lower()
        if status == 'delivered':
            deliveries_delivered.append(d)
        elif status in ('assigned', 'picked_up', 'in_transit'):
            deliveries_in_progress.append(d)
        else:
            deliveries_pending.append(d)

    pending_count = len(deliveries_pending)
    in_progress_count = len(deliveries_in_progress)
    delivered_count = len(deliveries_delivered)
    
    cur.close()
    conn.close()
    return render_template(
        'rider_dashboard.html',
        pending_orders=pending_orders,
        deliveries_pending=deliveries_pending,
        deliveries_in_progress=deliveries_in_progress,
        deliveries_delivered=deliveries_delivered,
        pending_count=pending_count,
        in_progress_count=in_progress_count,
        delivered_count=delivered_count,
    )


@rider_bp.route('/accept_order', methods=['POST'])
def accept_order():
    if 'rider_id' not in session:
        return redirect(url_for('rider.rider_login'))

    order_id = request.args.get('order_id', type=int)
    if not order_id:
        flash('Order ID is required.', 'error')
        return redirect(url_for('rider.rider_dashboard'))

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            UPDATE orders
            SET rider_id=%s, delivery_status='assigned', assigned_at=%s
            WHERE id=%s AND rider_id IS NULL AND LOWER(COALESCE(delivery_status::text,''))='pending'
            """,
            (session['rider_id'], datetime.utcnow(), order_id),
        )
        if cur.rowcount == 0:
            flash('Order is no longer available.', 'error')
            return redirect(url_for('rider.rider_dashboard'))
        conn.commit()
        flash('Order accepted.', 'success')
    except Exception:
        conn.rollback()
        flash('Unable to accept order.', 'error')
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('rider.rider_dashboard'))


@rider_bp.route('/update_delivery_status', methods=['POST'])
def update_delivery_status():
    if 'rider_id' not in session:
        return redirect(url_for('rider.rider_login'))

    order_id = request.args.get('order_id', type=int)
    new_status = (
        request.form.get('delivery_status')
        or request.form.get('status')
        or ''
    ).strip()
    if not order_id or not new_status:
        flash('Order ID and status are required.', 'error')
        return redirect(url_for('rider.rider_dashboard'))

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if new_status == 'delivered':
            cur.execute(
                "UPDATE orders SET delivery_status=%s, delivered_at=%s WHERE id=%s AND rider_id=%s",
                (new_status, datetime.utcnow(), order_id, session['rider_id']),
            )
        else:
            cur.execute(
                "UPDATE orders SET delivery_status=%s WHERE id=%s AND rider_id=%s",
                (new_status, order_id, session['rider_id']),
            )
        conn.commit()
        flash('Delivery status updated.', 'success')
    except Exception:
        conn.rollback()
        flash('Unable to update delivery status.', 'error')
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('rider.rider_dashboard'))


@rider_bp.route('/rider/update_status/<int:order_id>', methods=['POST'])
def upload_delivery_proof(order_id):
    if 'rider_id' not in session:
        return redirect(url_for('rider.rider_login'))

    file = request.files.get('delivery_proof')
    if not file or not file.filename:
        flash('Please upload a proof of delivery photo.', 'error')
        return redirect(url_for('rider.rider_dashboard'))

    filename = secure_filename(file.filename)
    if not filename:
        flash('Invalid file.', 'error')
        return redirect(url_for('rider.rider_dashboard'))

    static_root = os.path.join(os.path.dirname(__file__), '..', 'static')
    upload_dir = os.path.join(static_root, 'uploads', 'delivery_proof')
    os.makedirs(upload_dir, exist_ok=True)

    saved_name = f"{session['rider_id']}_{order_id}_{int(datetime.utcnow().timestamp())}_{filename}"
    save_path = os.path.join(upload_dir, saved_name)
    file.save(save_path)
    rel_path = f"uploads/delivery_proof/{saved_name}"

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            UPDATE orders
            SET delivery_status='delivered', delivered_at=%s, delivery_proof=%s
            WHERE id=%s AND rider_id=%s
            """,
            (datetime.utcnow(), rel_path, order_id, session['rider_id']),
        )
        if cur.rowcount == 0:
            flash('Order not found.', 'error')
            return redirect(url_for('rider.rider_dashboard'))
        conn.commit()
        flash('Delivery confirmed.', 'success')
    except Exception:
        conn.rollback()
        flash('Unable to confirm delivery.', 'error')
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('rider.rider_dashboard'))


@rider_bp.route('/rider_commissions')
def rider_commissions():
    if 'rider_id' not in session:
        return redirect(url_for('rider.rider_login'))

    rider_id = session['rider_id']
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        # Get commission statistics
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
        stats = cur.fetchone() or {}
        total_commission = float(stats.get('total_commission') or 0)
        total_delivered_orders = int(stats.get('total_delivered_orders') or 0)
        total_items_delivered = int(stats.get('total_items_delivered') or 0)
        avg_commission = total_commission / max(total_delivered_orders, 1)

        # Get detailed commission breakdown
        cur.execute(
            """
            SELECT
                o.id AS order_id,
                o.quantity,
                o.total,
                o.delivered_at,
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
        commissions = cur.fetchall() or []
        
        for commission in commissions:
            total = float(commission.get('total') or 0)
            qty = int(commission.get('quantity') or 1)
            commission['commission'] = total * 0.05
            commission['commission_per_item'] = (total * 0.05) / max(qty, 1)

        cur.close()
        conn.close()

        return render_template(
            'rider_commissions.html',
            total_commission=total_commission,
            total_delivered_orders=total_delivered_orders,
            total_items_delivered=total_items_delivered,
            avg_commission=avg_commission,
            commissions=commissions,
        )
    except Exception as e:
        print(f"Error loading rider commissions: {e}")
        cur.close()
        conn.close()
        flash('Unable to load commissions.', 'error')
        return redirect(url_for('rider.rider_dashboard'))
    file.save(save_path)
    rel_path = f"uploads/delivery_proof/{saved_name}"

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            UPDATE orders
            SET delivery_status='delivered', delivered_at=%s, delivery_proof=%s
            WHERE id=%s AND rider_id=%s
            """,
            (datetime.utcnow(), rel_path, order_id, session['rider_id']),
        )
        if cur.rowcount == 0:
            flash('Order not found.', 'error')
            return redirect(url_for('rider.rider_dashboard'))
        conn.commit()
        flash('Delivery confirmed.', 'success')
    except Exception:
        conn.rollback()
        flash('Unable to confirm delivery.', 'error')
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('rider.rider_dashboard'))
