"""Build a minimal indoor cycling activity FIT file."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fit_tool.fit_file_builder import FitFileBuilder
from fit_tool.profile.messages.activity_message import ActivityMessage
from fit_tool.profile.messages.file_id_message import FileIdMessage
from fit_tool.profile.messages.lap_message import LapMessage
from fit_tool.profile.messages.record_message import RecordMessage
from fit_tool.profile.messages.session_message import SessionMessage
from fit_tool.profile.profile_type import (
    Activity,
    Event,
    EventType,
    FileType,
    Manufacturer,
    Sport,
    SubSport,
)
from fit_tool.utils.conversions import to_seconds_since_1989_epoch

from kickr_pi.rides.models import RideRecording


def write_activity_fit(recording: RideRecording, path: Path) -> None:
    """Write an activity FIT for the recording. Path parent must exist."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_activity_fit(recording))


def build_activity_fit(recording: RideRecording) -> bytes:
    started = _as_utc(recording.started_at)
    ended = _as_utc(recording.ended_at)
    start_ms = int(started.timestamp() * 1000)
    end_ms = int(ended.timestamp() * 1000)
    duration = max(0.0, float(recording.duration_s))
    end_fit = to_seconds_since_1989_epoch(end_ms)

    file_id = FileIdMessage()
    file_id.type = FileType.ACTIVITY
    file_id.manufacturer = Manufacturer.DEVELOPMENT.value
    file_id.product = 0
    file_id.time_created = start_ms
    file_id.serial_number = 0x53544752  # "STGR"

    records: list[RecordMessage] = []
    for sample in recording.samples:
        rec = RecordMessage()
        rec.timestamp = start_ms + int(round(sample.elapsed_s * 1000))
        rec.power = int(sample.power_w)
        if sample.cadence_rpm is not None:
            rec.cadence = int(round(max(0.0, sample.cadence_rpm)))
        if sample.speed_kph is not None and sample.speed_kph > 0:
            # FIT speed is m/s
            rec.speed = float(sample.speed_kph) / 3.6
        if sample.heart_rate_bpm is not None:
            rec.heart_rate = int(sample.heart_rate_bpm)
        records.append(rec)

    if not records:
        # At least one record so the file is a valid activity
        rec = RecordMessage()
        rec.timestamp = start_ms
        rec.power = int(recording.avg_power_w or 0)
        records.append(rec)

    avg = recording.avg_power_w
    if avg is None and recording.samples:
        avg = int(
            round(
                sum(s.power_w for s in recording.samples) / len(recording.samples)
            )
        )

    lap = LapMessage()
    lap.message_index = 0
    lap.timestamp = end_ms
    lap.start_time = start_ms
    lap.total_elapsed_time = duration
    lap.total_timer_time = duration
    lap.sport = Sport.CYCLING
    lap.sub_sport = SubSport.INDOOR_CYCLING
    if avg is not None:
        lap.avg_power = int(avg)
    lap.event = Event.LAP
    lap.event_type = EventType.STOP
    lap.total_distance = 0.0

    session = SessionMessage()
    session.message_index = 0
    session.timestamp = end_ms
    session.start_time = start_ms
    session.total_elapsed_time = duration
    session.total_timer_time = duration
    session.sport = Sport.CYCLING
    session.sub_sport = SubSport.INDOOR_CYCLING
    if avg is not None:
        session.avg_power = int(avg)
    session.event = Event.SESSION
    session.event_type = EventType.STOP
    session.total_distance = 0.0
    if recording.workout_name:
        try:
            session.sport_profile_name = recording.workout_name[:50]
        except Exception:  # noqa: BLE001
            pass

    activity = ActivityMessage()
    activity.timestamp = end_ms
    activity.total_timer_time = duration
    activity.num_sessions = 1
    activity.type = Activity.MANUAL
    activity.event = Event.ACTIVITY
    activity.event_type = EventType.STOP
    activity.local_timestamp = end_fit

    builder = FitFileBuilder(auto_define=True, min_string_size=50)
    builder.add(file_id)
    builder.add_all(records)
    builder.add(lap)
    builder.add(session)
    builder.add(activity)
    return bytes(builder.build().to_bytes())


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
