INSERT INTO banks (id, name, connector) VALUES ('banco-estado', 'BancoEstado', 'banco_estado')
    ON CONFLICT (id) DO NOTHING;
