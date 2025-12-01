#!/bin/bash
# Copy your existing gcloud OAuth credentials for NoETL testing

echo "📋 Copying your gcloud user credentials for NoETL..."

# Source ADC file
ADC_FILE=~/.config/gcloud/legacy_credentials/kadyapam@gmail.com/adc.json

if [ ! -f "$ADC_FILE" ]; then
    echo "❌ ADC file not found at $ADC_FILE"
    echo "Run: gcloud auth application-default login"
    exit 1
fi

# Destination
DEST_FILE="tests/fixtures/credentials/google_oauth.json"

# Create credential in NoETL format
cat > "$DEST_FILE" << EOF
{
  "name": "google_oauth",
  "type": "google_oauth",
  "description": "Local gcloud user credentials (kadyapam@gmail.com)",
  "tags": ["oauth", "google", "local", "test"],
  "data": $(cat $ADC_FILE)
}
EOF

echo "✅ Created: $DEST_FILE"
echo ""
echo "Next steps:"
echo "1. Register with NoETL:"
echo "   curl -X POST http://localhost:8083/api/credentials \\"
echo "     -H 'Content-Type: application/json' \\"
echo "     --data-binary @$DEST_FILE"
echo ""
echo "2. Update playbooks with your project ID in workload section"
echo ""
echo "3. Run test:"
echo "   .venv/bin/noetl execute playbook 'tests/fixtures/playbooks/oauth/google_secret_manager' \\"
echo "     --host localhost --port 8083"
