-- PostgreSQL / Supabase compatibility patch
-- Run in Supabase SQL editor.

-- users
ALTER TABLE IF EXISTS users
    ADD COLUMN IF NOT EXISTS email_verified BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS verification_code VARCHAR(20),
    ADD COLUMN IF NOT EXISTS verification_code_expires TIMESTAMP,
    ADD COLUMN IF NOT EXISTS first_name VARCHAR(120),
    ADD COLUMN IF NOT EXISTS last_name VARCHAR(120),
    ADD COLUMN IF NOT EXISTS country VARCHAR(120),
    ADD COLUMN IF NOT EXISTS region VARCHAR(255),
    ADD COLUMN IF NOT EXISTS province VARCHAR(255),
    ADD COLUMN IF NOT EXISTS municipality VARCHAR(255),
    ADD COLUMN IF NOT EXISTS city VARCHAR(255),
    ADD COLUMN IF NOT EXISTS city_municipality VARCHAR(255),
    ADD COLUMN IF NOT EXISTS barangay VARCHAR(255),
    ADD COLUMN IF NOT EXISTS house_number VARCHAR(120),
    ADD COLUMN IF NOT EXISTS street_name VARCHAR(255),
    ADD COLUMN IF NOT EXISTS postal_code VARCHAR(32),
    ADD COLUMN IF NOT EXISTS refund_account_number VARCHAR(64),
    ADD COLUMN IF NOT EXISTS valid_id VARCHAR(500),
    ADD COLUMN IF NOT EXISTS profile_image VARCHAR(500);

-- sellers
ALTER TABLE IF EXISTS sellers
    ADD COLUMN IF NOT EXISTS email_verified BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS verification_code VARCHAR(20),
    ADD COLUMN IF NOT EXISTS verification_code_expires TIMESTAMP,
    ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ADD COLUMN IF NOT EXISTS first_name VARCHAR(120),
    ADD COLUMN IF NOT EXISTS last_name VARCHAR(120),
    ADD COLUMN IF NOT EXISTS address TEXT,
    ADD COLUMN IF NOT EXISTS country VARCHAR(120),
    ADD COLUMN IF NOT EXISTS region VARCHAR(255),
    ADD COLUMN IF NOT EXISTS province VARCHAR(255),
    ADD COLUMN IF NOT EXISTS municipality VARCHAR(255),
    ADD COLUMN IF NOT EXISTS city VARCHAR(255),
    ADD COLUMN IF NOT EXISTS city_municipality VARCHAR(255),
    ADD COLUMN IF NOT EXISTS barangay VARCHAR(255),
    ADD COLUMN IF NOT EXISTS house_number VARCHAR(120),
    ADD COLUMN IF NOT EXISTS street_name VARCHAR(255),
    ADD COLUMN IF NOT EXISTS postal_code VARCHAR(32),
    ADD COLUMN IF NOT EXISTS valid_id VARCHAR(500),
    ADD COLUMN IF NOT EXISTS profile_image VARCHAR(500),
    ADD COLUMN IF NOT EXISTS gcash_number VARCHAR(32),
    ADD COLUMN IF NOT EXISTS paymaya_number VARCHAR(32);

-- riders
ALTER TABLE IF EXISTS riders
    ADD COLUMN IF NOT EXISTS email VARCHAR(255),
    ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ADD COLUMN IF NOT EXISTS drivers_license VARCHAR(500);

-- products
ALTER TABLE IF EXISTS products
    ADD COLUMN IF NOT EXISTS category VARCHAR(120),
    ADD COLUMN IF NOT EXISTS image VARCHAR(500);

-- orders
ALTER TABLE IF EXISTS orders
    ADD COLUMN IF NOT EXISTS seller_confirmed BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS rider_id INTEGER,
    ADD COLUMN IF NOT EXISTS delivery_status VARCHAR(20) DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS pickup_address VARCHAR(500),
    ADD COLUMN IF NOT EXISTS delivery_address VARCHAR(500),
    ADD COLUMN IF NOT EXISTS customer_contact VARCHAR(32),
    ADD COLUMN IF NOT EXISTS assigned_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS picked_up_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS delivery_proof VARCHAR(500),
    ADD COLUMN IF NOT EXISTS order_received BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS order_received_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS admin_commission NUMERIC(12,2),
    ADD COLUMN IF NOT EXISTS seller_earnings NUMERIC(12,2);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints
        WHERE table_schema='public' AND table_name='orders' AND constraint_name='fk_orders_rider'
    ) THEN
        ALTER TABLE orders
            ADD CONSTRAINT fk_orders_rider FOREIGN KEY (rider_id) REFERENCES riders(id) ON DELETE SET NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_orders_rider_id ON orders(rider_id);
CREATE INDEX IF NOT EXISTS idx_orders_seller_confirmed ON orders(seller_confirmed);

-- password_reset_otp
CREATE TABLE IF NOT EXISTS password_reset_otp (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL,
    user_type VARCHAR(20) NOT NULL,
    otp_code VARCHAR(20) NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    used BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_password_reset_otp_email_usertype ON password_reset_otp(email, user_type);

-- refund_requests
CREATE TABLE IF NOT EXISTS refund_requests (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    seller_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    reason TEXT,
    evidence_file VARCHAR(500),
    rejection_reason TEXT,
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
    refund_status VARCHAR(20) CHECK (refund_status IN ('pending_pickup','picked_up','in_transit','completed')),
    rider_id INTEGER,
    pickup_address VARCHAR(500),
    return_address VARCHAR(500),
    picked_up_at TIMESTAMP,
    returned_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_refund_order FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
    CONSTRAINT fk_refund_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_refund_seller FOREIGN KEY (seller_id) REFERENCES sellers(id) ON DELETE CASCADE,
    CONSTRAINT fk_refund_product FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
    CONSTRAINT fk_refund_rider FOREIGN KEY (rider_id) REFERENCES riders(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_refund_order_id ON refund_requests(order_id);
CREATE INDEX IF NOT EXISTS idx_refund_user_id ON refund_requests(user_id);
CREATE INDEX IF NOT EXISTS idx_refund_seller_id ON refund_requests(seller_id);
CREATE INDEX IF NOT EXISTS idx_refund_product_id ON refund_requests(product_id);
CREATE INDEX IF NOT EXISTS idx_refund_rider_id ON refund_requests(rider_id);

-- user_notifications
CREATE TABLE IF NOT EXISTS user_notifications (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    message TEXT NOT NULL,
    type VARCHAR(50) DEFAULT 'info',
    is_read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_notification_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_user_notifications_user_id ON user_notifications(user_id);
