import argparse
import logging

from app.database.session import SessionLocal, engine
from app.core.config import validate_production_config, validate_runtime_config
from app.services.job_worker import run_worker


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Mailmind's durable background worker.")
    parser.add_argument("--once", action="store_true", help="Enqueue due rules and process at most one job.")
    parser.add_argument("--poll-interval", type=float, default=3.0)
    args = parser.parse_args()
    validate_runtime_config()
    validate_production_config()
    if engine is None:
        raise RuntimeError("DATABASE_URL must be configured before starting the worker")
    if not 0.1 <= args.poll_interval <= 60:
        raise ValueError("--poll-interval must be between 0.1 and 60 seconds")
    logging.basicConfig(level=logging.INFO)
    run_worker(
        SessionLocal,
        poll_interval_seconds=args.poll_interval,
        once=args.once,
    )


if __name__ == "__main__":
    main()
