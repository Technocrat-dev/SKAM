FROM golang:1.22-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o /service .

FROM gcr.io/distroless/static:nonroot
COPY --from=builder /service /service
EXPOSE 50056 8081
ENTRYPOINT ["/service"]
