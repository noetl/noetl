from google.cloud import secretmanager

_client = None

def get_secret_client():
    global _client
    if _client is None:
        _client = secretmanager.SecretManagerServiceClient()
    return _client

def get_secret(secret_name: str, version: str = "latest") -> str:
    client = get_secret_client()
    name = f"{secret_name}/versions/{version}"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")