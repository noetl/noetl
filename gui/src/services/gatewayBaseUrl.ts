const trimTrailingSlash = (value: string): string => value.replace(/\/+$/, "");

function isLocalHost(hostname: string): boolean {
  return hostname === "localhost" || hostname === "127.0.0.1";
}

function inferGatewayHostname(hostname: string): string {
  if (hostname === "gateway.mestumre.dev" || hostname.startsWith("gateway.")) {
    return hostname;
  }

  const strippedHost = hostname.replace(/^(www\.|gui\.)/i, "");
  return `gateway.${strippedHost}`;
}

export function resolveGatewayBaseUrl(): string {
  const envValue = import.meta.env.VITE_GATEWAY_URL;
  if (envValue && envValue.trim().length > 0) {
    return trimTrailingSlash(envValue.trim());
  }

  const { hostname, protocol, origin } = window.location;

  if (isLocalHost(hostname)) {
    return "http://localhost:8090";
  }

  const inferredGatewayHost = inferGatewayHostname(hostname);
  if (inferredGatewayHost === hostname) {
    return trimTrailingSlash(origin);
  }

  return trimTrailingSlash(`${protocol}//${inferredGatewayHost}`);
}
