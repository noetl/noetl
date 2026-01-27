---
sidebar_position: 5
title: Cloudflare Setup
description: DNS, SSL, and CDN configuration with Cloudflare
---

# Cloudflare Setup Guide

Configure Cloudflare as a DNS provider and CDN/proxy for the NoETL Gateway.

## Overview

Cloudflare provides:
- **DNS Management**: Manage DNS records for your domain
- **CDN/Proxy**: Cache and protect your gateway
- **SSL/TLS**: Free SSL certificates
- **DDoS Protection**: Protect against attacks
- **WAF**: Web Application Firewall rules

## Prerequisites

- Domain registered and nameservers pointed to Cloudflare
- NoETL Gateway deployed with a static IP address
- Cloudflare account (free tier is sufficient)

## DNS Configuration

### Add A Record for Gateway

1. Log into [Cloudflare Dashboard](https://dash.cloudflare.com)
2. Select your domain
3. Go to **DNS** > **Records**
4. Click **Add record**
5. Configure:

| Field | Value |
|-------|-------|
| Type | A |
| Name | gateway |
| IPv4 address | YOUR_STATIC_IP (e.g., 34.46.180.136) |
| Proxy status | Proxied (orange cloud) |
| TTL | Auto |

6. Click **Save**

### DNS Propagation

DNS changes typically propagate within minutes when using Cloudflare. Verify:

```bash
# Check DNS resolution
dig gateway.yourdomain.com

# Should return your static IP (or Cloudflare proxy IP if proxied)
nslookup gateway.yourdomain.com
```

## SSL/TLS Configuration

### Encryption Mode

1. Go to **SSL/TLS** > **Overview**
2. Select encryption mode:

| Mode | Description | When to Use |
|------|-------------|-------------|
| **Off** | No encryption | Never (insecure) |
| **Flexible** | HTTPS to Cloudflare, HTTP to origin | Origin doesn't support HTTPS |
| **Full** | HTTPS to origin (self-signed OK) | Origin has any certificate |
| **Full (strict)** | HTTPS to origin (valid cert required) | Origin has valid certificate |

**Recommended**: Use **Full** if your gateway's LoadBalancer doesn't have a certificate, or **Full (strict)** if using Ingress with managed certificates.

### Edge Certificates

Cloudflare automatically provisions SSL certificates for proxied domains. Verify:

1. Go to **SSL/TLS** > **Edge Certificates**
2. Ensure "Universal SSL" is active
3. Check certificate covers `gateway.yourdomain.com`

### Always Use HTTPS

1. Go to **SSL/TLS** > **Edge Certificates**
2. Enable **Always Use HTTPS**

This redirects all HTTP requests to HTTPS.

## Caching Configuration

### API Caching (Disable)

API endpoints should not be cached. Create a Cache Rule:

1. Go to **Caching** > **Cache Rules**
2. Click **Create rule**
3. Configure:
   - **Rule name**: Bypass API cache
   - **When incoming requests match**:
     - Field: URI Path
     - Operator: starts with
     - Value: `/api`
   - **Then**: Bypass cache
4. Click **Deploy**

### Static Assets (Optional)

If serving static files through gateway, enable caching:

1. Create another Cache Rule
2. Match: URI Path ends with `.js`, `.css`, `.html`
3. Then: Cache with TTL

## Security Configuration

### Firewall Rules

#### Block Bad Bots

1. Go to **Security** > **WAF** > **Custom rules**
2. Create rule:
   - **Name**: Block bad bots
   - **Expression**: `(cf.client.bot)`
   - **Action**: Block

#### Rate Limiting

1. Go to **Security** > **WAF** > **Rate limiting rules**
2. Create rule:
   - **Name**: API rate limit
   - **Expression**: `(http.request.uri.path contains "/api/")`
   - **Requests**: 100 per 10 seconds
   - **Action**: Block

### DDoS Protection

DDoS protection is automatically enabled. Adjust sensitivity:

1. Go to **Security** > **DDoS**
2. Review L7 DDoS settings
3. Adjust if needed (default usually fine)

## CORS Considerations

### Cloudflare and CORS

When Cloudflare proxies requests:
- CORS headers from origin are passed through
- Cloudflare doesn't add or remove CORS headers by default

### Preflight Caching Issue

If CORS preflight (OPTIONS) requests fail after working initially:

**Cause**: Cloudflare may cache the preflight response without CORS headers

**Solution**: Create a Cache Rule to bypass OPTIONS requests:

1. Go to **Caching** > **Cache Rules**
2. Create rule:
   - **Name**: Bypass OPTIONS cache
   - **Expression**: `(http.request.method eq "OPTIONS")`
   - **Then**: Bypass cache
3. Deploy

### Gateway CORS Configuration

Ensure gateway allows Cloudflare-proxied requests:

```yaml
# values.yaml
env:
  corsAllowedOrigins: "https://gateway.yourdomain.com,https://app.yourdomain.com"
```

## Page Rules (Legacy)

For fine-grained control, use Page Rules:

### Bypass Cache for API

1. Go to **Rules** > **Page Rules**
2. Create rule:
   - **URL**: `gateway.yourdomain.com/api/*`
   - **Setting**: Cache Level = Bypass

### Security Level for API

1. Create rule:
   - **URL**: `gateway.yourdomain.com/api/*`
   - **Setting**: Security Level = High

## Monitoring

### Analytics

1. Go to **Analytics** > **Traffic**
2. Monitor:
   - Total requests
   - Cached vs uncached
   - Threats blocked
   - Response codes

### Logs (Enterprise)

Enterprise plans can stream logs to external services:

1. Go to **Analytics** > **Logs**
2. Configure log destination

### Health Checks (Pro+)

1. Go to **Traffic** > **Health Checks**
2. Create check:
   - **Name**: Gateway health
   - **Address**: gateway.yourdomain.com
   - **Path**: /health
   - **Interval**: 60 seconds

## Troubleshooting

### DNS Not Resolving

```bash
# Check Cloudflare nameservers
dig NS yourdomain.com

# Should show Cloudflare nameservers
# Example: xxx.ns.cloudflare.com
```

### SSL Certificate Errors

**Error**: "Invalid SSL certificate"

**Solutions**:
1. Wait for certificate provisioning (up to 24 hours)
2. Check domain is active in Cloudflare
3. Verify SSL mode matches your origin setup

### Gateway Unreachable

**Error**: "Error 521 - Web server is down"

**Cause**: Cloudflare can't reach your origin

**Solutions**:
1. Verify gateway LoadBalancer has external IP
2. Check gateway health: `curl http://YOUR_STATIC_IP/health`
3. Verify firewall rules allow Cloudflare IPs

### Cloudflare IP Ranges

Allow Cloudflare IPs in your firewall:

```bash
# Get current Cloudflare IP ranges
curl https://www.cloudflare.com/ips-v4
curl https://www.cloudflare.com/ips-v6
```

### "Error 522 - Connection Timed Out"

**Cause**: Origin is slow to respond

**Solutions**:
1. Check gateway pod health
2. Increase gateway resources
3. Check network policies in GKE

### "Error 524 - A Timeout Occurred"

**Cause**: Request takes too long (>100s)

**Solutions**:
1. Optimize slow API endpoints
2. Consider async processing for long operations
3. Enterprise: Increase timeout limits

## Best Practices

### Security
- Enable "Always Use HTTPS"
- Set SSL mode to "Full (strict)" when possible
- Enable bot protection
- Configure rate limiting

### Performance
- Use caching rules appropriately
- Enable Brotli compression (Settings > Speed > Optimization)
- Consider Argo Smart Routing (paid feature)

### Reliability
- Set up health checks (Pro+)
- Configure load balancing if multiple origins
- Enable origin error page customization

## Quick Reference

### DNS Record

| Type | Name | Content | Proxy |
|------|------|---------|-------|
| A | gateway | 34.46.180.136 | Proxied |

### Important Settings

| Setting | Location | Recommended Value |
|---------|----------|-------------------|
| SSL Mode | SSL/TLS > Overview | Full |
| Always HTTPS | SSL/TLS > Edge Certificates | On |
| API Cache | Caching > Cache Rules | Bypass |
| OPTIONS Cache | Caching > Cache Rules | Bypass |
