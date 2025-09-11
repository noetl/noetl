import os
import uuid
import datetime
from typing import Dict, Any, Optional
from jinja2 import Environment
import httpx
import boto3
from botocore.exceptions import ClientError
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from noetl.logger import setup_logger
import json
import base64
import time
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
from Crypto.Hash import SHA256

logger = setup_logger(__name__, include_location=True)


def obtain_gcp_token(scopes=None, credentials_path: str | None = None, use_metadata: bool = False, service_account_secret: str | None = None, credentials_info: Any | None = None) -> Dict[str, Any]:
    """
    Blocking helper to obtain a GCP access token using service account JSON or ADC.
    """
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request as GARequest
        import google.auth
        import google.auth.transport.requests as ga_transport
        import os
        import os.path
        import json
        import base64

        if not scopes:
            scope_list = ["https://www.googleapis.com/auth/cloud-platform"]
        elif isinstance(scopes, str):
            scope_list = [scopes]
        else:
            scope_list = list(scopes)

        used_sa_file = False
        used_sa_info = False
        creds = None

        if service_account_secret:
            try:
                adc_creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
                adc_creds.refresh(GARequest())
                headers = {"Authorization": f"Bearer {adc_creds.token}"}
                resource_path = service_account_secret.strip()
                if not resource_path.startswith("projects/"):
                    raise ValueError("service_account_secret must be a full resource path: projects/{project}/secrets/{name}/versions/{version}")
                url = f"https://secretmanager.googleapis.com/v1/{resource_path}:access"
                with httpx.Client(timeout=20) as client:
                    resp = client.get(url, headers=headers)
                    resp.raise_for_status()
                    resp_json = resp.json()
                    payload_data = resp_json.get("payload", {}).get("data")
                    if not payload_data:
                        raise ValueError("Secret payload empty or missing")
                    secret_bytes = base64.b64decode(payload_data)
                    credentials_info = json.loads(secret_bytes.decode("utf-8"))
                    used_sa_info = True
            except Exception as gsm_err:
                raise

        if credentials_info is not None and creds is None:
            try:
                if isinstance(credentials_info, str):
                    import json as _json
                    credentials_info = _json.loads(credentials_info)
                creds = service_account.Credentials.from_service_account_info(credentials_info, scopes=scope_list)
                used_sa_info = True
            except Exception as info_err:
                creds = None

        if creds is None and use_metadata:
            try:
                creds, _ = google.auth.default(scopes=scope_list)
            except Exception:
                creds = None

        if creds is None:
            sa_path = credentials_path or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            if sa_path and os.path.exists(sa_path):
                creds = service_account.Credentials.from_service_account_file(sa_path, scopes=scope_list)
                used_sa_file = True

        if creds is None:
            creds, _ = google.auth.default(scopes=scope_list)

        req = GARequest()
        creds.refresh(req)
        expiry = getattr(creds, "expiry", None)
        token = getattr(creds, "token", None)
        if not token:
            raise RuntimeError("No access token in response.")
        return {
            "access_token": token,
            "token_expiry": expiry.isoformat() if expiry else None,
            "scopes": scope_list,
            "used_sa_file": used_sa_file,
            "used_sa_info": used_sa_info,
        }
    except Exception:
        raise

