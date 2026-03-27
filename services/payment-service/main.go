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
	paymentsTotal = promauto.NewCounter(prometheus.CounterOpts{
		Name: "payment_processed_total", Help: "Total payments processed",
	})
	paymentFailures = promauto.NewCounter(prometheus.CounterOpts{
		Name: "payment_failures_total", Help: "Total payment failures",
	})
	paymentDuration = promauto.NewHistogram(prometheus.HistogramOpts{
		Name: "payment_duration_seconds", Help: "Payment processing time",
	})
)

type paymentServer struct {
	failureRate float64
}

func main() {
	zerolog.TimeFieldFormat = zerolog.TimeFormatUnix
	log.Logger = zerolog.New(os.Stdout).With().Timestamp().Str("service", "payment-service").Logger()

	grpcServer := grpc.NewServer()
	server := &paymentServer{failureRate: 0.02} // 2% failure rate
	_ = server

	healthSrv := health.NewServer()
	healthpb.RegisterHealthServer(grpcServer, healthSrv)
	healthSrv.SetServingStatus("payment.PaymentService", healthpb.HealthCheckResponse_SERVING)
	reflection.Register(grpcServer)

	grpcPort := getEnv("GRPC_PORT", "50055")
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

func (s *paymentServer) ProcessPayment(ctx context.Context, orderID, userID string, amount float64) (string, error) {
	start := time.Now()
	paymentID := uuid.New().String()

	// Simulate processing latency (50-200ms)
	time.Sleep(time.Duration(50+rand.Intn(150)) * time.Millisecond)

	// Simulate occasional failures
	if rand.Float64() < s.failureRate {
		paymentFailures.Inc()
		paymentDuration.Observe(time.Since(start).Seconds())
		log.Warn().Str("order_id", orderID).Msg("Payment failed (simulated)")
		return "", status.Error(codes.Internal, "payment processing failed")
	}

	paymentsTotal.Inc()
	paymentDuration.Observe(time.Since(start).Seconds())

	log.Info().Str("payment_id", paymentID).Str("order_id", orderID).Float64("amount", amount).Msg("Payment processed")
	return paymentID, nil
}

func getEnv(key, fallback string) string {
	if v, ok := os.LookupEnv(key); ok {
		return v
	}
	return fallback
}
