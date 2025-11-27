# Interactive Brokers Web API - OAuth 2.0 Implementation Guide

Based on the official IBKR REST API documentation (v2.21.0), here's how OAuth 2.0 actually works with Interactive Brokers.

## Important Discovery

IBKR uses **JWT-based client assertion** for OAuth 2.0, which is more sophisticated than simple consumer_key/secret flow. The authentication requires:

1. **Client Assertion JWT**: A signed JWT token containing your OAuth credentials
2. **Token Endpoint**: `/oauth2/api/v1/token`
3. **Grant Type**: `client_credentials` (implied through JWT assertion)

## OAuth 2.0 Flow (Actual Implementation)

### Step 1: Create OAuth Application in IBKR Portal

1. Login to IBKR Client Portal:
   - Paper Trading: https://ndcdyn.interactivebrokers.com/sso/Login  
   - Live Trading: https://www.interactivebrokers.com/sso/Login

2. Navigate to: **Settings → API → OAuth Applications**

3. Create Application:
   ```
   Application Name: NoETL Test
   Application Type: Server Application  
   Redirect URIs: (not needed for client_credentials)
   Scopes: 
     - echo.read
     - echo.write
     (More scopes will be available based on your permissions)
   ```

4. Save and retrieve:
   - **Client ID**
   - **Client Secret**
   - **Private Key** (RSA key for signing JWT assertions)

### Step 2: Token Request Format

**Endpoint**: `POST /oauth2/api/v1/token`

**Content-Type**: `application/x-www-form-urlencoded`

**Request Body**:
```
client_assertion=<SIGNED_JWT>
client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer
```

**Signed JWT Format**:
```json
Header:
{
  "alg": "RS256",
  "kid": "<your_key_id>"
}

Payload:
{
  "iss": "<client_id>",
  "sub": "<client_id>",
  "aud": "https://api.ibkr.com/v1/oauth2/token",
  "exp": <unix_timestamp + 300>,
  "iat": <unix_timestamp>
}
```

Sign with your RSA private key using RS256 algorithm.

### Step 3: Token Response

**Success (200)**:
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "token_type": "Bearer",
  "scope": "echo.read echo.write",
  "expires_in": 86399
}
```

### Step 4: Using the Access Token

Add to HTTP request headers:
```
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc...
```

## API Endpoints

### Authentication
- **Token Generation**: `POST /oauth2/api/v1/token`
- **Auth Status**: `POST /iserver/auth/status`
- **SSO Validation**: `POST /sso/validate`

### Account Management
- **List Accounts**: `GET /gw/api/v1/accounts`
- **Account Details**: `GET /gw/api/v1/accounts/{accountId}/details`
- **Account Status**: `GET /gw/api/v1/accounts/{accountId}/status`
- **Switch Account**: `POST /iserver/account`

### Trading & Portfolio
- **Portfolio Accounts**: `GET /portfolio/accounts` (iserver endpoint)
- **Portfolio Positions**: `GET /portfolio/{accountId}/positions`
- **Portfolio Summary**: `GET /portfolio/{accountId}/summary`
- **Account Ledger**: `GET /portfolio/{accountId}/ledger`

### Market Data
- **Market Data Snapshot**: `GET /iserver/marketdata/snapshot`
- **Market History**: `GET /iserver/marketdata/history`

## NoETL Implementation Requirements

### 1. Token Provider Implementation

Create `noetl/core/auth/ib_provider.py`:

```python
import jwt
import time
from typing import Optional
from datetime import datetime, timedelta
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

class IBTokenProvider(TokenProvider):
    """Interactive Brokers OAuth 2.0 token provider with JWT client assertion."""
    
    def __init__(self, credential_data: dict):
        self.client_id = credential_data.get('client_id')
        self.private_key_pem = credential_data.get('private_key')
        self.key_id = credential_data.get('key_id')
        self.token_url = 'https://api.ibkr.com/v1/oauth2/token'
        self.access_token: Optional[str] = None
        self.token_expiry: Optional[datetime] = None
        
        # Load private key for signing
        self.private_key = serialization.load_pem_private_key(
            self.private_key_pem.encode('utf-8'),
            password=None,
            backend=default_backend()
        )
    
    def _create_client_assertion(self) -> str:
        """Create signed JWT assertion for token request."""
        now = int(time.time())
        
        # JWT header
        headers = {
            'alg': 'RS256',
            'kid': self.key_id
        }
        
        # JWT payload
        payload = {
            'iss': self.client_id,
            'sub': self.client_id,
            'aud': self.token_url,
            'exp': now + 300,  # 5 minutes expiry
            'iat': now
        }
        
        # Sign with RS256
        token = jwt.encode(
            payload,
            self.private_key,
            algorithm='RS256',
            headers=headers
        )
        
        return token
    
    def _fetch_token_impl(self, audience: Optional[str] = None) -> str:
        """Fetch OAuth 2.0 access token from IBKR."""
        import requests
        
        # Create client assertion
        client_assertion = self._create_client_assertion()
        
        # Token request
        response = requests.post(
            self.token_url,
            data={
                'client_assertion': client_assertion,
                'client_assertion_type': 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer'
            },
            headers={'Content-Type': 'application/x-www-form-urlencoded'}
        )
        response.raise_for_status()
        
        token_data = response.json()
        self.access_token = token_data['access_token']
        expires_in = token_data.get('expires_in', 86399)
        
        # Cache with 5 minute buffer
        self.token_expiry = datetime.utcnow() + timedelta(seconds=expires_in - 300)
        
        return self.access_token
    
    def is_token_valid(self) -> bool:
        """Check if current token is still valid."""
        if not self.access_token or not self.token_expiry:
            return False
        return datetime.utcnow() < self.token_expiry
```

### 2. Credential Structure

```json
{
  "name": "ib_oauth",
  "type": "interactive_brokers_oauth",
  "description": "IBKR OAuth 2.0 credentials with JWT client assertion",
  "tags": ["oauth", "ib", "jwt", "paper_trading"],
  "data": {
    "client_id": "your-oauth-client-id",
    "key_id": "your-rsa-key-id",
    "private_key": "-----BEGIN PRIVATE KEY-----\nYOUR_RSA_PRIVATE_KEY\n-----END PRIVATE KEY-----",
    "account_id": "DU8027814",
    "environment": "paper",
    "api_base_url": "https://api.ibkr.com/v1"
  }
}
```

### 3. Paper Trading Account Details

- **Username**: `wzeeym257`
- **Password**: `Test202$`
- **Account ID**: `DU8027814`
- **Environment**: Paper Trading

**Note**: Username/password are ONLY for logging into IBKR portal to create OAuth application. The OAuth flow uses client_id + signed JWT for API authentication.

## Key Differences from Standard OAuth

1. **JWT Signing Required**: Must sign client assertion with RSA private key
2. **No Client Secret in Request**: Client authentication via signed JWT
3. **Short-Lived Assertions**: JWT assertion expires in 5 minutes
4. **Long-Lived Tokens**: Access tokens valid for ~24 hours

## References

- **API Version**: 2.21.0
- **Documentation**: https://www.interactivebrokers.com/campus/ibkr-api-page/web-api/
- **API Reference**: https://ibkrcampus.com/campus/ibkr-api-page/webapi-ref/
- **OAuth Spec**: RFC 7521 (JWT Bearer Token Grant)

## Next Steps

1. Create OAuth application in IBKR portal
2. Download RSA private key
3. Implement IBTokenProvider with JWT signing
4. Test with paper trading account
5. Integrate with NoETL credential system
