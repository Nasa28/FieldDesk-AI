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
			r.Post("/signup", h.Signup)
			r.Post("/login", h.Login)
			r.Post("/logout", h.Logout)
			r.Get("/me", h.Me)
		})

		r.Group(func(r chi.Router) {
			r.Use(middleware.RequireTenant(db))

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
				r.Patch("/{id}", h.UpdateTicket)
				r.Post("/{id}/approve", h.ApproveTicket)
				r.Post("/{id}/reject", h.RejectTicket)
			})

			r.Route("/documents", func(r chi.Router) {
				r.Get("/", h.ListDocuments)
				r.Post("/", h.CreateDocument)
				r.Get("/{id}", h.GetDocument)
				r.Post("/{id}/upload-url", h.DocumentUploadURL)
				r.Post("/{id}/uploaded", h.DocumentUploaded)
				r.Delete("/{id}", h.DeleteDocument)
			})

			r.Route("/ai-jobs", func(r chi.Router) {
				r.Get("/", h.ListAIJobs)
				r.Get("/{id}", h.GetAIJob)
				r.Post("/{id}/retry", h.RetryAIJob)
			})

			r.Route("/model-logs", func(r chi.Router) {
				r.Get("/", h.ListModelLogs)
			})

			r.Route("/review-queue", func(r chi.Router) {
				r.Get("/", h.ListReviewQueue)
				r.Post("/{id}/resolve", h.ResolveReview)
			})

			r.Route("/rag", func(r chi.Router) {
				r.Post("/search", h.RAGSearch)
				r.Get("/queries/by-ticket/{id}", h.RAGQueryByTicket)
			})

			r.Route("/admin", func(r chi.Router) {
				r.Get("/metrics", h.AdminMetrics)
				r.Get("/costs", h.Costs)
				r.Get("/failures", h.AdminFailures)
				r.Get("/budgets", h.GetBudgets)
				r.Put("/budgets", h.PutBudgets)
			})
		})
	})

	return r
}
