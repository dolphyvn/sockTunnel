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
        print(f"New client connected: {connection_id} from {client_info}")
        
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    await self.process_message(websocket, connection_id, data)
                except json.JSONDecodeError as e:
                    print(f"Invalid JSON from client {connection_id}: {e}")
                    await websocket.send(json.dumps({
                        'type': 'error',
                        'message': 'Invalid JSON format'
                    }))
        except websockets.exceptions.ConnectionClosed:
            print(f"Client disconnected: {connection_id}")
        except Exception as e:
            print(f"Error handling client {connection_id}: {e}")
        finally:
            if connection_id in self.connections:
                del self.connections[connection_id]
            tunnels_to_remove = [tid for tid, info in self.tunnels.items() 
                               if info.get('connection_id') == connection_id]
            for tid in tunnels_to_remove:
                del self.tunnels[tid]
                print(f"Cleaned up tunnel: {tid}")
    
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
                'public_url': f"http://{tunnel_id}.tunnel.local:8081",
                'websocket': websocket
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
                'public_url': tunnel_info['public_url'],
                'protocol': tunnel_info['protocol']
            }
            await websocket.send(json.dumps(response))
            print(f"Created {tunnel_info['protocol']} tunnel: {tunnel_info['public_url']} -> {tunnel_info['local_host']}:{tunnel_info['local_port']}")
    
    def start_websocket_proxy(self, tunnel_id):
        """Start WebSocket proxy for a tunnel"""
        tunnel_info = self.tunnels.get(tunnel_id)
        if not tunnel_info:
            return
        
        import random
        proxy_port = random.randint(8082, 9000)
        
        async def websocket_proxy_handler(websocket):
            """Handle incoming WebSocket connections and proxy to local service"""
            # Get the path from the websocket (if available)
            path = getattr(websocket, 'path', '/')
            local_uri = f"ws://{tunnel_info['local_host']}:{tunnel_info['local_port']}{path}"
            print(f"WebSocket connection: {websocket.remote_address} -> {local_uri}")
            
            try:
                # Connect to local WebSocket service
                async with websockets.connect(local_uri) as local_ws:
                    # Start forwarding messages in both directions
                    async def forward_to_local():
                        try:
                            async for message in websocket:
                                await local_ws.send(message)
                        except websockets.exceptions.ConnectionClosed:
                            pass
                        except Exception as e:
                            print(f"Error forwarding to local: {e}")
                    
                    async def forward_to_client():
                        try:
                            async for message in local_ws:
                                await websocket.send(message)
                        except websockets.exceptions.ConnectionClosed:
                            pass
                        except Exception as e:
                            print(f"Error forwarding to client: {e}")
                    
                    # Run both forwarding tasks concurrently
                    await asyncio.gather(
                        forward_to_local(),
                        forward_to_client(),
                        return_exceptions=True
                    )
            
            except Exception as e:
                print(f"WebSocket proxy error: {e}")
                try:
                    await websocket.close(code=1011, reason="Proxy error")
                except:
                    pass
        
        async def start_ws_server():
            try:
                async with websockets.serve(websocket_proxy_handler, '0.0.0.0', proxy_port):
                    tunnel_info['proxy_port'] = proxy_port
                    # Use the server's external IP/hostname for public URL
                    public_host = self.server_host if self.server_host != '0.0.0.0' else 'localhost'
                    tunnel_info['public_url'] = f"ws://{public_host}:{proxy_port}"
                    
                    # Update client with real URL
                    if self.loop and tunnel_info.get('websocket'):
                        try:
                            asyncio.run_coroutine_threadsafe(
                                tunnel_info['websocket'].send(json.dumps({
                                    'type': 'tunnel_updated',
                                    'tunnel_id': tunnel_id,
                                    'public_url': tunnel_info['public_url']
                                })),
                                self.loop
                            )
                        except Exception as e:
                            print(f"Failed to send tunnel update: {e}")
                    
                    print(f"WebSocket proxy started: {tunnel_info['public_url']} -> ws://{tunnel_info['local_host']}:{tunnel_info['local_port']}")
                    await asyncio.Future()  # Run forever
            except Exception as e:
                print(f"Failed to start WebSocket proxy: {e}")
        
        # Run the WebSocket server in a new event loop
        def run_ws_server():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(start_ws_server())
            except Exception as e:
                print(f"WebSocket server loop error: {e}")
            finally:
                loop.close()
        
        threading.Thread(target=run_ws_server, daemon=True).start()
    
    def start_http_proxy(self, tunnel_id):
        """Start HTTP proxy for a tunnel"""
        tunnel_info = self.tunnels.get(tunnel_id)
        if not tunnel_info:
            return
        
        class TunnelHTTPHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass
                
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
                    
                    local_url = f"http://{tunnel_info['local_host']}:{tunnel_info['local_port']}{self.path}"
                    
                    headers = dict(self.headers)
                    headers.pop('Host', None)
                    
                    response = requests.request(
                        method=method,
                        url=local_url,
                        headers=headers,
                        data=body,
                        timeout=30,
                        allow_redirects=False
                    )
                    
                    self.send_response(response.status_code)
                    for header, value in response.headers.items():
                        if header.lower() not in ['content-encoding', 'transfer-encoding', 'connection']:
                            self.send_header(header, value)
                    self.end_headers()
                    self.wfile.write(response.content)
                    
                    print(f"Proxied {method} {self.path} -> {response.status_code}")
                    
                except requests.exceptions.ConnectionError:
                    self.send_error(502, "Bad Gateway: Could not connect to local service")
                except requests.exceptions.Timeout:
                    self.send_error(504, "Gateway Timeout")
                except Exception as e:
                    print(f"Proxy error: {e}")
                    self.send_error(502, f"Bad Gateway: {str(e)}")
        
        import random
        proxy_port = random.randint(8082, 9000)
        try:
            server = HTTPServer(('0.0.0.0', proxy_port), TunnelHTTPHandler)
            tunnel_info['proxy_port'] = proxy_port
            # Use the server's external IP/hostname for public URL
            public_host = self.server_host if self.server_host != '0.0.0.0' else 'localhost'
            tunnel_info['public_url'] = f"http://{public_host}:{proxy_port}"
            
            if self.loop and tunnel_info.get('websocket'):
                try:
                    asyncio.run_coroutine_threadsafe(
                        tunnel_info['websocket'].send(json.dumps({
                            'type': 'tunnel_updated',
                            'tunnel_id': tunnel_id,
                            'public_url': tunnel_info['public_url']
                        })),
                        self.loop
                    )
                except Exception as e:
                    print(f"Failed to send tunnel update: {e}")
            
            print(f"HTTP proxy started: {tunnel_info['public_url']} -> http://{tunnel_info['local_host']}:{tunnel_info['local_port']}")
            server.serve_forever()
        except Exception as e:
            print(f"Failed to start HTTP proxy: {e}")
    
    def start_tcp_proxy(self, tunnel_id):
        """Start TCP proxy for a tunnel"""
        tunnel_info = self.tunnels.get(tunnel_id)
        if not tunnel_info:
            return
        
        def handle_tcp_client(client_socket, tunnel_info):
            try:
                local_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                local_socket.settimeout(30)
                local_socket.connect((tunnel_info['local_host'], tunnel_info['local_port']))
                
                print(f"TCP connection established: {client_socket.getpeername()} -> {tunnel_info['local_host']}:{tunnel_info['local_port']}")
                
                def forward_data(source, destination, direction):
                    try:
                        while True:
                            data = source.recv(4096)
                            if not data:
                                break
                            destination.send(data)
                    except Exception as e:
                        print(f"TCP forward error ({direction}): {e}")
                    finally:
                        try:
                            source.close()
                            destination.close()
                        except:
                            pass
                
                t1 = threading.Thread(target=forward_data, args=(client_socket, local_socket, "client->local"), daemon=True)
                t2 = threading.Thread(target=forward_data, args=(local_socket, client_socket, "local->client"), daemon=True)
                t1.start()
                t2.start()
                
                t1.join()
                t2.join()
                
            except Exception as e:
                print(f"TCP proxy error: {e}")
            finally:
                try:
                    client_socket.close()
                except:
                    pass
        
        import random
        proxy_port = random.randint(8082, 9000)
        try:
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind(('0.0.0.0', proxy_port))
            server_socket.listen(5)
            
            tunnel_info['proxy_port'] = proxy_port
            # Use the server's external IP/hostname for public URL
            public_host = self.server_host if self.server_host != '0.0.0.0' else 'localhost'
            tunnel_info['public_url'] = f"tcp://{public_host}:{proxy_port}"
            
            if self.loop and tunnel_info.get('websocket'):
                try:
                    asyncio.run_coroutine_threadsafe(
                        tunnel_info['websocket'].send(json.dumps({
                            'type': 'tunnel_updated',
                            'tunnel_id': tunnel_id,
                            'public_url': tunnel_info['public_url']
                        })),
                        self.loop
                    )
                except Exception as e:
                    print(f"Failed to send tunnel update: {e}")
            
            print(f"TCP proxy started: {tunnel_info['public_url']} -> {tunnel_info['local_host']}:{tunnel_info['local_port']}")
            
            while True:
                try:
                    client_socket, addr = server_socket.accept()
                    threading.Thread(
                        target=handle_tcp_client,
                        args=(client_socket, tunnel_info),
                        daemon=True
                    ).start()
                except Exception as e:
                    print(f"TCP server error: {e}")
                    break
        except Exception as e:
            print(f"Failed to start TCP proxy: {e}")
    
    async def start_server(self):
        """Start the tunnel server"""
        print(f"Starting tunnel server on {self.server_host}:{self.server_port}")
        self.loop = asyncio.get_running_loop()
        
        try:
            async with websockets.serve(self.handle_client, self.server_host, self.server_port):
                print(f"Tunnel server is running on {self.server_host}:{self.server_port}")
                print("Clients can connect using:")
                if self.server_host == '0.0.0.0':
                    print(f"  ws://YOUR_SERVER_IP:{self.server_port}")
                else:
                    print(f"  ws://{self.server_host}:{self.server_port}")
                print("Press Ctrl+C to stop.")
                await asyncio.Future()
        except KeyboardInterrupt:
            print("\nShutting down tunnel server...")
        except Exception as e:
            print(f"Server error: {e}")


