-- seed_data.sql
-- Sample data for container-based test fixture
-- Variables: :schema_name, :execution_id

\set ECHO all
\set ON_ERROR_STOP on

\echo '=== Seeding test data in schema:' :schema_name '==='
\echo 'Execution ID:' :execution_id

-- Set search path
SET search_path TO container_test, public;

-- Seed customers
INSERT INTO container_test.customers (email, first_name, last_name, phone) VALUES
    ('john.doe@example.com', 'John', 'Doe', '+1-555-0101'),
    ('jane.smith@example.com', 'Jane', 'Smith', '+1-555-0102'),
    ('bob.wilson@example.com', 'Bob', 'Wilson', '+1-555-0103'),
    ('alice.brown@example.com', 'Alice', 'Brown', '+1-555-0104'),
    ('charlie.davis@example.com', 'Charlie', 'Davis', '+1-555-0105'),
    ('diana.evans@example.com', 'Diana', 'Evans', '+1-555-0106'),
    ('frank.miller@example.com', 'Frank', 'Miller', '+1-555-0107'),
    ('grace.moore@example.com', 'Grace', 'Moore', '+1-555-0108'),
    ('henry.taylor@example.com', 'Henry', 'Taylor', '+1-555-0109'),
    ('iris.white@example.com', 'Iris', 'White', '+1-555-0110')
ON CONFLICT (email) DO NOTHING;

\echo '✓ Customers seeded'

-- Seed products
INSERT INTO container_test.products (sku, name, description, price, stock_quantity) VALUES
    ('PROD-001', 'Laptop Pro 15', 'High-performance laptop with 15" display', 1299.99, 50),
    ('PROD-002', 'Wireless Mouse', 'Ergonomic wireless mouse with USB receiver', 29.99, 200),
    ('PROD-003', 'Mechanical Keyboard', 'RGB mechanical keyboard with blue switches', 89.99, 100),
    ('PROD-004', 'USB-C Hub', '7-in-1 USB-C hub with HDMI and Ethernet', 49.99, 150),
    ('PROD-005', 'External SSD 1TB', 'Portable external SSD drive 1TB capacity', 129.99, 75),
    ('PROD-006', 'Webcam HD', '1080p HD webcam with built-in microphone', 79.99, 120),
    ('PROD-007', 'Laptop Stand', 'Adjustable aluminum laptop stand', 39.99, 180),
    ('PROD-008', 'Monitor 27"', '27" 4K IPS monitor with USB-C', 399.99, 40),
    ('PROD-009', 'Desk Lamp', 'LED desk lamp with adjustable brightness', 34.99, 90),
    ('PROD-010', 'Cable Organizer', 'Cable management system for desk', 19.99, 250),
    ('PROD-011', 'Noise Cancelling Headphones', 'Over-ear wireless headphones with ANC', 249.99, 60),
    ('PROD-012', 'Phone Stand', 'Adjustable phone stand for desk', 14.99, 300),
    ('PROD-013', 'Laptop Bag', 'Water-resistant laptop backpack 15"', 59.99, 110),
    ('PROD-014', 'Screen Cleaner Kit', 'Screen cleaning solution and microfiber cloth', 12.99, 200),
    ('PROD-015', 'Power Bank 20000mAh', 'High-capacity power bank with fast charging', 44.99, 85)
ON CONFLICT (sku) DO NOTHING;

\echo '✓ Products seeded'

-- Seed orders and order items (using DO block for complex logic)
DO $$
DECLARE
    v_customer_id INTEGER;
    v_order_id INTEGER;
    v_product_id INTEGER;
    v_price DECIMAL(10,2);
