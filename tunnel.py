import asyncio
import websockets
import socket
import threading
import json
import uuid
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
import ssl
from urllib.parse import urlparse
import argparse
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class TunnelServer:
    def __init__(self, server_host="0.0.0.0", server_port=8080):
        self.server_host = server_host
        self.server_port = server_port
        self.tunnels = {}
        self.connections = {}
        self.loop = None
        
    async def handle_client(self, websocket):
        """Handle incoming tunnel client connections"""
        connection_id = str(uuid.uuid4())
        self.connections[connection_id] = websocket
        client_info = f"{websocket.remote_address[0]}:{websocket.remote_address[1]}"
        logger.info(f"New client connected: {connection_id} from {client_info}")
        
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    await self.process_message(websocket, connection_id, data)
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON from client {connection_id}: {e}")
                    await websocket.send(json.dumps({
                        'type': 'error',
                        'message': 'Invalid JSON format'
                    }))
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Client disconnected: {connection_id}")
        except Exception as e:
            logger.error(f"Error handling client {connection_id}: {e}")
        finally:
            if connection_id in self.connections:
                del self.connections[connection_id]
            tunnels_to_remove = [tid for tid, info in self.tunnels.items() 
                               if info.get('connection_id') == connection_id]
            for tid in tunnels_to_remove:
                del self.tunnels[tid]
                logger.info(f"Cleaned up tunnel: {tid}")
    
    async def process_message(self, websocket, connection_id, data):
        """Process messages from tunnel clients"""
        msg_type = data.get('type')
        
        if msg_type == 'create_tunnel':
            tunnel_id = str(uuid.uuid4())
            tunnel_info = {
                'id': tunnel_id,
                'connection_id': connection_id,
                'protocol': data.get('protocol', 'http'),
                'local_port': data.get('local_port'),
                'local_host': data.get('local_host', 'localhost'),
                'client_websocket': websocket,
                'client_ip': websocket.remote_address[0]
            }
            
            self.tunnels[tunnel_id] = tunnel_info
            
            # Start appropriate proxy
            if tunnel_info['protocol'] == 'http':
                threading.Thread(
                    target=self.start_http_proxy,
                    args=(tunnel_id,),
                    daemon=True
                ).start()
            elif tunnel_info['protocol'] == 'tcp':
                threading.Thread(
                    target=self.start_tcp_proxy,
                    args=(tunnel_id,),
                    daemon=True
                ).start()
            elif tunnel_info['protocol'] == 'websocket':
                threading.Thread(
                    target=self.start_websocket_proxy,
                    args=(tunnel_id,),
                    daemon=True
                ).start()
            
            response = {
                'type': 'tunnel_created',
                'tunnel_id': tunnel_id,
                'protocol': tunnel_info['protocol']
            }
            await websocket.send(json.dumps(response))
            logger.info(f"Created {tunnel_info['protocol']} tunnel: {tunnel_id} -> {tunnel_info['client_ip']}:{tunnel_info['local_port']}")
        
        elif msg_type == 'http_response':
            # Handle HTTP response from client
            tunnel_id = data.get('tunnel_id')
            request_id = data.get('request_id')
            response_data = data.get('response')
            
            if tunnel_id in self.tunnels:
                tunnel_info = self.tunnels[tunnel_id]
                if 'pending_requests' in tunnel_info and request_id in tunnel_info['pending_requests']:
                    # Send response back to the pending HTTP request
                    tunnel_info['pending_requests'][request_id].put(response_data)
    
    def start_http_proxy(self, tunnel_id):
        """Start HTTP proxy for a tunnel"""
        tunnel_info = self.tunnels.get(tunnel_id)
        if not tunnel_info:
            return
        
        # Add pending requests storage
        tunnel_info['pending_requests'] = {}
        
        class TunnelHTTPHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                logger.info(f"HTTP: {format % args}")
                
            def do_GET(self):
                self.proxy_request('GET')
            
            def do_POST(self):
                self.proxy_request('POST')
            
            def do_PUT(self):
                self.proxy_request('PUT')
            
            def do_DELETE(self):
                self.proxy_request('DELETE')
            
            def proxy_request(self, method):
                try:
                    content_length = int(self.headers.get('Content-Length', 0))
                    body = self.rfile.read(content_length) if content_length > 0 else b''
                    
                    # Create request to send to client
                    request_id = str(uuid.uuid4())
                    request_data = {
                        'type': 'http_request',
                        'tunnel_id': tunnel_id,
                        'request_id': request_id,
                        'method': method,
                        'path': self.path,
                        'headers': dict(self.headers),
                        'body': body.decode('utf-8', errors='ignore') if body else ''
                    }
                    
                    # Send request to client via WebSocket
                    import queue
                    response_queue = queue.Queue()
                    tunnel_info['pending_requests'][request_id] = response_queue
                    
                    async def send_request():
                        try:
                            await tunnel_info['client_websocket'].send(json.dumps(request_data))
                        except Exception as e:
                            logger.error(f"Failed to send request to client: {e}")
                    
                    # Send the request
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(send_request())
                    loop.close()
                    
                    # Wait for response
                    try:
                        response_data = response_queue.get(timeout=30)
                        
                        # Send response back to browser
                        self.send_response(response_data.get('status_code', 200))
                        for header, value in response_data.get('headers', {}).items():
                            if header.lower() not in ['content-encoding', 'transfer-encoding', 'connection']:
                                self.send_header(header, value)
                        self.end_headers()
                        
                        body = response_data.get('body', '')
                        if isinstance(body, str):
                            body = body.encode('utf-8')
                        self.wfile.write(body)
                        
                    except queue.Empty:
                        self.send_error(504, "Gateway Timeout")
                    finally:
                        if request_id in tunnel_info['pending_requests']:
                            del tunnel_info['pending_requests'][request_id]
                    
                except Exception as e:
                    logger.error(f"Proxy error: {e}")
                    self.send_error(502, f"Bad Gateway: {str(e)}")
        
        import random
        proxy_port = random.randint(8082, 9000)
        try:
            server = HTTPServer(('0.0.0.0', proxy_port), TunnelHTTPHandler)
            tunnel_info['proxy_port'] = proxy_port
            
            # Get public host
            if self.server_host != '0.0.0.0':
                public_host = self.server_host
            else:
                try:
                    import socket
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.connect(("8.8.8.8", 80))
                    public_host = s.getsockname()[0]
                    s.close()
                except:
                    public_host = 'localhost'
                    
            tunnel_info['public_url'] = f"http://{public_host}:{proxy_port}"
            
            if self.loop and tunnel_info.get('client_websocket'):
                try:
                    asyncio.run_coroutine_threadsafe(
                        tunnel_info['client_websocket'].send(json.dumps({
                            'type': 'tunnel_updated',
                            'tunnel_id': tunnel_id,
                            'public_url': tunnel_info['public_url']
                        })),
                        self.loop
                    )
                except Exception as e:
                    logger.error(f"Failed to send tunnel update: {e}")
            
            logger.info(f"HTTP proxy started: {tunnel_info['public_url']} -> {tunnel_info['client_ip']}:{tunnel_info['local_port']}")
            server.serve_forever()
        except Exception as e:
            logger.error(f"Failed to start HTTP proxy: {e}")
    
    def start_websocket_proxy(self, tunnel_id):
        """Start WebSocket proxy for a tunnel - placeholder"""
        pass
    
    def start_tcp_proxy(self, tunnel_id):
        """Start TCP proxy for a tunnel - placeholder"""
        pass
    
    async def start_server(self):
        """Start the tunnel server"""
        logger.info(f"Starting tunnel server on {self.server_host}:{self.server_port}")
        self.loop = asyncio.get_running_loop()
        
        try:
            async with websockets.serve(
                self.handle_client, 
                self.server_host, 
                self.server_port,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=10
            ):
                logger.info(f"Tunnel server is running on {self.server_host}:{self.server_port}")
                print("Clients can connect using:")
                if self.server_host == '0.0.0.0':
                    print(f"  ws://YOUR_SERVER_IP:{self.server_port}")
                else:
                    print(f"  ws://{self.server_host}:{self.server_port}")
                print("Press Ctrl+C to stop.")
                await asyncio.Future()
        except KeyboardInterrupt:
            logger.info("Shutting down tunnel server...")
        except Exception as e:
            logger.error(f"Server error: {e}")