class SecretManager:
    def __init__(self, jinja_env: Environment, mock_mode: bool = False):
        """
        Initialize the SecretManager.

        Args:
            jinja_env: The Jinja2 environment
            mock_mode: Flag to use mock mode for testing
        """
        self.jinja_env = jinja_env
        self.mock_mode = mock_mode

    def render_template(self, template: Any, context: Dict) -> Any:
        """
        Render Jinja2 template.

        Args:
            template: The template to render
            context: The context for rendering

        Returns:
            The rendered template
        """
        if isinstance(template, str) and '{{' in template and '}}' in template:
            try:
                template_obj = self.jinja_env.from_string(template)
                rendered = template_obj.render(**context)
                return rendered
            except Exception as e:
                logger.error(f"Template rendering error: {e}. Template: {template}.")
                return ""
        elif isinstance(template, dict):
            return {k: self.render_template(v, context) for k, v in template.items()}
        elif isinstance(template, list):
            return [self.render_template(item, context) for item in template]
        return template

    def get_secret(self, task_config: Dict, context: Dict, log_event_callback=None) -> Dict:
        """
        Retrieve a secret from the specified provider.

        Args:
            task_config: The task configuration
            context: The context for rendering templates
            log_event_callback: A callback function to log events

        Returns:
            A dictionary of the task result
        """
        task_id = str(uuid.uuid4())
        task_name = task_config.get('task', 'secrets_task')
        start_time = datetime.datetime.now()

        try:
            provider = task_config.get('provider', '').lower()
            raw_secret_name = task_config.get('secret_name', '')
            if raw_secret_name == "{{ workload.secret_name }}" and "workload" in context and "secret_name" in context["workload"]:
                raw_secret_name = context.get("workload", {}).get("secret_name")
            secret_name = self.render_template(raw_secret_name, context)
            if "{{" in secret_name and "}}" in secret_name:
                try:
                    template_obj = self.jinja_env.from_string(secret_name)
                    secret_name = template_obj.render(**context)
                except Exception as e:
                    logger.warning(f"Failed to render secret_name template: {e}.")

            version = self.render_template(task_config.get('version', 'latest'), context)
            project_id = self.render_template(task_config.get('project_id', ''), context)
            region = self.render_template(task_config.get('region', ''), context)
            auth = self.render_template(task_config.get('auth', {}), context)
            api_endpoint = self.render_template(task_config.get('api_endpoint', ''), context)
            logger.info(f"Retrieving secret '{secret_name}' from provider '{provider}'")
            event_id = None
            if log_event_callback:
                event_id = log_event_callback(
                    'task_start', task_id, task_name, 'secrets',
                    'in_progress', 0, context, None,
                    {'provider': provider, 'secret_name': secret_name}, None
                )
            if self.mock_mode:
                response_data = {
                    "secret_value": f"mock-secret-value-for-{secret_name}",
                    "version": version,
                    "provider": provider
                }

                end_time = datetime.datetime.now()
                duration = (end_time - start_time).total_seconds()

                if log_event_callback:
                    log_event_callback(
                        'task_complete', task_id, task_name, 'secrets',
                        'success', duration, context, response_data,
                        {'provider': provider, 'secret_name': secret_name}, event_id
                    )

                return {
                    'id': task_id,
                    'status': 'success',
                    'data': response_data
                }
            else:
                headers = {}
                params = {}
                payload = {}
                if provider == 'google':
                    if not project_id:
                        if secret_name and secret_name.startswith('projects/') and '/secrets/' in secret_name:
                            parts = secret_name.split('/')
                            if len(parts) >= 4 and parts[0] == 'projects' and parts[2] == 'secrets':
                                project_id = parts[1]
                                secret_name = parts[3]

                        if not project_id:
                            project_id = context.get('GOOGLE_CLOUD_PROJECT', '')

                        if not project_id:
                            project_id = os.environ.get('GOOGLE_CLOUD_PROJECT', '')
                            if not project_id:
                                try:
                                    import json
                                    creds_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', '')
                                    if creds_path and os.path.exists(creds_path):
                                        with open(creds_path, 'r') as f:
                                            creds_data = json.load(f)
                                            project_id = creds_data.get('quota_project_id', '')
                                except Exception:
                                    pass

                    if not project_id:
                        raise ValueError("Project ID is required for Google Secret Manager.")

                    if not api_endpoint:
                        api_endpoint = f"https://secretmanager.googleapis.com/v1/projects/{project_id}/secrets/{secret_name}/versions/{version}:access"

                    import google.auth
                    import google.auth.transport.requests

                    try:
                        scopes = ['https://www.googleapis.com/auth/cloud-platform']
                        credentials, _ = google.auth.default(scopes=scopes)
                        auth_req = google.auth.transport.requests.Request()
                        credentials.refresh(auth_req)
                        headers["Authorization"] = f"Bearer {credentials.token}"
                        method = "GET"
                    except Exception as auth_error:
                        raise ValueError(f"Failed to authenticate with Google: {auth_error}")

                elif provider == 'aws':
                    if not region:
                        region = os.environ.get('AWS_REGION', 'us-east-1')
                    try:
                        session = boto3.session.Session()
                        client = session.client(
                            service_name='secretsmanager',
                            region_name=region
                        )

                        get_secret_value_response = client.get_secret_value(
                            SecretId=secret_name,
                            VersionStage=version if version != 'latest' else 'AWSCURRENT'
                        )

                        if 'SecretString' in get_secret_value_response:
                            secret_value = get_secret_value_response['SecretString']
                        else:
                            secret_value = get_secret_value_response['SecretBinary']

                        response_data = {
                            "secret_value": secret_value,
                            "version": get_secret_value_response.get('VersionId', version),
                            "provider": provider
                        }

                        end_time = datetime.datetime.now()
                        duration = (end_time - start_time).total_seconds()

                        if log_event_callback:
                            log_event_callback(
                                'task_complete', task_id, task_name, 'secrets',
                                'success', duration, context, {"status": "success"},
                                {'provider': provider, 'secret_name': secret_name}, event_id
                            )

                        return {
                            'id': task_id,
                            'status': 'success',
                            'data': response_data
                        }

                    except ClientError as e:
                        error_msg = f"AWS Secrets Manager error: {str(e)}"
                        raise ValueError(error_msg)

                elif provider == 'azure':
                    if not api_endpoint:
                        vault_name = task_config.get('vault_name', '')
                        if not vault_name:
                            raise ValueError("Vault name is required for Azure Key Vault")
                        api_endpoint = f"https://{vault_name}.vault.azure.net/secrets/{secret_name}?api-version=7.3"

                    try:
                        credential = DefaultAzureCredential()
                        vault_url = f"https://{task_config.get('vault_name')}.vault.azure.net/"
                        client = SecretClient(vault_url=vault_url, credential=credential)
                        secret = client.get_secret(secret_name, version=None if version == 'latest' else version)

                        response_data = {
                            "secret_value": secret.value,
                            "version": secret.properties.version,
                            "provider": provider
                        }

                        end_time = datetime.datetime.now()
                        duration = (end_time - start_time).total_seconds()

                        if log_event_callback:
                            log_event_callback(
                                'task_complete', task_id, task_name, 'secrets',
                                'success', duration, context, {"status": "success"},
                                {'provider': provider, 'secret_name': secret_name}, event_id
                            )

                        return {
                            'id': task_id,
                            'status': 'success',
                            'data': response_data
                        }

                    except Exception as e:
                        error_msg = f"Azure Key Vault error: {str(e)}"
                        raise ValueError(error_msg)

                elif provider == 'lastpass':
                    if not api_endpoint:
                        api_endpoint = "https://support.lastpass.com/s/document-item?language=en_US&bundleId=lastpass&topicId=LastPass/api_get_user_data.html&_LANG=enus"

                    username = auth.get('username', os.environ.get('LASTPASS_USERNAME', ''))
                    password = auth.get('password', os.environ.get('LASTPASS_PASSWORD', ''))

                    if not username or not password:
                        raise ValueError("Username and password are required for LastPass")
                    headers = {
                        "Content-Type": "application/json"
                    }
                    payload = {
                        "username": username,
                        "password": password,
                        "id": secret_name
                    }
                    method = "POST"

                elif provider in ['gcp_token', 'gcp-token', 'gcp.access_token', 'gcp']:
                    scopes_param = task_config.get('scopes')
                    scopes_val = self.render_template(scopes_param, context) if scopes_param is not None else None
                    creds_path_param = task_config.get('credentials_path')
                    creds_path_val = self.render_template(creds_path_param, context) if creds_path_param is not None else None
                    use_metadata = bool(task_config.get('use_metadata', False))
                    sa_secret_param = task_config.get('service_account_secret')
                    sa_secret_val = self.render_template(sa_secret_param, context) if sa_secret_param is not None else None
                    creds_info_param = task_config.get('credentials_info')
                    creds_info_val = self.render_template(creds_info_param, context) if creds_info_param is not None else None

                    token_info = obtain_gcp_token(
                        scopes=scopes_val,
                        credentials_path=creds_path_val,
                        use_metadata=use_metadata,
                        service_account_secret=sa_secret_val,
                        credentials_info=creds_info_val
                    )

                    response_data = token_info

                    end_time = datetime.datetime.now()
                    duration = (end_time - start_time).total_seconds()

                    if log_event_callback:
                        log_event_callback(
                            'task_complete', task_id, task_name, 'secrets',
                            'success', duration, context, {"status": "success"},
                            {'provider': 'gcp_token', 'secret_name': secret_name}, event_id
                        )

                    return {
                        'id': task_id,
                        'status': 'success',
                        'data': response_data
                    }

                elif provider == 'custom':
                    if not api_endpoint:
                        raise ValueError("API endpoint is required for custom provider")
                    headers = auth.get('headers', {})
                    params = auth.get('params', {})
                    payload = auth.get('payload', {})
                    method = auth.get('method', 'GET').upper()
                    if method in ['GET', 'DELETE']:
                        params['secret_name'] = secret_name
                        if version != 'latest':
                            params['version'] = version
                    else:
                        payload['secret_name'] = secret_name
                        if version != 'latest':
                            payload['version'] = version

                else:
                    raise ValueError(f"Unsupported secret provider: {provider}")
                if provider in ['google', 'custom', 'lastpass']:
                    timeout = task_config.get('timeout', 30)

                    try:
                        with httpx.Client(timeout=timeout) as client:
                            if method == 'GET':
                                response = client.get(api_endpoint, params=params, headers=headers)
                            elif method == 'POST':
                                response = client.post(api_endpoint, json=payload, params=params, headers=headers)
                            else:
                                raise ValueError(f"Unsupported HTTP method for secrets: {method}")

                            response.raise_for_status()

                            try:
                                response_json = response.json()
                            except ValueError:
                                response_json = {"text": response.text}
                            if provider == 'google':
                                secret_value = response_json.get('payload', {}).get('data', '')
                                if isinstance(secret_value, str):
                                    import base64
                                    secret_value = base64.b64decode(secret_value).decode('utf-8')
                            elif provider == 'custom' or provider == 'lastpass':
                                secret_value = response_json.get('secret_value', response_json)

                            response_data = {
                                "secret_value": secret_value,
                                "version": response_json.get('version', version),
                                "provider": provider
                            }

                            end_time = datetime.datetime.now()
                            duration = (end_time - start_time).total_seconds()

                            if log_event_callback:
                                log_event_callback(
                                    'task_complete', task_id, task_name, 'secrets',
                                    'success', duration, context, {"status": "success"},
                                    {'provider': provider, 'secret_name': secret_name}, event_id
                                )

                            return {
                                'id': task_id,
                                'status': 'success',
                                'data': response_data
                            }

                    except httpx.HTTPStatusError as e:
                        if e.response.status_code == 404:
                            logger.warning(f"Secret not found: {secret_name} in project {project_id}. Using fallback value.")
                            secret_value = f"fallback-value-for-{secret_name}"
                            response_data = {
                                "secret_value": secret_value,
                                "version": "fallback",
                                "provider": provider
                            }

                            end_time = datetime.datetime.now()
                            duration = (end_time - start_time).total_seconds()

                            if log_event_callback:
                                log_event_callback(
                                    'task_complete', task_id, task_name, 'secrets',
                                    'success', duration, context, {"status": "success", "used_fallback": True},
                                    {'provider': provider, 'secret_name': secret_name, 'used_fallback': True}, event_id
                                )

                            return {
                                'id': task_id,
                                'status': 'success',
                                'data': response_data
                            }
                        else:
                            error_msg = f"HTTP error: {e.response.status_code} - {e.response.text}"
                            raise ValueError(error_msg)
                    except httpx.RequestError as e:
                        error_msg = f"Request error: {str(e)}"
                        raise ValueError(error_msg)

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Secrets task error: {error_msg}", exc_info=True)
            end_time = datetime.datetime.now()
            duration = (end_time - start_time).total_seconds()

            if log_event_callback:
                log_event_callback(
                    'task_error', task_id, task_name, 'secrets',
                    'error', duration, context, None,
                    {'error': error_msg}, event_id
                )

            return {
                'id': task_id,
                'status': 'error',
                'error': error_msg
            }



