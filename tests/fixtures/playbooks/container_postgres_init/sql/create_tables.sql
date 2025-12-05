-- create_tables.sql
-- Table creation for container-based test fixture
-- Variables: :schema_name

\set ECHO all
\set ON_ERROR_STOP on

\echo '=== Creating tables in schema:' :schema_name '==='

-- Set search path for convenience
SET search_path TO container_test, public;

-- Drop tables if they exist (for clean testing)
DROP TABLE IF EXISTS container_test.order_items CASCADE;
DROP TABLE IF EXISTS container_test.orders CASCADE;
DROP TABLE IF EXISTS container_test.customers CASCADE;
DROP TABLE IF EXISTS container_test.products CASCADE;

-- Customers table
CREATE TABLE container_test.customers (
    customer_id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    phone VARCHAR(20),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_customers_email ON container_test.customers(email);
COMMENT ON TABLE container_test.customers IS 'Customer master data for container test';

-- Products table
CREATE TABLE container_test.products (
    product_id SERIAL PRIMARY KEY,
    sku VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    price DECIMAL(10, 2) NOT NULL CHECK (price >= 0),
    stock_quantity INTEGER DEFAULT 0 CHECK (stock_quantity >= 0),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_products_sku ON container_test.products(sku);
COMMENT ON TABLE container_test.products IS 'Product catalog for container test';

-- Orders table
CREATE TABLE container_test.orders (
    order_id SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES container_test.customers(customer_id) ON DELETE CASCADE,
    order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(50) DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'cancelled')),
    total_amount DECIMAL(10, 2) DEFAULT 0.00 CHECK (total_amount >= 0),
    shipping_address TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_orders_customer_id ON container_test.orders(customer_id);
CREATE INDEX idx_orders_status ON container_test.orders(status);
CREATE INDEX idx_orders_order_date ON container_test.orders(order_date);
COMMENT ON TABLE container_test.orders IS 'Customer orders for container test';

-- Order items table (junction table with details)
CREATE TABLE container_test.order_items (
    order_item_id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES container_test.orders(order_id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES container_test.products(product_id) ON DELETE RESTRICT,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price DECIMAL(10, 2) NOT NULL CHECK (unit_price >= 0),
    subtotal DECIMAL(10, 2) GENERATED ALWAYS AS (quantity * unit_price) STORED,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_order_items_order_id ON container_test.order_items(order_id);
CREATE INDEX idx_order_items_product_id ON container_test.order_items(product_id);
COMMENT ON TABLE container_test.order_items IS 'Line items for orders in container test';

-- Create view for order summary
CREATE OR REPLACE VIEW container_test.order_summary AS
SELECT 
    o.order_id,
    o.order_date,
    o.status,
    c.email AS customer_email,
    c.first_name || ' ' || c.last_name AS customer_name,
    COUNT(oi.order_item_id) AS item_count,
    SUM(oi.subtotal) AS calculated_total,
    o.total_amount
FROM container_test.orders o
JOIN container_test.customers c ON o.customer_id = c.customer_id
LEFT JOIN container_test.order_items oi ON o.order_id = oi.order_id
GROUP BY o.order_id, o.order_date, o.status, c.email, c.first_name, c.last_name, o.total_amount;

COMMENT ON VIEW container_test.order_summary IS 'Order summary view with customer details';

-- Grant permissions
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA container_test TO CURRENT_USER;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA container_test TO CURRENT_USER;
GRANT SELECT ON container_test.order_summary TO CURRENT_USER;

\echo '✓ All tables and views created successfully'

-- Report created objects
SELECT 
    schemaname,
    tablename AS object_name,
    'table' AS object_type
FROM pg_tables 
WHERE schemaname = 'container_test'
UNION ALL
SELECT 
    schemaname,
    viewname AS object_name,
    'view' AS object_type
FROM pg_views 
WHERE schemaname = 'container_test'
ORDER BY object_type, object_name;
