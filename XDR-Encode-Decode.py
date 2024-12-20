import struct
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass
from enum import IntEnum
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class XDRError(Exception):
    """Base class for XDR-related errors"""
    pass

class NFSType(IntEnum):
    """NFS data types for XDR encoding"""
    LAYOUT_WCC = 1
    DEVICEID = 2
    STATEID = 3
    FILEHANDLE = 4
    ATTRIBUTE = 5

@dataclass
class XDRPadding:
    """XDR padding calculator"""
    @staticmethod
    def calculate(length: int) -> int:
        """Calculates required padding to align to 4 bytes"""
        return (4 - (length % 4)) % 4

class XDREncoder:
    """Encodes data structures into XDR format"""
    
    def __init__(self):
        self._buffer = bytearray()
    
    def encode_layout_wcc(self, layout: Dict[str, Any]) -> bytes:
        """Encodes LAYOUT_WCC structure"""
        try:
            # Start with type identifier
            self._encode_uint32(NFSType.LAYOUT_WCC)
            
            # Encode mirrors array
            mirrors = layout.get('mirrors', [])
            self._encode_array(mirrors, self._encode_mirror)
            
            return bytes(self._buffer)
        
        except Exception as e:
            logger.error(f"Error encoding LAYOUT_WCC: {e}")
            raise XDRError(f"Failed to encode LAYOUT_WCC: {e}")

    def _encode_mirror(self, mirror: Dict[str, Any]) -> None:
        """Encodes a mirror structure"""
        # Encode mirror identifier
        self._encode_string(mirror.get('mirror_id', ''))
        
        # Encode data servers array
        servers = mirror.get('data_servers', [])
        self._encode_array(servers, self._encode_data_server)

    def _encode_data_server(self, server: Dict[str, Any]) -> None:
        """Encodes a data server structure"""
        # Encode device ID
        self._encode_deviceid(server.get('device_id', ''))
        
        # Encode state ID
        self._encode_stateid(server.get('state_id', {}))
        
        # Encode file handles
        handles = server.get('file_handles', [])
        self._encode_array(handles, self._encode_filehandle)
        
        # Encode attributes
        self._encode_attributes(server.get('attributes', {}))

    def _encode_deviceid(self, device_id: str) -> None:
        """Encodes device ID"""
        self._encode_uint32(NFSType.DEVICEID)
        self._encode_fixed_opaque(device_id.encode(), 16)  # Device IDs are 16 bytes

    def _encode_stateid(self, state_id: Dict[str, Any]) -> None:
        """Encodes state ID"""
        self._encode_uint32(NFSType.STATEID)
        self._encode_uint32(state_id.get('seqid', 0))
        self._encode_fixed_opaque(
            state_id.get('other', b'').ljust(12, b'\0'),
            12
        )

    def _encode_filehandle(self, handle: str) -> None:
        """Encodes file handle"""
        self._encode_uint32(NFSType.FILEHANDLE)
        self._encode_variable_opaque(handle.encode())

    def _encode_attributes(self, attrs: Dict[str, Any]) -> None:
        """Encodes file attributes"""
        self._encode_uint32(NFSType.ATTRIBUTE)
        
        # Encode attribute mask
        mask = self._calculate_attribute_mask(attrs)
        self._encode_uint32(mask)
        
        # Encode present attributes
        if 'size' in attrs:
            self._encode_uint64(attrs['size'])
        if 'mtime' in attrs:
            self._encode_uint64(int(attrs['mtime']))
        # Add other attributes as needed

    def _encode_uint32(self, value: int) -> None:
        """Encodes 32-bit unsigned integer"""
        self._buffer.extend(struct.pack("!I", value))

    def _encode_uint64(self, value: int) -> None:
        """Encodes 64-bit unsigned integer"""
        self._buffer.extend(struct.pack("!Q", value))

    def _encode_string(self, value: str) -> None:
        """Encodes string with length prefix"""
        encoded = value.encode()
        self._encode_uint32(len(encoded))
        self._buffer.extend(encoded)
        padding = XDRPadding.calculate(len(encoded))
        self._buffer.extend(b'\0' * padding)

    def _encode_fixed_opaque(self, data: bytes, length: int) -> None:
        """Encodes fixed-length opaque data"""
        if len(data) != length:
            raise XDRError(f"Fixed opaque data must be exactly {length} bytes")
        self._buffer.extend(data)

    def _encode_variable_opaque(self, data: bytes) -> None:
        """Encodes variable-length opaque data"""
        self._encode_uint32(len(data))
        self._buffer.extend(data)
        padding = XDRPadding.calculate(len(data))
        self._buffer.extend(b'\0' * padding)

    def _encode_array(self, items: List[Any], encoder_func) -> None:
        """Encodes array of items"""
        self._encode_uint32(len(items))
        for item in items:
            encoder_func(item)

    def _calculate_attribute_mask(self, attrs: Dict[str, Any]) -> int:
        """Calculates attribute mask based on present attributes"""
        mask = 0
        if 'size' in attrs:
            mask |= 0x1
        if 'mtime' in attrs:
            mask |= 0x2
        # Add other attribute bits as needed
        return mask

