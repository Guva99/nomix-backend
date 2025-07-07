DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_database WHERE datname = 'numix') THEN
        CREATE DATABASE numix;
    END IF;
END $$;