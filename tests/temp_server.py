import socket
import time
import sys
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(message)s')

port = int(sys.argv[1])
logger.info(f"Starting server on port {port}")
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.bind(('localhost', port))
sock.listen(1)
logger.info(f"Server started on port {port}")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    logger.info("Server stopped")
finally:
    sock.close()
