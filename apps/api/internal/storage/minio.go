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

func (m *MinIO) Exists(ctx context.Context, key string) (bool, error) {
	info, err := m.Stat(ctx, key)
	if err != nil {
		return false, err
	}
	return info.Exists, nil
}

func (m *MinIO) Stat(ctx context.Context, key string) (ObjectInfo, error) {
	info, err := m.cli.StatObject(ctx, m.bucket, key, minio.StatObjectOptions{})
	if err == nil {
		return ObjectInfo{
			Exists:      true,
			Size:        info.Size,
			ContentType: info.ContentType,
		}, nil
	}
	er := minio.ToErrorResponse(err)
	if er.StatusCode == http.StatusNotFound || er.Code == "NoSuchKey" {
		return ObjectInfo{Exists: false}, nil
	}
	return ObjectInfo{}, fmt.Errorf("stat object: %w", err)
}

// Swap the in-cluster host for a browser-reachable one. Safe to mutate
// scheme+host after signing because minio-go signs the path + query, not the host.
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
