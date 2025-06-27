import socket
import time
import sys

port = int(sys.argv[1])
print(f"Starting server on port {port}")
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.bind(('localhost', port))
sock.listen(1)
print(f"Server started on port {port}")
sys.stdout.flush()

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("Server stopped")
finally:
    sock.close()
