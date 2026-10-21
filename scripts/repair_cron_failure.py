"""Keep failed native one-shot reminders visible and disabled for explicit recovery."""
import hashlib
from pathlib import Path
from service import PYTHON

ROOT = Path(__file__).resolve().parents[1]
TARGET = PYTHON.parent / "Lib/site-packages/astrbot/core/cron/manager.py"
ORIGINAL = "3c0a1ff2421b181b4f20632d83ed66f390e61d591e43d54995799fb280e3f5f5"
OLD = '''            if job.run_once and delete_run_once:
                # one-shot: remove after execution regardless of success
                await self.delete_job(job_id)'''
NEW = '''            if job.run_once and delete_run_once:
                if status == "completed":
                    await self.delete_job(job_id)
                else:
                    # Retain failure evidence; never blindly resend uncertain delivery.
                    await self.update_job(job_id, enabled=False, next_run_time=None)'''
CHANGES = [
    (OLD, NEW),
    ('from datetime import datetime, timezone', 'from datetime import datetime, timedelta, timezone'),
    ('            await self.sync_from_db()', '            await self.sync_from_db(recover_interrupted=True)'),
    ('    async def sync_from_db(self) -> None:', '    async def sync_from_db(self, *, recover_interrupted=False) -> None:'),
    ('''            if job.job_type == "basic" and job.job_id not in self._basic_handlers:''',
     '''            if recover_interrupted and job.run_once:
                interrupted = job.status == "running"
                overdue = False
                try:
                    due = getattr(self._build_trigger(job), "run_date", None)
                    overdue = bool(due and due < datetime.now(timezone.utc) - timedelta(seconds=300))
                except CronJobSchedulingError:
                    pass  # The existing scheduling validation below reports malformed jobs.
                if interrupted or overdue:
                    reason = "Execution interrupted; delivery status unknown" if interrupted else "Missed while offline beyond scheduler grace period"
                    await self.db.update_cron_job(job.job_id, enabled=False, status="failed", last_error=reason, next_run_time=None)
                    continue
            if job.job_type == "basic" and job.job_id not in self._basic_handlers:'''),
    ('''        except Exception as e:  # noqa: BLE001
            status = "failed"''',
     '''        except asyncio.CancelledError:
            status = "failed"
            last_error = "Execution cancelled; delivery status unknown"
            raise
        except Exception as e:  # noqa: BLE001
            status = "failed"'''),
    ('''                except CronJobSchedulingError:
                    pass  # The existing scheduling validation below reports malformed jobs.''',
     '''                except (CronJobSchedulingError, ValueError, TypeError):
                    pass  # The existing scheduling validation below reports malformed jobs.'''),
]


def repair():
    original = TARGET.read_bytes()
    current = original.decode("utf-8")
    base = current
    for old, new in reversed(CHANGES):
        if new in base:
            base = base.replace(new, old, 1)
    if hashlib.sha256(base.encode()).hexdigest() != ORIGINAL:
        raise ValueError("Cron manager changed; refusing to overwrite other code")
    corrected = base
    for old, new in CHANGES:
        if corrected.count(old) != 1:
            raise ValueError("Cron source contract changed")
        corrected = corrected.replace(old, new, 1)
    if corrected == current:
        return
    backup = ROOT / "runtime/backups/cron_manager.py.before-failure-retention"
    if not backup.exists():
        backup.write_text(base, encoding="utf-8", newline="")
    TARGET.write_text(corrected, encoding="utf-8", newline="")


if __name__ == "__main__":
    repair()
    print("Failed one-shot reminders retained and disabled; successful tasks retain native cleanup.")
