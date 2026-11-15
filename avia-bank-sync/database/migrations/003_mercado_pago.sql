INSERT INTO banks (id, name, connector) VALUES ('mercado-pago', 'Mercado Pago', 'mercado_pago')
ON CONFLICT (id) DO NOTHING;
