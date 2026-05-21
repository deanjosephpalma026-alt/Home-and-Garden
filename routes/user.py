from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from database import get_db_connection
from utils import _user_public_payload
import psycopg2.extras
import os
import uuid
from werkzeug.utils import secure_filename

user_bp = Blueprint('user', __name__)

@user_bp.route('/profile')
def profile():
    if 'id' not in session:
        return redirect(url_for('auth.login'))
        
    user_id = session['id']
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    
    if not user:
        flash('User not found.', 'error')
        return redirect(url_for('main.home'))
        
    return render_template('profile.html', user=user)

@user_bp.route('/edit_profile', methods=['GET', 'POST'])
def edit_profile():
    if 'id' not in session:
        return redirect(url_for('auth.login'))
        
    user_id = session['id']
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    if request.method == 'POST':
        name = request.form['name']
        first_name = request.form.get('first_name', '')
        last_name = request.form.get('last_name', '')
        address = request.form.get('address', '')
        
        profile_image = request.files.get('profile_image')
        image_path = None
        
        if profile_image and profile_image.filename:
            filename = secure_filename(f"{uuid.uuid4().hex}_{profile_image.filename}")
            image_dir = os.path.join(current_app.static_folder, 'uploads', 'profile')
            os.makedirs(image_dir, exist_ok=True)
            profile_image.save(os.path.join(image_dir, filename))
            image_path = f"uploads/profile/{filename}"
            
        if image_path:
            cur.execute("""
                UPDATE users 
                SET name=%s, first_name=%s, last_name=%s, address=%s, profile_image=%s 
                WHERE id=%s
            """, (name, first_name, last_name, address, image_path, user_id))
        else:
            cur.execute("""
                UPDATE users 
                SET name=%s, first_name=%s, last_name=%s, address=%s 
                WHERE id=%s
            """, (name, first_name, last_name, address, user_id))
            
        conn.commit()
        session['name'] = name
        flash('Profile updated successfully!', 'success')
        return redirect(url_for('user.profile'))
        
    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    
    return render_template('edit_profile.html', user=user)

@user_bp.route('/user_notifications')
def user_notifications():
    if 'id' not in session:
        return redirect(url_for('auth.login'))
        
    user_id = session['id']
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM user_notifications WHERE user_id = %s ORDER BY created_at DESC", (user_id,))
    notifications = cur.fetchall()
    cur.close()
    conn.close()
    
    return render_template('notifications.html', notifications=notifications)
