"""Single entrypoint that runs the whole thing: scheduled sort loop,
scheduled retention sweep, and the Telegram approval listener - all in one
process. This is what the Docker image's CMD runs; see docs/ARCHITECTURE.md
section 11 for the deployment picture.

    mailbox-agent-serve
"""

import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from mailbox_agent import config
from mailbox_agent.logging_config import configure_logging
from mailbox_agent.scripts import run_sort, run_sweep, telegram_bot

logger = logging.getLogger(__name__)


def main():
    configure_logging()
    if config.DRY_RUN:
        logger.warning("DRY_RUN is enabled — retention sweep will only report candidates, not act on them.")

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_sort.run_for_all_accounts,
        trigger=IntervalTrigger(minutes=config.SORT_INTERVAL_MINUTES),
        id="sort_loop",
        next_run_time=datetime.now(),
    )
    scheduler.add_job(
        run_sweep.run_for_all_accounts,
        trigger=CronTrigger(day_of_week=config.SWEEP_DAY_OF_WEEK, hour=config.SWEEP_HOUR),
        id="retention_sweep",
    )
    scheduler.start()
    logger.info(
        "Scheduler started: sort every %dmin, sweep %s at %02d:00",
        config.SORT_INTERVAL_MINUTES,
        config.SWEEP_DAY_OF_WEEK,
        config.SWEEP_HOUR,
    )

    try:
        telegram_bot.poll_forever()  # blocks main thread, keeps the process alive
    except KeyboardInterrupt:
        logger.info("shutting down")
        scheduler.shutdown()


if __name__ == "__main__":
    main()
