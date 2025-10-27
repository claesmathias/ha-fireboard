# Capturing FireBoard WebSocket Traffic

## Steps to Capture:

1. **Open FireBoard Web App**
   - Go to https://fireboard.io in Chrome/Firefox
   - Log in with your credentials

2. **Open Browser DevTools**
   - Press F12 or right-click → Inspect
   - Go to the **Network** tab
   - Filter by **WS** (WebSocket)

3. **Look for WebSocket Connection**
   - Start a cooking session or view an active device
   - Look for connections to `wss://` or `ws://`
   - Click on the WebSocket connection

4. **Capture the Following:**
   - **Connection URL**: Full WebSocket URL
   - **Headers**: Request Headers (especially Authentication)
   - **Subprotocol**: Look for `Sec-WebSocket-Protocol` header
   - **Messages**: Click on "Messages" tab to see data format

5. **What to Document:**
```
Connection URL: wss://fireboard.io/ws (or similar)

Request Headers:
- Sec-WebSocket-Protocol: mqtt, mqttv3.1, etc.
- Origin: https://fireboard.io
- Cookie: sessionid=...; csrftoken=...
- Authorization: Token ... (if present)

Message Format (example):
→ SUBSCRIBE: fireboard/UUID/temps
← PUBLISH: {"channel": 1, "temp": 225, ...}
```

## What We're Looking For:

1. **Authentication Method**:
   - Is it using cookies?
   - Authorization header?
   - Token in URL params?

2. **Protocol**:
   - Raw WebSocket?
   - MQTT over WebSocket?
   - Something custom?

3. **Topic Structure**:
   - What topics does it subscribe to?
   - Format: `fireboard/{uuid}/temps`?

4. **Message Format**:
   - JSON?
   - Binary/protobuf?
   - MQTT packets?

## Next Steps:

Once captured, paste the information and we'll:
1. Update the MQTT client to match the exact connection method
2. Replicate the authentication
3. Subscribe to the correct topics
4. Parse the message format correctly
