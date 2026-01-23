"""AWS DynamoDB database strategy implementation."""

from typing import Any, Dict, Optional

import aioboto3
from botocore.exceptions import ClientError

from .base import DatabaseStrategy


class DynamoDBStrategy(DatabaseStrategy):
    """DynamoDB strategy for database operations."""

    def __init__(
        self,
        region: str = "us-east-1",
        endpoint_url: Optional[str] = None,
        table_name: str = "vidx-items",
    ):
        """Initialize DynamoDB strategy.
        
        Args:
            region: AWS region
            endpoint_url: Optional endpoint URL for LocalStack
            table_name: DynamoDB table name
        """
        self.region = region
        self.endpoint_url = endpoint_url
        self.table_name = table_name
        self.session = aioboto3.Session()
        self.dynamodb = None

    async def connect(self) -> None:
        """Establish DynamoDB connection."""
        async with self.session.client("dynamodb", region_name=self.region, endpoint_url=self.endpoint_url) as client:
            # Verify table exists or create it
            try:
                await client.describe_table(TableName=self.table_name)
            except ClientError as e:
                if e.response["Error"]["Code"] == "ResourceNotFoundException":
                    # Create table if it doesn't exist
                    await client.create_table(
                        TableName=self.table_name,
                        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
                        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
                        BillingMode="PAY_PER_REQUEST",
                    )

    async def disconnect(self) -> None:
        """Close DynamoDB connection."""
        pass

    async def health_check(self) -> bool:
        """Check if DynamoDB is healthy."""
        try:
            async with self.session.client("dynamodb", region_name=self.region, endpoint_url=self.endpoint_url) as client:
                await client.describe_table(TableName=self.table_name)
                return True
        except Exception:
            return False

    async def get(self, key: str) -> Optional[Any]:
        """Get item by ID."""
        try:
            async with self.session.resource("dynamodb", region_name=self.region, endpoint_url=self.endpoint_url) as dynamodb:
                table = await dynamodb.Table(self.table_name)
                response = await table.get_item(Key={"id": key})
                return response.get("Item")
        except Exception:
            return None

    async def put(self, key: str, value: Dict[str, Any]) -> None:
        """Put item with key."""
        try:
            async with self.session.resource("dynamodb", region_name=self.region, endpoint_url=self.endpoint_url) as dynamodb:
                table = await dynamodb.Table(self.table_name)
                item = {"id": key, **value}
                await table.put_item(Item=item)
        except Exception:
            pass

    async def update(self, key: str, value: Dict[str, Any]) -> None:
        """Update item with key."""
        try:
            async with self.session.resource("dynamodb", region_name=self.region, endpoint_url=self.endpoint_url) as dynamodb:
                table = await dynamodb.Table(self.table_name)
                # Build update expression
                update_expr = "SET " + ", ".join([f"{k} = :{k}" for k in value.keys()])
                expr_values = {f":{k}": v for k, v in value.items()}
                await table.update_item(
                    Key={"id": key},
                    UpdateExpression=update_expr,
                    ExpressionAttributeValues=expr_values,
                )
        except Exception:
            pass

    async def delete(self, key: str) -> None:
        """Delete item by key."""
        try:
            async with self.session.resource("dynamodb", region_name=self.region, endpoint_url=self.endpoint_url) as dynamodb:
                table = await dynamodb.Table(self.table_name)
                await table.delete_item(Key={"id": key})
        except Exception:
            pass

    async def query(self, query_params: Dict[str, Any]) -> list:
        """Query items by parameters (simplified)."""
        try:
            async with self.session.resource("dynamodb", region_name=self.region, endpoint_url=self.endpoint_url) as dynamodb:
                table = await dynamodb.Table(self.table_name)
                
                # For complex queries, use scan with filter
                if not query_params:
                    response = await table.scan()
                else:
                    # Build filter expression
                    filter_expr = " AND ".join([f"{k} = :{k}" for k in query_params.keys()])
                    expr_values = {f":{k}": v for k, v in query_params.items()}
                    response = await table.scan(
                        FilterExpression=filter_expr,
                        ExpressionAttributeValues=expr_values,
                    )
                
                return response.get("Items", [])
        except Exception:
            return []
