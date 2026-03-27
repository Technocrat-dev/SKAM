package main

import (
	"context"
	"fmt"
	"math/rand"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/redis/go-redis/v9"
	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/health"
	healthpb "google.golang.org/grpc/health/grpc_health_v1"
	"google.golang.org/grpc/reflection"
	"google.golang.org/grpc/status"
)

var (
	ordersProcessed = promauto.NewCounter(prometheus.CounterOpts{
		Name: "orders_processed_total", Help: "Total orders processed",
	})
	orderDuration = promauto.NewHistogram(prometheus.HistogramOpts{
		Name: "order_processing_duration_seconds", Help: "Order processing time",
	})
)

type orderServer struct {
	db  *pgxpool.Pool
	rdb *redis.Client
}

func main() {
	zerolog.TimeFieldFormat = zerolog.TimeFormatUnix
	log.Logger = zerolog.New(os.Stdout).With().Timestamp().Str("service", "order-service").Logger()

	dbURL := getEnv("DATABASE_URL", "postgres://postgres:hackathon@postgres:5432/orders_db?sslmode=disable")
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	pool, err := pgxpool.New(ctx, dbURL)
	if err != nil {
		log.Fatal().Err(err).Msg("Failed to connect to database")
	}
	defer pool.Close()

	rdb := redis.NewClient(&redis.Options{
		Addr: getEnv("REDIS_ADDR", "redis:6379"),
	})
	defer rdb.Close()

	initDB(ctx, pool)

	grpcServer := grpc.NewServer()
	server := &orderServer{db: pool, rdb: rdb}
	_ = server

	healthSrv := health.NewServer()
	healthpb.RegisterHealthServer(grpcServer, healthSrv)
	healthSrv.SetServingStatus("order.OrderService", healthpb.HealthCheckResponse_SERVING)
	reflection.Register(grpcServer)

	grpcPort := getEnv("GRPC_PORT", "50053")
	lis, err := net.Listen("tcp", fmt.Sprintf(":%s", grpcPort))
	if err != nil {
		log.Fatal().Err(err).Msg("Failed to listen")
	}

	go func() {
		log.Info().Str("port", grpcPort).Msg("gRPC server starting")
		grpcServer.Serve(lis)
	}()

	metricsPort := getEnv("METRICS_PORT", "8081")
	mux := http.NewServeMux()
	mux.Handle("/metrics", promhttp.Handler())
	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{"status":"healthy"}`))
	})
	metricsSrv := &http.Server{Addr: fmt.Sprintf(":%s", metricsPort), Handler: mux}
	go metricsSrv.ListenAndServe()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit
	grpcServer.GracefulStop()
}

func initDB(ctx context.Context, pool *pgxpool.Pool) {
	schema := `
	CREATE TABLE IF NOT EXISTS orders (
		id VARCHAR(36) PRIMARY KEY,
		user_id VARCHAR(36) NOT NULL,
		product_id VARCHAR(36) NOT NULL,
		quantity INT NOT NULL DEFAULT 1,
		status VARCHAR(20) NOT NULL DEFAULT 'pending',
		total DECIMAL(10,2) NOT NULL,
		created_at TIMESTAMP NOT NULL DEFAULT NOW()
	);`
	pool.Exec(ctx, schema)
	log.Info().Msg("Order DB initialized")
}

func (s *orderServer) CreateOrder(ctx context.Context, userID, productID string, quantity int, total float64) (string, error) {
	start := time.Now()
	id := uuid.New().String()

	_, err := s.db.Exec(ctx,
		"INSERT INTO orders (id, user_id, product_id, quantity, status, total) VALUES ($1,$2,$3,$4,$5,$6)",
		id, userID, productID, quantity, "pending", total)
	if err != nil {
		return "", status.Error(codes.Internal, "insert failed")
	}

	// Cache order status in Redis
	s.rdb.Set(ctx, fmt.Sprintf("order:%s:status", id), "pending", 10*time.Minute)

	// Simulate calling payment + notification services
	time.Sleep(time.Duration(50+rand.Intn(150)) * time.Millisecond)

	// Update status
	s.db.Exec(ctx, "UPDATE orders SET status='completed' WHERE id=$1", id)
	s.rdb.Set(ctx, fmt.Sprintf("order:%s:status", id), "completed", 10*time.Minute)

	ordersProcessed.Inc()
	orderDuration.Observe(time.Since(start).Seconds())

	log.Info().Str("order_id", id).Str("user_id", userID).Msg("Order completed")
	return id, nil
}

func (s *orderServer) GetOrder(ctx context.Context, id string) (map[string]interface{}, error) {
	// Try Redis cache first
	cachedStatus, err := s.rdb.Get(ctx, fmt.Sprintf("order:%s:status", id)).Result()
	if err == nil {
		log.Debug().Str("order_id", id).Msg("Cache hit")
	}

	var userID, productID, orderStatus string
	var quantity int
	var total float64
	var createdAt time.Time

	err = s.db.QueryRow(ctx,
		"SELECT id, user_id, product_id, quantity, status, total, created_at FROM orders WHERE id=$1", id).
		Scan(&id, &userID, &productID, &quantity, &orderStatus, &total, &createdAt)
	if err != nil {
		return nil, status.Error(codes.NotFound, "order not found")
	}

	if cachedStatus != "" {
		orderStatus = cachedStatus
	}

	return map[string]interface{}{
		"id": id, "user_id": userID, "product_id": productID,
		"quantity": quantity, "status": orderStatus, "total": total,
		"created_at": createdAt.Format(time.RFC3339),
	}, nil
}

func getEnv(key, fallback string) string {
	if v, ok := os.LookupEnv(key); ok {
		return v
	}
	return fallback
}
