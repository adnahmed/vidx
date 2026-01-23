"""Dependency injection container for strategies."""

import os
from typing import Optional

from vidx.services.database.base import DatabaseStrategy
from vidx.services.database.mongodb import MongoDBStrategy
from vidx.services.database.dynamodb import DynamoDBStrategy
from vidx.services.cache.base import CacheStrategy
from vidx.services.cache.redis import RedisStrategy
from vidx.services.cache.elasticache import ElastiCacheStrategy


class ServiceContainer:
    """Dependency injection container for service strategies."""

    _db_strategy: Optional[DatabaseStrategy] = None
    _cache_strategy: Optional[CacheStrategy] = None

    @classmethod
    def get_database_strategy(cls) -> DatabaseStrategy:
        """Get or create database strategy based on configuration.
        
        Environment variables:
            DB_TYPE: 'mongodb' or 'dynamodb' (default: 'mongodb')
            VIDX_DB_HOST: MongoDB host (default: 'localhost')
            VIDX_DB_PORT: MongoDB port (default: 27017)
            VIDX_DB_USER: MongoDB user
            VIDX_DB_PASSWORD: MongoDB password
            VIDX_DB_NAME: MongoDB database (default: 'vidx')
            AWS_REGION: AWS region for DynamoDB (default: 'us-east-1')
            AWS_ENDPOINT_URL: Optional DynamoDB endpoint (for LocalStack)
            DYNAMODB_TABLE_NAME: DynamoDB table name (default: 'vidx-items')
        
        Returns:
            DatabaseStrategy: MongoDB or DynamoDB strategy
        """
        if cls._db_strategy is None:
            db_type = os.getenv("DB_TYPE", "mongodb").lower()

            if db_type == "dynamodb":
                cls._db_strategy = DynamoDBStrategy(
                    region=os.getenv("AWS_REGION", "us-east-1"),
                    endpoint_url=os.getenv("AWS_ENDPOINT_URL"),
                    table_name=os.getenv("DYNAMODB_TABLE_NAME", "vidx-items"),
                )
            else:  # MongoDB (default)
                host = os.getenv("VIDX_DB_HOST", "localhost")
                port = os.getenv("VIDX_DB_PORT", "27017")
                user = os.getenv("VIDX_DB_USER", "vidx")
                password = os.getenv("VIDX_DB_PASSWORD", "vidx")
                db_name = os.getenv("VIDX_DB_NAME", "vidx")

                connection_url = f"mongodb://{user}:{password}@{host}:{port}/{db_name}"
                cls._db_strategy = MongoDBStrategy(connection_url)

        return cls._db_strategy

    @classmethod
    def get_cache_strategy(cls) -> CacheStrategy:
        """Get or create cache strategy based on configuration.
        
        Environment variables:
            CACHE_TYPE: 'redis' or 'elasticache' (default: 'redis')
            REDIS_HOST: Redis host (default: 'localhost')
            REDIS_PORT: Redis port (default: 6379)
            REDIS_DB: Redis database (default: 0)
            REDIS_PASSWORD: Optional Redis password
            ELASTICACHE_ENDPOINT: ElastiCache endpoint
            ELASTICACHE_PORT: ElastiCache port (default: 6379)
            ELASTICACHE_PASSWORD: Optional ElastiCache AUTH token
            ELASTICACHE_SSL: Use SSL for ElastiCache (default: 'true')
        
        Returns:
            CacheStrategy: Redis or ElastiCache strategy
        """
        if cls._cache_strategy is None:
            cache_type = os.getenv("CACHE_TYPE", "redis").lower()

            if cache_type == "elasticache":
                endpoint = os.getenv("ELASTICACHE_ENDPOINT", "localhost")
                port = int(os.getenv("ELASTICACHE_PORT", "6379"))
                password = os.getenv("ELASTICACHE_PASSWORD")
                ssl = os.getenv("ELASTICACHE_SSL", "true").lower() == "true"

                cls._cache_strategy = ElastiCacheStrategy(
                    endpoint=endpoint,
                    port=port,
                    password=password,
                    ssl=ssl,
                )
            else:  # Redis (default)
                host = os.getenv("REDIS_HOST", "localhost")
                port = int(os.getenv("REDIS_PORT", "6379"))
                db = int(os.getenv("REDIS_DB", "0"))
                password = os.getenv("REDIS_PASSWORD")

                cls._cache_strategy = RedisStrategy(
                    host=host,
                    port=port,
                    db=db,
                    password=password,
                )

        return cls._cache_strategy

    @classmethod
    def reset(cls) -> None:
        """Reset strategies (useful for testing)."""
        cls._db_strategy = None
        cls._cache_strategy = None

    @classmethod
    def set_database_strategy(cls, strategy: DatabaseStrategy) -> None:
        """Manually set database strategy (useful for testing)."""
        cls._db_strategy = strategy

    @classmethod
    def set_cache_strategy(cls, strategy: CacheStrategy) -> None:
        """Manually set cache strategy (useful for testing)."""
        cls._cache_strategy = strategy
