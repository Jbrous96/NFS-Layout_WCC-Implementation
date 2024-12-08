import asyncio
import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from contextlib import asynccontextmanager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class RetryConfig:
    """Configuration for retry behavior"""
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    exponential_base: float = 2.0

@dataclass
class OperationMetrics:
    """Metrics for operation monitoring"""
    start_time: datetime
    end_time: Optional[datetime] = None
    retries: int = 0
    success: bool = False
    error: Optional[str] = None

class ErrorRecoveryManager:
    """Manages error recovery for NFS operations"""
    
    def __init__(self, retry_config: RetryConfig):
        self.retry_config = retry_config
        self.operation_metrics: Dict[str, OperationMetrics] = {}
        self._lock = asyncio.Lock()
    
    async def execute_with_recovery(
        self, 
        operation_id: str,
        operation,
        *args,
        **kwargs
    ) -> Any:
        """Executes operation with automatic error recovery"""
        metrics = OperationMetrics(start_time=datetime.now())
        self.operation_metrics[operation_id] = metrics
        
        try:
            for attempt in range(self.retry_config.max_retries):
                try:
                    result = await operation(*args, **kwargs)
                    metrics.success = True
                    return result
                
                except (NFSTransportError, NFSStateError) as e:
                    metrics.retries += 1
                    if attempt == self.retry_config.max_retries - 1:
                        metrics.error = str(e)
                        raise
                    
                    # Calculate delay with exponential backoff
                    delay = min(
                        self.retry_config.base_delay * (
                            self.retry_config.exponential_base ** attempt
                        ),
                        self.retry_config.max_delay
                    )
                    
                    logger.warning(
                        f"Operation {operation_id} failed, "
                        f"retrying in {delay} seconds..."
                    )
                    
                    await asyncio.sleep(delay)
        
        finally:
            metrics.end_time = datetime.now()

class PerformanceOptimizer:
    """Manages performance optimization features"""
    
    def __init__(self, cache_size: int = 10000):
        self.cache = LRUCache(cache_size)
        self.metrics = OperationMetrics()
        self._lock = asyncio.Lock()
    
    async def get_cached_layout(
        self, 
        layout_id: str
    ) -> Optional[Dict[str, Any]]:
        """Retrieves layout from cache if available"""
        async with self._lock:
            entry = self.cache.get(layout_id)
            if entry and not self._is_expired(entry):
                return entry['data']
            return None
    
    async def cache_layout(
        self, 
        layout_id: str,
        layout_data: Dict[str, Any],
        ttl: int = 300
    ) -> None:
        """Caches layout data with TTL"""
        async with self._lock:
            self.cache[layout_id] = {
                'data': layout_data,
                'timestamp': datetime.now(),
                'ttl': ttl
            }
    
    def _is_expired(self, entry: Dict[str, Any]) -> bool:
        """Checks if cache entry is expired"""
        age = datetime.now() - entry['timestamp']
        return age.total_seconds() > entry['ttl']

class LRUCache:
    """Least Recently Used Cache implementation"""
    
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.cache: Dict[str, Any] = {}
        self.usage: List[str] = []
    
    def get(self, key: str) -> Optional[Any]:
        """Retrieves item from cache"""
        if key in self.cache:
            self.usage.remove(key)
            self.usage.append(key)
            return self.cache[key]
        return None
    
    def __setitem__(self, key: str, value: Any) -> None:
        """Sets item in cache"""
        if key in self.cache:
            self.usage.remove(key)
        elif len(self.cache) >= self.capacity:
            oldest = self.usage.pop(0)
            del self.cache[oldest]
        
        self.cache[key] = value
        self.usage.append(key)

class ConnectionManager:
    """Manages NFS connections with connection pooling"""
    
    def __init__(
        self,
        pool_size: int = 10,
        idle_timeout: int = 300
    ):
        self.pool_size = pool_size
        self.idle_timeout = idle_timeout
        self.active_connections: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()
    
    @asynccontextmanager
    async def get_connection(self, server_id: str):
        """Gets connection from pool or creates new one"""
        connection = None
        try:
            connection = await self._acquire_connection(server_id)
            yield connection
        finally:
            if connection:
                await self._release_connection(server_id, connection)
    
    async def _acquire_connection(self, server_id: str):
        """Acquires connection from pool or creates new one"""
        async with self._lock:
            server_pool = self.active_connections.get(server_id, {})
            
            # Find available connection
            for conn_id, conn_info in server_pool.items():
                if not conn_info['in_use']:
                    if self._is_connection_expired(conn_info):
                        await self._close_connection(conn_info['connection'])
                        continue
                    
                    conn_info['in_use'] = True
                    conn_info['last_used'] = datetime.now()
                    return conn_info['connection']
            
            # Create new connection if pool not full
            if len(server_pool) < self.pool_size:
                connection = await self._create_connection(server_id)
                conn_id = f"conn_{len(server_pool)}"
                server_pool[conn_id] = {
                    'connection': connection,
                    'in_use': True,
                    'created': datetime.now(),
                    'last_used': datetime.now()
                }
                self.active_connections[server_id] = server_pool
                return connection
            
            raise ConnectionError("Connection pool exhausted")
    
    async def _release_connection(self, server_id: str, connection) -> None:
        """Releases connection back to pool"""
        async with self._lock:
            server_pool = self.active_connections.get(server_id, {})
            
            # Find and release connection
            for conn_id, conn_info in server_pool.items():
                if conn_info['connection'] is connection:
                    conn_info['in_use'] = False
                    conn_info['last_used'] = datetime.now()
                    return
    
    async def _create_connection(self, server_id: str):
        """Creates new connection to server"""
        # Implementation would depend on your specific NFS client library
        # This is a placeholder for demonstration
        return {'server_id': server_id, 'connected': True}
    
    async def _close_connection(self, connection) -> None:
        """Closes connection"""
        # Implementation would depend on your specific NFS client library
        pass
    
    def _is_connection_expired(self, conn_info: Dict[str, Any]) -> bool:
        """Checks if connection has exceeded idle timeout"""
        if not conn_info['in_use']:
            idle_time = datetime.now() - conn_info['last_used']
            return idle_time.total_seconds() > self.idle_timeout
        return False
    
    async def cleanup(self) -> None:
        """Cleans up all connections"""
        async with self._lock:
            for server_id, server_pool in self.active_connections.items():
                for conn_info in server_pool.values():
                    await self._close_connection(conn_info['connection'])
            self.active_connections.clear()

# Example usage
async def main():
    # Initialize components
    retry_config = RetryConfig(
        max_retries=3,
        base_delay=1.0,
        max_delay=30.0,
        exponential_base=2.0
    )
    
    error_manager = ErrorRecoveryManager(retry_config)
    performance_optimizer = PerformanceOptimizer(cache_size=10000)
    connection_manager = ConnectionManager(pool_size=10, idle_timeout=300)
    
    try:
        # Example operation with error recovery
        async def sample_operation():
            async with connection_manager.get_connection("server1") as conn:
                # Check cache first
                cached_result = await performance_optimizer.get_cached_layout("layout1")
                if cached_result:
                    return cached_result
                
                # Perform operation
                result = {"some": "data"}  # Placeholder
                
                # Cache result
                await performance_optimizer.cache_layout("layout1", result)
                return result
        
        # Execute with error recovery
        result = await error_manager.execute_with_recovery(
            "op1",
            sample_operation
        )
        
        print(f"Operation completed successfully: {result}")
        
    except Exception as e:
        print(f"Operation failed: {e}")
    
    finally:
        # Cleanup
        await connection_manager.cleanup()

if __name__ == "__main__":
    asyncio.run(main())