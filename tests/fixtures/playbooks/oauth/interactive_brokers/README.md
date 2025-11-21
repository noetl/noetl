# Interactive Brokers OAuth Test

This playbook tests OAuth-based authentication with Interactive Brokers Client Portal API.

## What This Tests

1. **OAuth 2.0 Authentication**: IBKR supports OAuth 2.0 for server-to-server API access
2. **Account Information**: Retrieves account details and balances
3. **Portfolio Data**: Access positions and portfolio summary
4. **Market Data**: Test market data access via OAuth
5. **Paper Trading**: Safe testing with paper trading account

## Authentication Methods

Interactive Brokers Client Portal API supports multiple authentication methods:

| Method | Use Case | Implementation Status |
|--------|----------|----------------------|
| **OAuth 2.0** | Server-to-server, automated workflows | ✅ Supported |
| **OAuth 1.0a** | Legacy applications | ✅ Supported |
| **SSO** | Web-based applications | ⏳ Not implemented |
| **CP Gateway** | Java-based local gateway | ⏳ Alternative method |

This test focuses on **OAuth 2.0**.

## Interactive Brokers OAuth Overview

### Authentication Methods

Interactive Brokers offers several authentication methods:

1. **OAuth 2.0** (Recommended for production)
   - Client Credentials flow
   - Used for server-to-server applications
   - Requires OAuth app registration

## Prerequisites

### 1. Register OAuth Application

1. Log into IBKR Client Portal:
   - Paper Trading: https://ndcdyn.interactivebrokers.com/sso/Login
   - Live Trading: https://www.interactivebrokers.com/sso/Login

2. Navigate to **Settings → API → OAuth Applications**

3. Click **Create Application**:
   ```
   Application Name: NoETL Test
   Application Type: Server-to-Server
   Redirect URI: (not needed for client credentials flow)
   Scopes: Select required permissions:
     - Read account information
     - Read portfolio data
     - Read market data
   ```

4. Save and note down:
   - **Consumer Key** (Client ID)
   - **Consumer Secret** (Client Secret)

### 2. Create Credential File

Create `tests/fixtures/credentials/ib_oauth.json`:

```json
{
  "name": "ib_oauth",
  "type": "interactive_brokers_oauth",
  "description": "Interactive Brokers OAuth credentials for paper trading",
  "tags": ["oauth", "ib", "interactive_brokers", "paper_trading", "test"],
  "data": {
    "consumer_key": "your-consumer-key-here",
    "consumer_secret": "your-consumer-secret-here",
    "account_id": "DU8027814",
    "environment": "paper",
    "api_base_url": "https://api.ibkr.com/v1/api",
    "oauth_version": "2.0"
  }
}
```

**Note**: Your paper trading account details:
- Username: `wzeeym257`
- Password: `Test202$`
- Account ID: `DU8027814` (paper trading account)

### 3. Register Credential with NoETL

```bash
# Start NoETL
task noetl:local:start

# Register credential
curl -X POST http://localhost:8083/api/credentials \
  -H 'Content-Type: application/json' \
  --data-binary @tests/fixtures/credentials/ib_oauth.json

# Verify registration
curl http://localhost:8083/api/credentials/ib_oauth | jq .
```

## Configuration

Edit the `workload` section in `ib_oauth.yaml`:

```yaml
workload:
  ib_auth: ib_oauth                # Credential name in NoETL
  account_id: DU8027814            # Your paper trading account ID
  environment: paper               # 'paper' or 'live'
  message: Test IBKR OAuth authentication
```

## Execution

```bash
# Execute playbook
.venv/bin/noetl execute playbook \
  "tests/fixtures/playbooks/oauth/interactive_brokers" \
  --host localhost \
  --port 8083
```

## Expected Output

Successful execution should show:

```json
{
  "status": "success",
  "message": "IBKR OAuth authentication fully verified!",
  "accounts_found": 1,
  "account_id": "DU8027814",
  "portfolio_accessed": "SUCCESS",
  "validation": "OAuth token generated, API calls succeeded"
}
```

## API Endpoints Used

