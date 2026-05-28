-- +goose Up
-- +goose StatementBegin

-- A recommendation may only cite the rag_query that was produced for the same
-- ticket and tenant. The existing rag_query_id FK proves the row exists; this
-- trigger proves it is the right retrieval row for this recommendation.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM ticket_recommendations r
        LEFT JOIN rag_queries rq
               ON rq.id = r.rag_query_id
              AND rq.tenant_id = r.tenant_id
              AND rq.job_ticket_id = r.job_ticket_id
        WHERE r.rag_query_id IS NOT NULL
          AND rq.id IS NULL
    ) THEN
        RAISE EXCEPTION
            'existing ticket_recommendations rows reference rag_queries from another ticket or tenant';
    END IF;
END $$;

CREATE OR REPLACE FUNCTION enforce_ticket_recommendation_rag_query_ticket()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.rag_query_id IS NULL THEN
        RETURN NEW;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM rag_queries rq
        WHERE rq.id = NEW.rag_query_id
          AND rq.tenant_id = NEW.tenant_id
          AND rq.job_ticket_id = NEW.job_ticket_id
    ) THEN
        RAISE EXCEPTION
            'ticket_recommendations.rag_query_id must reference a rag_queries row for the same tenant and job_ticket'
            USING ERRCODE = '23503';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER ticket_recommendations_rag_query_ticket_check
BEFORE INSERT OR UPDATE OF tenant_id, job_ticket_id, rag_query_id
ON ticket_recommendations
FOR EACH ROW
EXECUTE FUNCTION enforce_ticket_recommendation_rag_query_ticket();

-- +goose StatementEnd

-- +goose Down
-- +goose StatementBegin

DROP TRIGGER IF EXISTS ticket_recommendations_rag_query_ticket_check
    ON ticket_recommendations;
DROP FUNCTION IF EXISTS enforce_ticket_recommendation_rag_query_ticket();

-- +goose StatementEnd
