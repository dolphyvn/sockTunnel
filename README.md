Python Tunneling Service
A lightweight tunneling service similar to ngrok that allows you to expose local services through public URLs. Supports HTTP, TCP, and WebSocket protocols.
Features

🌐 HTTP Tunneling - Expose web applications and APIs
🔌 TCP Tunneling - Forward raw TCP connections
🔄 WebSocket Tunneling - Tunnel WebSocket connections
🖥️ Self-hosted - Run your own tunnel server
🚀 Easy to use - Simple command-line interface
🔒 Secure - All connections go through WebSocket with proper authentication

Installation
Requirements

Python 3.8+
Required packages:

bashpip install websockets requests
Download
Save the tunnel script as tunnel.py or clone this repository.
Basic Usage
1. Start the Tunnel Server
Run this on a public server (VPS, cloud instance, etc.) with a public IP:
bashpython tunnel.py server --server-host 0.0.0.0 --server-port 8080
2. Create Tunnels
Run this on your local machine where your service is running:
bashpython tunnel.py client --protocol http --port 8888 --server-url ws://YOUR_SERVER_IP:8080
Complete Examples
Example 1: Tunnel Jupyter Notebook
Scenario: Share your local Jupyter notebook with others
Step 1: Start Jupyter locally
bashjupyter notebook --no-browser --port=8888 --ip=0.0.0.0
# Note the token from the output
Step 2: Start tunnel server (on public server)
bashpython tunnel.py server --server-host 0.0.0.0 --server-port 8080
Step 3: Create HTTP tunnel (on local machine)
bashpython tunnel.py client --protocol http --port 8888 --server-url ws://your-server.com:8080
Step 4: Access from anywhere
http://your-server.com:8234  # Use the URL shown in tunnel output
Example 2: Tunnel Local Web Development
Scenario: Test your local website from mobile or share with team
Step 1: Start your local web server
bash# Using Python's built-in server
python -m http.server 3000

# Or your development server (React, Express, etc.)
npm start  # Usually runs on port 3000
Step 2: Create tunnel
bashpython tunnel.py client --protocol http --port 3000 --server-url ws://your-server.com:8080
Access: http://your-server.com:8156 (example port)
Example 3: Tunnel API Server
Scenario: Test webhooks or share API with external services
Step 1: Start your API server
bash# Express.js API
node server.js  # Port 4000

# Flask API
python app.py  # Port 5000

# FastAPI
uvicorn main:app --port 8000
Step 2: Create tunnel
bashpython tunnel.py client --protocol http --port 8000 --server-url ws://your-server.com:8080
Usage: External services can POST to http://your-server.com:8421/api/webhook
Example 4: Tunnel Database (TCP)
Scenario: Access local database from remote location
Step 1: Local PostgreSQL running on port 5432
bash# Ensure PostgreSQL is running
sudo systemctl start postgresql
Step 2: Create TCP tunnel
bashpython tunnel.py client --protocol tcp --port 5432 --server-url ws://your-server.com:8080
Step 3: Connect remotely
bashpsql -h your-server.com -p 8167 -U username -d database
Example 5: Tunnel WebSocket Service
Scenario: Share real-time WebSocket application
Step 1: WebSocket server (Node.js example)
javascript// server.js
const WebSocket = require('ws');
const wss = new WebSocket.Server({ port: 8080 });

wss.on('connection', function connection(ws) {
  ws.on('message', function incoming(message) {
    console.log('received: %s', message);
    ws.send('Echo: ' + message);
  });
});
Step 2: Create WebSocket tunnel
bashpython tunnel.py client --protocol websocket --port 8080 --server-url ws://your-server.com:8080
Step 3: Connect from client
javascriptconst ws = new WebSocket('ws://your-server.com:8289');
ws.on('message', data => console.log(data));
ws.send('Hello World!');
Example 6: Tunnel SSH Access
Scenario: SSH to local machine from anywhere
Step 1: Ensure SSH is running locally
bashsudo systemctl start ssh  # Port 22
Step 2: Create TCP tunnel
bashpython tunnel.py client --protocol tcp --port 22 --server-url ws://your-server.com:8080
Step 3: SSH through tunnel
bashssh -p 8198 username@your-server.com
Example 7: Multiple Tunnels
Scenario: Tunnel multiple services simultaneously
Terminal 1: Web app
bashpython tunnel.py client --protocol http --port 3000 --server-url ws://your-server.com:8080
Terminal 2: API server
bashpython tunnel.py client --protocol http --port 8000 --server-url ws://your-server.com:8080
Terminal 3: WebSocket service
bashpython tunnel.py client --protocol websocket --port 8080 --server-url ws://your-server.com:8080
Each will get a unique public URL.
Command Line Options
Server Mode
bashpython tunnel.py server [OPTIONS]
OptionDefaultDescription--server-host0.0.0.0IP address to bind server--server-port8080Port for tunnel server--debugFalseEnable debug logging
Client Mode
bashpython tunnel.py client [OPTIONS]
OptionRequiredDescription--protocolNohttp, tcp, or websocket (default: http)--portYesLocal port to tunnel--hostNoLocal host (default: localhost)--server-urlNoTunnel server WebSocket URL--debugNoEnable debug logging
Server Setup Examples
Cloud Providers
AWS EC2
bash# Launch EC2 instance with public IP
# Security Group: Allow inbound on port 8080 and 8082-9000

