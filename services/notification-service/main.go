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
	"github.com/redis/go-redis/v9"
	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
	"google.golang.org/grpc"
	"google.golang.org/grpc/health"
	healthpb "google.golang.org/grpc/health/grpc_health_v1"
	"google.golang.org/grpc/reflection"
)

var (
	notifsSent = promauto.NewCounter(prometheus.CounterOpts{
		Name: "notifications_sent_total", Help: "Total notifications sent",
	})
	notifQueueDepth = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "notification_queue_depth", Help: "Notification queue depth",
	})
)

type notificationServer struct {
	rdb *redis.Client
}

func main() {
	zerolog.TimeFieldFormat = zerolog.TimeFormatUnix
	log.Logger = zerolog.New(os.Stdout).With().Timestamp().Str("service", "notification-service").Logger()

	rdb := redis.NewClient(&redis.Options{
		Addr: getEnv("REDIS_ADDR", "redis:6379"),
	})
	defer rdb.Close()

	grpcServer := grpc.NewServer()
	server := &notificationServer{rdb: rdb}
	_ = server

	healthSrv := health.NewServer()
	healthpb.RegisterHealthServer(grpcServer, healthSrv)
	healthSrv.SetServingStatus("notification.NotificationService", healthpb.HealthCheckResponse_SERVING)
	reflection.Register(grpcServer)

	grpcPort := getEnv("GRPC_PORT", "50056")
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

func (s *notificationServer) Send(ctx context.Context, userID, notifType, subject, body string) (string, error) {
	id := uuid.New().String()

	// Queue in Redis
	s.rdb.LPush(ctx, "notifications:queue", fmt.Sprintf("%s|%s|%s", id, userID, subject))
	notifQueueDepth.Inc()

	// Simulate sending (100-500ms)
	go func() {
		time.Sleep(time.Duration(100+rand.Intn(400)) * time.Millisecond)
		s.rdb.Set(context.Background(), fmt.Sprintf("notif:%s:status", id), "delivered", 1*time.Hour)
		s.rdb.LRem(context.Background(), "notifications:queue", 1, fmt.Sprintf("%s|%s|%s", id, userID, subject))
		notifQueueDepth.Dec()
		notifsSent.Inc()
		log.Info().Str("id", id).Str("user_id", userID).Str("type", notifType).Msg("Notification delivered")
	}()

	return id, nil
}

func (s *notificationServer) GetStatus(ctx context.Context, id string) (string, error) {
	st, err := s.rdb.Get(ctx, fmt.Sprintf("notif:%s:status", id)).Result()
	if err != nil {
		return "pending", nil
	}
	return st, nil
}

func getEnv(key, fallback string) string {
	if v, ok := os.LookupEnv(key); ok {
		return v
	}
	return fallback
}
