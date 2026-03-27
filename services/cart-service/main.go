package main

import (
	"context"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"syscall"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/redis/go-redis/v9"
	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
	"google.golang.org/grpc"
	"google.golang.org/grpc/health"
	healthpb "google.golang.org/grpc/health/grpc_health_v1"
	"google.golang.org/grpc/reflection"
)

var (
	cartItemsTotal = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "cart_items_total", Help: "Total items across all carts",
	})
	redisOpDuration = promauto.NewHistogramVec(prometheus.HistogramOpts{
		Name: "redis_operation_duration_seconds", Help: "Redis operation duration",
	}, []string{"operation"})
)

type cartServer struct {
	rdb *redis.Client
}

func main() {
	zerolog.TimeFieldFormat = zerolog.TimeFormatUnix
	log.Logger = zerolog.New(os.Stdout).With().Timestamp().Str("service", "cart-service").Logger()

	rdb := redis.NewClient(&redis.Options{
		Addr: getEnv("REDIS_ADDR", "redis:6379"),
	})
	defer rdb.Close()

	grpcServer := grpc.NewServer()
	server := &cartServer{rdb: rdb}
	_ = server

	healthSrv := health.NewServer()
	healthpb.RegisterHealthServer(grpcServer, healthSrv)
	healthSrv.SetServingStatus("cart.CartService", healthpb.HealthCheckResponse_SERVING)
	reflection.Register(grpcServer)

	grpcPort := getEnv("GRPC_PORT", "50054")
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
	go http.ListenAndServe(fmt.Sprintf(":%s", metricsPort), mux)

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit
	grpcServer.GracefulStop()
}

func (s *cartServer) AddItem(ctx context.Context, userID, productID string, quantity int) error {
	key := fmt.Sprintf("cart:%s", userID)
	s.rdb.HSet(ctx, key, productID, strconv.Itoa(quantity))
	total := s.getCartTotal(ctx, userID)
	cartItemsTotal.Set(float64(total))
	log.Info().Str("user_id", userID).Str("product_id", productID).Int("qty", quantity).Msg("Item added to cart")
	return nil
}

func (s *cartServer) RemoveItem(ctx context.Context, userID, productID string) error {
	key := fmt.Sprintf("cart:%s", userID)
	s.rdb.HDel(ctx, key, productID)
	return nil
}

func (s *cartServer) GetCart(ctx context.Context, userID string) (map[string]string, error) {
	key := fmt.Sprintf("cart:%s", userID)
	return s.rdb.HGetAll(ctx, key).Result()
}

func (s *cartServer) ClearCart(ctx context.Context, userID string) error {
	key := fmt.Sprintf("cart:%s", userID)
	s.rdb.Del(ctx, key)
	return nil
}

func (s *cartServer) getCartTotal(ctx context.Context, userID string) int {
	key := fmt.Sprintf("cart:%s", userID)
	items, _ := s.rdb.HGetAll(ctx, key).Result()
	total := 0
	for _, v := range items {
		q, _ := strconv.Atoi(v)
		total += q
	}
	return total
}

func getEnv(key, fallback string) string {
	if v, ok := os.LookupEnv(key); ok {
		return v
	}
	return fallback
}
