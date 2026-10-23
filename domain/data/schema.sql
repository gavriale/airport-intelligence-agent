-- Airport snapshot. Tables are filled from the committed CSV files by the loader.

CREATE TABLE IF NOT EXISTS airports (
    iata              TEXT PRIMARY KEY,
    ident             TEXT NOT NULL,
    name              TEXT NOT NULL,
    city              TEXT,
    state             TEXT NOT NULL,
    latitude          DOUBLE PRECISION NOT NULL,
    longitude         DOUBLE PRECISION NOT NULL,
    elevation_ft      INTEGER,
    type              TEXT NOT NULL,
    scheduled_service BOOLEAN NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_airports_state ON airports (state);

-- One row per open physical runway.
CREATE TABLE IF NOT EXISTS runways (
    id           INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    airport_iata TEXT NOT NULL REFERENCES airports (iata),
    runway       TEXT NOT NULL,
    length_ft    INTEGER,
    width_ft     INTEGER,
    surface      TEXT,
    lighted      BOOLEAN NOT NULL
);
-- Added after the first release; the ALTER keeps databases created earlier working.
ALTER TABLE runways ADD COLUMN IF NOT EXISTS commercial_capable BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS idx_runways_airport ON runways (airport_iata);

-- BTS T-100 summary by origin airport, monthly, peer airports only.
-- departures = domestic_departures + international_departures (checked on every row).
-- Includes all-cargo flights: they add departures and freight but no passengers or seats.
CREATE TABLE IF NOT EXISTS airport_month (
    iata                     TEXT NOT NULL REFERENCES airports (iata),
    month                    DATE NOT NULL,
    departures               INTEGER NOT NULL,
    passengers               BIGINT NOT NULL,
    seats                    BIGINT NOT NULL,
    domestic_departures      INTEGER NOT NULL,
    international_departures INTEGER NOT NULL,
    international_seats      BIGINT NOT NULL,
    avg_flight_distance_mi   DOUBLE PRECISION,
    avg_domestic_distance_mi DOUBLE PRECISION,
    freight_lbs              BIGINT NOT NULL,
    PRIMARY KEY (iata, month)
);
CREATE INDEX IF NOT EXISTS idx_airport_month_month ON airport_month (month);

-- Provenance and the hash of the loaded snapshot (used to skip an unchanged reload).
CREATE TABLE IF NOT EXISTS snapshot_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