### Authentication
- OAuth 2.0 Token: `POST https://api.ibkr.com/v1/oauth2/token`

### Account Information
- List Accounts: `GET /v1/api/portfolio/accounts`
- Account Summary: `GET /v1/api/portfolio/{accountId}/summary`
- Account Ledger: `GET /v1/api/portfolio/{accountId}/ledger`

### Portfolio Data
- Positions: `GET /v1/api/portfolio/{accountId}/positions`
- Portfolio Allocation: `GET /v1/api/portfolio/{accountId}/allocation`

### Market Data
- Market Data Snapshot: `GET /v1/api/md/snapshot`
- Market History: `GET /v1/api/iserver/marketdata/history`

## OAuth 2.0 Flow

IBKR uses **Client Credentials** grant type:

```
1. Application sends consumer_key + consumer_secret
2. IBKR returns access_token (JWT)
3. Token valid for ~60 minutes
4. Use token in Authorization header: Bearer {token}
5. Refresh token before expiry
```

## Troubleshooting

### Error: "Invalid consumer key"

**Cause**: OAuth application not created or incorrect credentials

**Fix**:
```bash
# Verify you've created OAuth app in IBKR portal
# Check Settings → API → OAuth Applications
# Ensure consumer key matches exactly
```

### Error: "Insufficient permissions"

**Cause**: OAuth app needs proper scopes

**Fix**:
1. Go to IBKR portal → Settings → API → OAuth Applications
2. Edit your application
3. Grant required scopes:
   - Read account information ✓
   - Read portfolio data ✓
   - Read market data ✓
4. Save changes and retry

### Error: "Account not accessible"

**Cause**: Paper trading account not enabled or expired

**Fix**:
```bash
# Login to paper trading portal
https://ndcdyn.interactivebrokers.com/sso/Login

# Verify account is active
# Paper trading accounts expire after 60 days of inactivity
# Request new paper account if needed
```

### Error: "SSL certificate verification failed"

**Cause**: Network/proxy issues

**Fix**:
```bash
# Test IBKR API connectivity
curl -v https://api.ibkr.com/v1/api/portfolio/accounts

# Check if proxy/firewall blocking access
# IBKR API requires TLS 1.2 or higher
```

## Differences from CP Gateway

| Feature | OAuth 2.0 | CP Gateway |
|---------|-----------|------------|
| **Setup** | Register OAuth app | Download & run Java gateway |
| **Authentication** | Token-based | Session cookies |
| **Automation** | ✅ Fully automated | ⚠️ Manual login required |
| **Production Ready** | ✅ Yes | ⚠️ Requires maintenance |
| **Rate Limits** | Standard API limits | Same |
| **Use Case** | Server-to-server | Local development |

**Recommendation**: Use OAuth 2.0 for production workloads.

## Implementation Status

- ✅ OAuth 2.0 credential schema defined
- ⏳ Token provider implementation pending
- ⏳ Test playbook ready (requires token provider)
- ⏳ Integration testing pending

## Next Steps

To complete implementation:

1. **Implement Token Provider** (`noetl/core/auth/ib_provider.py`):
   ```python
   class IBTokenProvider(TokenProvider):
       def _fetch_token_impl(self, audience=None):
           # POST to https://api.ibkr.com/v1/oauth2/token
           # with consumer_key + consumer_secret
           # return access_token
   ```

2. **Register Provider** in `noetl/core/auth/token_manager.py`:
   ```python
   "interactive_brokers_oauth": IBTokenProvider
   ```

3. **Test with Paper Account**:
   - Create OAuth app in IBKR portal
   - Register credentials in NoETL
   - Execute test playbook
   - Verify account data retrieval

## Resources