class TunnelClient:
    def __init__(self, server_url="ws://localhost:8080"):
        self.server_url = server_url
        self.websocket = None
        self.tunnels = {}
    
    async def connect(self):
        """Connect to tunnel server"""
        try:
            logger.info(f"Connecting to tunnel server: {self.server_url}")
            self.websocket = await websockets.connect(
                self.server_url,
                ping_interval=20,
                ping_timeout=10
            )
            logger.info("✓ Connected to tunnel server successfully!")
            return True
        except Exception as e:
            logger.error(f"✗ Failed to connect to tunnel server: {e}")
            print(f"Make sure the server is running on {self.server_url}")
            return False
    
    async def listen_for_messages(self):
        """Listen for messages from server"""
        try:
            async for message in self.websocket:
                try:
                    data = json.loads(message)
                    await self.handle_message(data)
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON from server: {e}")
        except websockets.exceptions.ConnectionClosed:
            logger.info("Connection to server closed")
        except Exception as e:
            logger.error(f"Error receiving messages: {e}")
    
    async def handle_message(self, data):
        """Handle messages from server"""
        msg_type = data.get('type')
        
        if msg_type == 'tunnel_created':
            print(f"✓ Tunnel created successfully!")
            print(f"  Protocol: {data['protocol']}")
            print(f"  Tunnel ID: {data['tunnel_id']}")
        
        elif msg_type == 'tunnel_updated':
            print(f"✓ Tunnel URL updated: {data['public_url']}")
            
        elif msg_type == 'error':
            print(f"✗ Server error: {data.get('message', 'Unknown error')}")
            
        elif msg_type == 'http_request':
            # Handle HTTP request from server
            await self.handle_http_request(data)
    
    async def handle_http_request(self, request_data):
        """Handle HTTP request forwarded from server"""
        try:
            tunnel_id = request_data['tunnel_id']
            request_id = request_data['request_id']
            method = request_data['method']
            path = request_data['path']
            headers = request_data['headers']
            body = request_data['body']
            
            # Make request to local service
            local_url = f"http://localhost:{self.local_port}{path}"
            
            # Clean up headers
            clean_headers = {}
            for k, v in headers.items():
                if k.lower() not in ['host', 'connection']:
                    clean_headers[k] = v
            
            response = requests.request(
                method=method,
                url=local_url,
                headers=clean_headers,
                data=body.encode('utf-8') if body else None,
                timeout=30,
                allow_redirects=False
            )
            
            # Send response back to server
            response_data = {
                'type': 'http_response',
                'tunnel_id': tunnel_id,
                'request_id': request_id,
                'response': {
                    'status_code': response.status_code,
                    'headers': dict(response.headers),
                    'body': response.content.decode('utf-8', errors='ignore')
                }
            }
            
            await self.websocket.send(json.dumps(response_data))
            logger.info(f"Handled {method} {path} -> {response.status_code}")
            
        except Exception as e:
            logger.error(f"Error handling HTTP request: {e}")
            # Send error response
            error_response = {
                'type': 'http_response',
                'tunnel_id': request_data['tunnel_id'],
                'request_id': request_data['request_id'],
                'response': {
                    'status_code': 502,
                    'headers': {'Content-Type': 'text/plain'},
                    'body': f"Error: {str(e)}"
                }
            }
            await self.websocket.send(json.dumps(error_response))
    
    async def create_tunnel(self, protocol, local_port, local_host="localhost"):
        """Create a new tunnel"""
        if not self.websocket:
            logger.error("Not connected to server")
            return False
        
        self.local_port = local_port
        self.local_host = local_host
            
        message = {
            'type': 'create_tunnel',
            'protocol': protocol,
            'local_port': local_port,
            'local_host': local_host
        }
        
        try:
            await self.websocket.send(json.dumps(message))
            logger.info(f"Requesting {protocol} tunnel for {local_host}:{local_port}...")
            return True
        except Exception as e:
            logger.error(f"Failed to create tunnel: {e}")
            return False


