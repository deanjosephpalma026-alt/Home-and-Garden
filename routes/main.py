from flask import (
    Blueprint,
    render_template,
    session,
    flash,
    redirect,
    url_for,
    request,
    jsonify,
    current_app,
)
from database import get_db_connection, add_column_if_missing
import json
import os
import psycopg2.extras

main_bp = Blueprint('main', __name__)
_locations_docs_cache = None


def _load_location_docs():
    global _locations_docs_cache
    if _locations_docs_cache is not None:
        return _locations_docs_cache, None

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

        docs = {
            'regions': regions_doc,
            'provinces': provinces_doc,
            'cities_municipalities': cities_doc,
            'barangays': barangays_doc,
        }
        _locations_docs_cache = docs
        return docs, None
    except Exception as e:
        return None, e

@main_bp.route('/')
def index():
    return redirect(url_for('main.home'))

@main_bp.route('/home')
def home():
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT p.id, p.name, p.description, p.price, p.stock, p.image, p.seller_id,
                   s.shop_name, s.name as seller_name
            FROM products p
            JOIN sellers s ON p.seller_id = s.id
            WHERE s.status = 'approved'
            LIMIT 8
        """)
        products = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Database error in home(): {e}")
        products = []
        flash('Unable to load products. Please try again later.', 'error')
    
    name = session.get('name', '')
    return render_template('home.html', name=name, products=products)

@main_bp.route('/about')
def about():
    return render_template('about.html')


@main_bp.route('/products')
def products():
    search_query = (request.args.get('search') or '').strip()
    selected_category = (request.args.get('category') or '').strip()

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    where = ["s.status = 'approved'"]
    params = []
    if search_query:
        where.append("(LOWER(p.name) LIKE LOWER(%s) OR LOWER(p.description) LIKE LOWER(%s))")
        params.extend([f"%{search_query}%", f"%{search_query}%"])
    if selected_category:
        where.append("p.category = %s")
        params.append(selected_category)

    where_sql = " AND ".join(where)
    cur.execute(
        f"""
        SELECT p.*, s.shop_name, s.name AS seller_name
        FROM products p
        JOIN sellers s ON p.seller_id = s.id
        WHERE {where_sql}
        ORDER BY p.created_at DESC
        """,
        tuple(params),
    )
    products_rows = cur.fetchall() or []

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

    cur.close()
    conn.close()

    return render_template(
        'products.html',
        products=products_rows,
        categories=categories,
        selected_category=selected_category or None,
        search_query=search_query or None,
    )


@main_bp.route('/product_detail')
def product_detail():
    product_id = request.args.get('id', type=int)
    if not product_id:
        flash('Product not found.', 'error')
        return redirect(url_for('main.products'))

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        add_column_if_missing(conn, 'products', 'size_options', 'TEXT DEFAULT NULL')
        add_column_if_missing(conn, 'products', 'color_options', 'TEXT DEFAULT NULL')
    except Exception:
        pass
    try:
        from utils import ensure_product_reviews_table
        ensure_product_reviews_table(conn)
    except Exception:
        pass
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
        LIMIT 20
        """,
        (product_id,),
    )
    reviews = cur.fetchall() or []
    cur.close()
    conn.close()

    if not product:
        flash('Product not found.', 'error')
        return redirect(url_for('main.products'))

    product_tuple = [
        product.get('id'),
        product.get('name'),
        product.get('price'),
        product.get('stock'),
        product.get('description'),
        product.get('category'),
        product.get('image'),
    ]

    return render_template(
        'product_detail.html',
        product_id=product['id'],
        product=product_tuple,
        name=product.get('name'),
        description=product.get('description'),
        price=product.get('price'),
        stock=product.get('stock'),
        image_path=product.get('image') or '',
        category=product.get('category'),
        seller_id=product.get('seller_id'),
        shop_name=product.get('shop_name'),
        seller_name=product.get('seller_name'),
        seller_profile_image=product.get('seller_profile_image'),
        size_options=[item for item in (product.get('size_options') or '').replace('|', ',').split(',') if item.strip()],
        color_options=[item for item in (product.get('color_options') or '').replace('|', ',').split(',') if item.strip()],
        sold_count=int(product.get('sold_count') or 0),
        review_count=int(product.get('review_count') or 0),
        average_rating=float(product.get('average_rating') or 0),
        reviews=reviews,
    )


@main_bp.route('/seller_profile_public')
def seller_profile_public():
    seller_id = request.args.get('seller_id', type=int)
    if not seller_id:
        flash('Seller not found.', 'error')
        return redirect(url_for('main.products'))

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM sellers WHERE id=%s", (seller_id,))
    seller = cur.fetchone()
    cur.execute(
        """
        SELECT * FROM products
        WHERE seller_id=%s
        ORDER BY created_at DESC
        """,
        (seller_id,),
    )
    products_rows = cur.fetchall() or []
    cur.close()
    conn.close()

    if not seller:
        flash('Seller not found.', 'error')
        return redirect(url_for('main.products'))

    return render_template(
        'seller_profile_public.html',
        seller=seller,
        products=products_rows,
        seller_id=seller_id,
        shop_name=seller.get('shop_name'),
        seller_name=seller.get('name'),
    )


@main_bp.route('/get_regions', methods=['GET'])
def get_regions():
    docs, err = _load_location_docs()
    if err is not None or docs is None:
        return jsonify({'regions': []}), 500
    regions_doc = docs.get('regions') or {}
    regions = (regions_doc.get('regions') or []) if isinstance(regions_doc, dict) else []
    return jsonify({'regions': regions})


@main_bp.route('/get_provinces', methods=['GET'])
def get_provinces():
    region = (request.args.get('region') or '').strip()
    docs, err = _load_location_docs()
    if err is not None or docs is None:
        return jsonify({'provinces': []}), 500
    provinces_doc = docs.get('provinces') or {}
    provinces = (
        (provinces_doc.get(region) or []) if isinstance(provinces_doc, dict) else []
    )
    return jsonify({'provinces': provinces})


@main_bp.route('/get_city_municipality', methods=['GET'])
def get_city_municipality():
    region = (request.args.get('region') or '').strip()
    province = (request.args.get('province') or '').strip()
    docs, err = _load_location_docs()
    if err is not None or docs is None:
        return jsonify({'cities_municipalities': []}), 500
    cities_doc = docs.get('cities_municipalities') or {}
    region_map = (
        (cities_doc.get(region) or {}) if isinstance(cities_doc, dict) else {}
    )
    cities = (region_map.get(province) or []) if isinstance(region_map, dict) else []
    return jsonify({'cities_municipalities': cities})


@main_bp.route('/get_barangays', methods=['GET'])
def get_barangays():
    region = (request.args.get('region') or '').strip()
    province = (request.args.get('province') or '').strip()
    city_municipality = (request.args.get('city_municipality') or '').strip()
    docs, err = _load_location_docs()
    if err is not None or docs is None:
        return jsonify({'barangays': []}), 500
    barangays_doc = docs.get('barangays') or {}
    region_map = (
        (barangays_doc.get(region) or {}) if isinstance(barangays_doc, dict) else {}
    )
    province_map = (
        (region_map.get(province) or {}) if isinstance(region_map, dict) else {}
    )
    barangays = (
        (province_map.get(city_municipality) or [])
        if isinstance(province_map, dict)
        else []
    )
    return jsonify({'barangays': barangays})
