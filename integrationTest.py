import pytest
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any
from unittest.mock import Mock, patch
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Import your implementation modules
from nfs_transport import NFSTransportConfig, NFSTransportProtocol
from nfs_server import NFSServerConfig, NFSServerIntegration
from nfs_xdr import XDREncoder, XDRDecoder
from error_recovery import ErrorRecoveryManager, RetryConfig
from performance import PerformanceOptimizer, ConnectionManager

# Test configurations
@pytest.fixture
def transport_config():
    return NFSTransportConfig(
        host="test.example.com",
        port=2049,
        use_ssl=True,
        timeout=5.0,
        max_retries=2,
        retry_delay=0.1
    )

@pytest.fixture
def server_config():
    return NFSServerConfig(
        mount_point="/mnt/test",
        export_path="/exports/test",
        max_connections=10,
        cache_size=100,
        grace_period=30
    )

@pytest.fixture
def sample_layout_data():
    return {
        'mirrors': [
            {
                'mirror_id': 'test_mirror',
                'data_servers': [
                    {
                        'device_id': 'test_device',
                        'state_id': {
                            'seqid': 1,
                            'other': b'test_state_id'
                        },
                        'file_handles': ['handle1'],
                        'attributes': {
                            'size': 1024,
                            'mtime': int(datetime.now().timestamp())
                        }
                    }
                ]
            }
        ]
    }

# Integration Tests
class TestNFSIntegration:
    @pytest.mark.asyncio
    async def test_full_layout_operation(
        self,
        transport_config,
        server_config,
        sample_layout_data
    ):
        """Tests complete layout operation flow"""
        transport = NFSTransportProtocol(transport_config)
        server = NFSServerIntegration(server_config)
        
        try:
            # Initialize components
            await transport.connect()
            await server.initialize()
            
            # Encode layout data
            encoder = XDREncoder()
            encoded_data = encoder.encode_layout_wcc(sample_layout_data)
            
            # Send layout update
            xid, response = await transport.send_layout_wcc(encoded_data)
            
            # Process response
            decoder = XDRDecoder(response)
            decoded_response = decoder.decode_layout_wcc()
            
            # Verify response
            assert decoded_response['status'] == 'success'
            assert 'mirrors' in decoded_response
            
        finally:
            await transport.close()
            await server.cleanup()

    @pytest.mark.asyncio
    async def test_error_recovery(
        self,
        transport_config,
        server_config,
        sample_layout_data
    ):
        """Tests error recovery mechanisms"""
        retry_config = RetryConfig(
            max_retries=3,
            base_delay=0.1,
            max_delay=1.0,
            exponential_base=2.0
        )
        
        error_manager = ErrorRecoveryManager(retry_config)
        
        # Mock failed operation that succeeds on third try
        attempt_count = 0
        
        async def mock_operation():
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:
                raise NFSTransportError("Simulated failure")
            return {"status": "success"}
        
        # Execute with recovery
        result = await error_manager.execute_with_recovery(
            "test_op",
            mock_operation
        )
        
        # Verify results
        assert result["status"] == "success"
        assert attempt_count == 3
        
        # Verify metrics
        metrics = error_manager.operation_metrics["test_op"]
        assert metrics.success
        assert metrics.retries == 2

    @pytest.mark.asyncio
    async def test_performance_optimization(
        self,
        sample_layout_data
    ):
        """Tests performance optimization features"""
        optimizer = PerformanceOptimizer(cache_size=10)
        
        # Test caching
        layout_id = "test_layout"
        
        # Initial cache miss
        cached_result = await optimizer.get_cached_layout(layout_id)
        assert cached_result is None
        
        # Cache layout
        await optimizer.cache_layout(
            layout_id,
            sample_layout_data,
            ttl=1
        )
        
        # Verify cache hit
        cached_result = await optimizer.get_cached_layout(layout_id)
        assert cached_result == sample_layout_data
        
        # Wait for TTL expiration
        await asyncio.sleep(1.1)
        
        # Verify cache miss after expiration
        cached_result = await optimizer.get_cached_layout(layout_id)
        assert cached_result is None

    @pytest.mark.asyncio
    async def test_connection_management(self):
        """Tests connection pooling and management"""
        connection_manager = ConnectionManager(
            pool_size=2,
            idle_timeout=1
        )
        
        try:
            # Test connection acquisition
            async with connection_manager.get_connection("server1") as conn1:
                assert conn1['connected']
                
                # Try getting second connection
                async with connection_manager.get_connection("server1") as conn2:
                    assert conn2['connected']
                    assert conn1 != conn2
                    
                    # Third connection should fail (pool size = 2)
                    with pytest.raises(ConnectionError):
                        async with connection_manager.get_connection("server1"):
                            pass
            
            # Test connection reuse
            async with connection_manager.get_connection("server1") as conn3:
                # Should get a previously created connection
                assert conn3['connected']
            
            # Test connection timeout
            await asyncio.sleep(1.1)  # Wait for idle timeout
            
            # Should get new connection after timeout
            async with connection_manager.get_connection("server1") as conn4:
                assert conn4['connected']
                assert conn4 != conn1
                assert conn4 != conn2
        
        finally:
            await connection_manager.cleanup()

    @pytest.mark.asyncio
    async def test_stress_test(
        self,
        transport_config,
        server_config,
        sample_layout_data
    ):
        """Performs stress testing of the system"""
        transport = NFSTransportProtocol(transport_config)
        server = NFSServerIntegration(server_config)
        optimizer = PerformanceOptimizer(cache_size=1000)
        
        try:
            await transport.connect()
            await server.initialize()
            
            # Perform multiple concurrent operations
            async def single_operation(op_id: int):
                layout_id = f"layout_{op_id}"
                
                # Try cache first
                result = await optimizer.get_cached_layout(layout_id)
                if result is None:
                    # Encode and send
                    encoder = XDREncoder()
                    encoded_data = encoder.encode_layout_wcc(sample_layout_data)
                    xid, response = await transport.send_layout_wcc(encoded_data)
                    
                    # Cache result
                    decoder = XDRDecoder(response)
                    result = decoder.decode_layout_wcc()
                    await optimizer.cache_layout(layout_id, result)
                
                return result
            
            # Execute multiple operations concurrently
            tasks = [
                single_operation(i) for i in range(10)
            ]
            
            results = await asyncio.gather(*tasks)
            
            # Verify results
            for result in results:
                assert result['status'] == 'success'
                assert 'mirrors' in result
        
        finally:
            await transport.close()
            await server.cleanup()

if __name__ == "__main__":
    pytest.main([__file__, "-v"])