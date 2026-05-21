from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from database import get_db_connection
import psycopg2.extras
from datetime import datetime


admin_bp = Blueprint('admin', __name__)

def _sanitize_rows(rows):
    sanitized = []
    for row in rows or []:
        if not isinstance(row, dict):
            sanitized.append(row)
            continue
        clean = dict(row)
        clean.pop('password', None)
        for k, v in list(clean.items()):
            if isinstance(v, datetime):
                clean[k] = v.isoformat()
        sanitized.append(clean)
    return sanitized


def _require_admin():
    role = session.get('role') or session.get('user_role')
    if role != 'admin':
        flash('Unauthorized access.', 'error')
        return False
    return True


@admin_bp.route('/admin_dashboard')
def admin_dashboard():
    if not _require_admin():
        return redirect(url_for('auth.login'))

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    total_commission = 0.0
    commissions_by_seller = []
    commissions_by_item = []
    try:
        cur.execute("SELECT * FROM sellers ORDER BY id DESC")
        sellers = _sanitize_rows(cur.fetchall() or [])
    except Exception:
        sellers = []

    try:
        cur.execute("SELECT * FROM users ORDER BY id DESC")
        users = _sanitize_rows(cur.fetchall() or [])
    except Exception:
        users = []

    try:
        cur.execute("SELECT * FROM riders ORDER BY id DESC")
        riders = _sanitize_rows(cur.fetchall() or [])
    except Exception:
        riders = []

    try:
        cur.execute(
            """
            SELECT COALESCE(SUM(COALESCE(admin_commission, total * 0.10, 0)), 0) AS total_commission
            FROM orders
            WHERE LOWER(COALESCE(delivery_status::text, '')) <> 'cancelled'
            """,
        )
        total_commission = float((cur.fetchone() or {}).get('total_commission') or 0)
    except Exception:
        total_commission = 0.0

    try:
        cur.execute(
            """
            SELECT
                s.id AS seller_id,
                s.name AS seller_name,
                s.shop_name AS shop_name,
                COUNT(o.id) AS order_count,
                COALESCE(SUM(o.total), 0) AS total_sales,
                COALESCE(SUM(COALESCE(o.admin_commission, o.total * 0.10, 0)), 0) AS total_commission
            FROM orders o
            LEFT JOIN sellers s ON o.seller_id = s.id
            WHERE LOWER(COALESCE(o.delivery_status::text, '')) <> 'cancelled'
            GROUP BY s.id, s.name, s.shop_name
            ORDER BY total_sales DESC
            """,
        )
        commissions_by_seller = cur.fetchall() or []
    except Exception:
        commissions_by_seller = []

    try:
        cur.execute(
            """
            SELECT
                o.id AS order_id,
                o.order_date,
                o.quantity,
                o.total,
                COALESCE(o.admin_commission, o.total * 0.10, 0) AS commission,
                p.name AS product_name,
                s.name AS seller_name,
                s.shop_name,
                u.name AS customer_name,
                COALESCE(r.name, '') AS rider_name,
                o.rider_id,
                o.delivery_status,
                o.delivery_proof
            FROM orders o
            LEFT JOIN products p ON o.product_id = p.id
            LEFT JOIN sellers s ON o.seller_id = s.id
            LEFT JOIN users u ON o.user_id = u.id
            LEFT JOIN riders r ON o.rider_id = r.id
            WHERE LOWER(COALESCE(o.delivery_status::text, '')) <> 'cancelled'
            ORDER BY o.order_date DESC
            LIMIT 300
            """,
        )
        commissions_by_item = cur.fetchall() or []
    except Exception:
        commissions_by_item = []

    cur.close()
    conn.close()

    return render_template(
        'admin_dashboard.html',
        sellers=sellers,
        users=users,
        riders=riders,
        total_commission=total_commission,
        commissions_by_seller=commissions_by_seller,
        commissions_by_item=commissions_by_item,
    )


@admin_bp.route('/assign_rider', methods=['POST'])
def assign_rider():
    if not _require_admin():
        return redirect(url_for('auth.login'))

    order_id = request.form.get('order_id', type=int)
    rider_id = request.form.get('rider_id', type=int)
    if not order_id or not rider_id:
        flash('Order and rider are required.', 'error')
        return redirect(url_for('admin.admin_dashboard'))

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            UPDATE orders
            SET rider_id=%s, delivery_status='assigned', assigned_at=COALESCE(assigned_at, CURRENT_TIMESTAMP)
            WHERE id=%s
            """,
            (rider_id, order_id),
        )
        if cur.rowcount == 0:
            flash('Order not found.', 'error')
        else:
            conn.commit()
            flash('Rider assigned successfully.', 'success')
    except Exception:
        conn.rollback()
        flash('Unable to assign rider.', 'error')
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('admin.admin_dashboard'))


@admin_bp.route('/approve_seller')
def approve_seller():
    if not _require_admin():
        return redirect(url_for('auth.login'))

    seller_id = request.args.get('seller_id', type=int)
    if not seller_id:
        flash('Seller ID is required.', 'error')
        return redirect(url_for('admin.admin_dashboard'))

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE sellers SET status='approved' WHERE id=%s", (seller_id,))
        conn.commit()
        flash('Seller approved successfully.', 'success')
    except Exception:
        conn.rollback()
        flash('Unable to approve seller.', 'error')
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('admin.admin_dashboard'))


@admin_bp.route('/reject_seller')
def reject_seller():
    if not _require_admin():
        return redirect(url_for('auth.login'))

    seller_id = request.args.get('seller_id', type=int)
    if not seller_id:
        flash('Seller ID is required.', 'error')
        return redirect(url_for('admin.admin_dashboard'))

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE sellers SET status='rejected' WHERE id=%s", (seller_id,))
        conn.commit()
        flash('Seller rejected.', 'success')
    except Exception:
        conn.rollback()
        flash('Unable to reject seller.', 'error')
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('admin.admin_dashboard'))


@admin_bp.route('/approve_rider')
def approve_rider():
    if not _require_admin():
        return redirect(url_for('auth.login'))

    rider_id = request.args.get('rider_id', type=int)
    if not rider_id:
        flash('Rider ID is required.', 'error')
        return redirect(url_for('admin.admin_dashboard'))

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE riders SET status='approved' WHERE id=%s", (rider_id,))
        conn.commit()
        flash('Rider approved successfully.', 'success')
    except Exception:
        conn.rollback()
        flash('Unable to approve rider.', 'error')
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('admin.admin_dashboard'))


@admin_bp.route('/reject_rider')
def reject_rider():
    if not _require_admin():
        return redirect(url_for('auth.login'))

    rider_id = request.args.get('rider_id', type=int)
    if not rider_id:
        flash('Rider ID is required.', 'error')
        return redirect(url_for('admin.admin_dashboard'))

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE riders SET status='rejected' WHERE id=%s", (rider_id,))
        conn.commit()
        flash('Rider rejected.', 'success')
    except Exception:
        conn.rollback()
        flash('Unable to reject rider.', 'error')
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('admin.admin_dashboard'))
