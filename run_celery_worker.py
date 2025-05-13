# run_celery_worker.py

import multiprocessing
import subprocess


def main():
    concurrency = multiprocessing.cpu_count()
    subprocess.run(
        [
            "celery",
            "-A",
            "vidx.services.celery.worker.celery",
            "worker",
            "--loglevel=info",
            "--concurrency",
            str(concurrency),
        ]
    )
