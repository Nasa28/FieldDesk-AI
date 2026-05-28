package storage

import (
	"context"
	"fmt"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"
)

// MinIOConfig is everything needed to build a MinIO client.
// PublicEndpoint is optional — when set, presigned URLs are rewritten
// to use it so a browser can reach the bucket through a host-visible URL
// (e.g. http://localhost:9000) even though the API uses the in-cluster
// hostname (e.g. minio:9000) for direct calls.
type MinIOConfig struct {
	Endpoint        string
	PublicEndpoint  string
	Region          string
	Bucket          string
	AccessKeyID     string
	SecretAccessKey string
	UseSSL          bool
}

type MinIO struct {
	cli            *minio.Client
	bucket         string
	publicEndpoint string
}

// NewMinIO builds a MinIO/S3 client. Endpoint must be a bare host:port,
// not a URL — minio-go takes the scheme via UseSSL.
func NewMinIO(cfg MinIOConfig) (*MinIO, error) {
	endpoint := stripScheme(cfg.Endpoint)
	cli, err := minio.New(endpoint, &minio.Options{
		Creds:  credentials.NewStaticV4(cfg.AccessKeyID, cfg.SecretAccessKey, ""),
		Secure: cfg.UseSSL,
		Region: cfg.Region,
	})
	if err != nil {
		return nil, fmt.Errorf("minio client: %w", err)
	}
	return &MinIO{
		cli:            cli,
		bucket:         cfg.Bucket,
		publicEndpoint: strings.TrimRight(cfg.PublicEndpoint, "/"),
	}, nil
}

func (m *MinIO) PresignPut(ctx context.Context, key, contentType string, expires time.Duration) (string, error) {
	headers := make(http.Header)
	if contentType != "" {
		headers.Set("Content-Type", contentType)
	}
	u, err := m.cli.PresignHeader(ctx, http.MethodPut, m.bucket, key, expires, url.Values{}, headers)
	if err != nil {
		return "", fmt.Errorf("presign put: %w", err)
	}
	return m.rewriteForPublic(u).String(), nil
}

// rewriteForPublic swaps the in-cluster host (e.g. http://minio:9000) for a
// browser-reachable host (e.g. http://localhost:9000) when PublicEndpoint is set.
// minio-go signs the request based on its configured endpoint, so we only
// touch scheme + host — the signature stays valid.
func (m *MinIO) rewriteForPublic(u *url.URL) *url.URL {
	if m.publicEndpoint == "" {
		return u
	}
	pub, err := url.Parse(m.publicEndpoint)
	if err != nil || pub.Host == "" {
		return u
	}
	out := *u
	out.Scheme = pub.Scheme
	out.Host = pub.Host
	return &out
}

func stripScheme(endpoint string) string {
	endpoint = strings.TrimSpace(endpoint)
	endpoint = strings.TrimPrefix(endpoint, "http://")
	endpoint = strings.TrimPrefix(endpoint, "https://")
	endpoint = strings.TrimSuffix(endpoint, "/")
	return endpoint
}
