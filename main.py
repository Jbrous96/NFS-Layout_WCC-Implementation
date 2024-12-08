#!/usr/bin/env python3
"""
Main application entry point for NFS LAYOUT_WCC implementation.
This ties together all components and provides the primary interface.
"""

import asyncio
import argparse
import logging
import sys
import yaml
from typing import Dict, Any
from pathlib import Path

# Import our components
from nfs_transport import NFSTransportConfig, NFSTransportProtocol
from nfs_server import NFSServerConfig, NFSServerIntegration
from error_recovery import ErrorRecoveryManager, RetryConfig
from performance import PerformanceOptimizer, ConnectionManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class NFSLayoutApplication:
    """Main application class for NFS LAYOUT_WCC"""
    
    def __init__(self, config_path: str):
        self.config = self._load_config(config_path)
        self.transport = None
        self.server = None
        self.error_manager = None
        self.performance_optimizer = None
        self.connection_manager = None
    
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Loads configuration from YAML file"""
        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
            logger.info(f"Configuration loaded from {config_path}")
            return config
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            sys.exit(1)
    
    async def initialize(self):
        """Initializes all components"""
        try:
            # Initialize transport
            transport_config = NFSTransportConfig(**self.config['transport'])
            self.transport = NFSTransportProtocol(transport_config)
            
            # Initialize server integration
            server_config = NFSServerConfig(**self.config['server'])
            self.server = NFSServerIntegration(server_config)
            
            # Initialize error recovery
            retry_config = RetryConfig(**self.config['retry'])
            self.error_manager = ErrorRecoveryManager(retry_config)
            
            # Initialize performance optimization
            self.performance_optimizer = PerformanceOptimizer(
                cache_size=self.config['performance']['cache_size']
            )
            
            # Initialize connection management
            self.connection_manager = ConnectionManager(
                pool_size=self.config['performance']['connection_pool_size'],
                idle_timeout=self.config['performance']['connection_idle_timeout']
            )
            
            # Connect transport
            await self.transport.connect()
            
            # Initialize server
            await self.server.initialize()
            
            logger.info("Application initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize application: {e}")
            await self.cleanup()
            sys.exit(1)
    
    async def cleanup(self):
        """Cleans up all components"""
        try:
            if self.transport:
                await self.transport.close()
            
            if self.server:
                await self.server.cleanup()
            
            if self.connection_manager:
                await self.connection_manager.cleanup()
            
            logger.info("Application cleanup completed")
            
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
    
    async def process_layout_operation(self, operation_data: Dict[str, Any]):
        """Processes a layout operation with full error recovery and optimization"""
        try:
            async def operation():
                # Check cache first
                cache_key = operation_data.get('layout_id')
                if cache_key:
                    cached_result = await self.performance_optimizer.get_cached_layout(cache_key)
                    if cached_result:
                        logger.info(f"Cache hit for layout {cache_key}")
                        return cached_result
                
                # Get connection from pool
                async with self.connection_manager.get_connection(
                    operation_data.get('server_id', 'default')
                ) as conn:
                    # Process layout operation
                    result = await self.server.process_layout_wcc(operation_data)
                    
                    # Cache result if successful
                    if result['status'] == 'success' and cache_key:
                        await self.performance_optimizer.cache_layout(
                            cache_key,
                            result,
                            ttl=self.config['performance']['cache_ttl']
                        )
                    
                    return result
            
            # Execute with error recovery
            result = await self.error_manager.execute_with_recovery(
                operation_data.get('operation_id', 'unknown'),
                operation
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Error processing layout operation: {e}")
            raise

def parse_arguments():
    """Parses command line arguments"""
    parser = argparse.ArgumentParser(description='NFS LAYOUT_WCC Application')
    parser.add_argument(
        '--config',
        type=str,
        default='config.yaml',
        help='Path to configuration file'
    )
    return parser.parse_args()

async def main():
    """Main application entry point"""
    args = parse_arguments()
    
    # Initialize application
    app = NFSLayoutApplication(args.config)
    
    try:
        await app.initialize()
        
        # Start processing operations
        # In a real application, this might involve:
        # - Setting up API endpoints
        # - Starting a message queue consumer
        # - Processing scheduled tasks
        # For this example, we'll just keep the application running
        while True:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Application shutdown requested")
    except Exception as e:
        logger.error(f"Application error: {e}")
    finally:
        await app.cleanup()

if __name__ == "__main__":
    asyncio.run(main())