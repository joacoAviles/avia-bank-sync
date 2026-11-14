"""Scheduler: sincronización diaria en America/Santiago y aviso al runner de Actual."""

from __future__ import annotations

import logging

import httpx
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .engine.sync import SyncInProgress

log = logging.getLogger("avia.scheduler")


class AviaScheduler:
    def __init__(self, settings, service):
        self.settings = settings
        self.service = service
        self._s = BackgroundScheduler(timezone=settings.timezone)

    @property
    def running(self) -> bool:
        return self._s.running

    def start(self) -> None:
        self._s.add_job(
            self.daily,
            CronTrigger(hour=self.settings.daily_sync_hour, minute=self.settings.daily_sync_minute,
                        timezone=self.settings.timezone),
            id="daily-sync", max_instances=1, coalesce=True, misfire_grace_time=6 * 3600,
        )
        self._s.start()
        log.info("scheduler iniciado", extra={"next_run": str(self.next_run_time())})

    def shutdown(self) -> None:
        if self._s.running:
            self._s.shutdown(wait=False)

    def next_run_time(self):
        job = self._s.get_job("daily-sync")
        return job.next_run_time if job else None

    def daily(self) -> None:
        if not self.service.status()["configured"]:
            return
        try:
            res = self.service.engine.run("schedule")
        except SyncInProgress:
            log.info("sincronización diaria omitida: otra en curso")
            return
        self.after_sync(res)

    def after_sync(self, result: dict) -> None:
        """Tras sincronizar los bancos, pedir al runner que Actual importe (vía su propio bank sync)."""
        self._notify(result)
        url = self.settings.actual_runner_url
        if not url or result.get("status") == "failed":
            return
        try:
            r = httpx.post(f"{url.rstrip('/')}/run", timeout=10,
                           headers={"Authorization": f"Bearer {self.settings.api_token}"})
            log.info("runner de Actual notificado", extra={"status_code": r.status_code})
        except httpx.HTTPError as exc:
            log.warning("no se pudo notificar al runner de Actual", extra={"error": str(exc)})

    def _notify(self, result: dict) -> None:
        url = self.settings.notify_webhook_url
        if not url or result.get("status") == "succeeded":
            return
        s = result.get("stats", {})
        msg = f"AVIA Bank Sync: {result.get('status')} — {len(s.get('errors', []))} error(es)"
        try:
            httpx.post(url, content=msg.encode(), timeout=10)  # compatible con ntfy
        except httpx.HTTPError:
            log.warning("webhook de notificación falló")
