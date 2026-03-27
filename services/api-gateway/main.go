package main

import (
	"context"
	"fmt"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/go-chi/chi/v5"
	chimw "github.com/go-chi/chi/v5/middleware"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

// Service connections
var (
	userConn    *grpc.ClientConn
	productConn *grpc.ClientConn
	orderConn   *grpc.ClientConn
	cartConn    *grpc.ClientConn
	paymentConn *grpc.ClientConn
	notifConn   *grpc.ClientConn
)

func main() {
	// Structured logging
	zerolog.TimeFieldFormat = zerolog.TimeFormatUnix
	log.Logger = zerolog.New(os.Stdout).With().Timestamp().Str("service", "api-gateway").Logger()

	// Connect to backend gRPC services
	connectServices()
	defer closeConnections()

	// Router
	r := chi.NewRouter()

	// Middleware
	r.Use(chimw.RequestID)
	r.Use(chimw.RealIP)
	r.Use(chimw.Recoverer)
	r.Use(prometheusMiddleware)
	r.Use(loggingMiddleware)

	// Health & Metrics
	r.Get("/health", healthHandler)
	r.Get("/ready", readyHandler)
	r.Get("/metrics", promhttp.Handler().ServeHTTP)

	// API Routes
	r.Route("/api", func(r chi.Router) {
		// User routes
		r.Post("/users", createUserHandler)
		r.Get("/users/{id}", getUserHandler)
		r.Post("/auth/login", loginHandler)

		// Product routes
		r.Get("/products", listProductsHandler)
		r.Get("/products/{id}", getProductHandler)
		r.Post("/products", createProductHandler)

		// Order routes
		r.Post("/orders", createOrderHandler)
		r.Get("/orders/{id}", getOrderHandler)
		r.Get("/orders/user/{userId}", listUserOrdersHandler)

		// Cart routes
		r.Post("/cart/items", addCartItemHandler)
		r.Delete("/cart/items", removeCartItemHandler)
		r.Get("/cart/{userId}", getCartHandler)
		r.Delete("/cart/{userId}", clearCartHandler)

		// Payment routes
		r.Post("/payments/process", processPaymentHandler)
		r.Get("/payments/{id}", getPaymentStatusHandler)
	})

	port := getEnv("PORT", "8080")
	log.Info().Str("port", port).Msg("API Gateway starting")

	server := &http.Server{
		Addr:         fmt.Sprintf(":%s", port),
		Handler:      r,
		ReadTimeout:  15 * time.Second,
		WriteTimeout: 15 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	// Start server in goroutine
	go func() {
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			log.Fatal().Err(err).Msg("Server failed")
		}
	}()

	// Graceful shutdown
	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit

	log.Info().Msg("Shutting down API Gateway...")
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	if err := server.Shutdown(ctx); err != nil {
		log.Fatal().Err(err).Msg("Forced shutdown")
	}
	log.Info().Msg("API Gateway stopped")
}

func connectServices() {
	opts := []grpc.DialOption{grpc.WithTransportCredentials(insecure.NewCredentials())}

	var err error

	userAddr := getEnv("USER_SERVICE_ADDR", "user-service:50051")
	userConn, err = grpc.NewClient(userAddr, opts...)
	if err != nil {
		log.Fatal().Err(err).Msg("Failed to connect to user-service")
	}

	productAddr := getEnv("PRODUCT_SERVICE_ADDR", "product-service:50052")
	productConn, err = grpc.NewClient(productAddr, opts...)
	if err != nil {
		log.Fatal().Err(err).Msg("Failed to connect to product-service")
	}

	orderAddr := getEnv("ORDER_SERVICE_ADDR", "order-service:50053")
	orderConn, err = grpc.NewClient(orderAddr, opts...)
	if err != nil {
		log.Fatal().Err(err).Msg("Failed to connect to order-service")
	}

	cartAddr := getEnv("CART_SERVICE_ADDR", "cart-service:50054")
	cartConn, err = grpc.NewClient(cartAddr, opts...)
	if err != nil {
		log.Fatal().Err(err).Msg("Failed to connect to cart-service")
	}

	paymentAddr := getEnv("PAYMENT_SERVICE_ADDR", "payment-service:50055")
	paymentConn, err = grpc.NewClient(paymentAddr, opts...)
	if err != nil {
		log.Fatal().Err(err).Msg("Failed to connect to payment-service")
	}

	notifAddr := getEnv("NOTIFICATION_SERVICE_ADDR", "notification-service:50056")
	notifConn, err = grpc.NewClient(notifAddr, opts...)
	if err != nil {
		log.Fatal().Err(err).Msg("Failed to connect to notification-service")
	}

	log.Info().Msg("Connected to all backend services")
}

func closeConnections() {
	for _, conn := range []*grpc.ClientConn{userConn, productConn, orderConn, cartConn, paymentConn, notifConn} {
		if conn != nil {
			conn.Close()
		}
	}
}

func getEnv(key, fallback string) string {
	if v, ok := os.LookupEnv(key); ok {
		return v
	}
	return fallback
}
