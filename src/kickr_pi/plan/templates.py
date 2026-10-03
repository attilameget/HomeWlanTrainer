"""ERG bike workout templates and run session builders (% FTP)."""

from __future__ import annotations

from typing import Any

from kickr_pi.plan.models import SessionKind


def _stage(
    index: int,
    name: str,
    kind: str,
    duration_s: int,
    *,
    ftp_w: int,
    pct: float | None = None,
    start_pct: float | None = None,
    end_pct: float | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    if start_pct is not None and end_pct is not None:
        return {
            "index": index,
            "name": name,
            "kind": kind,
            "duration_s": duration_s,
            "target_mode": "ramp",
            "start_w": int(ftp_w * start_pct),
            "end_w": int(ftp_w * end_pct),
            "target_w": None,
            "resistance_pct": None,
            "cadence_hint": None,
            "note": note,
        }
    watts = int(ftp_w * pct) if pct is not None else None
    return {
        "index": index,
        "name": name,
        "kind": kind,
        "duration_s": duration_s,
        "target_mode": "erg" if watts is not None else "resistance",
        "target_w": watts,
        "start_w": None,
        "end_w": None,
        "resistance_pct": None if watts is not None else 20,
        "cadence_hint": None,
        "note": note,
    }


def build_bike_stages(
    kind: SessionKind,
    *,
    ftp_w: int,
    duration_s: int,
) -> list[dict[str, Any]]:
    """Build flat ERG stages for a bike session of roughly duration_s."""
    duration_s = max(20 * 60, int(duration_s))
    ftp = max(80, int(ftp_w))

    if kind == "recovery":
        wu, main, cd = 5 * 60, duration_s - 10 * 60, 5 * 60
        return [
            _stage(0, "Easy spin-up", "warmup", wu, ftp_w=ftp, start_pct=0.40, end_pct=0.50),
            _stage(1, "Recovery spin", "recovery", max(600, main), ftp_w=ftp, pct=0.50),
            _stage(2, "Cool-down", "cooldown", cd, ftp_w=ftp, start_pct=0.48, end_pct=0.40),
        ]

    if kind == "tempo":
        wu, cd = 10 * 60, 8 * 60
        main = max(12 * 60, duration_s - wu - cd)
        return [
            _stage(0, "Warm-up", "warmup", wu, ftp_w=ftp, start_pct=0.45, end_pct=0.65),
            _stage(1, "Tempo", "interval", main, ftp_w=ftp, pct=0.88, note="Steady tempo"),
            _stage(2, "Cool-down", "cooldown", cd, ftp_w=ftp, start_pct=0.60, end_pct=0.40),
        ]

    if kind == "intervals":
        # 4–6 × (3 min @ 110% / 3 min recover), scaled to duration
        wu, cd = 12 * 60, 8 * 60
        budget = max(18 * 60, duration_s - wu - cd)
        reps = max(3, min(6, budget // (6 * 60)))
        stages: list[dict[str, Any]] = [
            _stage(0, "Warm-up", "warmup", wu, ftp_w=ftp, start_pct=0.45, end_pct=0.70),
        ]
        idx = 1
        for i in range(reps):
            stages.append(
                _stage(
                    idx,
                    f"VO2 #{i + 1}",
                    "interval",
                    3 * 60,
                    ftp_w=ftp,
                    pct=1.10,
                    note="Hard, controlled",
                )
            )
            idx += 1
            stages.append(
                _stage(idx, "Recover", "recovery", 3 * 60, ftp_w=ftp, pct=0.55)
            )
            idx += 1
        stages.append(
            _stage(idx, "Cool-down", "cooldown", cd, ftp_w=ftp, start_pct=0.55, end_pct=0.40)
        )
        return stages

    if kind == "long":
        wu, cd = 10 * 60, 10 * 60
        main = max(30 * 60, duration_s - wu - cd)
        mid = main // 2
        return [
            _stage(0, "Warm-up", "warmup", wu, ftp_w=ftp, start_pct=0.45, end_pct=0.60),
            _stage(1, "Endurance A", "interval", mid, ftp_w=ftp, pct=0.65),
            _stage(
                2,
                "Endurance B",
                "interval",
                main - mid,
                ftp_w=ftp,
                pct=0.70,
                note="Settle in",
            ),
            _stage(3, "Cool-down", "cooldown", cd, ftp_w=ftp, start_pct=0.55, end_pct=0.40),
        ]

    # endurance / easy default
    wu, cd = 8 * 60, 7 * 60
    main = max(15 * 60, duration_s - wu - cd)
    return [
        _stage(0, "Warm-up", "warmup", wu, ftp_w=ftp, start_pct=0.45, end_pct=0.60),
        _stage(1, "Endurance", "interval", main, ftp_w=ftp, pct=0.68),
        _stage(2, "Cool-down", "cooldown", cd, ftp_w=ftp, start_pct=0.55, end_pct=0.40),
    ]


def run_distance_m(kind: SessionKind, duration_s: int) -> int:
    """Estimate run distance from duration using easy/tempo paces."""
    # ~5:30–6:30 /km easy → ~2.7–3.0 m/s; use conservative 2.75 m/s (~6:00/km)
    pace_mps = 2.9 if kind in ("tempo", "intervals") else 2.7
    if kind == "long":
        pace_mps = 2.6
    return int(max(2000, duration_s * pace_mps))
