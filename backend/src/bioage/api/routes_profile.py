"""Profile and dated body measurements."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from bioage.api.deps import get_session
from bioage.api.schemas import MeasurementIn, MeasurementOut, ProfileIn, ProfileOut
from bioage.db.models import Measurement, Profile
from bioage.scoring import rescore_all

router = APIRouter(prefix="/api/profile", tags=["profile"])


def _measurements(session: Session) -> list[Measurement]:
    stmt = select(Measurement).order_by(Measurement.kind, Measurement.measured_on)
    return list(session.execute(stmt).scalars().all())


@router.get("", response_model=ProfileOut)
def get_profile(session: Session = Depends(get_session)) -> ProfileOut:
    profile = session.get(Profile, 1)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not set")
    return ProfileOut(
        sex=profile.sex,
        birthdate=profile.birthdate,
        measurements=[MeasurementOut.model_validate(m) for m in _measurements(session)],
    )


@router.put("", response_model=ProfileOut)
def put_profile(payload: ProfileIn, session: Session = Depends(get_session)) -> ProfileOut:
    session.merge(Profile(id=1, sex=payload.sex, birthdate=payload.birthdate))
    session.flush()
    rescore_all(session)
    session.commit()
    return get_profile(session)


@router.post("/measurements", response_model=MeasurementOut, status_code=201)
def add_measurement(
    payload: MeasurementIn, session: Session = Depends(get_session)
) -> Measurement:
    measurement = Measurement(**payload.model_dump())
    session.add(measurement)
    session.flush()
    rescore_all(session)
    session.commit()
    return measurement


@router.delete("/measurements/{measurement_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_measurement(
    measurement_id: int, session: Session = Depends(get_session)
) -> Response:
    measurement = session.get(Measurement, measurement_id)
    if measurement is None:
        raise HTTPException(status_code=404, detail="Measurement not found")
    session.delete(measurement)
    session.flush()
    rescore_all(session)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
