package config

import (
	"errors"
	"os"
	"strconv"
	"time"

	"github.com/joho/godotenv"
)

type Config struct {
	Env         string
	Port        string
	DatabaseURL string

	S3Endpoint        string
	S3PublicEndpoint  string
	S3Region          string
	S3Bucket          string
	S3AccessKeyID     string
	S3SecretAccessKey string
	S3UseSSL          bool

	VoiceNoteMaxBytes int64
	PresignTTL        time.Duration

	AIWorkerURL string
}

func Load() (*Config, error) {
	_ = godotenv.Load()

	cfg := &Config{
		Env:               getenv("APP_ENV", "development"),
		Port:              getenv("PORT", "8080"),
		DatabaseURL:       os.Getenv("DATABASE_URL"),
		S3Endpoint:        os.Getenv("S3_ENDPOINT"),
		S3PublicEndpoint:  os.Getenv("S3_PUBLIC_ENDPOINT"),
		S3Region:          getenv("S3_REGION", "us-east-1"),
		S3Bucket:          getenv("S3_BUCKET", "fielddesk"),
		S3AccessKeyID:     os.Getenv("S3_ACCESS_KEY_ID"),
		S3SecretAccessKey: os.Getenv("S3_SECRET_ACCESS_KEY"),
		S3UseSSL:          getenvBool("S3_USE_SSL", false),
		VoiceNoteMaxBytes: getenvInt64("VOICE_NOTE_MAX_BYTES", 50*1024*1024),
		PresignTTL:        time.Duration(getenvInt64("PRESIGN_TTL_SECONDS", 900)) * time.Second,
		AIWorkerURL:       os.Getenv("AI_WORKER_URL"),
	}

	if cfg.DatabaseURL == "" {
		return nil, errors.New("DATABASE_URL is required")
	}
	if cfg.S3Endpoint == "" {
		return nil, errors.New("S3_ENDPOINT is required")
	}
	if cfg.S3AccessKeyID == "" || cfg.S3SecretAccessKey == "" {
		return nil, errors.New("S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY are required")
	}
	return cfg, nil
}

func getenv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func getenvBool(key string, fallback bool) bool {
	v := os.Getenv(key)
	if v == "" {
		return fallback
	}
	b, err := strconv.ParseBool(v)
	if err != nil {
		return fallback
	}
	return b
}

func getenvInt64(key string, fallback int64) int64 {
	v := os.Getenv(key)
	if v == "" {
		return fallback
	}
	n, err := strconv.ParseInt(v, 10, 64)
	if err != nil {
		return fallback
	}
	return n
}
