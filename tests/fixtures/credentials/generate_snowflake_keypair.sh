#!/bin/bash
# Generate RSA Key Pair for Snowflake Authentication
# This script generates a private/public key pair for Snowflake key-pair authentication
# which bypasses MFA/TOTP requirements.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRIVATE_KEY="$SCRIPT_DIR/sf_rsa_key.p8"
PUBLIC_KEY="$SCRIPT_DIR/sf_rsa_key.pub"

echo "=== Generating RSA Key Pair for Snowflake Authentication ==="
echo ""

# Generate private key
echo "Generating 2048-bit RSA private key..."
openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out "$PRIVATE_KEY" -nocrypt

if [ ! -f "$PRIVATE_KEY" ]; then
    echo "ERROR: Failed to generate private key"
    exit 1
fi

echo "✓ Private key generated: $PRIVATE_KEY"

# Generate public key
echo ""
echo "Generating public key..."
openssl rsa -in "$PRIVATE_KEY" -pubout -out "$PUBLIC_KEY"

if [ ! -f "$PUBLIC_KEY" ]; then
    echo "ERROR: Failed to generate public key"
    exit 1
fi

echo "✓ Public key generated: $PUBLIC_KEY"

# Display public key for Snowflake
echo ""
echo "=== Public Key for Snowflake (copy this) ==="
echo ""
# Remove header/footer and join lines
grep -v "BEGIN PUBLIC KEY" "$PUBLIC_KEY" | grep -v "END PUBLIC KEY" | tr -d '\n'
echo ""
echo ""

# Display SQL command
echo "=== SQL Command to Assign Public Key ==="
echo ""
echo "Run this in Snowflake:"
echo ""
echo "ALTER USER <YOUR_USERNAME> SET RSA_PUBLIC_KEY='"
grep -v "BEGIN PUBLIC KEY" "$PUBLIC_KEY" | grep -v "END PUBLIC KEY" | tr -d '\n'
echo "';"
echo ""
echo "-- Verify with:"
echo "DESC USER <YOUR_USERNAME>;"
echo ""

# Display private key preview
echo "=== Private Key Preview ==="
echo ""
head -n 3 "$PRIVATE_KEY"
echo "..."
tail -n 2 "$PRIVATE_KEY"
echo ""

# Create example credential JSON
EXAMPLE_JSON="$SCRIPT_DIR/sf_test_keypair_example.json"
PRIVATE_KEY_CONTENT=$(cat "$PRIVATE_KEY" | sed 's/$/\\n/' | tr -d '\n' | sed 's/\\n$//')

cat > "$EXAMPLE_JSON" << EOF
{
  "name": "sf_test_keypair",
  "type": "snowflake",
  "description": "Snowflake connection using RSA key-pair authentication (MFA bypass)",
  "tags": ["test", "snowflake", "keypair"],
  "data": {
    "sf_account": "ACCOUNT-LOCATOR",
    "sf_user": "YOUR_USERNAME",
    "sf_private_key": "$PRIVATE_KEY_CONTENT",
    "sf_warehouse": "YOUR_WAREHOUSE",
    "sf_database": "YOUR_DATABASE",
    "sf_schema": "PUBLIC",
    "sf_role": "YOUR_ROLE"
  }
}
EOF

echo "✓ Example credential JSON created: $EXAMPLE_JSON"
echo ""
echo "=== Next Steps ==="
echo ""
echo "1. Copy the public key shown above"
echo "2. Run the SQL command in Snowflake to assign it to your user"
echo "3. Edit $EXAMPLE_JSON with your Snowflake details"
echo "4. Upload the credential via:"
echo "   - NoETL UI: Credentials tab → New Credential → Upload File"
echo "   - CLI: curl -X POST http://localhost:8082/api/credentials -H 'Content-Type: application/json' --data-binary @$EXAMPLE_JSON"
echo ""
echo "=== Security Notes ==="
echo ""
echo "⚠️  Keep $PRIVATE_KEY secure - it provides authentication without password/MFA"
echo "⚠️  Add sf_rsa_key.p8 to .gitignore to prevent accidental commits"
echo "⚠️  Rotate keys periodically for security"
echo ""

# Update .gitignore
GITIGNORE="$SCRIPT_DIR/.gitignore"
if [ ! -f "$GITIGNORE" ]; then
    echo "sf_rsa_key.p8" > "$GITIGNORE"
    echo "sf_rsa_key.pub" >> "$GITIGNORE"
    echo "✓ Created .gitignore for key files"
else
    if ! grep -q "sf_rsa_key.p8" "$GITIGNORE"; then
        echo "sf_rsa_key.p8" >> "$GITIGNORE"
        echo "sf_rsa_key.pub" >> "$GITIGNORE"
        echo "✓ Updated .gitignore with key files"
    fi
fi

echo "Done!"
