#!/bin/bash
set -e

echo "=========================================="
echo "Cleaning Snowflake credentials from Git history"
echo "=========================================="
echo ""
echo "WARNING: This will rewrite Git history!"
echo "Press Ctrl+C within 5 seconds to cancel..."
sleep 5

# Create a backup branch just in case
echo "Creating backup branch..."
git branch backup-before-credential-cleanup 2>/dev/null || echo "Backup branch already exists"

# Create replacement patterns file
echo "Creating replacement patterns..."
cat > /tmp/credential_replacements.txt << 'EOF'
Cybx_noetl_!2345==>your_password
NDCFGPC-MI21697==>your_account.region
NOETL==>your_username
SNOWFLAKE_LEARNING_WH==>COMPUTE_WH
ACCOUNTADMIN==>SYSADMIN
EOF

echo "Rewriting history with git-filter-repo..."
# Note: git-filter-repo requires a fresh clone or removes origin remote
# We'll back up the remote URL first
ORIGIN_URL=$(git remote get-url origin)
echo "Saved origin URL: $ORIGIN_URL"

# Run filter-repo to replace sensitive text
git filter-repo --force \
  --replace-text /tmp/credential_replacements.txt \
  --path tests/fixtures/credentials/sf_test.json

# Restore the origin remote
echo "Restoring origin remote..."
git remote add origin "$ORIGIN_URL"

# Clean up
rm -f /tmp/credential_replacements.txt

echo ""
echo "=========================================="
echo "History rewrite complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Review the changes with: git log --oneline -- tests/fixtures/credentials/sf_test.json"
echo "2. Force push to remote: git push origin master --force"
echo "3. Notify team members to re-clone or reset their branches"
echo "4. Rotate the Snowflake credentials immediately"
echo ""
echo "If something went wrong, restore from backup:"
echo "  git reset --hard backup-before-credential-cleanup"