BEGIN
    -- Order 1: John Doe
    SELECT customer_id INTO v_customer_id FROM container_test.customers WHERE email = 'john.doe@example.com';
    INSERT INTO container_test.orders (customer_id, status, order_date, shipping_address)
    VALUES (v_customer_id, 'completed', CURRENT_TIMESTAMP - INTERVAL '5 days', '123 Main St, Springfield, IL 62701')
    RETURNING order_id INTO v_order_id;
    
    -- Order items for Order 1
    SELECT product_id, price INTO v_product_id, v_price FROM container_test.products WHERE sku = 'PROD-001';
    INSERT INTO container_test.order_items (order_id, product_id, quantity, unit_price)
    VALUES (v_order_id, v_product_id, 1, v_price);
    
    SELECT product_id, price INTO v_product_id, v_price FROM container_test.products WHERE sku = 'PROD-002';
    INSERT INTO container_test.order_items (order_id, product_id, quantity, unit_price)
    VALUES (v_order_id, v_product_id, 2, v_price);
    
    UPDATE container_test.orders SET total_amount = (SELECT SUM(subtotal) FROM container_test.order_items WHERE order_id = v_order_id) WHERE order_id = v_order_id;

    -- Order 2: Jane Smith
    SELECT customer_id INTO v_customer_id FROM container_test.customers WHERE email = 'jane.smith@example.com';
    INSERT INTO container_test.orders (customer_id, status, order_date, shipping_address)
    VALUES (v_customer_id, 'processing', CURRENT_TIMESTAMP - INTERVAL '2 days', '456 Oak Ave, Chicago, IL 60601')
    RETURNING order_id INTO v_order_id;
    
    SELECT product_id, price INTO v_product_id, v_price FROM container_test.products WHERE sku = 'PROD-008';
    INSERT INTO container_test.order_items (order_id, product_id, quantity, unit_price)
    VALUES (v_order_id, v_product_id, 1, v_price);
    
    SELECT product_id, price INTO v_product_id, v_price FROM container_test.products WHERE sku = 'PROD-003';
    INSERT INTO container_test.order_items (order_id, product_id, quantity, unit_price)
    VALUES (v_order_id, v_product_id, 1, v_price);
    
    UPDATE container_test.orders SET total_amount = (SELECT SUM(subtotal) FROM container_test.order_items WHERE order_id = v_order_id) WHERE order_id = v_order_id;

    -- Order 3: Bob Wilson
    SELECT customer_id INTO v_customer_id FROM container_test.customers WHERE email = 'bob.wilson@example.com';
    INSERT INTO container_test.orders (customer_id, status, order_date, shipping_address)
    VALUES (v_customer_id, 'pending', CURRENT_TIMESTAMP - INTERVAL '1 day', '789 Elm Rd, Boston, MA 02101')
    RETURNING order_id INTO v_order_id;
    
    SELECT product_id, price INTO v_product_id, v_price FROM container_test.products WHERE sku = 'PROD-011';
    INSERT INTO container_test.order_items (order_id, product_id, quantity, unit_price)
    VALUES (v_order_id, v_product_id, 1, v_price);
    
    SELECT product_id, price INTO v_product_id, v_price FROM container_test.products WHERE sku = 'PROD-013';
    INSERT INTO container_test.order_items (order_id, product_id, quantity, unit_price)
    VALUES (v_order_id, v_product_id, 1, v_price);
    
    SELECT product_id, price INTO v_product_id, v_price FROM container_test.products WHERE sku = 'PROD-010';
    INSERT INTO container_test.order_items (order_id, product_id, quantity, unit_price)
    VALUES (v_order_id, v_product_id, 3, v_price);
    
    UPDATE container_test.orders SET total_amount = (SELECT SUM(subtotal) FROM container_test.order_items WHERE order_id = v_order_id) WHERE order_id = v_order_id;

    -- Order 4: Alice Brown
    SELECT customer_id INTO v_customer_id FROM container_test.customers WHERE email = 'alice.brown@example.com';
    INSERT INTO container_test.orders (customer_id, status, order_date, shipping_address)
    VALUES (v_customer_id, 'completed', CURRENT_TIMESTAMP - INTERVAL '7 days', '321 Pine St, Seattle, WA 98101')
    RETURNING order_id INTO v_order_id;
    
    SELECT product_id, price INTO v_product_id, v_price FROM container_test.products WHERE sku = 'PROD-005';
    INSERT INTO container_test.order_items (order_id, product_id, quantity, unit_price)
    VALUES (v_order_id, v_product_id, 2, v_price);
    
    UPDATE container_test.orders SET total_amount = (SELECT SUM(subtotal) FROM container_test.order_items WHERE order_id = v_order_id) WHERE order_id = v_order_id;

    -- Order 5: Charlie Davis
    SELECT customer_id INTO v_customer_id FROM container_test.customers WHERE email = 'charlie.davis@example.com';
    INSERT INTO container_test.orders (customer_id, status, order_date, shipping_address)
    VALUES (v_customer_id, 'completed', CURRENT_TIMESTAMP - INTERVAL '10 days', '654 Maple Dr, Portland, OR 97201')
    RETURNING order_id INTO v_order_id;
    
    SELECT product_id, price INTO v_product_id, v_price FROM container_test.products WHERE sku = 'PROD-004';
    INSERT INTO container_test.order_items (order_id, product_id, quantity, unit_price)
    VALUES (v_order_id, v_product_id, 1, v_price);
    
    SELECT product_id, price INTO v_product_id, v_price FROM container_test.products WHERE sku = 'PROD-007';
    INSERT INTO container_test.order_items (order_id, product_id, quantity, unit_price)
    VALUES (v_order_id, v_product_id, 1, v_price);
    
    SELECT product_id, price INTO v_product_id, v_price FROM container_test.products WHERE sku = 'PROD-009';
    INSERT INTO container_test.order_items (order_id, product_id, quantity, unit_price)
    VALUES (v_order_id, v_product_id, 1, v_price);
    
    UPDATE container_test.orders SET total_amount = (SELECT SUM(subtotal) FROM container_test.order_items WHERE order_id = v_order_id) WHERE order_id = v_order_id;
END $$;

\echo '✓ Orders and order items seeded'

-- Display summary
\echo ''
\echo '=== Data Summary ==='
SELECT 'Customers' AS entity, COUNT(*) AS count FROM container_test.customers
UNION ALL
SELECT 'Products' AS entity, COUNT(*) AS count FROM container_test.products
UNION ALL
SELECT 'Orders' AS entity, COUNT(*) AS count FROM container_test.orders
UNION ALL
SELECT 'Order Items' AS entity, COUNT(*) AS count FROM container_test.order_items
ORDER BY entity;

\echo ''
\echo '✓ Data seeding complete'
