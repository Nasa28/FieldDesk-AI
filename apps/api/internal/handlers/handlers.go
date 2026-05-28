package handlers

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"time"

	"github.com/fielddesk-ai/api/internal/config"
	"github.com/fielddesk-ai/api/internal/database"
	"github.com/fielddesk-ai/api/internal/storage"
)

type Handlers struct {
	cfg     *config.Config
	db      *database.DB
	logger  *slog.Logger
	storage storage.ObjectStore
}

func New(cfg *config.Config, db *database.DB, logger *slog.Logger, store storage.ObjectStore) *Handlers {
	return &Handlers{cfg: cfg, db: db, logger: logger, storage: store}
}

func (h *Handlers) Health(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{
		"status": "ok",
		"time":   time.Now().UTC(),
	})
}

func (h *Handlers) Ready(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	if err := h.db.Ping(ctx); err != nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{
			"status": "unready",
			"error":  err.Error(),
		})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"status": "ready"})
}

func (h *Handlers) NotImplemented(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusNotImplemented, map[string]any{
		"error": "not_implemented",
		"path":  r.URL.Path,
	})
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

func writeError(w http.ResponseWriter, status int, code, message string) {
	writeJSON(w, status, map[string]string{"error": code, "message": message})
}

func decodeJSON(r *http.Request, dst any) error {
	dec := json.NewDecoder(r.Body)
	dec.DisallowUnknownFields()
	if err := dec.Decode(dst); err != nil {
		return errors.New("invalid JSON body: " + err.Error())
	}
	return nil
}
