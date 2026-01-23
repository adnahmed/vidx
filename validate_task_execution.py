"""
Validation script to ensure all new modules import correctly.
Run this to verify the refactoring is complete.

Usage:
    python backend/validate_task_execution.py
"""

import sys
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent
sys.path.insert(0, str(backend_path))


def validate_imports():
    """Validate all new modules can be imported."""
    print("Validating task execution module imports...\n")

    try:
        print("✓ Importing base strategy...")
        from vidx.services.task_execution.base import (
            TaskExecutionStrategy,
            VideoProcessingContext,
        )

        print("✓ Importing AWS Batch executor...")
        from vidx.services.task_execution.aws_batch import AWSBatchExecutor

        print("✓ Importing local executor...")
        from vidx.services.task_execution.local_process import LocalProcessExecutor

        print("✓ Importing factory...")
        from vidx.services.task_execution.factory import ExecutionStrategyFactory

        print("✓ Importing manager...")
        from vidx.services.task_execution.manager import TaskExecutionManager

        print("✓ Importing package...")
        from vidx.services import task_execution

        print("✓ Importing refactored tasks...")
        from vidx.services.celery.tasks import (
            merge_videos,
            _merge_videos_sync,
            mime_to_codecs,
            get_execution_manager,
        )

        return True

    except ImportError as e:
        print(f"✗ Import error: {e}")
        return False
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        return False


def validate_interfaces():
    """Validate strategy interface is properly implemented."""
    print("\n\nValidating interface implementations...\n")

    from vidx.services.task_execution.base import TaskExecutionStrategy
    from vidx.services.task_execution.aws_batch import AWSBatchExecutor
    from vidx.services.task_execution.local_process import LocalProcessExecutor

    strategies = [
        ("LocalProcessExecutor", LocalProcessExecutor()),
        ("AWSBatchExecutor", AWSBatchExecutor(
            aws_region="us-east-1",
            batch_job_queue="test",
            batch_job_definition="test",
            s3_bucket="test",
            endpoint_url="http://localhost:4566"
        )),
    ]

    for name, strategy in strategies:
        required_methods = [
            "submit_merge_task",
            "get_task_status",
            "cancel_task",
            "is_available",
            "get_name",
        ]

        missing = [m for m in required_methods if not hasattr(strategy, m)]

        if missing:
            print(f"✗ {name} missing methods: {missing}")
            return False
        else:
            print(f"✓ {name} implements all required methods")

    return True


def validate_settings():
    """Validate new settings are available."""
    print("\n\nValidating settings configuration...\n")

    try:
        from vidx.settings import settings

        required_settings = [
            "batch_enabled",
            "batch_job_queue",
            "batch_job_definition",
            "task_execution_strategy",
        ]

        missing = [s for s in required_settings if not hasattr(settings, s)]

        if missing:
            print(f"✗ Missing settings: {missing}")
            return False

        print(f"✓ All Batch settings configured:")
        for setting in required_settings:
            value = getattr(settings, setting)
            print(f"  - {setting}: {value}")

        return True

    except Exception as e:
        print(f"✗ Settings error: {e}")
        return False


def validate_factory():
    """Validate factory can create strategies."""
    print("\n\nValidating ExecutionStrategyFactory...\n")

    try:
        from vidx.services.task_execution.factory import ExecutionStrategyFactory

        # Test local creation
        local_strategy = ExecutionStrategyFactory.create_strategy(
            environment="dev",
            ffmpeg_binary="/usr/bin/ffmpeg"
        )
        print(f"✓ Created local strategy: {local_strategy.get_name()}")

        # Test AWS Batch creation (won't connect to AWS, just instantiate)
        batch_strategy = ExecutionStrategyFactory.create_strategy(
            environment="prod",
            aws_region="us-east-1",
            batch_job_queue="test",
            batch_job_definition="test",
            s3_bucket="test",
            aws_endpoint_url="http://localhost:4566"
        )
        print(f"✓ Created Batch strategy: {batch_strategy.get_name()}")

        return True

    except Exception as e:
        print(f"✗ Factory error: {e}")
        return False


def main():
    """Run all validations."""
    print("=" * 60)
    print("Task Execution Module Validation")
    print("=" * 60)

    checks = [
        ("Imports", validate_imports),
        ("Interfaces", validate_interfaces),
        ("Settings", validate_settings),
        ("Factory", validate_factory),
    ]

    results = []
    for name, check in checks:
        try:
            result = check()
            results.append((name, result))
        except Exception as e:
            print(f"\n✗ {name} validation failed: {e}")
            results.append((name, False))

    # Summary
    print("\n" + "=" * 60)
    print("VALIDATION SUMMARY")
    print("=" * 60)

    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")

    all_passed = all(r for _, r in results)

    if all_passed:
        print("\n✓ All validations passed!")
        print("\nNext steps:")
        print("1. Test with LocalStack: docker-compose -f docker-compose.localstack.yml up")
        print("2. Run tests: python -m pytest tests/test_task_execution.py")
        print("3. Deploy: cd terraform && terraform apply -var-file=terraform.prod.tfvars")
        return 0
    else:
        print("\n✗ Some validations failed. Please fix errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
