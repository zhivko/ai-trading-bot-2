# YouTube Transcript Proxy Setup Guide

This guide explains how to set up proxies to work around YouTube IP bans when downloading transcripts.

## 🎯 Why Use Proxies?

YouTube blocks IP addresses that make too many transcript requests. Proxies help by:
- Rotating IP addresses
- Masking your real IP
- Distributing requests across multiple IPs

## 🔧 Configuration

Add these environment variables to your `.env` file:

```bash
# Enable proxy usage
USE_YOUTUBE_PROXY=true

# Proxy server details
YOUTUBE_PROXY_URL=your-proxy-server.com:port
YOUTUBE_PROXY_USERNAME=your-username  # Optional
YOUTUBE_PROXY_PASSWORD=your-password  # Optional
```

## 🌐 Proxy Options

### 1. **Free Proxies** (Not Recommended)
```bash
USE_YOUTUBE_PROXY=true
YOUTUBE_PROXY_URL=free-proxy-list.net:8080
```

**⚠️ Warning:** Free proxies are unreliable and often blocked by YouTube.

### 2. **Residential Proxies** (Recommended)
```bash
USE_YOUTUBE_PROXY=true
YOUTUBE_PROXY_URL=proxy-provider.com:8080
YOUTUBE_PROXY_USERNAME=your-account
YOUTUBE_PROXY_PASSWORD=your-password
```

**Popular Providers:**
- Bright Data (formerly Luminati)
- Oxylabs
- Smart Proxy
- GeoSurf
- Storm Proxies

### 3. **Datacenter Proxies**
```bash
USE_YOUTUBE_PROXY=true
YOUTUBE_PROXY_URL=dc-proxy-provider.com:8080
YOUTUBE_PROXY_USERNAME=user
YOUTUBE_PROXY_PASSWORD=pass
```

**Good for:** High-speed, low-cost bulk processing

### 4. **VPN as Proxy**
If you have a VPN, you can use it as a proxy:

```bash
USE_YOUTUBE_PROXY=true
YOUTUBE_PROXY_URL=localhost:1080  # SOCKS5 proxy port
```

## 🛠️ Setting Up Popular Proxy Services

### **Bright Data (Recommended)**
1. Sign up at https://brightdata.com/
2. Create a residential proxy zone
3. Get your proxy details:
```bash
USE_YOUTUBE_PROXY=true
YOUTUBE_PROXY_URL=your-zone.brightdata.com:22225
YOUTUBE_PROXY_USERNAME=your-username
YOUTUBE_PROXY_PASSWORD=your-password
```

### **Oxylabs**
1. Sign up at https://oxylabs.io/
2. Create residential proxy
3. Configuration:
```bash
USE_YOUTUBE_PROXY=true
YOUTUBE_PROXY_URL=pr.oxylabs.io:7777
YOUTUBE_PROXY_USERNAME=customer-username
YOUTUBE_PROXY_PASSWORD=password
```

### **Smart Proxy**
1. Sign up at https://smartproxy.com/
2. Get residential proxy credentials:
```bash
USE_YOUTUBE_PROXY=true
YOUTUBE_PROXY_URL=gate.smartproxy.com:7000
YOUTUBE_PROXY_USERNAME=user-sp123456
YOUTUBE_PROXY_PASSWORD=password
```

## 📊 Expected Results

### **Without Proxy:**
```
YouTube Monitor: IP blocked for transcript nzSFfOfhByI
YouTube Monitor: Failed to get transcript for nzSFfOfhByI
```

### **With Working Proxy:**
```
YouTube Monitor: Using authenticated proxy for transcript nzSFfOfhByI
YouTube Monitor: Downloaded transcript for nzSFfOfhByI (2847 chars)
YouTube Monitor: Generated excerpt with LM Studio (156 chars)
```

## 🔍 Testing Your Proxy

Test your proxy setup:

```bash
# Test HTTP proxy
curl -x http://username:password@proxy-server.com:port https://httpbin.org/ip

# Test HTTPS proxy
curl -x http://username:password@proxy-server.com:port https://httpbin.org/ip
```

## ⚙️ Advanced Configuration

### **Multiple Proxies**
For high-volume processing, use proxy rotation:

```python
# In your environment, you can rotate proxies
YOUTUBE_PROXY_URL=proxy1.com:8080,proxy2.com:8080,proxy3.com:8080
```

### **Proxy Rotation**
Some providers offer automatic rotation:

```bash
# Bright Data rotation
YOUTUBE_PROXY_URL=your-zone.brightdata.com:22225
# Add ?zone=your-zone-name for rotation
```

## 🚨 Troubleshooting

### **Proxy Connection Failed**
```
YouTube Monitor: Error generating excerpt with LM Studio: Connection refused
```
**Solution:** Check proxy credentials and server status

### **Proxy Authentication Failed**
```
HTTP 407 Proxy Authentication Required
```
**Solution:** Verify username/password

### **Proxy Still Blocked**
```
YouTube Monitor: IP blocked for transcript
```
**Solution:** Try a different proxy provider or residential proxies

## 💰 Cost Considerations

### **Proxy Pricing (Approximate)**
- **Free proxies:** $0 (unreliable)
- **Datacenter proxies:** $0.50-2/GB
- **Residential proxies:** $5-15/GB
- **Premium residential:** $10-30/GB

### **Usage Estimate**
- 1 video transcript = ~50KB
- 1000 videos = ~50MB = $0.25-7.50 (depending on proxy type)

## 🔄 Alternative Solutions

If proxies don't work for you:

### **1. Reduce Request Frequency**
```bash
TRANSCRIPT_DELAY=10  # 10 seconds between requests
```

### **2. Use Multiple API Keys**
Rotate between different YouTube API keys:
```bash
YOUTUBE_API_KEY=key1,key2,key3
```

### **3. Process in Batches**
Only process a few videos at a time, wait between batches.

### **4. Use VPN**
Connect through a VPN service for IP rotation.

## 🎯 Best Practices

1. **Start with Residential Proxies** - Most reliable for YouTube
2. **Monitor Success Rate** - Track how many transcripts succeed
3. **Have Fallbacks** - Use video descriptions when transcripts fail
4. **Rotate Proxies** - Don't use the same proxy for too long
5. **Monitor Costs** - Track proxy usage and costs

## 📞 Support

If you need help setting up proxies:
1. Check your proxy provider's documentation
2. Test proxy connectivity manually
3. Verify credentials and server details
4. Try different proxy types if one doesn't work

---

**🎉 With proper proxy setup, you can download YouTube transcripts without IP bans!**