class TunnelClient:
    def __init__(self, server_url="ws://localhost:8080"):
        self.server_url = server_url
        self.websocket = None
        self.tunnels = {}
    
    async def connect(self):
        """Connect to tunnel server"""
        try:
            print(f"Connecting to tunnel server: {self.server_url}")
            self.websocket = await websockets.connect(self.server_url)
            print(f"✓ Connected to tunnel server successfully!")
            return True
        except Exception as e:
            print(f"✗ Failed to connect to tunnel server: {e}")
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
                    print(f"Invalid JSON from server: {e}")
        except websockets.exceptions.ConnectionClosed:
            print("Connection to server closed")
        except Exception as e:
            print(f"Error receiving messages: {e}")
    
    async def handle_message(self, data):
        """Handle messages from server"""
        msg_type = data.get('type')
        
        if msg_type == 'tunnel_created':
            print(f"✓ Tunnel created successfully!")
            print(f"  Public URL: {data['public_url']}")
            print(f"  Protocol: {data['protocol']}")
            print(f"  Tunnel ID: {data['tunnel_id']}")
        
        elif msg_type == 'tunnel_updated':
            print(f"✓ Tunnel URL updated: {data['public_url']}")
            
        elif msg_type == 'error':
            print(f"✗ Server error: {data.get('message', 'Unknown error')}")
    
    async def create_tunnel(self, protocol, local_port, local_host="localhost"):
        """Create a new tunnel"""
        if not self.websocket:
            print("Not connected to server")
            return False
            
        message = {
            'type': 'create_tunnel',
            'protocol': protocol,
            'local_port': local_port,
            'local_host': local_host
        }
        
        try:
            await self.websocket.send(json.dumps(message))
            print(f"Requesting {protocol} tunnel for {local_host}:{local_port}...")
            return True
        except Exception as e:
            print(f"Failed to create tunnel: {e}")
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
    
    args = parser.parse_args()
    
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
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
