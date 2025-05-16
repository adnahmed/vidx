# run_celery_worker.py

import multiprocessing
import os
import subprocess


def main():
    concurrency = multiprocessing.cpu_count()

    env = os.environ.copy()
    subprocess.run(
        [
            "celery",
            "-A",
            "vidx.services.celery.worker.celery",
            "worker",
            "--loglevel=info",
            "--concurrency",
            str(concurrency),
        ],
        env=env,
    )


if __name__ == "__main__":
    main()
