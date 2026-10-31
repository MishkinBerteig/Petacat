"""``configuration_state``: whether the database holds the loaded configuration.

One row, written in the same transaction as the first load of the Metacat Standard
Configuration (``seed_data/*.json``) into an empty database.  Start-up reads it to
classify the database: no row and empty configuration tables is EMPTY (load), a ``ready``
row with populated tables is COMPLETE (use), anything else is refused.  There is no state
for a half-finished load because the load is one transaction, and no state for an older
schema because existing databases are never upgraded.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Column, DateTime, Integer, String, func

from server.models.metadata import Base

#: ``configuration_state.load_state`` of a database whose first load committed.
LOAD_STATE_READY = "ready"

#: ``configuration_state.origin`` of a database loaded from the Metacat Standard Configuration.
ORIGIN_METACAT_STANDARD = "metacat_standard"


class ConfigurationState(Base):
    __tablename__ = "configuration_state"
    __table_args__ = (CheckConstraint("id = 1", name="ck_configuration_state_single_row"),)

    id = Column(Integer, primary_key=True, default=1)
    origin = Column(String(32), nullable=False)
    #: Digest of the Metacat Standard Configuration files the database was loaded from.
    #: Provenance only: nothing compares it with the files at start-up.
    standard_hash = Column(String(64), nullable=False)
    loaded_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    load_state = Column(String(16), nullable=False)