def _derive_key(secret: str) -> bytes:
    if not isinstance(secret, (str, bytes)):
        raise ValueError("Encryption key must be str or bytes")
    if isinstance(secret, str):
        secret = secret.encode("utf-8")
    h = SHA256.new()
    h.update(secret)
    return h.digest()  # 32 bytes for AES-256


def encrypt_json(data: Any, secret: Optional[str] = None) -> str:
    """
    Encrypt a JSON-serializable object using AES-256-GCM.
    Returns a JSON string containing iv/tag/ciphertext in base64.
    """
    key_str = secret or os.getenv("NOETL_ENCRYPTION_KEY")
    if not key_str:
        raise RuntimeError("NOETL_ENCRYPTION_KEY is not set; cannot encrypt credentials")

    key = _derive_key(key_str)
    iv = get_random_bytes(12)
    cipher = AES.new(key, AES.MODE_GCM, nonce=iv)

    plaintext = json.dumps(data, separators=(",", ":")).encode("utf-8")
    ciphertext, tag = cipher.encrypt_and_digest(plaintext)

    blob = {
        "version": "n8n-aes-256-gcm",
        "iv": base64.b64encode(iv).decode("ascii"),
        "tag": base64.b64encode(tag).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        "ts": int(time.time()),
    }
    return json.dumps(blob, separators=(",", ":"))