- [IBKR Client Portal API](https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/)
- [OAuth Documentation](https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#oauth)
- [Paper Trading Account](https://www.interactivebrokers.com/en/index.php?f=1286)
- [API Reference](https://www.interactivebrokers.com/api/doc.html)

## Related Documentation

- [Token Auth Implementation](../../../../docs/token_auth_implementation.md)
- [OAuth Test Setup Guide](../SETUP_GUIDE.md)
- [Credentials Guide](../../../credentials/README.md)

Create `noetl/core/auth/ib_provider.py`:

```python
from typing import Optional
from datetime import datetime, timedelta
from noetl.core.auth.providers import TokenProvider

class IBTokenProvider(TokenProvider):
    """Interactive Brokers OAuth token provider."""
    
    def __init__(self, credential_data: dict):
        self.client_id = credential_data.get('client_id')
        self.client_secret = credential_data.get('client_secret')
        self.token_url = credential_data.get('token_url', 'https://api.ibkr.com/v1/oauth/token')
        self.access_token: Optional[str] = None
        self.token_expiry: Optional[datetime] = None
    
    def _fetch_token_impl(self, audience: Optional[str] = None) -> str:
        """Fetch OAuth token from IB."""
        import requests
        
        response = requests.post(
            self.token_url,
            auth=(self.client_id, self.client_secret),
            data={'grant_type': 'client_credentials'}
        )
        response.raise_for_status()
        
        token_data = response.json()
        self.access_token = token_data['access_token']
        expires_in = token_data.get('expires_in', 3600)
        self.token_expiry = datetime.utcnow() + timedelta(seconds=expires_in - 300)
        
        return self.access_token
    
    def is_token_valid(self) -> bool:
        """Check if current token is still valid."""
        if not self.access_token or not self.token_expiry:
            return False
        return datetime.utcnow() < self.token_expiry
```

### 4. Register Provider

Update `noetl/core/auth/providers.py`:

```python
def get_token_provider(credential_data: Dict) -> TokenProvider:
    """Factory to get appropriate token provider."""
    provider_type = credential_data.get('type', '').lower()
    
    if provider_type in ['google_service_account', 'google_oauth', 'gcp']:
        from noetl.core.auth.google_provider import GoogleTokenProvider
        return GoogleTokenProvider(credential_data)
    
    elif provider_type in ['interactive_brokers_oauth', 'ib_oauth']:
        from noetl.core.auth.ib_provider import IBTokenProvider
        return IBTokenProvider(credential_data)
    
    else:
        raise ValueError(f"Unsupported token provider type: {provider_type}")
```

## API Endpoints

Once implemented, the playbook will test these endpoints:

### Account Information
- `GET /v1/api/portfolio/{accountId}/summary` - Account summary
- `GET /v1/api/portfolio/{accountId}/ledger` - Account ledger
- `GET /v1/api/portfolio/accounts` - List accounts

### Positions & Orders
- `GET /v1/api/portfolio/{accountId}/positions` - Current positions
- `GET /v1/api/iserver/account/orders` - Order status
- `POST /v1/api/iserver/account/orders` - Place order

### Market Data
- `GET /v1/api/md/snapshot` - Market data snapshot
- `GET /v1/api/iserver/marketdata/history` - Historical data

## Testing with Paper Account

```bash
# Set environment variable for paper trading
export IB_ENVIRONMENT=paper
export IB_ACCOUNT_ID=DU1234567

# Execute test playbook
.venv/bin/noetl execute playbook \
  "tests/fixtures/playbooks/oauth/interactive_brokers" \
  --host localhost \
  --port 8083
```

## Resources

- [IB API Documentation](https://www.interactivebrokers.com/api/doc.html)
- [IB OAuth Guide](https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/#oauth)
- [IB Paper Trading](https://www.interactivebrokers.com/en/index.php?f=1286)

## Contributing

To contribute to IB OAuth implementation:

1. Register for IB paper trading account
2. Set up OAuth app in IB portal
3. Implement `IBTokenProvider` class
4. Update credential schema
5. Test with paper trading endpoints
6. Submit PR with tests

## Notes

- IB OAuth requires active paper or live trading account
- Tokens typically expire after 1 hour
- Rate limits apply (check IB documentation)
- Paper trading environment recommended for testing
- Live trading requires additional approvals and agreements

## Timeline

- **Phase 1**: Basic OAuth token generation ⏳
- **Phase 2**: Account and position queries ⏳
- **Phase 3**: Market data access ⏳
- **Phase 4**: Order placement (live trading) ⏳

Stay tuned for updates!
