package http

import (
	"log/slog"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	chimw "github.com/go-chi/chi/v5/middleware"
	"github.com/go-chi/cors"

	"github.com/fielddesk-ai/api/internal/config"
	"github.com/fielddesk-ai/api/internal/database"
	"github.com/fielddesk-ai/api/internal/handlers"
	"github.com/fielddesk-ai/api/internal/middleware"
	"github.com/fielddesk-ai/api/internal/storage"
)

func NewRouter(cfg *config.Config, db *database.DB, logger *slog.Logger, store storage.ObjectStore) http.Handler {
	r := chi.NewRouter()

	r.Use(chimw.RequestID)
	r.Use(chimw.RealIP)
	r.Use(middleware.Logger(logger))
	r.Use(chimw.Recoverer)
	r.Use(chimw.Timeout(30 * time.Second))
	r.Use(cors.Handler(cors.Options{
		AllowedOrigins:   []string{"*"},
		AllowedMethods:   []string{"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"},
		AllowedHeaders:   []string{"Accept", "Authorization", "Content-Type", "X-Tenant-ID"},
		AllowCredentials: false,
		MaxAge:           300,
	}))

	h := handlers.New(cfg, db, logger, store)

	r.Get("/healthz", h.Health)
	r.Get("/readyz", h.Ready)

	r.Route("/v1", func(r chi.Router) {
		// /auth is outside RequireTenant because signup/login establish the tenant.
		r.Route("/auth", func(r chi.Router) {
			r.Post("/signup", h.NotImplemented)
			r.Post("/login", h.NotImplemented)
			r.Post("/logout", h.NotImplemented)
			r.Get("/me", h.NotImplemented)
		})

		r.Group(func(r chi.Router) {
			r.Use(middleware.RequireTenant)

			r.Route("/voice-notes", func(r chi.Router) {
				r.Get("/", h.ListVoiceNotes)
				r.Post("/", h.CreateVoiceNote)
				r.Get("/{id}", h.GetVoiceNote)
				r.Post("/{id}/upload-url", h.VoiceNoteUploadURL)
				r.Post("/{id}/uploaded", h.VoiceNoteUploaded)
			})

			r.Route("/tickets", func(r chi.Router) {
				r.Get("/", h.ListTickets)
				r.Get("/{id}", h.GetTicket)
				r.Patch("/{id}", h.NotImplemented)
				r.Post("/{id}/approve", h.ApproveTicket)
				r.Post("/{id}/reject", h.RejectTicket)
			})

			r.Route("/documents", func(r chi.Router) {
				r.Get("/", h.NotImplemented)
				r.Post("/", h.NotImplemented)
				r.Delete("/{id}", h.NotImplemented)
			})

			r.Route("/ai-jobs", func(r chi.Router) {
				r.Get("/", h.NotImplemented)
				r.Get("/{id}", h.NotImplemented)
				r.Post("/{id}/retry", h.NotImplemented)
			})

			r.Route("/model-logs", func(r chi.Router) {
				r.Get("/", h.NotImplemented)
			})

			r.Route("/review-queue", func(r chi.Router) {
				r.Get("/", h.ListReviewQueue)
				r.Post("/{id}/resolve", h.ResolveReview)
			})

			r.Route("/admin", func(r chi.Router) {
				r.Get("/metrics", h.NotImplemented)
				r.Get("/costs", h.NotImplemented)
				r.Get("/failures", h.NotImplemented)
				r.Get("/budgets", h.NotImplemented)
				r.Put("/budgets", h.NotImplemented)
			})
		})
	})

	return r
}