async def run_server(server_host, server_port):
    server = TunnelServer(server_host, server_port)
    await server.start_server()


async def run_client(protocol, local_port, local_host, server_url):
    client = TunnelClient(server_url)
    
    if not await client.connect():
        return
    
    if not await client.create_tunnel(protocol, local_port, local_host):
        return
    
    print("Listening for tunnel updates...")
    await client.listen_for_messages()


def main():
    parser = argparse.ArgumentParser(description='Python Tunneling Service')
    parser.add_argument('mode', choices=['server', 'client'], help='Run as server or client')
    parser.add_argument('--protocol', choices=['http', 'tcp', 'websocket'], default='http', help='Tunnel protocol')
    parser.add_argument('--port', type=int, help='Local port to tunnel (client mode)')
    parser.add_argument('--host', default='localhost', help='Local host to tunnel (client mode)')
    parser.add_argument('--server-url', help='Tunnel server URL for client (e.g., ws://server.com:8080)')
    parser.add_argument('--server-host', default='0.0.0.0', help='Server bind host (server mode)')
    parser.add_argument('--server-port', type=int, default=8080, help='Server bind port (server mode)')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    try:
        if args.mode == 'server':
            print(f"Starting tunnel server...")
            print(f"Binding to: {args.server_host}:{args.server_port}")
            asyncio.run(run_server(args.server_host, args.server_port))
        
        elif args.mode == 'client':
            if not args.port:
                print("Error: --port is required for client mode")
                return
            
            # Determine server URL
            if args.server_url:
                server_url = args.server_url
            else:
                server_url = f"ws://localhost:{args.server_port}"
            
            print(f"Starting tunnel client...")
            print(f"Local service: {args.protocol}://{args.host}:{args.port}")
            print(f"Server: {server_url}")
            print("Press Ctrl+C to stop")
            
            asyncio.run(run_client(args.protocol, args.port, args.host, server_url))
    
    except KeyboardInterrupt:
        print("\nGoodbye!")
    except Exception as e:
        logger.error(f"Error: {e}")


if __name__ == "__main__":
    main()