
-- PostgreSQL Schema for Supabase
-- This schema is converted from MySQL to PostgreSQL format

BEGIN TRANSACTION;

-- Enum types
CREATE TYPE user_role AS ENUM ('user', 'admin');
CREATE TYPE seller_status AS ENUM ('pending', 'approved', 'rejected');
CREATE TYPE rider_status AS ENUM ('pending', 'approved', 'rejected');
CREATE TYPE delivery_status AS ENUM ('pending', 'assigned', 'picked_up', 'in_transit', 'delivered', 'cancelled');
CREATE TYPE refund_status AS ENUM ('pending', 'approved', 'rejected');
CREATE TYPE refund_status_enum AS ENUM ('pending_pickup', 'picked_up', 'in_transit', 'completed');

CREATE TABLE cart (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL,
  product_id INTEGER NOT NULL,
  quantity INTEGER DEFAULT 1,
  subtotal NUMERIC(10,2) NOT NULL,
  added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);CREATE TABLE notifications (
  id SERIAL PRIMARY KEY,
  seller_id INTEGER NOT NULL,
  message TEXT NOT NULL,
  is_read SMALLINT DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);CREATE TABLE orders (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL,
  product_id INTEGER NOT NULL,
  quantity INTEGER NOT NULL,
  total NUMERIC(10,2) DEFAULT NULL,
  payment_method VARCHAR(50) NOT NULL,
  payment_status VARCHAR(20) DEFAULT 'Pending',
  order_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  address VARCHAR(255) DEFAULT NULL,
  seller_confirmed SMALLINT DEFAULT 0,
  seller_id INTEGER DEFAULT NULL,
  rider_id INTEGER DEFAULT NULL,
  delivery_status delivery_status DEFAULT 'pending',
  pickup_address VARCHAR(500) DEFAULT NULL,
  delivery_address VARCHAR(500) DEFAULT NULL,
  customer_contact VARCHAR(20) DEFAULT NULL,
  assigned_at TIMESTAMP DEFAULT NULL,
  picked_up_at TIMESTAMP DEFAULT NULL,
  delivered_at TIMESTAMP DEFAULT NULL,
  delivery_proof VARCHAR(255) DEFAULT NULL,
  admin_commission NUMERIC(10,2) DEFAULT NULL,
  seller_earnings NUMERIC(10,2) DEFAULT NULL,
  order_received SMALLINT DEFAULT 0,
  order_received_at TIMESTAMP DEFAULT NULL
);
CREATE TABLE order_items (
  id SERIAL PRIMARY KEY,
  order_id INTEGER NOT NULL,
  product_id INTEGER NOT NULL,
  quantity INTEGER NOT NULL,
  price NUMERIC(10,2) NOT NULL,
  subtotal NUMERIC(10,2) NOT NULL
);CREATE TYPE user_type AS ENUM ('user', 'seller');

