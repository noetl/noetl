#!/bin/bash

# Script to create database tables for save storage tests directly in Kubernetes postgres

echo "Creating database tables for save storage tests..."

# Execute SQL commands directly on the postgres pod
kubectl exec deployment/postgres -n postgres -- psql -h localhost -p 5432 -U demo -d demo_noetl -c "
CREATE TABLE IF NOT EXISTS simple_test_flat (
  test_id VARCHAR(255) PRIMARY KEY,
  test_name VARCHAR(255),
  test_value INTEGER,
  storage_type VARCHAR(255),
  test_execution VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS simple_test_nested (
  test_id VARCHAR(255) PRIMARY KEY,
  test_name VARCHAR(255),
  test_data JSONB,
  storage_type VARCHAR(255),
  test_execution VARCHAR(255)
);
"

echo "Database tables created successfully!"