class XDRDecoder:
    """Decodes XDR format into data structures"""
    
    def __init__(self, data: bytes):
        self._data = data
        self._offset = 0

    def decode_layout_wcc(self) -> Dict[str, Any]:
        """Decodes LAYOUT_WCC structure"""
        try:
            # Verify type identifier
            type_id = self._decode_uint32()
            if type_id != NFSType.LAYOUT_WCC:
                raise XDRError(f"Invalid type identifier: {type_id}")
            
            # Decode mirrors array
            mirrors = self._decode_array(self._decode_mirror)
            
            return {'mirrors': mirrors}
        
        except Exception as e:
            logger.error(f"Error decoding LAYOUT_WCC: {e}")
            raise XDRError(f"Failed to decode LAYOUT_WCC: {e}")

    def _decode_mirror(self) -> Dict[str, Any]:
        """Decodes a mirror structure"""
        mirror_id = self._decode_string()
        servers = self._decode_array(self._decode_data_server)
        
        return {
            'mirror_id': mirror_id,
            'data_servers': servers
        }

    def _decode_data_server(self) -> Dict[str, Any]:
        """Decodes a data server structure"""
        device_id = self._decode_deviceid()
        state_id = self._decode_stateid()
        handles = self._decode_array(self._decode_filehandle)
        attributes = self._decode_attributes()
        
        return {
            'device_id': device_id,
            'state_id': state_id,
            'file_handles': handles,
            'attributes': attributes
        }

    def _decode_deviceid(self) -> str:
        """Decodes device ID"""
        type_id = self._decode_uint32()
        if type_id != NFSType.DEVICEID:
            raise XDRError(f"Invalid device ID type: {type_id}")
        return self._decode_fixed_opaque(16).hex()

    def _decode_stateid(self) -> Dict[str, Any]:
        """Decodes state ID"""
        type_id = self._decode_uint32()
        if type_id != NFSType.STATEID:
            raise XDRError(f"Invalid state ID type: {type_id}")
        
        return {
            'seqid': self._decode_uint32(),
            'other': self._decode_fixed_opaque(12)
        }

    def _decode_filehandle(self) -> str:
        """Decodes file handle"""
        type_id = self._decode_uint32()
        if type_id != NFSType.FILEHANDLE:
            raise XDRError(f"Invalid file handle type: {type_id}")
        return self._decode_variable_opaque().hex()

    def _decode_attributes(self) -> Dict[str, Any]:
        """Decodes file attributes"""
        type_id = self._decode_uint32()
        if type_id != NFSType.ATTRIBUTE:
            raise XDRError(f"Invalid attribute type: {type_id}")
        
        mask = self._decode_uint32()
        attrs = {}
        
        if mask & 0x1:
            attrs['size'] = self._decode_uint64()
        if mask & 0x2:
            attrs['mtime'] = self._decode_uint64()
        # Add other attributes as needed
        
        return attrs

    def _decode_uint32(self) -> int:
        """Decodes 32-bit unsigned integer"""
        value = struct.unpack("!I", self._read_bytes(4))[0]
        return value

    def _decode_uint64(self) -> int:
        """Decodes 64-bit unsigned integer"""
        value = struct.unpack("!Q", self._read_bytes(8))[0]
        return value

    def _decode_string(self) -> str:
        """Decodes string with length prefix"""
        length = self._decode_uint32()
        data = self._read_bytes(length)
        padding = XDRPadding.calculate(length)
        self._skip_bytes(padding)
        return data.decode()

    def _decode_fixed_opaque(self, length: int) -> bytes:
        """Decodes fixed-length opaque data"""
        return self._read_bytes(length)

    def _decode_variable_opaque(self) -> bytes:
        """Decodes variable-length opaque data"""
        length = self._decode_uint32()
        data = self._read_bytes(length)
        padding = XDRPadding.calculate(length)
        self._skip_bytes(padding)
        return data

    def _decode_array(self, decoder_func) -> List[Any]:
        """Decodes array of items"""
        length = self._decode_uint32()
        return [decoder_func() for _ in range(length)]

    def _read_bytes(self, length: int) -> bytes:
        """Reads specified number of bytes"""
        if self._offset + length > len(self._data):
            raise XDRError("Unexpected end of data")
        data = self._data[self._offset:self._offset + length]
        self._offset += length
        return data

    def _skip_bytes(self, length: int) -> None:
        """Skips specified number of bytes"""
        if self._offset + length > len(self._data):
            raise XDRError("Unexpected end of data")
        self._offset += length

# Example usage
def main():
    # Example layout data
    layout_data = {
        'mirrors': [
            {
                'mirror_id': 'mirror1',
                'data_servers': [
                    {
                        'device_id': '0123456789abcdef',
                        'state_id': {
                            'seqid': 1,
                            'other': b'stateidentifier'
                        },
                        'file_handles': ['handle1', 'handle2'],
                        'attributes': {
                            'size': 1024,
                            'mtime': 1638360000
                        }
                    }
                ]
            }
        ]
    }
    
    try:
        # Encode
        encoder = XDREncoder()
        encoded_data = encoder.encode_layout_wcc(layout_data)
        print(f"Encoded data length: {len(encoded_data)} bytes")
        
        # Decode
        decoder = XDRDecoder(encoded_data)
        decoded_data = decoder.decode_layout_wcc()
        print(f"Decoded data: {decoded_data}")
        
    except XDRError as e:
        print(f"XDR error: {e}")

if __name__ == "__main__":
    main()
