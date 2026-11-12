-- Optional amount threshold for completeness rules: required_fields apply only when the invoice
-- amount_cents >= min_amount_cents (inclusive). NULL keeps the previous behaviour (applies to every invoice).
ALTER TABLE invoice_rule ADD COLUMN min_amount_cents bigint CHECK (min_amount_cents IS NULL OR min_amount_cents >= 0);
