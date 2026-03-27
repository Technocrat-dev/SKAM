package main

import (
	"context"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/rs/zerolog/log"
)

func initDB(ctx context.Context, pool *pgxpool.Pool) error {
	schema := `
	CREATE TABLE IF NOT EXISTS users (
		id VARCHAR(36) PRIMARY KEY,
		username VARCHAR(100) NOT NULL UNIQUE,
		email VARCHAR(255) NOT NULL UNIQUE,
		password_hash VARCHAR(64) NOT NULL,
		created_at TIMESTAMP NOT NULL DEFAULT NOW()
	);

	-- Seed data for demo
	INSERT INTO users (id, username, email, password_hash, created_at) 
	VALUES 
		('usr-001', 'alice', 'alice@example.com', 'dummy_hash', NOW()),
		('usr-002', 'bob', 'bob@example.com', 'dummy_hash', NOW())
	ON CONFLICT (id) DO NOTHING;
	`

	_, err := pool.Exec(ctx, schema)
	if err != nil {
		log.Error().Err(err).Msg("Failed to initialize database schema")
		return err
	}

	log.Info().Msg("Database schema initialized")
	return nil
}
