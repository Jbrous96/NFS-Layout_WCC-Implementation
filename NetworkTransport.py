import asyncio
import struct
import ssl
import logging
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass
from enum import IntEnum

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class NFSVersion(IntEnum):
    """NFS protocol versions"""
    NFSv4_2 = 4.2

class RPCMessageType(IntEnum):
    """RPC message types"""
    CALL = 0
    REPLY = 1

@dataclass
class NFSTransportConfig:
    """Configuration for NFS transport"""
    host: str
    port: int
    use_ssl: bool = True
    timeout: float = 30.0
    max_retries: int = 3
    retry_delay: float = 1.0

class NFSTransportError(Exception):
    """Base class for NFS transport errors"""
    pass

class NFSTransportProtocol:
    """Protocol implementation for NFS transport"""
    
    def __init__(self, config: NFSTransportConfig):
        self.config = config
        self._transport: Optional[asyncio.Transport] = None
        self._protocol: Optional[asyncio.Protocol] = None
        self._connected = False
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._xid_counter = 0
        self._ssl_context = self._create_ssl_context() if config.use_ssl else None
    
    def _create_ssl_context(self) -> ssl.SSLContext:
        """Creates SSL context with appropriate security settings"""
        context = ssl.create_default_context()
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        return context

    async def connect(self) -> None:
        """Establishes connection to NFS server"""
        try:
            if self._ssl_context:
                transport, protocol = await asyncio.get_event_loop().create_connection(
                    lambda: NFSProtocolHandler(self),
                    self.config.host,
                    self.config.port,
                    ssl=self._ssl_context
                )
            else:
                transport, protocol = await asyncio.get_event_loop().create_connection(
                    lambda: NFSProtocolHandler(self),
                    self.config.host,
                    self.config.port
                )
            
            self._transport = transport
            self._protocol = protocol
            self._connected = True
            logger.info(f"Connected to NFS server at {self.config.host}:{self.config.port}")
        
        except Exception as e:
            logger.error(f"Failed to connect to NFS server: {e}")
            raise NFSTransportError(f"Connection failed: {e}")

    async def send_layout_wcc(self, payload: bytes) -> Tuple[int, bytes]:
        """Sends LAYOUT_WCC operation to server"""
        if not self._connected:
            raise NFSTransportError("Not connected to server")

        xid = self._get_next_xid()
        message = self._build_rpc_message(xid, payload)
        
        future = asyncio.Future()
        self._pending_requests[xid] = future
        
        try:
            self._transport.write(message)
            response = await asyncio.wait_for(future, timeout=self.config.timeout)
            return xid, response
        except asyncio.TimeoutError:
            del self._pending_requests[xid]
            raise NFSTransportError("Request timed out")
        except Exception as e:
            del self._pending_requests[xid]
            raise NFSTransportError(f"Failed to send request: {e}")

    def _get_next_xid(self) -> int:
        """Generates next transaction ID"""
        self._xid_counter = (self._xid_counter + 1) % 0xFFFFFFFF
        return self._xid_counter

    def _build_rpc_message(self, xid: int, payload: bytes) -> bytes:
        """Builds RPC message with appropriate headers"""
        # RPC header format:
        # XID (4 bytes)
        # Message Type (4 bytes)
        # RPC Version (4 bytes)
        # Program Number (4 bytes)
        # Program Version (4 bytes)
        # Procedure Number (4 bytes)
        header = struct.pack(
            "!IIIIII",
            xid,                    # XID
            RPCMessageType.CALL,    # Message Type
            2,                      # RPC Version
            100003,                 # NFS Program Number
            4,                      # NFSv4
            0                       # LAYOUT_WCC Procedure
        )
        
        return header + payload

    def handle_response(self, xid: int, data: bytes) -> None:
        """Handles response from server"""
        future = self._pending_requests.get(xid)
        if future and not future.done():
            future.set_result(data)
            del self._pending_requests[xid]

    async def close(self) -> None:
        """Closes the connection"""
        if self._transport:
            self._transport.close()
            self._connected = False
            logger.info("Connection closed")

class NFSProtocolHandler(asyncio.Protocol):
    """Handles low-level protocol operations"""
    
    def __init__(self, transport_protocol: NFSTransportProtocol):
        self.transport_protocol = transport_protocol
        self._buffer = bytearray()
        self._expected_length = None

    def connection_made(self, transport: asyncio.Transport) -> None:
        """Called when connection is established"""
        logger.info("Connection established")

    def data_received(self, data: bytes) -> None:
        """Handles received data"""
        self._buffer.extend(data)
        
        while len(self._buffer) >= 4:
            if self._expected_length is None:
                self._expected_length = struct.unpack("!I", self._buffer[:4])[0]
                self._buffer = self._buffer[4:]
            
            if len(self._buffer) >= self._expected_length:
                message = bytes(self._buffer[:self._expected_length])
                self._buffer = self._buffer[self._expected_length:]
                self._process_message(message)
                self._expected_length = None

    def _process_message(self, message: bytes) -> None:
        """Processes complete message"""
        try:
            xid = struct.unpack("!I", message[:4])[0]
            self.transport_protocol.handle_response(xid, message[4:])
        except Exception as e:
            logger.error(f"Error processing message: {e}")

    def connection_lost(self, exc: Optional[Exception]) -> None:
        """Called when connection is lost"""
        logger.warning(f"Connection lost: {exc}")

# Example usage
async def main():
    config = NFSTransportConfig(
        host="nfs.example.com",
        port=2049,
        use_ssl=True
    )
    
    transport = NFSTransportProtocol(config)
    
    try:
        await transport.connect()
        
        # Example LAYOUT_WCC request
        payload = b"..." # Your actual LAYOUT_WCC payload
        xid, response = await transport.send_layout_wcc(payload)
        
        print(f"Received response for XID {xid}")
        
    finally:
        await transport.close()

if __name__ == "__main__":
    asyncio.run(main())