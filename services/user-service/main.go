package main

import (
	"context"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
	"google.golang.org/grpc"
	"google.golang.org/grpc/health"
	healthpb "google.golang.org/grpc/health/grpc_health_v1"
	"google.golang.org/grpc/reflection"
)

func main() {
	zerolog.TimeFieldFormat = zerolog.TimeFormatUnix
	log.Logger = zerolog.New(os.Stdout).With().Timestamp().Str("service", "user-service").Logger()

	// Database
	dbURL := getEnv("DATABASE_URL", "postgres://postgres:hackathon@postgres:5432/users_db?sslmode=disable")
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	pool, err := pgxpool.New(ctx, dbURL)
	if err != nil {
		log.Fatal().Err(err).Msg("Failed to connect to database")
	}
	defer pool.Close()

	// Init schema
	if err := initDB(ctx, pool); err != nil {
		log.Fatal().Err(err).Msg("Failed to init database schema")
	}

	// gRPC server
	// NOTE: After running `make proto`, add gRPC metrics interceptors:
	//   grpcprom "github.com/grpc-ecosystem/go-grpc-middleware/providers/prometheus"
	//   srvMetrics := grpcprom.NewServerMetrics()
	//   grpc.ChainUnaryInterceptor(srvMetrics.UnaryServerInterceptor())
	grpcServer := grpc.NewServer()

	// Register user service
	// TODO: After `make proto`, replace with:
	//   userpb.RegisterUserServiceServer(grpcServer, server)
	server := &userServer{db: pool}
	_ = server // Will be registered after protoc generates registration func

	// Health check
	healthSrv := health.NewServer()
	healthpb.RegisterHealthServer(grpcServer, healthSrv)
	healthSrv.SetServingStatus("user.UserService", healthpb.HealthCheckResponse_SERVING)

	reflection.Register(grpcServer)

	// Start gRPC
	grpcPort := getEnv("GRPC_PORT", "50051")
	lis, err := net.Listen("tcp", fmt.Sprintf(":%s", grpcPort))
	if err != nil {
		log.Fatal().Err(err).Msg("Failed to listen")
	}

	go func() {
		log.Info().Str("port", grpcPort).Msg("gRPC server starting")
		if err := grpcServer.Serve(lis); err != nil {
			log.Fatal().Err(err).Msg("gRPC server failed")
		}
	}()

	// Metrics + Health HTTP server
	metricsPort := getEnv("METRICS_PORT", "8081")
	mux := http.NewServeMux()
	mux.Handle("/metrics", promhttp.Handler())
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		if err := pool.Ping(r.Context()); err != nil {
			w.WriteHeader(http.StatusServiceUnavailable)
			w.Write([]byte(`{"status":"unhealthy","reason":"db_unreachable"}`))
			return
		}
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{"status":"healthy"}`))
	})

	metricsSrv := &http.Server{Addr: fmt.Sprintf(":%s", metricsPort), Handler: mux}
	go func() {
		log.Info().Str("port", metricsPort).Msg("Metrics server starting")
		if err := metricsSrv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatal().Err(err).Msg("Metrics server failed")
		}
	}()

	// Graceful shutdown
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	log.Info().Msg("Shutting down...")
	grpcServer.GracefulStop()
	metricsSrv.Shutdown(context.Background())
}

func getEnv(key, fallback string) string {
	if v, ok := os.LookupEnv(key); ok {
		return v
	}
	return fallback
}