# On EC2 instance:
python tunnel.py server --server-host 0.0.0.0 --server-port 8080
DigitalOcean Droplet
bash# Create droplet with public IP
# Firewall: Allow TCP 8080, 8082-9000

# On droplet:
python tunnel.py server --server-host 0.0.0.0 --server-port 8080
Google Cloud VM
bash# Create VM with external IP
# Firewall rules: Allow tcp:8080,tcp:8082-9000

# On VM:
python tunnel.py server --server-host 0.0.0.0 --server-port 8080
Self-hosted Server
bash# On your server with public IP:
# Open firewall ports
sudo ufw allow 8080
sudo ufw allow 8082:9000/tcp

# Run server
python tunnel.py server --server-host 0.0.0.0 --server-port 8080
Advanced Usage
Custom Ports
bash# Server on custom port
python tunnel.py server --server-port 9000

# Client connecting to custom port
python tunnel.py client --protocol http --port 8888 --server-url ws://server.com:9000
Tunnel Non-localhost Services
bash# Tunnel service running on different local IP
python tunnel.py client --protocol http --port 8080 --host 192.168.1.100 --server-url ws://server.com:8080
Debug Mode
bash# Enable detailed logging
python tunnel.py server --debug
python tunnel.py client --protocol http --port 8888 --server-url ws://server.com:8080 --debug
Common Use Cases
Use CaseProtocolExample CommandWeb DevelopmenthttpShare localhost:3000 React appAPI TestinghttpExpose REST API for webhooksDatabase AccesstcpAccess local PostgreSQL/MySQLSSH AccesstcpSSH to local machine remotelyReal-time AppswebsocketShare WebSocket chat appIoT DevelopmenttcpExpose local MQTT brokerGame DevelopmenttcpShare local game serverJupyter NotebookshttpShare data science work
Troubleshooting
Connection Issues
Problem: Client can't connect to server
✗ Failed to connect to tunnel server: [Errno 111] Connection refused
Solutions:

Check server is running: netstat -tulpn | grep 8080
Verify firewall allows port 8080
Check server IP address is correct
Ensure no other service uses port 8080

HTTP 502 Bad Gateway
Problem: Tunnel shows 502 errors
HTTP: "GET / HTTP/1.1" 502 -
Solutions:

Verify local service is running: netstat -tulpn | grep 8888
Check local service accepts connections: curl http://localhost:8888
Use --host 0.0.0.0 when starting local service

Port Already in Use
Problem: Server won't start
OSError: [Errno 98] Address already in use
Solutions:

Use different port: --server-port 8081
Kill existing process: sudo fuser -k 8080/tcp
Check what's using port: sudo lsof -i :8080

WebSocket Connection Errors
Problem: Invalid upgrade errors
websockets.exceptions.InvalidUpgrade: invalid Connection header: keep-alive
Solution: This is normal - browsers/bots trying HTTP on WebSocket endpoint. Tunnel still works.
Security Considerations

🔒 Use HTTPS/WSS in production - Add TLS termination
🔑 Add authentication - Implement token-based auth
🚫 Restrict access - Use firewall rules
📝 Monitor logs - Watch for suspicious activity
🔄 Rotate credentials - Change server regularly

Performance Tips

💾 Use SSD storage on tunnel server
🌐 Choose server location close to users
📊 Monitor bandwidth usage
⚡ Use CDN for static content
🔧 Tune TCP settings for high-throughput

License
MIT License - feel free to use in personal and commercial projects.

Questions? Open an issue or contribute improvements!
