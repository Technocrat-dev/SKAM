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

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	"github.com/prometheus/client_golang/prometheus/promhttp"
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
	dbQueryDuration = promauto.NewHistogramVec(prometheus.HistogramOpts{
		Name: "db_query_duration_seconds", Help: "DB query duration",
	}, []string{"operation"})
	cacheHitRate = promauto.NewCounter(prometheus.CounterOpts{
		Name: "product_cache_hits_total", Help: "Product cache hits",
	})
)

type productServer struct {
	db *pgxpool.Pool
}

func main() {
	zerolog.TimeFieldFormat = zerolog.TimeFormatUnix
	log.Logger = zerolog.New(os.Stdout).With().Timestamp().Str("service", "product-service").Logger()

	dbURL := getEnv("DATABASE_URL", "postgres://postgres:hackathon@postgres:5432/products_db?sslmode=disable")
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	pool, err := pgxpool.New(ctx, dbURL)
	if err != nil {
		log.Fatal().Err(err).Msg("Failed to connect to database")
	}
	defer pool.Close()

	initDB(ctx, pool)

	grpcServer := grpc.NewServer()
	server := &productServer{db: pool}
	_ = server

	healthSrv := health.NewServer()
	healthpb.RegisterHealthServer(grpcServer, healthSrv)
	healthSrv.SetServingStatus("product.ProductService", healthpb.HealthCheckResponse_SERVING)
	reflection.Register(grpcServer)

	grpcPort := getEnv("GRPC_PORT", "50052")
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
	CREATE TABLE IF NOT EXISTS products (
		id VARCHAR(36) PRIMARY KEY,
		name VARCHAR(200) NOT NULL,
		price DECIMAL(10,2) NOT NULL,
		stock INT NOT NULL DEFAULT 0,
		category VARCHAR(100)
	);
	INSERT INTO products (id, name, price, stock, category) VALUES 
		('prd-001', 'Laptop Pro', 999.99, 50, 'electronics'),
		('prd-002', 'Wireless Headphones', 79.99, 200, 'electronics'),
		('prd-003', 'Mechanical Keyboard', 149.99, 100, 'accessories'),
		('prd-004', 'USB-C Hub', 49.99, 300, 'accessories'),
		('prd-005', 'Monitor 27"', 399.99, 75, 'electronics')
	ON CONFLICT (id) DO NOTHING;`
	pool.Exec(ctx, schema)
	log.Info().Msg("Product DB initialized")
}

func (s *productServer) ListProducts(ctx context.Context) ([]map[string]interface{}, error) {
	start := time.Now()
	defer func() { dbQueryDuration.WithLabelValues("list").Observe(time.Since(start).Seconds()) }()

	rows, err := s.db.Query(ctx, "SELECT id, name, price, stock, category FROM products LIMIT 50")
	if err != nil {
		return nil, status.Error(codes.Internal, "query failed")
	}
	defer rows.Close()

	var products []map[string]interface{}
	for rows.Next() {
		var id, name, category string
		var price float64
		var stock int
		rows.Scan(&id, &name, &price, &stock, &category)
		products = append(products, map[string]interface{}{
			"id": id, "name": name, "price": price, "stock": stock, "category": category,
		})
	}
	return products, nil
}

func (s *productServer) GetProduct(ctx context.Context, id string) (map[string]interface{}, error) {
	start := time.Now()
	defer func() { dbQueryDuration.WithLabelValues("get").Observe(time.Since(start).Seconds()) }()

	var name, category string
	var price float64
	var stock int
	err := s.db.QueryRow(ctx, "SELECT id, name, price, stock, category FROM products WHERE id=$1", id).
		Scan(&id, &name, &price, &stock, &category)
	if err != nil {
		return nil, status.Error(codes.NotFound, "product not found")
	}
	cacheHitRate.Inc()
	return map[string]interface{}{"id": id, "name": name, "price": price, "stock": stock, "category": category}, nil
}

func (s *productServer) CreateProduct(ctx context.Context, name string, price float64, stock int, category string) (string, error) {
	id := uuid.New().String()
	_, err := s.db.Exec(ctx, "INSERT INTO products (id, name, price, stock, category) VALUES ($1,$2,$3,$4,$5)",
		id, name, price, stock, category)
	if err != nil {
		return "", status.Error(codes.Internal, "insert failed")
	}
	return id, nil
}

func getEnv(key, fallback string) string {
	if v, ok := os.LookupEnv(key); ok {
		return v
	}
	return fallback
}
