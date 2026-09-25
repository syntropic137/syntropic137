-- Migration: 006_session_conversations_requested_model
-- Description: Store the REQUESTED model beside the observed one (ADR-067)
--
-- `model` used to hold the phase's declared model, usually an alias such as
-- `opus`, which says nothing about what ran. From ADR-067 on, `model` is what
-- the harness REPORTED (or NULL) and the declared model is `requested_model`.
-- Rows indexed before this column existed are classified on read by
-- `syn_adapters.conversations.minio_index.normalize_recorded_model`.
--
-- MinioConversationStorage applies this itself on startup unless
-- SYN_SKIP_AUTO_CREATE_TABLES is set, in which case apply it by hand. Until it
-- is applied, conversations are still indexed, just without the request.

ALTER TABLE session_conversations ADD COLUMN IF NOT EXISTS requested_model TEXT;
