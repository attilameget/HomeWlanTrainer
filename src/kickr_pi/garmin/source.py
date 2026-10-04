"""Garmin Connect workout source (python-garminconnect)."""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from pathlib import Path
from typing import Any

from kickr_pi.garmin.parser import WorkoutSummary

logger = logging.getLogger(__name__)

CYCLING_KEYS = frozenset(
    {
        "cycling",
        "road_biking",
        "mountain_biking",
        "gravel_cycling",
        "virtual_ride",
        "indoor_cycling",
        "cyclocross",
        "bike",
        "biking",
    }
)


class GarminMfaRequired(Exception):
    """Login needs an MFA code; call login() again with mfa=."""


class GarminAuthError(Exception):
    """Garmin authentication failed."""


class GarminSource:
    """Fetch cycling workouts from Garmin Connect; tokens under token_dir."""

    def __init__(self, token_dir: Path, *, ftp_w: int = 200) -> None:
        self._token_dir = Path(token_dir)
        self._token_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._token_dir.chmod(0o700)
        except OSError:
            pass
        self._ftp_w = ftp_w
        self._client: Any | None = None
        self._authenticated = False
        self._mfa_pending = False
        self._display_name: str | None = None

    @property
    def authenticated(self) -> bool:
        return self._authenticated

    @property
    def display_name(self) -> str | None:
        return self._display_name

    async def try_restore_session(self) -> bool:
        """Load saved tokens if present. Returns True when authenticated."""
        token_file = self._token_dir / "garmin_tokens.json"
        if not token_file.exists():
            return False
        try:
            from garminconnect import Garmin

            client = Garmin()
            await asyncio.to_thread(client.login, str(self._token_dir))
            self._client = client
            self._authenticated = True
            self._mfa_pending = False
            self._display_name = getattr(client, "display_name", None) or getattr(
                client, "full_name", None
            )
            logger.info("Garmin session restored (%s)", self._display_name or "ok")
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Garmin token restore failed: %s", exc)
            self._client = None
            self._authenticated = False
            return False

    async def login(
        self, email: str, password: str, mfa: str | None = None
    ) -> dict[str, Any]:
        """
        Log in with email/password. If MFA is required, returns
        ``{"needs_mfa": True}``; call again with the same credentials + mfa code
        (the in-memory MFA challenge is reused).
        """
        from garminconnect import Garmin
        from garminconnect.exceptions import (
            GarminConnectAuthenticationError,
            GarminConnectTooManyRequestsError,
        )

        token_dir = str(self._token_dir)

        # Complete pending MFA on the same client instance
        if mfa and self._mfa_pending and self._client is not None:
            try:
                await asyncio.to_thread(self._client.resume_login, {}, mfa.strip())
                await asyncio.to_thread(self._persist_tokens, self._client, token_dir)
            except Exception as exc:  # noqa: BLE001
                # Keep MFA pending so a mistyped code can be retried
                raise GarminAuthError(f"MFA failed: {exc}") from exc
            return self._mark_authenticated(self._client)

        # Fresh password login: do not pass tokenstore (avoids a failed load of
        # missing/stale tokens before SSO). Persist only after success.
        # If MFA code is already known, complete in one shot via prompt_mfa
        if mfa:
            def _prompt() -> str:
                return mfa.strip()

            try:
                client = Garmin(email.strip(), password, prompt_mfa=_prompt)
                await asyncio.to_thread(client.login)
                await asyncio.to_thread(self._persist_tokens, client, token_dir)
            except GarminConnectTooManyRequestsError as exc:
                raise GarminAuthError(
                    "Too many login attempts — wait a few minutes and try again."
                ) from exc
            except GarminConnectAuthenticationError as exc:
                raise GarminAuthError(str(exc)) from exc
            except Exception as exc:  # noqa: BLE001
                raise GarminAuthError(f"Garmin login failed: {exc}") from exc
            return self._mark_authenticated(client)

        try:
            client = Garmin(email.strip(), password, return_on_mfa=True)
            status, _ = await asyncio.to_thread(client.login)
        except GarminConnectTooManyRequestsError as exc:
            raise GarminAuthError(
                "Too many login attempts — wait a few minutes and try again."
            ) from exc
        except GarminConnectAuthenticationError as exc:
            raise GarminAuthError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise GarminAuthError(f"Garmin login failed: {exc}") from exc

        if status == "needs_mfa":
            self._client = client
            self._mfa_pending = True
            self._authenticated = False
            return {"authenticated": False, "needs_mfa": True}

        # return_on_mfa=True skips profile load + token dump on success — finish them
        try:
            await asyncio.to_thread(client._load_profile_and_settings)
            await asyncio.to_thread(self._persist_tokens, client, token_dir)
        except Exception as exc:  # noqa: BLE001
            raise GarminAuthError(f"Garmin login incomplete: {exc}") from exc
        return self._mark_authenticated(client)

    def _mark_authenticated(self, client: Any) -> dict[str, Any]:
        self._client = client
        self._authenticated = True
        self._mfa_pending = False
        self._display_name = getattr(client, "display_name", None) or getattr(
            client, "full_name", None
        )
        return {
            "authenticated": True,
            "needs_mfa": False,
            "display_name": self._display_name,
        }

    @staticmethod
    def _persist_tokens(client: Any, token_dir: str) -> None:
        try:
            client.client.dump(token_dir)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not persist Garmin tokens: %s", exc)

    async def logout(self) -> None:
        if self._client is not None:
            try:
                await asyncio.to_thread(self._client.logout)
            except Exception:  # noqa: BLE001
                pass
        token_file = self._token_dir / "garmin_tokens.json"
        if token_file.exists():
            try:
                token_file.unlink()
            except OSError:
                pass
        self._client = None
        self._authenticated = False
        self._mfa_pending = False
        self._display_name = None

    def _require_client(self) -> Any:
        if not self._client or not self._authenticated:
            raise GarminAuthError("Not logged in to Garmin Connect")
        return self._client

    async def todays_workouts(self) -> list[WorkoutSummary]:
        """Today's cycling sessions from calendar + Garmin Coach adaptive plan."""
        client = self._require_client()
        today = date.today()
        today_str = today.isoformat()
        data = await asyncio.to_thread(
            client.get_scheduled_workouts, today.year, today.month
        )
        items = (data or {}).get("calendarItems") or []
        out: list[WorkoutSummary] = []
        seen: set[str] = set()

        for item in items:
            if (item.get("date") or "") != today_str:
                continue
            summary = _summary_from_calendar_item(item, today_str)
            if summary is None or summary.id in seen:
                continue
            seen.add(summary.id)
            out.append(summary)

        # Fill missing Coach durations from the adaptive plan task list
        if any(w.duration_s is None and w.source == "garmin-coach" for w in out):
            out = await self._enrich_coach_durations(out)

        # Prefer Coach bike sessions first when both coach + library schedule exist
        out.sort(key=lambda w: (0 if w.source == "garmin-coach" else 1, w.name))
        return out

    async def _enrich_coach_durations(
        self, workouts: list[WorkoutSummary]
    ) -> list[WorkoutSummary]:
        client = self._require_client()
        try:
            plans = await asyncio.to_thread(client.get_training_plans)
            plan_list = (plans or {}).get("trainingPlanList") or []
            adaptive = next(
                (
                    p
                    for p in plan_list
                    if str(p.get("trainingPlanCategory") or "").upper() == "FBT_ADAPTIVE"
                ),
                None,
            )
            if not adaptive:
                return workouts
            detail = await asyncio.to_thread(
                client.get_adaptive_training_plan_by_id, adaptive["trainingPlanId"]
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Coach duration enrich failed: %s", exc)
            return workouts

        by_uuid: dict[str, int] = {}
        for task in (detail or {}).get("taskList") or []:
            tw = task.get("taskWorkout") or {}
            uuid = tw.get("workoutUuid")
            dur = tw.get("estimatedDurationInSecs")
            if uuid and dur is not None:
                try:
                    by_uuid[str(uuid)] = int(float(dur))
                except (TypeError, ValueError):
                    pass

        enriched: list[WorkoutSummary] = []
        for w in workouts:
            if w.duration_s is None and w.id in by_uuid:
                enriched.append(
                    WorkoutSummary(
                        id=w.id,
                        name=w.name,
                        sport=w.sport,
                        duration_s=by_uuid[w.id],
                        scheduled_date=w.scheduled_date,
                        source=w.source,
                    )
                )
            else:
                enriched.append(w)
        return enriched

    async def library(self) -> list[WorkoutSummary]:
        client = self._require_client()
        workouts = await asyncio.to_thread(client.get_workouts, 0, 100)
        out: list[WorkoutSummary] = []
        for w in workouts or []:
            if not _is_cycling_workout(w):
                continue
            wid = w.get("workoutId") or w.get("id")
            if wid is None:
                continue
            out.append(
                WorkoutSummary(
                    id=str(wid),
                    name=str(w.get("workoutName") or w.get("name") or f"Workout {wid}"),
                    sport="cycling",
                    duration_s=_duration_from_workout(w),
                    scheduled_date=None,
                    source="garmin",
                )
            )
        return out

    async def get_workout(self, source_id: str) -> dict[str, Any]:
        client = self._require_client()
        sid = source_id.strip()
        if _looks_like_uuid(sid):
            raw = await asyncio.to_thread(
                client.connectapi, f"/workout-service/fbt-adaptive/{sid}"
            )
        else:
            raw = await asyncio.to_thread(client.get_workout_by_id, sid)
        if not isinstance(raw, dict):
            raise GarminAuthError(f"Unexpected workout payload for id={source_id}")
        return raw

    def require_client(self) -> Any:
        """Expose authenticated client for plan sync (raises if logged out)."""
        return self._require_client()

    async def recent_activities(
        self, *, lookback_days: int = 28
    ) -> list[dict[str, Any]]:
        """Fetch recent bike + run activities from Garmin Connect."""
        from datetime import date, timedelta

        client = self._require_client()
        end = date.today()
        start = end - timedelta(days=max(1, lookback_days))
        out: list[dict[str, Any]] = []
        for activity_type in ("cycling", "running"):
            try:
                batch = await asyncio.to_thread(
                    client.get_activities_by_date,
                    start.isoformat(),
                    end.isoformat(),
                    activity_type,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Garmin activities (%s) failed: %s", activity_type, exc
                )
                continue
            if batch:
                out.extend(batch)
        return out


def _looks_like_uuid(value: str) -> bool:
    # Garmin Coach adaptive workouts are identified by UUID, not numeric id
    return value.count("-") >= 4 and not value.isdigit()


def _summary_from_calendar_item(
    item: dict[str, Any], today_str: str
) -> WorkoutSummary | None:
    item_type = str(item.get("itemType") or "")
    if item_type not in ("workout", "fbtAdaptiveWorkout"):
        return None
    if not _is_cycling_calendar_item(item):
        return None

    if item_type == "fbtAdaptiveWorkout":
        wid = item.get("workoutUuid") or item.get("workoutId")
        if not wid:
            return None
        duration = _duration_from_item(item)
        return WorkoutSummary(
            id=str(wid),
            name=str(item.get("title") or item.get("workoutName") or "Coach workout"),
            sport="cycling",
            duration_s=duration,
            scheduled_date=today_str,
            source="garmin-coach",
        )

    wid = item.get("workoutId") or item.get("id")
    if wid is None:
        return None
    return WorkoutSummary(
        id=str(wid),
        name=str(
            item.get("title")
            or item.get("workoutName")
            or item.get("name")
            or f"Workout {wid}"
        ),
        sport="cycling",
        duration_s=_duration_from_item(item),
        scheduled_date=today_str,
        source="garmin",
    )


def _sport_key(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return str(
            value.get("sportTypeKey")
            or value.get("typeKey")
            or value.get("key")
            or ""
        ).lower()
    return str(value).lower()


def _is_cycling_workout(w: dict[str, Any]) -> bool:
    key = _sport_key(w.get("sportType") or w.get("sport"))
    if key in CYCLING_KEYS or "cycl" in key or "bike" in key:
        return True
    return False


def _is_cycling_calendar_item(item: dict[str, Any]) -> bool:
    key = _sport_key(
        item.get("sportTypeKey")
        or item.get("sportType")
        or item.get("sport")
        or item.get("workoutSportType")
        or (item.get("workout") or {}).get("sportType")
    )
    if key in CYCLING_KEYS or "cycl" in key or "bike" in key:
        return True
    # Calendar payload sometimes only has workoutTypeId: 2 = cycling
    wtid = item.get("workoutTypeId") or item.get("sportTypeId")
    if wtid in (2, "2"):
        return True
    # Regular scheduled workouts sometimes omit sport — keep them
    if item.get("itemType") == "workout" and not key and not wtid:
        return True
    return False


def _duration_from_item(item: dict[str, Any]) -> int | None:
    for key in ("duration", "durationInSeconds", "estimatedDurationInSecs"):
        if item.get(key) is not None:
            try:
                return int(float(item[key]))
            except (TypeError, ValueError):
                pass
    return None


def _duration_from_workout(w: dict[str, Any]) -> int | None:
    for key in ("estimatedDurationInSecs", "duration", "totalDuration"):
        if w.get(key) is not None:
            try:
                return int(float(w[key]))
            except (TypeError, ValueError):
                pass
    return None
