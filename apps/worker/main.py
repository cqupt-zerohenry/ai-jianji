"""
Worker entry point — starts an RQ worker consuming from the job queue.
Run this process separately from the API.
"""
import sys
import os
import logging

# Allow importing from monorepo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../../../.env"))

import redis
from rq import Worker, Queue
from apps.api.queue.redis_client import get_redis
from apps.api.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("worker")


def main():
    settings = get_settings()
    r = get_redis()

    logger.info(f"Starting worker, queue: {settings.task_queue_name}")
    logger.info(f"Redis: {settings.redis_url}")

    queues = [Queue(settings.task_queue_name, connection=r)]
    worker = Worker(queues, connection=r)
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
