\connect postgres;

ALTER SYSTEM SET listen_addresses = '*';
ALTER SYSTEM SET max_connections = 200;

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_database WHERE datname = 'numix') THEN
        CREATE DATABASE numix;
    END IF;
END $$;