import socket
import json
import logging

logger = logging.getLogger(__name__)

def start_udp_discovery_server(api_port=5000, discovery_port=5001):
    """
    Listens for UDP broadcast packets from the Flutter app on `discovery_port`.
    Replies with the `api_port` so the app knows where to connect.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        sock.bind(('', discovery_port))
        logger.info(f"UDP Discovery server listening on port {discovery_port}")
    except Exception as e:
        logger.error(f"Failed to bind UDP server: {e}")
        return

    while True:
        try:
            data, addr = sock.recvfrom(1024)
            message = data.decode('utf-8').strip()
            
            if message == "DISCOVER_E_COMMERCE_BACKEND":
                logger.info(f"Discovery request received from {addr}")
                response = json.dumps({
                    "status": "ok", 
                    "port": api_port
                })
                # Send reply back to the sender
                sock.sendto(response.encode('utf-8'), addr)
        except Exception as e:
            logger.error(f"UDP Discovery error: {e}")
