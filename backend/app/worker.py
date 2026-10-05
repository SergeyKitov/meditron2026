import logging
import time

from app.application.service import dispatch_once
from app.persistence.db import database


def process_one(sessions):
    # Commit one delivery before claiming the next one. A worker holds at most
    # one outbox row and one case row across this transaction.
    with sessions.begin() as session:
        return dispatch_once(session, limit=1)


def run_iteration(sessions):
    try:
        count = process_one(sessions)
        if count:
            logging.info("outbox_processed=%s", count)
        return count
    except Exception as error:
        # Database errors can contain report values in their message or SQL params.
        logging.error("outbox_iteration_failed error_code=%s", type(error).__name__)
        return 0


def main():
    _, sessions = database()
    logging.basicConfig(level=logging.INFO)
    while True:
        if not run_iteration(sessions):
            time.sleep(0.5)


if __name__ == "__main__":
    main()
