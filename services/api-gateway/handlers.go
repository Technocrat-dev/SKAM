package main

import (
	"context"
	"encoding/json"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
)

// ─── Health ─────────────────────────────────────────────────

func healthHandler(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "healthy", "service": "api-gateway"})
}

func readyHandler(w http.ResponseWriter, r *http.Request) {
	// Check if all backends are reachable
	writeJSON(w, http.StatusOK, map[string]string{"status": "ready"})
}

// ─── User Handlers ──────────────────────────────────────────

func createUserHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Username string `json:"username"`
		Email    string `json:"email"`
		Password string `json:"password"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()

	// TODO: Call gRPC user-service
	_ = ctx
	writeJSON(w, http.StatusCreated, map[string]string{
		"id": "usr-001", "username": req.Username, "email": req.Email,
	})
}

func getUserHandler(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()
	_ = ctx

	writeJSON(w, http.StatusOK, map[string]string{"id": id, "username": "demo_user", "email": "demo@example.com"})
}

func loginHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Email    string `json:"email"`
		Password string `json:"password"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	writeJSON(w, http.StatusOK, map[string]string{"user_id": "usr-001", "token": "jwt-token-placeholder"})
}

// ─── Product Handlers ───────────────────────────────────────

func listProductsHandler(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()
	_ = ctx

	products := []map[string]interface{}{
		{"id": "prd-001", "name": "Laptop", "price": 999.99, "stock": 50, "category": "electronics"},
		{"id": "prd-002", "name": "Headphones", "price": 79.99, "stock": 200, "category": "electronics"},
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{"products": products, "total": len(products)})
}

func getProductHandler(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"id": id, "name": "Laptop", "price": 999.99, "stock": 50, "category": "electronics",
	})
}

func createProductHandler(w http.ResponseWriter, r *http.Request) {
	var req map[string]interface{}
	json.NewDecoder(r.Body).Decode(&req)
	req["id"] = "prd-new"
	writeJSON(w, http.StatusCreated, req)
}

// ─── Order Handlers ─────────────────────────────────────────

func createOrderHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		UserID    string `json:"user_id"`
		ProductID string `json:"product_id"`
		Quantity  int    `json:"quantity"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	writeJSON(w, http.StatusCreated, map[string]interface{}{
		"id": "ord-001", "user_id": req.UserID, "product_id": req.ProductID,
		"quantity": req.Quantity, "status": "pending", "total": 999.99,
	})
}

func getOrderHandler(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"id": id, "user_id": "usr-001", "product_id": "prd-001",
		"quantity": 1, "status": "completed", "total": 999.99,
	})
}

func listUserOrdersHandler(w http.ResponseWriter, r *http.Request) {
	userId := chi.URLParam(r, "userId")
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"orders": []map[string]interface{}{
			{"id": "ord-001", "user_id": userId, "status": "completed", "total": 999.99},
		},
	})
}

// ─── Cart Handlers ──────────────────────────────────────────

func addCartItemHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		UserID    string `json:"user_id"`
		ProductID string `json:"product_id"`
		Quantity  int    `json:"quantity"`
	}
	json.NewDecoder(r.Body).Decode(&req)
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"user_id": req.UserID, "items": []map[string]interface{}{
			{"product_id": req.ProductID, "quantity": req.Quantity},
		}, "total_items": req.Quantity,
	})
}

func removeCartItemHandler(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]interface{}{"user_id": "usr-001", "items": []interface{}{}, "total_items": 0})
}

func getCartHandler(w http.ResponseWriter, r *http.Request) {
	userId := chi.URLParam(r, "userId")
	writeJSON(w, http.StatusOK, map[string]interface{}{"user_id": userId, "items": []interface{}{}, "total_items": 0})
}

func clearCartHandler(w http.ResponseWriter, r *http.Request) {
	userId := chi.URLParam(r, "userId")
	writeJSON(w, http.StatusOK, map[string]interface{}{"user_id": userId, "items": []interface{}{}, "total_items": 0})
}

// ─── Payment Handlers ───────────────────────────────────────

func processPaymentHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		OrderID string  `json:"order_id"`
		UserID  string  `json:"user_id"`
		Amount  float64 `json:"amount"`
	}
	json.NewDecoder(r.Body).Decode(&req)
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"id": "pay-001", "order_id": req.OrderID, "status": "completed", "amount": req.Amount,
	})
}

func getPaymentStatusHandler(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"id": id, "order_id": "ord-001", "status": "completed", "amount": 999.99,
	})
}

// ─── Helpers ────────────────────────────────────────────────

func writeJSON(w http.ResponseWriter, status int, data interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(data)
}

func writeError(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, map[string]string{"error": message})
}
