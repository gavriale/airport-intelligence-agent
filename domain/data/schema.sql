CREATE TABLE IF NOT EXISTS customers (
    customer_id TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    phone_last4 CHAR(4) NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    product_id TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    kind       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS holdings (
    customer_id  TEXT NOT NULL REFERENCES customers (customer_id),
    product_id   TEXT NOT NULL REFERENCES products (product_id),
    units        NUMERIC(18, 4) NOT NULL,
    value_nis    NUMERIC(18, 2) NOT NULL,
    PRIMARY KEY (customer_id, product_id)
);

CREATE TABLE IF NOT EXISTS transactions (
    id          INTEGER PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers (customer_id),
    booked_on   DATE NOT NULL,
    kind        TEXT NOT NULL,
    product_id  TEXT REFERENCES products (product_id),
    amount_nis  NUMERIC(18, 2) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_transactions_customer_date
    ON transactions (customer_id, booked_on DESC);

CREATE SEQUENCE IF NOT EXISTS withdrawal_seq START 2000;

CREATE TABLE IF NOT EXISTS withdrawal_requests (
    request_id      TEXT PRIMARY KEY,
    customer_id     TEXT NOT NULL REFERENCES customers (customer_id),
    amount_nis      NUMERIC(18, 2) NOT NULL,
    status          TEXT NOT NULL,
    created_on      DATE NOT NULL DEFAULT CURRENT_DATE,
    idempotency_key TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_withdrawals_customer
    ON withdrawal_requests (customer_id);
