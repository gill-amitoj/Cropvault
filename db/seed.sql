-- Sample experiments for the demo. Safe to run more than once.
INSERT INTO experiments (code, title, description) VALUES
    ('EXP-2026-001', 'Wheat drought tolerance', 'Greenhouse wheat lines under reduced watering.'),
    ('EXP-2026-002', 'Canola leaf disease survey', 'Field canola leaves imaged for disease lesions.')
ON CONFLICT (code) DO NOTHING;
