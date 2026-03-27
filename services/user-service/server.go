package main

// This file contains the gRPC handler implementations for UserService.
// NOTE: The placeholder types below will be REPLACED by protoc-generated code.
// After running `make proto`, delete the placeholder section and import:
//   userpb "skam/proto/userpb"

import (
	"context"
	"crypto/sha256"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	"github.com/rs/zerolog/log"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

// ──────────────────────────────────────────────────────────────
// PLACEHOLDER TYPES — Delete after running `make proto`
// These mirror the proto definitions so the code compiles now.
// ──────────────────────────────────────────────────────────────

type CreateUserRequest struct {
	Username string
	Email    string
	Password string
}

type GetUserRequest struct {
	Id string
}

type LoginRequest struct {
	Email    string
	Password string
}

type UserResponse struct {
	Id        string
	Username  string
	Email     string
	CreatedAt string
}

type LoginResponse struct {
	UserId string
	Token  string
}

type HealthRequest struct{}
type HealthResponse struct {
	Status string
}

// ──────────────────────────────────────────────────────────────
// Prometheus Metrics
// ──────────────────────────────────────────────────────────────

var (
	dbQueryDuration = promauto.NewHistogramVec(prometheus.HistogramOpts{
		Name:    "db_query_duration_seconds",
		Help:    "Database query duration in seconds",
		Buckets: prometheus.DefBuckets,
	}, []string{"operation"})

	dbActiveConnections = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "db_active_connections",
		Help: "Number of active database connections",
	})
)

// ──────────────────────────────────────────────────────────────
// gRPC Server Implementation
// ──────────────────────────────────────────────────────────────

type userServer struct {
	db *pgxpool.Pool
}

func (s *userServer) CreateUser(ctx context.Context, req *CreateUserRequest) (*UserResponse, error) {
	start := time.Now()
	defer func() {
		dbQueryDuration.WithLabelValues("create_user").Observe(time.Since(start).Seconds())
	}()

	id := uuid.New().String()
	hash := fmt.Sprintf("%x", sha256.Sum256([]byte(req.Password)))
	now := time.Now()

	_, err := s.db.Exec(ctx,
		"INSERT INTO users (id, username, email, password_hash, created_at) VALUES ($1, $2, $3, $4, $5)",
		id, req.Username, req.Email, hash, now)
	if err != nil {
		log.Error().Err(err).Msg("Failed to create user")
		return nil, status.Error(codes.Internal, "failed to create user")
	}

	log.Info().Str("user_id", id).Str("username", req.Username).Msg("User created")
	return &UserResponse{
		Id: id, Username: req.Username, Email: req.Email, CreatedAt: now.Format(time.RFC3339),
	}, nil
}

func (s *userServer) GetUser(ctx context.Context, req *GetUserRequest) (*UserResponse, error) {
	start := time.Now()
	defer func() {
		dbQueryDuration.WithLabelValues("get_user").Observe(time.Since(start).Seconds())
	}()

	var resp UserResponse
	err := s.db.QueryRow(ctx,
		"SELECT id, username, email, created_at FROM users WHERE id = $1", req.Id).
		Scan(&resp.Id, &resp.Username, &resp.Email, &resp.CreatedAt)
	if err != nil {
		return nil, status.Error(codes.NotFound, "user not found")
	}

	return &resp, nil
}

func (s *userServer) Login(ctx context.Context, req *LoginRequest) (*LoginResponse, error) {
	start := time.Now()
	defer func() {
		dbQueryDuration.WithLabelValues("login").Observe(time.Since(start).Seconds())
	}()

	hash := fmt.Sprintf("%x", sha256.Sum256([]byte(req.Password)))

	var userId string
	err := s.db.QueryRow(ctx,
		"SELECT id FROM users WHERE email = $1 AND password_hash = $2", req.Email, hash).
		Scan(&userId)
	if err != nil {
		return nil, status.Error(codes.Unauthenticated, "invalid credentials")
	}

	return &LoginResponse{UserId: userId, Token: fmt.Sprintf("token-%s", userId)}, nil
}

func (s *userServer) HealthCheck(ctx context.Context, req *HealthRequest) (*HealthResponse, error) {
	if err := s.db.Ping(ctx); err != nil {
		return &HealthResponse{Status: "unhealthy"}, nil
	}
	return &HealthResponse{Status: "serving"}, nil
}