def decrypt_json(blob_str: str, secret: Optional[str] = None) -> Any:
    """
    Decrypt a blob produced by encrypt_json and return the parsed JSON object.
    """
    if not blob_str:
        raise ValueError("Empty encrypted blob")
    key_str = secret or os.getenv("NOETL_ENCRYPTION_KEY")
    if not key_str:
        raise RuntimeError("NOETL_ENCRYPTION_KEY is not set; cannot decrypt credentials")

    try:
        blob = json.loads(blob_str)
        iv = base64.b64decode(blob["iv"]) if isinstance(blob.get("iv"), str) else None
        tag = base64.b64decode(blob["tag"]) if isinstance(blob.get("tag"), str) else None
        ciphertext = base64.b64decode(blob["ciphertext"]) if isinstance(blob.get("ciphertext"), str) else None
    except Exception as e:
        raise ValueError(f"Invalid encrypted blob: {e}")

    key = _derive_key(key_str)
    cipher = AES.new(key, AES.MODE_GCM, nonce=iv)
    plaintext = cipher.decrypt_and_verify(ciphertext, tag)
    return json.loads(plaintext.decode("utf-8"))


def normalize_http_bearer(data: Dict[str, Any]) -> Optional[str]:
    """
    Extract bearer token from a decrypted credential payload.
    """
    if not isinstance(data, dict):
        return None
    for k in ("token", "access_token", "bearer", "value"):
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    inner = data.get("data") if isinstance(data.get("data"), dict) else None
    if inner:
        for k in ("token", "access_token", "bearer", "value"):
            v = inner.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return None


def get_noetl_schema() -> str:
    return os.getenv("NOETL_SCHEMA", "noetl")