CREATE TABLE password_reset_otp (
  id SERIAL PRIMARY KEY,
  email VARCHAR(100) NOT NULL,
  user_type user_type NOT NULL,
  otp_code VARCHAR(10) NOT NULL,
  expires_at TIMESTAMP NOT NULL,
  used SMALLINT DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE products (
  id SERIAL PRIMARY KEY,
  seller_id INTEGER NOT NULL,
  name VARCHAR(150) NOT NULL,
  category VARCHAR(100) DEFAULT NULL,
  description TEXT DEFAULT NULL,
  price NUMERIC(10,2) NOT NULL,
  stock INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  image VARCHAR(255) DEFAULT NULL
);
CREATE TABLE refund_requests (
  id SERIAL PRIMARY KEY,
  order_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  seller_id INTEGER NOT NULL,
  product_id INTEGER NOT NULL,
  reason TEXT DEFAULT NULL,
  evidence_file VARCHAR(500) DEFAULT NULL,
  rejection_reason TEXT DEFAULT NULL,
  status refund_status DEFAULT 'pending',
  refund_status refund_status_enum DEFAULT NULL,
  rider_id INTEGER DEFAULT NULL,
  pickup_address VARCHAR(500) DEFAULT NULL,
  return_address VARCHAR(500) DEFAULT NULL,
  picked_up_at TIMESTAMP DEFAULT NULL,
  returned_at TIMESTAMP DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE riders (
  id SERIAL PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  contact VARCHAR(20) NOT NULL UNIQUE,
  password VARCHAR(255) NOT NULL,
  drivers_license VARCHAR(255) DEFAULT NULL,
  status rider_status DEFAULT 'pending',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE sellers (
  id SERIAL PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  email VARCHAR(100) NOT NULL UNIQUE,
  shop_name VARCHAR(150) NOT NULL,
  password VARCHAR(255) NOT NULL,
  status seller_status DEFAULT 'pending',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  first_name VARCHAR(100) DEFAULT NULL,
  last_name VARCHAR(100) DEFAULT NULL,
  address VARCHAR(255) DEFAULT NULL,
  country VARCHAR(100) DEFAULT NULL,
  region VARCHAR(100) DEFAULT NULL,
  province VARCHAR(100) DEFAULT NULL,
  municipality VARCHAR(100) DEFAULT NULL,
  city VARCHAR(100) DEFAULT NULL,
  city_municipality VARCHAR(100) DEFAULT NULL,
  barangay VARCHAR(100) DEFAULT NULL,
  house_number VARCHAR(50) DEFAULT NULL,
  street_name VARCHAR(255) DEFAULT NULL,
  postal_code VARCHAR(20) DEFAULT NULL,
  valid_id VARCHAR(255) DEFAULT NULL,
  email_verified SMALLINT DEFAULT 0,
  verification_code VARCHAR(10) DEFAULT NULL,
  verification_code_expires TIMESTAMP DEFAULT NULL,
  gcash_number VARCHAR(20) DEFAULT NULL,
  paymaya_number VARCHAR(20) DEFAULT NULL
);

CREATE TABLE users (
  id SERIAL PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  email VARCHAR(100) NOT NULL UNIQUE,
  password VARCHAR(255) NOT NULL,
  role user_role DEFAULT 'user',
  address VARCHAR(255) DEFAULT NULL,
  profile_image VARCHAR(255) DEFAULT 'uploads/profile/default.jpg',
  first_name VARCHAR(100) DEFAULT NULL,
  last_name VARCHAR(100) DEFAULT NULL,
  country VARCHAR(100) DEFAULT NULL,
  region VARCHAR(100) DEFAULT NULL,
  province VARCHAR(100) DEFAULT NULL,
  municipality VARCHAR(100) DEFAULT NULL,
  city VARCHAR(100) DEFAULT NULL,
  city_municipality VARCHAR(100) DEFAULT NULL,
  barangay VARCHAR(100) DEFAULT NULL,
  house_number VARCHAR(50) DEFAULT NULL,
  street_name VARCHAR(255) DEFAULT NULL,
  postal_code VARCHAR(20) DEFAULT NULL,
  refund_account_number VARCHAR(20) DEFAULT NULL,
  email_verified SMALLINT DEFAULT 0,
  verification_code VARCHAR(10) DEFAULT NULL,
  verification_code_expires TIMESTAMP DEFAULT NULL
);

INSERT INTO users (id, name, email, password, role, address, profile_image, first_name, last_name, country, region, province, municipality, city, city_municipality, barangay, house_number, street_name, postal_code, refund_account_number, email_verified, verification_code, verification_code_expires) VALUES
(1, 'Admin', 'admin@gmail.com', 'admin123', 'admin', NULL, 'uploads/profile/default.jpg', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 1, NULL, NULL);CREATE TABLE user_notifications (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL,
  message TEXT NOT NULL,
  type VARCHAR(50) DEFAULT 'info',
  is_read SMALLINT DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);-- Create Indexes
CREATE INDEX idx_cart_user ON cart(user_id);
CREATE INDEX idx_cart_product ON cart(product_id);

CREATE INDEX idx_notifications_seller ON notifications(seller_id);

CREATE INDEX idx_orders_user ON orders(user_id);
CREATE INDEX idx_orders_product ON orders(product_id);
CREATE INDEX idx_orders_seller ON orders(seller_id);
CREATE INDEX idx_orders_rider ON orders(rider_id);

CREATE INDEX idx_order_items_order ON order_items(order_id);
CREATE INDEX idx_order_items_product ON order_items(product_id);

CREATE INDEX idx_password_reset_email_type ON password_reset_otp(email, user_type);
CREATE INDEX idx_password_reset_expires ON password_reset_otp(expires_at);

CREATE INDEX idx_products_seller ON products(seller_id);

CREATE INDEX idx_refund_order ON refund_requests(order_id);
CREATE INDEX idx_refund_user ON refund_requests(user_id);
CREATE INDEX idx_refund_seller ON refund_requests(seller_id);
CREATE INDEX idx_refund_product ON refund_requests(product_id);
CREATE INDEX idx_refund_rider ON refund_requests(rider_id);

CREATE INDEX idx_user_notifications_user ON user_notifications(user_id);

-- Add Foreign Key Constraints
ALTER TABLE cart
  ADD CONSTRAINT fk_cart_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  ADD CONSTRAINT fk_cart_product FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE;

ALTER TABLE notifications
  ADD CONSTRAINT fk_notifications_seller FOREIGN KEY (seller_id) REFERENCES sellers(id) ON DELETE CASCADE;

ALTER TABLE orders
  ADD CONSTRAINT fk_orders_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  ADD CONSTRAINT fk_orders_product FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
  ADD CONSTRAINT fk_orders_seller FOREIGN KEY (seller_id) REFERENCES sellers(id) ON DELETE CASCADE,
  ADD CONSTRAINT fk_orders_rider FOREIGN KEY (rider_id) REFERENCES riders(id) ON DELETE SET NULL;

ALTER TABLE order_items
  ADD CONSTRAINT fk_order_items_order FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
  ADD CONSTRAINT fk_order_items_product FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE;

ALTER TABLE products
  ADD CONSTRAINT fk_products_seller FOREIGN KEY (seller_id) REFERENCES sellers(id) ON DELETE CASCADE;

ALTER TABLE refund_requests
  ADD CONSTRAINT fk_refund_order FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
  ADD CONSTRAINT fk_refund_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  ADD CONSTRAINT fk_refund_seller FOREIGN KEY (seller_id) REFERENCES sellers(id) ON DELETE CASCADE,
  ADD CONSTRAINT fk_refund_product FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
  ADD CONSTRAINT fk_refund_rider FOREIGN KEY (rider_id) REFERENCES riders(id) ON DELETE SET NULL;

ALTER TABLE user_notifications
  ADD CONSTRAINT fk_notification_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;

-- Trigger for updating refund_requests.updated_at
CREATE OR REPLACE FUNCTION update_refund_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = CURRENT_TIMESTAMP;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_refund_updated_at
  BEFORE UPDATE ON refund_requests
  FOR EACH ROW
  EXECUTE FUNCTION update_refund_updated_at();

COMMIT;
