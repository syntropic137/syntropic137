// @generated — do not edit. Regenerate with: pnpm generate:types

export interface paths {
    "/workflows": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Workflows Endpoint
         * @description List all workflow templates.
         */
        get: operations["list_workflows_endpoint_workflows_get"];
        put?: never;
        /**
         * Create Workflow Endpoint
         * @description Create a new workflow template.
         */
        post: operations["create_workflow_endpoint_workflows_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/workflows/{workflow_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Workflow Endpoint
         * @description Get workflow details by ID (supports partial ID prefix matching).
         */
        get: operations["get_workflow_endpoint_workflows__workflow_id__get"];
        put?: never;
        post?: never;
        /**
         * Archive (soft-delete) a workflow template
         * @description Archive (soft-delete) a workflow template.
         *
         *     Archived templates are excluded from listing by default but remain
         *     accessible via `GET /workflows/{id}` and with `?include_archived=true`.
         */
        delete: operations["delete_workflow_endpoint_workflows__workflow_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/workflows/{workflow_id}/export": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Export Workflow Endpoint
         * @description Export a workflow as a distributable package or Claude Code plugin.
         */
        get: operations["export_workflow_endpoint_workflows__workflow_id__export_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/workflows/{workflow_id}/runs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Workflow Runs Endpoint
         * @description List all execution runs for a workflow.
         */
        get: operations["list_workflow_runs_endpoint_workflows__workflow_id__runs_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/workflows/{workflow_id}/history": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Workflow History Endpoint
         * @description DEPRECATED: Use /workflows/{workflow_id}/runs instead.
         */
        get: operations["get_workflow_history_endpoint_workflows__workflow_id__history_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/workflows/validate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Validate Yaml Endpoint
         * @description Validate a workflow YAML definition.
         */
        post: operations["validate_yaml_endpoint_workflows_validate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/workflows/{workflow_id}/phases/{phase_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Update Phase Prompt Endpoint
         * @description Update a workflow phase's prompt template and optional config.
         */
        put: operations["update_phase_prompt_endpoint_workflows__workflow_id__phases__phase_id__put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/workflows/from-yaml": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Create Workflow From Yaml Endpoint
         * @description Create a workflow template by uploading raw YAML.
         *
         *     The CLI (`syn workflow create --from <file>`) POSTs the file bytes
         *     here. Every semantic field (name, classification, repository,
         *     phases, inputs, requires_repos) comes from the YAML itself.
         *
         *     Query-string ``name`` and ``workflow_id`` are optional overrides
         *     intended for scripted bulk installation (e.g. renaming a template
         *     on install). They are *not* a second source of truth for fields
         *     that live in the YAML.
         */
        post: operations["create_workflow_from_yaml_endpoint_workflows_from_yaml_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/executions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Executions Endpoint
         * @description List all workflow executions across all workflows.
         */
        get: operations["list_executions_endpoint_executions_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/executions/{execution_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Execution Endpoint
         * @description Get detailed information about a workflow execution run (supports partial ID prefix matching).
         */
        get: operations["get_execution_endpoint_executions__execution_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/workflows/{workflow_id}/execute": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Execute Workflow Endpoint
         * @description Start workflow execution in background.
         */
        post: operations["execute_workflow_endpoint_workflows__workflow_id__execute_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/workflows/{workflow_id}/executions/{execution_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Execution Status Endpoint
         * @description Get the status of a workflow execution.
         */
        get: operations["get_execution_status_endpoint_workflows__workflow_id__executions__execution_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/workflows/executions/active": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Active Executions Endpoint
         * @description List all active (non-completed) executions.
         */
        get: operations["list_active_executions_endpoint_workflows_executions_active_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/executions/{execution_id}/pause": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Pause Execution Endpoint
         * @description Pause a running execution.
         */
        post: operations["pause_execution_endpoint_executions__execution_id__pause_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/executions/{execution_id}/resume": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Resume Execution Endpoint
         * @description Resume a paused execution.
         */
        post: operations["resume_execution_endpoint_executions__execution_id__resume_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/executions/{execution_id}/cancel": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Cancel Execution Endpoint
         * @description Cancel a running or paused execution.
         */
        post: operations["cancel_execution_endpoint_executions__execution_id__cancel_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/executions/{execution_id}/inject": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Inject Context Endpoint
         * @description Inject a message into the execution context.
         */
        post: operations["inject_context_endpoint_executions__execution_id__inject_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/executions/{execution_id}/state": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Execution State Endpoint
         * @description Get current execution state.
         */
        get: operations["get_execution_state_endpoint_executions__execution_id__state_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/sessions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Sessions Endpoint
         * @description List agent sessions with optional filtering.
         */
        get: operations["list_sessions_endpoint_sessions_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/sessions/{session_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Session Endpoint
         * @description Get session details by ID (supports partial ID prefix matching).
         */
        get: operations["get_session_endpoint_sessions__session_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/artifacts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Artifacts Endpoint
         * @description List artifacts with optional filtering.
         */
        get: operations["list_artifacts_endpoint_artifacts_get"];
        put?: never;
        /**
         * Create Artifact Endpoint
         * @description Create a new artifact.
         */
        post: operations["create_artifact_endpoint_artifacts_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/artifacts/{artifact_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Artifact Endpoint
         * @description Get artifact details by ID (supports partial ID prefix matching).
         */
        get: operations["get_artifact_endpoint_artifacts__artifact_id__get"];
        /**
         * Update Artifact Endpoint
         * @description Update artifact metadata.
         */
        put: operations["update_artifact_endpoint_artifacts__artifact_id__put"];
        post?: never;
        /**
         * Delete Artifact Endpoint
         * @description Soft-delete an artifact.
         */
        delete: operations["delete_artifact_endpoint_artifacts__artifact_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/artifacts/{artifact_id}/content": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Artifact Content Endpoint
         * @description Get artifact content only (for large artifacts).
         */
        get: operations["get_artifact_content_endpoint_artifacts__artifact_id__content_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/artifacts/{artifact_id}/upload": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Upload Artifact Endpoint
         * @description Upload binary content for an existing artifact (max 50 MB).
         */
        post: operations["upload_artifact_endpoint_artifacts__artifact_id__upload_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/metrics": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Metrics Endpoint
         * @description Get aggregated metrics across all workflows or for a specific workflow.
         */
        get: operations["get_metrics_endpoint_metrics_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/observability/sessions/{session_id}/tools": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Tool Timeline Endpoint
         * @description Get tool execution timeline for a session.
         */
        get: operations["get_tool_timeline_endpoint_observability_sessions__session_id__tools_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/observability/sessions/{session_id}/tokens": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Token Metrics Endpoint
         * @description Get token usage metrics for a session.
         */
        get: operations["get_token_metrics_endpoint_observability_sessions__session_id__tokens_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/costs/sessions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Session Costs Endpoint
         * @description List session costs with optional filtering.
         */
        get: operations["list_session_costs_endpoint_costs_sessions_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/costs/sessions/{session_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Session Cost Endpoint
         * @description Get cost for a specific session.
         */
        get: operations["get_session_cost_endpoint_costs_sessions__session_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/costs/executions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Execution Costs Endpoint
         * @description List execution costs.
         */
        get: operations["list_execution_costs_endpoint_costs_executions_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/costs/executions/{execution_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Execution Cost Endpoint
         * @description Get aggregated cost for a workflow execution.
         */
        get: operations["get_execution_cost_endpoint_costs_executions__execution_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/costs/summary": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Cost Summary Endpoint
         * @description Get summary of all costs across sessions and executions.
         */
        get: operations["get_cost_summary_endpoint_costs_summary_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/events/recent": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Recent Activity Endpoint
         * @description Get recent activity events for the global dashboard feed.
         */
        get: operations["get_recent_activity_endpoint_events_recent_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/events/sessions/{session_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Session Events Endpoint
         * @description Get all events for a session.
         */
        get: operations["get_session_events_endpoint_events_sessions__session_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/events/sessions/{session_id}/timeline": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Session Timeline Endpoint
         * @description Get a timeline view of session events.
         */
        get: operations["get_session_timeline_endpoint_events_sessions__session_id__timeline_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/events/sessions/{session_id}/costs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Session Costs Endpoint
         * @description Get cost summary for a session.
         */
        get: operations["get_session_costs_endpoint_events_sessions__session_id__costs_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/events/sessions/{session_id}/tools": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Session Tools Endpoint
         * @description Get tool usage summary for a session.
         */
        get: operations["get_session_tools_endpoint_events_sessions__session_id__tools_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/github/repos": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Accessible Repos Endpoint
         * @description List repositories accessible to the GitHub App.
         *
         *     Queries all active installations and aggregates results when no
         *     installation_id is provided. The installation list is cached locally with
         *     a 1-hour TTL: if empty or stale, it bootstraps automatically from the
         *     GitHub API without requiring a webhook URL. Stale data is kept as a
         *     fallback if the GitHub API is unreachable during refresh.
         */
        get: operations["list_accessible_repos_endpoint_github_repos_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/conversations/{session_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Conversation Log Endpoint
         * @description Get conversation log for a session.
         */
        get: operations["get_conversation_log_endpoint_conversations__session_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/conversations/{session_id}/metadata": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Conversation Metadata Endpoint
         * @description Get conversation metadata for a session.
         */
        get: operations["get_conversation_metadata_endpoint_conversations__session_id__metadata_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/triggers": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Triggers Endpoint
         * @description List all trigger rules.
         */
        get: operations["list_triggers_endpoint_triggers_get"];
        put?: never;
        /**
         * Register Trigger Endpoint
         * @description Register a new trigger rule.
         */
        post: operations["register_trigger_endpoint_triggers_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/triggers/history": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get All History Endpoint
         * @description Get all trigger activity (global).
         */
        get: operations["get_all_history_endpoint_triggers_history_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/triggers/{trigger_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Trigger Endpoint
         * @description Get trigger details.
         */
        get: operations["get_trigger_endpoint_triggers__trigger_id__get"];
        put?: never;
        post?: never;
        /**
         * Delete Trigger Endpoint
         * @description Delete a trigger rule.
         */
        delete: operations["delete_trigger_endpoint_triggers__trigger_id__delete"];
        options?: never;
        head?: never;
        /**
         * Update Trigger Endpoint
         * @description Update trigger (pause/resume).
         */
        patch: operations["update_trigger_endpoint_triggers__trigger_id__patch"];
        trace?: never;
    };
    "/triggers/{trigger_id}/history": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Trigger History Endpoint
         * @description Get execution history for a trigger.
         */
        get: operations["get_trigger_history_endpoint_triggers__trigger_id__history_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/triggers/presets/{preset_name}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Enable Preset Endpoint
         * @description Enable a preset for a repository.
         */
        post: operations["enable_preset_endpoint_triggers_presets__preset_name__post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/webhooks/github": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Github Webhook Endpoint
         * @description Handle GitHub webhooks.
         */
        post: operations["github_webhook_endpoint_webhooks_github_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/sse/executions/{execution_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Execution Sse
         * @description Stream domain events for a single execution.
         *
         *     Sends a ``connected`` handshake frame on connect, then forwards every
         *     domain event emitted by the RealTimeProjection for this execution.
         *     Closes automatically when a terminal event (WorkflowCompleted /
         *     WorkflowFailed) is broadcast, or when the client disconnects.
         */
        get: operations["execution_sse_sse_executions__execution_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/sse/activity": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Activity Sse
         * @description Stream the global activity feed (git events, system-wide activity).
         *
         *     Runs indefinitely until the client disconnects.  There is no terminal
         *     sentinel for the activity channel, it never completes.
         */
        get: operations["activity_sse_sse_activity_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/sse/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Sse Health
         * @description Health check for the SSE subsystem.
         *
         *     Returns active subscriber and execution counts from the RealTimeProjection.
         */
        get: operations["sse_health_sse_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/organizations": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Organizations Endpoint
         * @description List all organizations.
         */
        get: operations["list_organizations_endpoint_organizations_get"];
        put?: never;
        /**
         * Create Organization Endpoint
         * @description Create a new organization.
         */
        post: operations["create_organization_endpoint_organizations_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/organizations/{organization_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Organization Endpoint
         * @description Get organization details.
         */
        get: operations["get_organization_endpoint_organizations__organization_id__get"];
        /**
         * Update Organization Endpoint
         * @description Update an organization.
         */
        put: operations["update_organization_endpoint_organizations__organization_id__put"];
        post?: never;
        /**
         * Delete Organization Endpoint
         * @description Soft-delete an organization.
         */
        delete: operations["delete_organization_endpoint_organizations__organization_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/systems": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Systems Endpoint
         * @description List systems with optional organization filter.
         */
        get: operations["list_systems_endpoint_systems_get"];
        put?: never;
        /**
         * Create System Endpoint
         * @description Create a new system.
         */
        post: operations["create_system_endpoint_systems_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/systems/{system_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get System Endpoint
         * @description Get system details.
         */
        get: operations["get_system_endpoint_systems__system_id__get"];
        /**
         * Update System Endpoint
         * @description Update a system.
         */
        put: operations["update_system_endpoint_systems__system_id__put"];
        post?: never;
        /**
         * Delete System Endpoint
         * @description Soft-delete a system.
         */
        delete: operations["delete_system_endpoint_systems__system_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/systems/{system_id}/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get System Status Endpoint
         * @description Get cross-repo health overview for a system.
         */
        get: operations["get_system_status_endpoint_systems__system_id__status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/systems/{system_id}/cost": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get System Cost Endpoint
         * @description Get cost breakdown for a system.
         */
        get: operations["get_system_cost_endpoint_systems__system_id__cost_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/systems/{system_id}/activity": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get System Activity Endpoint
         * @description Get execution timeline for a system.
         */
        get: operations["get_system_activity_endpoint_systems__system_id__activity_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/systems/{system_id}/patterns": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get System Patterns Endpoint
         * @description Get recurring failure and cost patterns for a system.
         */
        get: operations["get_system_patterns_endpoint_systems__system_id__patterns_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/systems/{system_id}/history": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get System History Endpoint
         * @description Get historical execution timeline for a system.
         */
        get: operations["get_system_history_endpoint_systems__system_id__history_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/repos": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Repos Endpoint
         * @description List repos with optional filters.
         */
        get: operations["list_repos_endpoint_repos_get"];
        put?: never;
        /**
         * Register Repo Endpoint
         * @description Register a new repo.
         */
        post: operations["register_repo_endpoint_repos_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/repos/{repo_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Repo Endpoint
         * @description Get repo details.
         */
        get: operations["get_repo_endpoint_repos__repo_id__get"];
        /**
         * Update Repo Endpoint
         * @description Update mutable fields of a repo.
         */
        put: operations["update_repo_endpoint_repos__repo_id__put"];
        post?: never;
        /**
         * Deregister Repo Endpoint
         * @description Deregister (soft-delete) a repo.
         */
        delete: operations["deregister_repo_endpoint_repos__repo_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/repos/{repo_id}/assign": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Assign Repo To System Endpoint
         * @description Assign a repo to a system.
         */
        post: operations["assign_repo_to_system_endpoint_repos__repo_id__assign_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/repos/{repo_id}/unassign": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Unassign Repo From System Endpoint
         * @description Unassign a repo from its system.
         */
        post: operations["unassign_repo_from_system_endpoint_repos__repo_id__unassign_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/repos/{repo_id}/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Repo Health Endpoint
         * @description Get health snapshot for a repo.
         */
        get: operations["get_repo_health_endpoint_repos__repo_id__health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/repos/{repo_id}/cost": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Repo Cost Endpoint
         * @description Get cost breakdown for a repo.
         */
        get: operations["get_repo_cost_endpoint_repos__repo_id__cost_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/repos/{repo_id}/activity": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Repo Activity Endpoint
         * @description Get execution timeline for a repo.
         */
        get: operations["get_repo_activity_endpoint_repos__repo_id__activity_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/repos/{repo_id}/failures": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Repo Failures Endpoint
         * @description Get recent failures for a repo.
         */
        get: operations["get_repo_failures_endpoint_repos__repo_id__failures_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/repos/{repo_id}/sessions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Repo Sessions Endpoint
         * @description Get agent sessions for a repo.
         */
        get: operations["get_repo_sessions_endpoint_repos__repo_id__sessions_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/insights/overview": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Global Overview Endpoint
         * @description Get global overview of all systems and repos.
         */
        get: operations["get_global_overview_endpoint_insights_overview_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/insights/cost": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Global Cost Endpoint
         * @description Get global cost breakdown, optionally filtered by system.
         */
        get: operations["get_global_cost_endpoint_insights_cost_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/insights/contribution-heatmap": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Contribution Heatmap Endpoint
         * @description Get daily contribution heatmap data.
         */
        get: operations["get_contribution_heatmap_endpoint_insights_contribution_heatmap_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Root
         * @description Root endpoint with API info.
         */
        get: operations["root__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Health
         * @description Health check endpoint with detailed subscription status.
         */
        get: operations["health_health_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /**
         * ArtifactActionResponse
         * @description Response for artifact update/delete actions.
         */
        ArtifactActionResponse: {
            /** Artifact Id */
            artifact_id: string;
            /** Status */
            status: string;
        };
        /** ArtifactContentResponse */
        ArtifactContentResponse: {
            /** Artifact Id */
            artifact_id: string;
            /** Content */
            content: string | null;
            /** Content Type */
            content_type: string;
            /** Size Bytes */
            size_bytes: number | null;
        };
        /**
         * ArtifactResponse
         * @description Detailed artifact response.
         */
        ArtifactResponse: {
            /** Id */
            id: string;
            /** Workflow Id */
            workflow_id: string | null;
            /** Phase Id */
            phase_id: string | null;
            /** Session Id */
            session_id: string | null;
            /** Artifact Type */
            artifact_type: string;
            /**
             * Is Primary Deliverable
             * @default true
             */
            is_primary_deliverable: boolean;
            /** Content */
            content?: string | null;
            /**
             * Content Type
             * @default text/markdown
             */
            content_type: string;
            /** Content Hash */
            content_hash?: string | null;
            /**
             * Size Bytes
             * @default 0
             */
            size_bytes: number;
            /** Title */
            title?: string | null;
            /** Derived From */
            derived_from?: string[];
            /** Created At */
            created_at?: string | null;
            /** Created By */
            created_by?: string | null;
            /** Metadata */
            metadata?: {
                [key: string]: unknown;
            };
        };
        /**
         * ArtifactSummaryResponse
         * @description Summary of an artifact.
         */
        ArtifactSummaryResponse: {
            /** Id */
            id: string;
            /** Workflow Id */
            workflow_id: string | null;
            /** Phase Id */
            phase_id: string | null;
            /** Artifact Type */
            artifact_type: string;
            /** Title */
            title?: string | null;
            /**
             * Size Bytes
             * @default 0
             */
            size_bytes: number;
            /** Created At */
            created_at?: string | null;
        };
        /**
         * AssignRepoToSystemRequest
         * @description Request body for assigning a repo to a system.
         */
        AssignRepoToSystemRequest: {
            /** System Id */
            system_id: string;
        };
        /** Body_upload_artifact_endpoint_artifacts__artifact_id__upload_post */
        Body_upload_artifact_endpoint_artifacts__artifact_id__upload_post: {
            /** File */
            file: string;
        };
        /**
         * CancelRequest
         * @description Request to cancel an execution.
         */
        CancelRequest: {
            /** Reason */
            reason?: string | null;
        };
        /**
         * ConditionRequest
         * @description A single trigger condition (field operator value).
         */
        ConditionRequest: {
            /** Field */
            field: string;
            /** Operator */
            operator: string;
            /** Value */
            value: string;
        };
        /**
         * ContributionHeatmapResponse
         * @description Contribution heatmap data.
         */
        ContributionHeatmapResponse: {
            /** Metric */
            metric: string;
            /** Start Date */
            start_date: string;
            /** End Date */
            end_date: string;
            /**
             * Total
             * @default 0
             */
            total: number;
            /** Days */
            days?: components["schemas"]["HeatmapDayBucketResponse"][];
            /** Filter */
            filter?: {
                [key: string]: string | null;
            };
        };
        /**
         * ControlResponse
         * @description Response from a control command.
         */
        ControlResponse: {
            /** Success */
            success: boolean;
            /** Execution Id */
            execution_id: string;
            /** State */
            state: string;
            /** Message */
            message?: string | null;
            /** Error */
            error?: string | null;
        };
        /**
         * ConversationLineResponse
         * @description A single line from the conversation log.
         */
        ConversationLineResponse: {
            /** Line Number */
            line_number: number;
            /** Raw */
            raw: string;
            /** Parsed */
            parsed?: {
                [key: string]: unknown;
            } | null;
            /** Event Type */
            event_type?: string | null;
            /** Tool Name */
            tool_name?: string | null;
            /** Content Preview */
            content_preview?: string | null;
        };
        /**
         * ConversationLogResponse
         * @description Response containing conversation log.
         */
        ConversationLogResponse: {
            /** Session Id */
            session_id: string;
            /** Lines */
            lines: components["schemas"]["ConversationLineResponse"][];
            /** Total Lines */
            total_lines: number;
            /** Metadata */
            metadata?: {
                [key: string]: unknown;
            } | null;
        };
        /**
         * ConversationMetadataResponse
         * @description Conversation index metadata.
         */
        ConversationMetadataResponse: {
            /** Session Id */
            session_id: string;
            /** Execution Id */
            execution_id?: string | null;
            /** Workflow Id */
            workflow_id?: string | null;
            /** Phase Id */
            phase_id?: string | null;
            /** Event Count */
            event_count?: number | null;
            /** Total Input Tokens */
            total_input_tokens?: number | null;
            /** Total Output Tokens */
            total_output_tokens?: number | null;
            /** Tool Counts */
            tool_counts?: {
                [key: string]: number;
            } | null;
            /** Started At */
            started_at?: string | null;
            /** Completed At */
            completed_at?: string | null;
            /** Model */
            model?: string | null;
            /** Success */
            success?: boolean | null;
            /** Size Bytes */
            size_bytes?: number | null;
        };
        /**
         * CostOutlierResponse
         * @description An execution with unusually high cost.
         */
        CostOutlierResponse: {
            /**
             * Execution Id
             * @default
             */
            execution_id: string;
            /**
             * Repo Full Name
             * @default
             */
            repo_full_name: string;
            /**
             * Workflow Name
             * @default
             */
            workflow_name: string;
            /**
             * Cost Usd
             * @default 0
             */
            cost_usd: string;
            /**
             * Median Cost Usd
             * @default 0
             */
            median_cost_usd: string;
            /**
             * Deviation Factor
             * @default 0
             */
            deviation_factor: number;
            /**
             * Executed At
             * @default
             */
            executed_at: string;
        };
        /** CreateArtifactRequest */
        CreateArtifactRequest: {
            /** Workflow Id */
            workflow_id: string;
            /** Artifact Type */
            artifact_type: string;
            /** Title */
            title: string;
            /** Content */
            content: string;
            /** Phase Id */
            phase_id?: string | null;
            /** Session Id */
            session_id?: string | null;
            /**
             * Content Type
             * @default text/markdown
             */
            content_type: string;
        };
        /** CreateArtifactResponse */
        CreateArtifactResponse: {
            /** Id */
            id: string;
            /** Title */
            title: string;
            /** Artifact Type */
            artifact_type: string;
            /** Status */
            status: string;
        };
        /**
         * CreateOrganizationRequest
         * @description Request body for creating a new organization.
         */
        CreateOrganizationRequest: {
            /** Name */
            name: string;
            /** Slug */
            slug: string;
            /**
             * Created By
             * @default api
             */
            created_by: string;
        };
        /**
         * CreateSystemRequest
         * @description Request body for creating a new system.
         */
        CreateSystemRequest: {
            /** Organization Id */
            organization_id: string;
            /** Name */
            name: string;
            /**
             * Description
             * @default
             */
            description: string;
            /**
             * Created By
             * @default api
             */
            created_by: string;
        };
        /** CreateWorkflowRequest */
        CreateWorkflowRequest: {
            /** Id */
            id?: string | null;
            /** Name */
            name: string;
            /**
             * Workflow Type
             * @default custom
             */
            workflow_type: string;
            /**
             * Classification
             * @default standard
             */
            classification: string;
            /**
             * Repository Url
             * @default
             */
            repository_url: string;
            /**
             * Repository Ref
             * @default main
             */
            repository_ref: string;
            /** Description */
            description?: string | null;
            /** Project Name */
            project_name?: string | null;
            /** Phases */
            phases?: {
                [key: string]: unknown;
            }[] | null;
            /** Input Declarations */
            input_declarations?: {
                [key: string]: unknown;
            }[] | null;
            /**
             * Repos
             * @description Default GitHub URLs for this workflow template (ADR-058). Can be overridden at execution time via the repos field on the execute request.
             */
            repos?: string[];
            /**
             * Requires Repos
             * @description Whether this workflow requires repository access at execution time (ADR-058 #666). Set to false for research or analysis workflows that don't need repos.
             * @default true
             */
            requires_repos: boolean;
        };
        /** CreateWorkflowResponse */
        CreateWorkflowResponse: {
            /** Id */
            id: string;
            /** Name */
            name: string;
            /** Workflow Type */
            workflow_type: string;
            /** Classification */
            classification: string;
            /** Repository Url */
            repository_url: string;
            /** Requires Repos */
            requires_repos: boolean;
            /** Status */
            status: string;
        };
        /** DeleteWorkflowResponse */
        DeleteWorkflowResponse: {
            /** Workflow Id */
            workflow_id: string;
            /** Status */
            status: string;
        };
        /**
         * EventListResponse
         * @description List of events response.
         */
        EventListResponse: {
            /** Events */
            events: components["schemas"]["EventResponse"][];
            /** Count */
            count: number;
            /**
             * Has More
             * @default false
             */
            has_more: boolean;
        };
        /**
         * EventResponse
         * @description Single event response.
         */
        EventResponse: {
            /** Time */
            time?: string | null;
            /** Event Type */
            event_type: string;
            /** Session Id */
            session_id?: string | null;
            /** Execution Id */
            execution_id?: string | null;
            /** Phase Id */
            phase_id?: string | null;
            /**
             * Data
             * @default {}
             */
            data: {
                [key: string]: unknown;
            };
        };
        /**
         * ExecuteWorkflowRequest
         * @description Request to execute a workflow.
         */
        ExecuteWorkflowRequest: {
            /**
             * Inputs
             * @description Input variables for the workflow.
             */
            inputs?: {
                [key: string]: string;
            };
            /**
             * Task
             * @description Primary task description -- substituted for $ARGUMENTS in phase prompts.
             */
            task?: string | null;
            /**
             * Repos
             * @description GitHub URLs to pre-clone for workspace hydration (ADR-058). Overrides the workflow template's repository_url. Equivalent to passing inputs={'repos': 'url1,url2'} but type-safe.
             */
            repos?: string[];
            /**
             * Provider
             * @deprecated
             * @description Agent provider to use. Currently ignored by execute(); sending this field has no effect.
             * @default claude
             */
            provider: string;
            /**
             * Max Budget Usd
             * @deprecated
             * @description Maximum budget in USD. Currently ignored by execute(); sending this field has no effect.
             */
            max_budget_usd?: number | null;
        };
        /**
         * ExecuteWorkflowResponse
         * @description Response after starting workflow execution.
         */
        ExecuteWorkflowResponse: {
            /** Execution Id */
            execution_id: string;
            /** Workflow Id */
            workflow_id: string;
            /**
             * Status
             * @default started
             */
            status: string;
            /**
             * Message
             * @default Workflow execution started
             */
            message: string;
        };
        /**
         * ExecutionCostResponse
         * @description Aggregated cost for a workflow execution.
         */
        ExecutionCostResponse: {
            /** Execution Id */
            execution_id: string;
            /** Workflow Id */
            workflow_id?: string | null;
            /**
             * Session Count
             * @default 0
             */
            session_count: number;
            /** Session Ids */
            session_ids?: string[];
            /**
             * Total Cost Usd
             * @default 0
             */
            total_cost_usd: string;
            /**
             * Token Cost Usd
             * @default 0
             */
            token_cost_usd: string;
            /**
             * Compute Cost Usd
             * @default 0
             */
            compute_cost_usd: string;
            /**
             * Input Tokens
             * @default 0
             */
            input_tokens: number;
            /**
             * Output Tokens
             * @default 0
             */
            output_tokens: number;
            /**
             * Total Tokens
             * @default 0
             */
            total_tokens: number;
            /**
             * Cache Creation Tokens
             * @default 0
             */
            cache_creation_tokens: number;
            /**
             * Cache Read Tokens
             * @default 0
             */
            cache_read_tokens: number;
            /**
             * Tool Calls
             * @default 0
             */
            tool_calls: number;
            /**
             * Turns
             * @default 0
             */
            turns: number;
            /**
             * Duration Ms
             * @default 0
             */
            duration_ms: number;
            /** Cost By Phase */
            cost_by_phase?: {
                [key: string]: string;
            };
            /** Cost By Model */
            cost_by_model?: {
                [key: string]: string;
            };
            /** Cost By Tool */
            cost_by_tool?: {
                [key: string]: string;
            };
            /**
             * Is Complete
             * @default false
             */
            is_complete: boolean;
            /** Started At */
            started_at?: string | null;
            /** Completed At */
            completed_at?: string | null;
        };
        /** ExecutionDetailResponse */
        ExecutionDetailResponse: {
            /** Workflow Execution Id */
            workflow_execution_id: string;
            /** Workflow Id */
            workflow_id: string;
            /** Workflow Name */
            workflow_name: string;
            /** Status */
            status: string;
            /** Started At */
            started_at?: string | null;
            /** Completed At */
            completed_at?: string | null;
            /** Phases */
            phases?: components["schemas"]["PhaseExecutionInfo"][];
            /** Total Input Tokens */
            total_input_tokens: number;
            /** Total Output Tokens */
            total_output_tokens: number;
            /** Total Cache Creation Tokens */
            total_cache_creation_tokens: number;
            /** Total Cache Read Tokens */
            total_cache_read_tokens: number;
            /** Total Tokens */
            total_tokens: number;
            /**
             * Total Cost Usd
             * @default 0
             */
            total_cost_usd: string;
            /**
             * Total Duration Seconds
             * @default 0
             */
            total_duration_seconds: number;
            /** Artifact Ids */
            artifact_ids?: string[];
            /** Error Message */
            error_message?: string | null;
            /** Repos */
            repos?: string[];
        };
        /** ExecutionHistoryResponse */
        ExecutionHistoryResponse: {
            /** Workflow Id */
            workflow_id: string;
            /** Workflow Name */
            workflow_name: string;
            /** Executions */
            executions?: {
                [key: string]: unknown;
            }[];
            /**
             * Total Executions
             * @default 0
             */
            total_executions: number;
        };
        /** ExecutionListResponse */
        ExecutionListResponse: {
            /** Executions */
            executions: components["schemas"]["ExecutionSummaryResponse"][];
            /** Total */
            total: number;
            /**
             * Page
             * @default 1
             */
            page: number;
            /**
             * Page Size
             * @default 50
             */
            page_size: number;
        };
        /** ExecutionRunListResponse */
        ExecutionRunListResponse: {
            /** Runs */
            runs: components["schemas"]["ExecutionRunSummary"][];
            /** Total */
            total: number;
            /** Workflow Id */
            workflow_id: string;
            /** Workflow Name */
            workflow_name: string;
        };
        /** ExecutionRunSummary */
        ExecutionRunSummary: {
            /** Workflow Execution Id */
            workflow_execution_id: string;
            /** Workflow Id */
            workflow_id: string;
            /** Workflow Name */
            workflow_name: string;
            /** Status */
            status: string;
            /** Started At */
            started_at?: string | null;
            /** Completed At */
            completed_at?: string | null;
            /**
             * Completed Phases
             * @default 0
             */
            completed_phases: number;
            /**
             * Total Phases
             * @default 0
             */
            total_phases: number;
            /**
             * Total Tokens
             * @default 0
             */
            total_tokens: number;
            /**
             * Total Cost Usd
             * @default 0
             */
            total_cost_usd: string;
            /** Error Message */
            error_message?: string | null;
        };
        /**
         * ExecutionStatusResponse
         * @description Response for execution status check.
         */
        ExecutionStatusResponse: {
            /** Execution Id */
            execution_id: string;
            /** Workflow Id */
            workflow_id: string;
            /** Status */
            status: string;
            /** Current Phase */
            current_phase?: string | null;
            /**
             * Completed Phases
             * @default 0
             */
            completed_phases: number;
            /**
             * Total Phases
             * @default 0
             */
            total_phases: number;
            /** Started At */
            started_at?: string | null;
            /** Completed At */
            completed_at?: string | null;
            /** Error */
            error?: string | null;
        };
        /** ExecutionSummaryResponse */
        ExecutionSummaryResponse: {
            /** Workflow Execution Id */
            workflow_execution_id: string;
            /** Workflow Id */
            workflow_id: string;
            /** Workflow Name */
            workflow_name: string;
            /** Status */
            status: string;
            /** Started At */
            started_at?: string | null;
            /** Completed At */
            completed_at?: string | null;
            /**
             * Completed Phases
             * @default 0
             */
            completed_phases: number;
            /**
             * Total Phases
             * @default 0
             */
            total_phases: number;
            /** Total Tokens */
            total_tokens: number;
            /** Total Input Tokens */
            total_input_tokens: number;
            /** Total Output Tokens */
            total_output_tokens: number;
            /** Total Cache Creation Tokens */
            total_cache_creation_tokens: number;
            /** Total Cache Read Tokens */
            total_cache_read_tokens: number;
            /**
             * Total Cost Usd
             * @default 0
             */
            total_cost_usd: string;
            /**
             * Tool Call Count
             * @default 0
             */
            tool_call_count: number;
            /** Error Message */
            error_message?: string | null;
            /** Repos */
            repos?: string[];
        };
        /**
         * ExportManifestResponse
         * @description Structured export of a workflow as a file manifest.
         *
         *     Each key in ``files`` is a relative path; each value is the file content.
         *     The CLI writes these to disk to produce an installable package or plugin.
         */
        ExportManifestResponse: {
            /**
             * Format
             * @enum {string}
             */
            format: "package" | "plugin";
            /** Workflow Id */
            workflow_id: string;
            /** Workflow Name */
            workflow_name: string;
            /** Files */
            files: {
                [key: string]: string;
            };
        };
        /**
         * FailurePatternResponse
         * @description A recurring failure pattern within a system.
         */
        FailurePatternResponse: {
            /**
             * Error Type
             * @default
             */
            error_type: string;
            /**
             * Error Message
             * @default
             */
            error_message: string;
            /**
             * Occurrence Count
             * @default 0
             */
            occurrence_count: number;
            /** Affected Repos */
            affected_repos?: string[];
            /**
             * First Seen
             * @default
             */
            first_seen: string;
            /**
             * Last Seen
             * @default
             */
            last_seen: string;
        };
        /**
         * GitEventData
         * @description Structured git event data from observability hooks.
         *
         *     Field names match agentic_events.payloads dataclasses (single source of truth).
         *     This model is the Pydantic equivalent for API serialization.
         */
        GitEventData: {
            /** Operation */
            operation?: string | null;
            /** Sha */
            sha?: string | null;
            /** Branch */
            branch?: string | null;
            /** Repo */
            repo?: string | null;
            /** Message */
            message?: string | null;
            /** Prev Branch */
            prev_branch?: string | null;
            /** Is Clone */
            is_clone?: boolean | null;
            /** Remote */
            remote?: string | null;
            /** Author */
            author?: string | null;
            /** Files Changed */
            files_changed?: number | null;
            /** Insertions */
            insertions?: number | null;
            /** Deletions */
            deletions?: number | null;
            /** Commits Count */
            commits_count?: number | null;
            /** Commit Range */
            commit_range?: string | null;
            /** Remote Url */
            remote_url?: string | null;
            /** Details */
            details?: string | null;
            /** From Branch */
            from_branch?: string | null;
            /** To Branch */
            to_branch?: string | null;
            /** Estimated Tokens Added */
            estimated_tokens_added?: number | null;
            /** Estimated Tokens Removed */
            estimated_tokens_removed?: number | null;
        };
        /**
         * GitHubRepoListResponse
         * @description List of repositories accessible to the GitHub App.
         */
        GitHubRepoListResponse: {
            /** Repos */
            repos?: components["schemas"]["GitHubRepoResponse"][];
            /**
             * Total
             * @default 0
             */
            total: number;
            /** Installation Id */
            installation_id?: string | null;
        };
        /**
         * GitHubRepoResponse
         * @description A repository accessible to the GitHub App installation.
         */
        GitHubRepoResponse: {
            /** Github Id */
            github_id: number;
            /** Name */
            name: string;
            /** Full Name */
            full_name: string;
            /** Private */
            private: boolean;
            /** Default Branch */
            default_branch: string;
            /** Owner */
            owner: string;
            /** Installation Id */
            installation_id: string;
        };
        /**
         * GlobalCostResponse
         * @description Global cost breakdown across all repos.
         */
        GlobalCostResponse: {
            /**
             * System Id
             * @default
             */
            system_id: string;
            /**
             * System Name
             * @default
             */
            system_name: string;
            /**
             * Organization Id
             * @default
             */
            organization_id: string;
            /**
             * Total Cost Usd
             * @default 0
             */
            total_cost_usd: string;
            /**
             * Total Tokens
             * @default 0
             */
            total_tokens: number;
            /**
             * Total Input Tokens
             * @default 0
             */
            total_input_tokens: number;
            /**
             * Total Output Tokens
             * @default 0
             */
            total_output_tokens: number;
            /** Cost By Repo */
            cost_by_repo?: {
                [key: string]: string;
            };
            /** Cost By Workflow */
            cost_by_workflow?: {
                [key: string]: string;
            };
            /** Cost By Model */
            cost_by_model?: {
                [key: string]: string;
            };
            /**
             * Execution Count
             * @default 0
             */
            execution_count: number;
        };
        /**
         * GlobalOverviewResponse
         * @description Global overview of all systems and repos.
         */
        GlobalOverviewResponse: {
            /**
             * Total Systems
             * @default 0
             */
            total_systems: number;
            /**
             * Total Repos
             * @default 0
             */
            total_repos: number;
            /**
             * Unassigned Repos
             * @default 0
             */
            unassigned_repos: number;
            /**
             * Total Active Executions
             * @default 0
             */
            total_active_executions: number;
            /**
             * Total Cost Usd
             * @default 0
             */
            total_cost_usd: string;
            /** Systems */
            systems?: components["schemas"]["SystemOverviewEntryResponse"][];
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /**
         * HeatmapDayBucketResponse
         * @description Single day's aggregated activity.
         */
        HeatmapDayBucketResponse: {
            /** Date */
            date: string;
            /**
             * Count
             * @default 0
             */
            count: number;
            /** Breakdown */
            breakdown?: {
                [key: string]: number;
            };
        };
        /**
         * InjectRequest
         * @description Request to inject context into an execution.
         */
        InjectRequest: {
            /** Message */
            message: string;
            /**
             * Role
             * @default user
             * @enum {string}
             */
            role: "user" | "system";
        };
        /** InputDeclarationModel */
        InputDeclarationModel: {
            /** Name */
            name: string;
            /** Description */
            description?: string | null;
            /**
             * Required
             * @default true
             */
            required: boolean;
            /** Default */
            default?: string | null;
        };
        /**
         * MetricsResponse
         * @description Aggregated metrics response.
         */
        MetricsResponse: {
            /**
             * Total Workflows
             * @default 0
             */
            total_workflows: number;
            /**
             * Completed Workflows
             * @default 0
             */
            completed_workflows: number;
            /**
             * Failed Workflows
             * @default 0
             */
            failed_workflows: number;
            /**
             * Total Sessions
             * @default 0
             */
            total_sessions: number;
            /** Total Input Tokens */
            total_input_tokens: number;
            /** Total Output Tokens */
            total_output_tokens: number;
            /** Total Cache Creation Tokens */
            total_cache_creation_tokens: number;
            /** Total Cache Read Tokens */
            total_cache_read_tokens: number;
            /** Total Tokens */
            total_tokens: number;
            /**
             * Total Cost Usd
             * @default 0
             */
            total_cost_usd: string;
            /**
             * Total Artifacts
             * @default 0
             */
            total_artifacts: number;
            /**
             * Total Artifact Bytes
             * @default 0
             */
            total_artifact_bytes: number;
            /** Phases */
            phases?: components["schemas"]["PhaseMetrics"][];
        };
        /**
         * OperationInfo
         * @description Information about a session operation.
         */
        OperationInfo: {
            /** Operation Id */
            operation_id: string;
            /** Operation Type */
            operation_type: string;
            /** Timestamp */
            timestamp?: string | null;
            /** Duration Seconds */
            duration_seconds?: number | null;
            /**
             * Success
             * @default true
             */
            success: boolean;
            /** Input Tokens */
            input_tokens?: number | null;
            /** Output Tokens */
            output_tokens?: number | null;
            /** Total Tokens */
            total_tokens?: number | null;
            /** Tool Name */
            tool_name?: string | null;
            /** Tool Use Id */
            tool_use_id?: string | null;
            /** Tool Input */
            tool_input?: {
                [key: string]: unknown;
            } | null;
            /** Tool Output */
            tool_output?: string | null;
            /** Message Role */
            message_role?: string | null;
            /** Message Content */
            message_content?: string | null;
            /** Thinking Content */
            thinking_content?: string | null;
            git?: components["schemas"]["GitEventData"] | null;
            /** Git Sha */
            git_sha?: string | null;
            /** Git Message */
            git_message?: string | null;
            /** Git Branch */
            git_branch?: string | null;
            /** Git Repo */
            git_repo?: string | null;
        };
        /**
         * OrganizationActionResponse
         * @description Response for organization create/update/delete actions.
         */
        OrganizationActionResponse: {
            /** Organization Id */
            organization_id: string;
            /** Name */
            name?: string | null;
            /** Slug */
            slug?: string | null;
            /** Status */
            status: string;
        };
        /**
         * OrganizationListResponse
         * @description Paginated list of organizations.
         */
        OrganizationListResponse: {
            /** Total */
            total: number;
            /** Organizations */
            organizations?: components["schemas"]["OrganizationSummaryResponse"][];
        };
        /**
         * OrganizationSummaryResponse
         * @description Summary of an organization for list views.
         */
        OrganizationSummaryResponse: {
            /** Organization Id */
            organization_id: string;
            /** Name */
            name: string;
            /** Slug */
            slug: string;
            /**
             * Created By
             * @default
             */
            created_by: string;
            /** Created At */
            created_at?: string | null;
            /**
             * System Count
             * @default 0
             */
            system_count: number;
            /**
             * Repo Count
             * @default 0
             */
            repo_count: number;
        };
        /**
         * PauseRequest
         * @description Request to pause an execution.
         */
        PauseRequest: {
            /** Reason */
            reason?: string | null;
        };
        /** PhaseDefinition */
        PhaseDefinition: {
            /** Phase Id */
            phase_id: string;
            /** Name */
            name: string;
            /**
             * Order
             * @default 0
             */
            order: number;
            /** Description */
            description?: string | null;
            /**
             * Agent Type
             * @default
             */
            agent_type: string;
            /** Prompt Template */
            prompt_template?: string | null;
            /**
             * Timeout Seconds
             * @default 300
             */
            timeout_seconds: number;
            /** Allowed Tools */
            allowed_tools?: string[];
            /** Argument Hint */
            argument_hint?: string | null;
            /** Model */
            model?: string | null;
        };
        /** PhaseExecutionInfo */
        PhaseExecutionInfo: {
            /** Phase Id */
            phase_id: string;
            /** Name */
            name: string;
            /** Status */
            status: string;
            /** Session Id */
            session_id?: string | null;
            /** Artifact Id */
            artifact_id?: string | null;
            /** Input Tokens */
            input_tokens: number;
            /** Output Tokens */
            output_tokens: number;
            /** Cache Creation Tokens */
            cache_creation_tokens: number;
            /** Cache Read Tokens */
            cache_read_tokens: number;
            /** Total Tokens */
            total_tokens: number;
            /**
             * Duration Seconds
             * @default 0
             */
            duration_seconds: number;
            /**
             * Cost Usd
             * @default 0
             */
            cost_usd: string;
            /** Started At */
            started_at?: string | null;
            /** Completed At */
            completed_at?: string | null;
            /** Error Message */
            error_message?: string | null;
            /** Model */
            model?: string | null;
            /** Cost By Model */
            cost_by_model?: {
                [key: string]: string;
            };
            /** Operations */
            operations?: components["schemas"]["PhaseOperationInfo"][];
        };
        /**
         * PhaseMetrics
         * @description Metrics for a single phase.
         */
        PhaseMetrics: {
            /** Phase Id */
            phase_id: string;
            /** Phase Name */
            phase_name: string;
            /** Status */
            status: string;
            /**
             * Input Tokens
             * @default 0
             */
            input_tokens: number;
            /**
             * Output Tokens
             * @default 0
             */
            output_tokens: number;
            /**
             * Total Tokens
             * @default 0
             */
            total_tokens: number;
            /**
             * Cost Usd
             * @default 0
             */
            cost_usd: string;
            /**
             * Duration Seconds
             * @default 0
             */
            duration_seconds: number;
            /**
             * Artifact Count
             * @default 0
             */
            artifact_count: number;
        };
        /** PhaseOperationInfo */
        PhaseOperationInfo: {
            /** Operation Id */
            operation_id: string;
            /** Operation Type */
            operation_type: string;
            /** Timestamp */
            timestamp?: string | null;
            /** Tool Name */
            tool_name?: string | null;
            /** Tool Use Id */
            tool_use_id?: string | null;
            /**
             * Success
             * @default true
             */
            success: boolean;
        };
        /**
         * RegisterRepoRequest
         * @description Request body for registering a new repo.
         */
        RegisterRepoRequest: {
            /**
             * Organization Id
             * @default _unaffiliated
             */
            organization_id: string;
            /** Full Name */
            full_name: string;
            /**
             * Provider
             * @default github
             */
            provider: string;
            /**
             * Owner
             * @default
             */
            owner: string;
            /**
             * Default Branch
             * @default main
             */
            default_branch: string;
            /**
             * Provider Repo Id
             * @default
             */
            provider_repo_id: string;
            /**
             * Installation Id
             * @default
             */
            installation_id: string;
            /**
             * Is Private
             * @default false
             */
            is_private: boolean;
            /**
             * Created By
             * @default api
             */
            created_by: string;
        };
        /**
         * RegisterTriggerRequest
         * @description Request body for registering a new trigger rule.
         */
        RegisterTriggerRequest: {
            /** Name */
            name: string;
            /** Event */
            event: string;
            /** Repository */
            repository: string;
            /** Workflow Id */
            workflow_id: string;
            /** Conditions */
            conditions?: components["schemas"]["ConditionRequest"][] | null;
            /**
             * Installation Id
             * @default
             */
            installation_id: string;
            /** Input Mapping */
            input_mapping?: {
                [key: string]: string;
            } | null;
            config?: components["schemas"]["TriggerConfigRequest"] | null;
            /**
             * Created By
             * @default api
             */
            created_by: string;
        };
        /**
         * RepoActionResponse
         * @description Response for repo mutation actions (update, deregister, assign, unassign).
         */
        RepoActionResponse: {
            /** Repo Id */
            repo_id: string;
            /** Status */
            status: string;
            /** System Id */
            system_id?: string | null;
        };
        /**
         * RepoActivityEntryResponse
         * @description Single entry in a repo's execution timeline.
         */
        RepoActivityEntryResponse: {
            /** Execution Id */
            execution_id: string;
            /**
             * Workflow Id
             * @default
             */
            workflow_id: string;
            /**
             * Workflow Name
             * @default
             */
            workflow_name: string;
            /**
             * Status
             * @default
             */
            status: string;
            /** Started At */
            started_at?: string | null;
            /** Completed At */
            completed_at?: string | null;
            /**
             * Duration Seconds
             * @default 0
             */
            duration_seconds: number;
            /**
             * Trigger Source
             * @default
             */
            trigger_source: string;
        };
        /**
         * RepoActivityResponse
         * @description Paginated list of repo activity entries.
         */
        RepoActivityResponse: {
            /** Entries */
            entries?: components["schemas"]["RepoActivityEntryResponse"][];
            /**
             * Total
             * @default 0
             */
            total: number;
        };
        /**
         * RepoCostResponse
         * @description Per-repo cost breakdown by workflow and model.
         */
        RepoCostResponse: {
            /**
             * Repo Id
             * @default
             */
            repo_id: string;
            /**
             * Repo Full Name
             * @default
             */
            repo_full_name: string;
            /**
             * Total Cost Usd
             * @default 0
             */
            total_cost_usd: string;
            /**
             * Total Tokens
             * @default 0
             */
            total_tokens: number;
            /**
             * Total Input Tokens
             * @default 0
             */
            total_input_tokens: number;
            /**
             * Total Output Tokens
             * @default 0
             */
            total_output_tokens: number;
            /** Cost By Workflow */
            cost_by_workflow?: {
                [key: string]: string;
            };
            /** Cost By Model */
            cost_by_model?: {
                [key: string]: string;
            };
            /**
             * Execution Count
             * @default 0
             */
            execution_count: number;
        };
        /**
         * RepoCreatedResponse
         * @description Response after registering a new repo.
         */
        RepoCreatedResponse: {
            /** Repo Id */
            repo_id: string;
            /** Full Name */
            full_name: string;
        };
        /**
         * RepoFailureEntryResponse
         * @description A failed execution record for a repository.
         */
        RepoFailureEntryResponse: {
            /** Execution Id */
            execution_id: string;
            /**
             * Workflow Id
             * @default
             */
            workflow_id: string;
            /**
             * Workflow Name
             * @default
             */
            workflow_name: string;
            /** Failed At */
            failed_at?: string | null;
            /**
             * Error Message
             * @default
             */
            error_message: string;
            /**
             * Error Type
             * @default
             */
            error_type: string;
            /**
             * Phase Name
             * @default
             */
            phase_name: string;
            /** Conversation Tail */
            conversation_tail?: string[];
        };
        /**
         * RepoFailuresResponse
         * @description Paginated list of repo failure entries.
         */
        RepoFailuresResponse: {
            /** Failures */
            failures?: components["schemas"]["RepoFailureEntryResponse"][];
            /**
             * Total
             * @default 0
             */
            total: number;
        };
        /**
         * RepoHealthResponse
         * @description Per-repo health snapshot with success rate, trend, and accumulated costs.
         *
         *     Note: ``recent_cost_usd`` is accumulated from WorkflowCompleted/Failed events
         *     since the projection was last reset — it is not a fixed time window and may
         *     differ from ``RepoCostResponse.total_cost_usd`` which is a TimescaleDB total.
         */
        RepoHealthResponse: {
            /**
             * Repo Id
             * @default
             */
            repo_id: string;
            /**
             * Repo Full Name
             * @default
             */
            repo_full_name: string;
            /**
             * Total Executions
             * @default 0
             */
            total_executions: number;
            /**
             * Successful Executions
             * @default 0
             */
            successful_executions: number;
            /**
             * Failed Executions
             * @default 0
             */
            failed_executions: number;
            /**
             * Success Rate
             * @default 0
             */
            success_rate: number;
            /**
             * Trend
             * @default stable
             */
            trend: string;
            /**
             * Recent Cost Usd
             * @default 0
             */
            recent_cost_usd: string;
            /**
             * Window Tokens
             * @default 0
             */
            window_tokens: number;
            /**
             * Last Execution At
             * @default
             */
            last_execution_at: string;
        };
        /**
         * RepoListResponse
         * @description Paginated list of repos.
         */
        RepoListResponse: {
            /** Repos */
            repos?: components["schemas"]["RepoSummaryResponse"][];
            /**
             * Total
             * @default 0
             */
            total: number;
        };
        /**
         * RepoSessionEntryResponse
         * @description Lightweight session record for repo insight views.
         */
        RepoSessionEntryResponse: {
            /** Id */
            id: string;
            /** Execution Id */
            execution_id: string;
            /** Status */
            status: string;
            /** Started At */
            started_at?: string | null;
            /** Completed At */
            completed_at?: string | null;
            /**
             * Agent Type
             * @default
             */
            agent_type: string;
            /**
             * Total Tokens
             * @default 0
             */
            total_tokens: number;
            /**
             * Total Cost Usd
             * @default 0
             */
            total_cost_usd: string;
        };
        /**
         * RepoSessionsResponse
         * @description Paginated list of repo session entries.
         */
        RepoSessionsResponse: {
            /** Sessions */
            sessions?: components["schemas"]["RepoSessionEntryResponse"][];
            /**
             * Total
             * @default 0
             */
            total: number;
        };
        /**
         * RepoStatusEntryResponse
         * @description Health status for a single repo within a system.
         */
        RepoStatusEntryResponse: {
            /**
             * Repo Id
             * @default
             */
            repo_id: string;
            /**
             * Repo Full Name
             * @default
             */
            repo_full_name: string;
            /**
             * Status
             * @default inactive
             */
            status: string;
            /**
             * Success Rate
             * @default 0
             */
            success_rate: number;
            /**
             * Active Executions
             * @default 0
             */
            active_executions: number;
            /**
             * Last Execution At
             * @default
             */
            last_execution_at: string;
        };
        /**
         * RepoSummaryResponse
         * @description Summary of a repo for list views.
         */
        RepoSummaryResponse: {
            /** Repo Id */
            repo_id: string;
            /** Organization Id */
            organization_id: string;
            /**
             * System Id
             * @default
             */
            system_id: string;
            /**
             * Provider
             * @default github
             */
            provider: string;
            /**
             * Full Name
             * @default
             */
            full_name: string;
            /**
             * Owner
             * @default
             */
            owner: string;
            /**
             * Default Branch
             * @default main
             */
            default_branch: string;
            /**
             * Installation Id
             * @default
             */
            installation_id: string;
            /**
             * Is Private
             * @default false
             */
            is_private: boolean;
            /**
             * Created By
             * @default
             */
            created_by: string;
            /** Created At */
            created_at?: string | null;
        };
        /**
         * SSEHealthResponse
         * @description Health status of the SSE subsystem.
         */
        SSEHealthResponse: {
            /** Status */
            status: string;
            /** Active Executions */
            active_executions?: number | null;
            /** Active Connections */
            active_connections?: number | null;
        };
        /**
         * SessionCostResponse
         * @description Cost for a single session.
         */
        SessionCostResponse: {
            /** Session Id */
            session_id: string;
            /** Execution Id */
            execution_id?: string | null;
            /** Workflow Id */
            workflow_id?: string | null;
            /** Phase Id */
            phase_id?: string | null;
            /** Workspace Id */
            workspace_id?: string | null;
            /**
             * Total Cost Usd
             * @default 0
             */
            total_cost_usd: string;
            /**
             * Token Cost Usd
             * @default 0
             */
            token_cost_usd: string;
            /**
             * Compute Cost Usd
             * @default 0
             */
            compute_cost_usd: string;
            /**
             * Input Tokens
             * @default 0
             */
            input_tokens: number;
            /**
             * Output Tokens
             * @default 0
             */
            output_tokens: number;
            /**
             * Total Tokens
             * @default 0
             */
            total_tokens: number;
            /**
             * Cache Creation Tokens
             * @default 0
             */
            cache_creation_tokens: number;
            /**
             * Cache Read Tokens
             * @default 0
             */
            cache_read_tokens: number;
            /**
             * Tool Calls
             * @default 0
             */
            tool_calls: number;
            /**
             * Turns
             * @default 0
             */
            turns: number;
            /**
             * Duration Ms
             * @default 0
             */
            duration_ms: number;
            /** Cost By Model */
            cost_by_model?: {
                [key: string]: string;
            };
            /** Cost By Tool */
            cost_by_tool?: {
                [key: string]: string;
            };
            /** Tokens By Tool */
            tokens_by_tool?: {
                [key: string]: number;
            };
            /** Cost By Tool Tokens */
            cost_by_tool_tokens?: {
                [key: string]: string;
            };
            /**
             * Is Finalized
             * @default false
             */
            is_finalized: boolean;
            /** Started At */
            started_at?: string | null;
            /** Completed At */
            completed_at?: string | null;
        };
        /**
         * SessionListResponse
         * @description Wrapped list of session summaries.
         */
        SessionListResponse: {
            /** Sessions */
            sessions?: components["schemas"]["SessionSummaryResponse"][];
            /**
             * Total
             * @default 0
             */
            total: number;
        };
        /**
         * SessionResponse
         * @description Detailed session response.
         */
        SessionResponse: {
            /** Id */
            id: string;
            /** Workflow Id */
            workflow_id: string | null;
            /** Workflow Name */
            workflow_name?: string | null;
            /** Execution Id */
            execution_id?: string | null;
            /** Phase Id */
            phase_id: string | null;
            /** Milestone Id */
            milestone_id: string | null;
            /** Agent Provider */
            agent_provider: string | null;
            /** Agent Model */
            agent_model: string | null;
            /** Status */
            status: string;
            /** Workspace Path */
            workspace_path?: string | null;
            /**
             * Input Tokens
             * @default 0
             */
            input_tokens: number;
            /**
             * Output Tokens
             * @default 0
             */
            output_tokens: number;
            /**
             * Cache Creation Tokens
             * @default 0
             */
            cache_creation_tokens: number;
            /**
             * Cache Read Tokens
             * @default 0
             */
            cache_read_tokens: number;
            /**
             * Total Tokens
             * @default 0
             */
            total_tokens: number;
            /**
             * Total Cost Usd
             * @default 0
             */
            total_cost_usd: string;
            /** Cost By Model */
            cost_by_model?: {
                [key: string]: string;
            };
            /** Operations */
            operations?: components["schemas"]["OperationInfo"][];
            /** Started At */
            started_at?: string | null;
            /** Completed At */
            completed_at?: string | null;
            /** Duration Seconds */
            duration_seconds?: number | null;
            /** Error Message */
            error_message?: string | null;
            /** Metadata */
            metadata?: {
                [key: string]: unknown;
            };
        };
        /**
         * SessionSummaryResponse
         * @description Summary of an agent session.
         */
        SessionSummaryResponse: {
            /** Id */
            id: string;
            /** Workflow Id */
            workflow_id: string | null;
            /** Workflow Name */
            workflow_name?: string | null;
            /** Execution Id */
            execution_id?: string | null;
            /** Phase Id */
            phase_id: string | null;
            /** Status */
            status: string;
            /** Agent Provider */
            agent_provider: string | null;
            /**
             * Input Tokens
             * @default 0
             */
            input_tokens: number;
            /**
             * Output Tokens
             * @default 0
             */
            output_tokens: number;
            /**
             * Cache Creation Tokens
             * @default 0
             */
            cache_creation_tokens: number;
            /**
             * Cache Read Tokens
             * @default 0
             */
            cache_read_tokens: number;
            /**
             * Total Tokens
             * @default 0
             */
            total_tokens: number;
            /**
             * Total Cost Usd
             * @default 0
             */
            total_cost_usd: string;
            /** Started At */
            started_at?: string | null;
            /** Completed At */
            completed_at?: string | null;
        };
        /**
         * SessionTokenMetrics
         * @description Token usage metrics for a session.
         */
        SessionTokenMetrics: {
            /** Session Id */
            session_id: string;
            /**
             * Input Tokens
             * @default 0
             */
            input_tokens: number;
            /**
             * Output Tokens
             * @default 0
             */
            output_tokens: number;
            /**
             * Total Tokens
             * @default 0
             */
            total_tokens: number;
            /**
             * Total Cost Usd
             * @default 0
             */
            total_cost_usd: string;
            /**
             * Cache Creation Tokens
             * @default 0
             */
            cache_creation_tokens: number;
            /**
             * Cache Read Tokens
             * @default 0
             */
            cache_read_tokens: number;
        };
        /**
         * StateResponse
         * @description Response with execution state.
         */
        StateResponse: {
            /** Execution Id */
            execution_id: string;
            /** State */
            state: string;
        };
        /**
         * SystemActionResponse
         * @description Response for system mutation actions (update, delete).
         */
        SystemActionResponse: {
            /** System Id */
            system_id: string;
            /** Status */
            status: string;
        };
        /**
         * SystemActivityResponse
         * @description Paginated list of system activity entries.
         */
        SystemActivityResponse: {
            /** Entries */
            entries?: components["schemas"]["RepoActivityEntryResponse"][];
            /**
             * Total
             * @default 0
             */
            total: number;
        };
        /**
         * SystemCostResponse
         * @description System-wide cost breakdown by repo, workflow, and model.
         */
        SystemCostResponse: {
            /**
             * System Id
             * @default
             */
            system_id: string;
            /**
             * System Name
             * @default
             */
            system_name: string;
            /**
             * Organization Id
             * @default
             */
            organization_id: string;
            /**
             * Total Cost Usd
             * @default 0
             */
            total_cost_usd: string;
            /**
             * Total Tokens
             * @default 0
             */
            total_tokens: number;
            /**
             * Total Input Tokens
             * @default 0
             */
            total_input_tokens: number;
            /**
             * Total Output Tokens
             * @default 0
             */
            total_output_tokens: number;
            /** Cost By Repo */
            cost_by_repo?: {
                [key: string]: string;
            };
            /** Cost By Workflow */
            cost_by_workflow?: {
                [key: string]: string;
            };
            /** Cost By Model */
            cost_by_model?: {
                [key: string]: string;
            };
            /**
             * Execution Count
             * @default 0
             */
            execution_count: number;
        };
        /**
         * SystemCreatedResponse
         * @description Response after creating a new system.
         */
        SystemCreatedResponse: {
            /** System Id */
            system_id: string;
            /** Name */
            name: string;
        };
        /**
         * SystemHistoryResponse
         * @description Paginated list of system history entries.
         */
        SystemHistoryResponse: {
            /** Entries */
            entries?: components["schemas"]["RepoActivityEntryResponse"][];
            /**
             * Total
             * @default 0
             */
            total: number;
        };
        /**
         * SystemListResponse
         * @description Paginated list of systems.
         */
        SystemListResponse: {
            /** Systems */
            systems?: components["schemas"]["SystemSummaryResponse"][];
            /**
             * Total
             * @default 0
             */
            total: number;
        };
        /**
         * SystemOverviewEntryResponse
         * @description Summary of a single system for global overview.
         */
        SystemOverviewEntryResponse: {
            /**
             * System Id
             * @default
             */
            system_id: string;
            /**
             * System Name
             * @default
             */
            system_name: string;
            /**
             * Organization Id
             * @default
             */
            organization_id: string;
            /**
             * Organization Name
             * @default
             */
            organization_name: string;
            /**
             * Repo Count
             * @default 0
             */
            repo_count: number;
            /**
             * Overall Status
             * @default healthy
             */
            overall_status: string;
            /**
             * Active Executions
             * @default 0
             */
            active_executions: number;
            /**
             * Total Cost Usd
             * @default 0
             */
            total_cost_usd: string;
        };
        /**
         * SystemPatternsResponse
         * @description Recurring failure and cost patterns within a system.
         */
        SystemPatternsResponse: {
            /**
             * System Id
             * @default
             */
            system_id: string;
            /**
             * System Name
             * @default
             */
            system_name: string;
            /** Failure Patterns */
            failure_patterns?: components["schemas"]["FailurePatternResponse"][];
            /** Cost Outliers */
            cost_outliers?: components["schemas"]["CostOutlierResponse"][];
            /**
             * Analysis Window Hours
             * @default 168
             */
            analysis_window_hours: number;
        };
        /**
         * SystemStatusResponse
         * @description Cross-repo health overview within a system.
         */
        SystemStatusResponse: {
            /**
             * System Id
             * @default
             */
            system_id: string;
            /**
             * System Name
             * @default
             */
            system_name: string;
            /**
             * Organization Id
             * @default
             */
            organization_id: string;
            /**
             * Overall Status
             * @default healthy
             */
            overall_status: string;
            /**
             * Total Repos
             * @default 0
             */
            total_repos: number;
            /**
             * Healthy Repos
             * @default 0
             */
            healthy_repos: number;
            /**
             * Degraded Repos
             * @default 0
             */
            degraded_repos: number;
            /**
             * Failing Repos
             * @default 0
             */
            failing_repos: number;
            /** Repos */
            repos?: components["schemas"]["RepoStatusEntryResponse"][];
        };
        /**
         * SystemSummaryResponse
         * @description Summary of a system for list views.
         */
        SystemSummaryResponse: {
            /** System Id */
            system_id: string;
            /** Organization Id */
            organization_id: string;
            /** Name */
            name: string;
            /**
             * Description
             * @default
             */
            description: string;
            /**
             * Created By
             * @default
             */
            created_by: string;
            /** Created At */
            created_at?: string | null;
            /**
             * Repo Count
             * @default 0
             */
            repo_count: number;
        };
        /**
         * TimelineEntryResponse
         * @description Timeline entry for visualization.
         */
        TimelineEntryResponse: {
            /** Time */
            time?: string | null;
            /** Event Type */
            event_type: string;
            /** Tool Name */
            tool_name?: string | null;
            /** Duration Ms */
            duration_ms?: number | null;
            /** Success */
            success?: boolean | null;
        };
        /**
         * ToolSummary
         * @description Tool usage summary.
         */
        ToolSummary: {
            /** Tool Name */
            tool_name: string;
            /** Call Count */
            call_count: number;
            /** Success Count */
            success_count: number;
            /** Error Count */
            error_count: number;
            /** Total Duration Ms */
            total_duration_ms: number;
            /** Avg Duration Ms */
            avg_duration_ms: number;
        };
        /**
         * ToolTimelineEntry
         * @description Single entry in a tool execution timeline.
         */
        ToolTimelineEntry: {
            /**
             * Observation Id
             * @default
             */
            observation_id: string;
            /**
             * Operation Type
             * @default
             */
            operation_type: string;
            /** Tool Name */
            tool_name?: string | null;
            /** Timestamp */
            timestamp?: string | null;
            /** Duration Ms */
            duration_ms?: number | null;
            /** Success */
            success?: boolean | null;
        };
        /**
         * ToolTimelineResponse
         * @description Tool execution timeline for a session.
         */
        ToolTimelineResponse: {
            /** Session Id */
            session_id: string;
            /**
             * Total Executions
             * @default 0
             */
            total_executions: number;
            /** Executions */
            executions?: components["schemas"]["ToolTimelineEntry"][];
        };
        /**
         * TriggerActionResponse
         * @description Response for trigger create/update/delete actions.
         */
        TriggerActionResponse: {
            /** Trigger Id */
            trigger_id: string;
            /** Name */
            name?: string | null;
            /** Status */
            status: string;
            /** Preset */
            preset?: string | null;
            /** Action */
            action?: string | null;
        };
        /**
         * TriggerConfigRequest
         * @description Safety configuration for a trigger rule.
         */
        TriggerConfigRequest: {
            /**
             * Max Attempts
             * @default 3
             */
            max_attempts: number;
            /**
             * Daily Limit
             * @default 20
             */
            daily_limit: number;
            /**
             * Debounce Seconds
             * @default 0
             */
            debounce_seconds: number;
            /**
             * Cooldown Seconds
             * @default 300
             */
            cooldown_seconds: number;
        };
        /**
         * TriggerDetail
         * @description Detailed trigger rule response.
         */
        TriggerDetail: {
            /** Trigger Id */
            trigger_id: string;
            /** Name */
            name: string;
            /** Event */
            event: string;
            /** Repository */
            repository: string;
            /** Workflow Id */
            workflow_id: string;
            /**
             * Workflow Name
             * @default
             */
            workflow_name: string;
            /** Status */
            status: string;
            /**
             * Fire Count
             * @default 0
             */
            fire_count: number;
            /** Created At */
            created_at?: string | null;
            /** Conditions */
            conditions?: {
                [key: string]: unknown;
            }[];
            /** Input Mapping */
            input_mapping?: {
                [key: string]: string;
            };
            /** Config */
            config?: {
                [key: string]: unknown;
            };
            /**
             * Installation Id
             * @default
             */
            installation_id: string;
            /**
             * Created By
             * @default
             */
            created_by: string;
            /** Last Fired At */
            last_fired_at?: string | null;
        };
        /**
         * TriggerHistoryEntryResponse
         * @description Single entry in a trigger-specific history response.
         */
        TriggerHistoryEntryResponse: {
            /** Fired At */
            fired_at?: string | null;
            /**
             * Execution Id
             * @default
             */
            execution_id: string;
            /**
             * Webhook Delivery Id
             * @default
             */
            webhook_delivery_id: string;
            /**
             * Event Type
             * @default
             */
            event_type: string;
            /** Pr Number */
            pr_number?: number | null;
            /**
             * Status
             * @default dispatched
             */
            status: string;
            /** Cost Usd */
            cost_usd?: number | null;
            /**
             * Guard Name
             * @default
             */
            guard_name: string;
            /**
             * Block Reason
             * @default
             */
            block_reason: string;
        };
        /**
         * TriggerHistoryListEntry
         * @description Entry in a cross-trigger history listing.
         */
        TriggerHistoryListEntry: {
            /** Trigger Id */
            trigger_id: string;
            /** Fired At */
            fired_at?: string | null;
            /**
             * Execution Id
             * @default
             */
            execution_id: string;
            /**
             * Event Type
             * @default
             */
            event_type: string;
            /** Pr Number */
            pr_number?: number | null;
            /**
             * Status
             * @default dispatched
             */
            status: string;
            /**
             * Guard Name
             * @default
             */
            guard_name: string;
            /**
             * Block Reason
             * @default
             */
            block_reason: string;
        };
        /**
         * TriggerHistoryListResponse
         * @description Paginated list of trigger history entries (global).
         */
        TriggerHistoryListResponse: {
            /** Total */
            total: number;
            /** Entries */
            entries?: components["schemas"]["TriggerHistoryListEntry"][];
        };
        /**
         * TriggerHistoryResponse
         * @description History entries for a specific trigger.
         */
        TriggerHistoryResponse: {
            /** Trigger Id */
            trigger_id: string;
            /** Entries */
            entries?: components["schemas"]["TriggerHistoryEntryResponse"][];
        };
        /**
         * TriggerListResponse
         * @description Paginated list of trigger summaries.
         */
        TriggerListResponse: {
            /** Total */
            total: number;
            /** Triggers */
            triggers?: components["schemas"]["TriggerSummary"][];
        };
        /**
         * TriggerSummary
         * @description Summary of a trigger rule for list views.
         */
        TriggerSummary: {
            /** Trigger Id */
            trigger_id: string;
            /** Name */
            name: string;
            /** Event */
            event: string;
            /** Repository */
            repository: string;
            /** Workflow Id */
            workflow_id: string;
            /**
             * Workflow Name
             * @default
             */
            workflow_name: string;
            /** Status */
            status: string;
            /**
             * Fire Count
             * @default 0
             */
            fire_count: number;
            /** Created At */
            created_at?: string | null;
        };
        /** UpdateArtifactRequest */
        UpdateArtifactRequest: {
            /** Title */
            title?: string | null;
            /** Metadata */
            metadata?: {
                [key: string]: unknown;
            } | null;
            /** Is Primary Deliverable */
            is_primary_deliverable?: boolean | null;
        };
        /**
         * UpdateOrganizationRequest
         * @description Request body for updating an organization.
         */
        UpdateOrganizationRequest: {
            /** Name */
            name?: string | null;
            /** Slug */
            slug?: string | null;
        };
        /** UpdatePhasePromptRequest */
        UpdatePhasePromptRequest: {
            /** Prompt Template */
            prompt_template: string;
            /** Model */
            model?: string | null;
            /** Timeout Seconds */
            timeout_seconds?: number | null;
            /** Allowed Tools */
            allowed_tools?: string[] | null;
        };
        /** UpdatePhaseResponse */
        UpdatePhaseResponse: {
            /** Workflow Id */
            workflow_id: string;
            /** Phase Id */
            phase_id: string;
            /** Status */
            status: string;
        };
        /**
         * UpdateRepoRequest
         * @description Request body for updating a repo.
         */
        UpdateRepoRequest: {
            /** Default Branch */
            default_branch?: string | null;
            /** Is Private */
            is_private?: boolean | null;
            /** Installation Id */
            installation_id?: string | null;
            /**
             * Updated By
             * @default api
             */
            updated_by: string;
        };
        /**
         * UpdateSystemRequest
         * @description Request body for updating a system.
         */
        UpdateSystemRequest: {
            /** Name */
            name?: string | null;
            /** Description */
            description?: string | null;
        };
        /** UploadArtifactResponse */
        UploadArtifactResponse: {
            /** Artifact Id */
            artifact_id: string;
            /** Storage Url */
            storage_url: string;
            /** Status */
            status: string;
        };
        /** ValidateYamlRequest */
        ValidateYamlRequest: {
            /**
             * Content
             * @description Raw YAML content to validate
             */
            content?: string | null;
            /**
             * Filename
             * @description Original filename (informational)
             * @default workflow.yaml
             */
            filename: string;
            /**
             * File
             * @description Deprecated — file paths are no longer supported. Use 'content' instead.
             */
            file?: string | null;
        };
        /** ValidateYamlResponse */
        ValidateYamlResponse: {
            /** Valid */
            valid: boolean;
            /**
             * Name
             * @default
             */
            name: string;
            /**
             * Workflow Type
             * @default
             */
            workflow_type: string;
            /**
             * Phase Count
             * @default 0
             */
            phase_count: number;
            /** Errors */
            errors?: string[];
        };
        /** ValidationError */
        ValidationError: {
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
            /** Input */
            input?: unknown;
            /** Context */
            ctx?: Record<string, never>;
        };
        /** WorkflowListResponse */
        WorkflowListResponse: {
            /** Workflows */
            workflows: components["schemas"]["WorkflowSummaryResponse"][];
            /** Total */
            total: number;
            /**
             * Page
             * @default 1
             */
            page: number;
            /**
             * Page Size
             * @default 20
             */
            page_size: number;
        };
        /** WorkflowResponse */
        WorkflowResponse: {
            /** Id */
            id: string;
            /** Name */
            name: string;
            /** Description */
            description?: string | null;
            /** Workflow Type */
            workflow_type: string;
            /** Classification */
            classification: string;
            /** Phases */
            phases?: components["schemas"]["PhaseDefinition"][];
            /** Input Declarations */
            input_declarations?: components["schemas"]["InputDeclarationModel"][];
            /** Created At */
            created_at?: string | null;
            /**
             * Runs Count
             * @default 0
             */
            runs_count: number;
            /** Runs Link */
            runs_link?: string | null;
            /** Repository Url */
            repository_url?: string | null;
            /** Repos */
            repos?: string[];
            /**
             * Requires Repos
             * @default true
             */
            requires_repos: boolean;
        };
        /** WorkflowSummaryResponse */
        WorkflowSummaryResponse: {
            /** Id */
            id: string;
            /** Name */
            name: string;
            /** Workflow Type */
            workflow_type: string;
            /** Phase Count */
            phase_count: number;
            /** Created At */
            created_at?: string | null;
            /**
             * Runs Count
             * @default 0
             */
            runs_count: number;
            /**
             * Is Archived
             * @default false
             */
            is_archived: boolean;
            /**
             * Requires Repos
             * @default true
             */
            requires_repos: boolean;
        };
        /**
         * CostSummaryResponse
         * @description Summary of all costs across sessions/executions.
         */
        syn_api__routes__costs__CostSummaryResponse: {
            /**
             * Total Cost Usd
             * @default 0
             */
            total_cost_usd: string;
            /**
             * Total Sessions
             * @default 0
             */
            total_sessions: number;
            /**
             * Total Executions
             * @default 0
             */
            total_executions: number;
            /**
             * Total Tokens
             * @default 0
             */
            total_tokens: number;
            /**
             * Total Tool Calls
             * @default 0
             */
            total_tool_calls: number;
            /** Top Models */
            top_models?: {
                [key: string]: unknown;
            }[];
            /** Top Sessions */
            top_sessions?: {
                [key: string]: unknown;
            }[];
        };
        /**
         * CostSummaryResponse
         * @description Cost summary for a session.
         */
        syn_api__routes__events__CostSummaryResponse: {
            /** Session Id */
            session_id: string;
            /**
             * Input Tokens
             * @default 0
             */
            input_tokens: number;
            /**
             * Output Tokens
             * @default 0
             */
            output_tokens: number;
            /**
             * Total Tokens
             * @default 0
             */
            total_tokens: number;
            /**
             * Cache Creation Tokens
             * @default 0
             */
            cache_creation_tokens: number;
            /**
             * Cache Read Tokens
             * @default 0
             */
            cache_read_tokens: number;
            /** Estimated Cost Usd */
            estimated_cost_usd?: number | null;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    list_workflows_endpoint_workflows_get: {
        parameters: {
            query?: {
                /** @description Filter by workflow type */
                workflow_type?: string | null;
                /** @description Include archived workflows */
                include_archived?: boolean;
                page?: number;
                page_size?: number;
                /** @description Sort field (- prefix = descending) */
                order_by?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkflowListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_workflow_endpoint_workflows_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateWorkflowRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CreateWorkflowResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_workflow_endpoint_workflows__workflow_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workflow_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WorkflowResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_workflow_endpoint_workflows__workflow_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workflow_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DeleteWorkflowResponse"];
                };
            };
            /** @description Workflow template not found */
            404: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Conflict — workflow has active executions or is already archived */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    export_workflow_endpoint_workflows__workflow_id__export_get: {
        parameters: {
            query?: {
                /** @description Export format: 'package' (workflow.yaml + phases) or 'plugin' (full CC plugin) */
                format?: "package" | "plugin";
            };
            header?: never;
            path: {
                workflow_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExportManifestResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_workflow_runs_endpoint_workflows__workflow_id__runs_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workflow_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExecutionRunListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_workflow_history_endpoint_workflows__workflow_id__history_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workflow_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExecutionHistoryResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    validate_yaml_endpoint_workflows_validate_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ValidateYamlRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ValidateYamlResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_phase_prompt_endpoint_workflows__workflow_id__phases__phase_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workflow_id: string;
                phase_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdatePhasePromptRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UpdatePhaseResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_workflow_from_yaml_endpoint_workflows_from_yaml_post: {
        parameters: {
            query?: {
                name?: string | null;
                workflow_id?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CreateWorkflowResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_executions_endpoint_executions_get: {
        parameters: {
            query?: {
                /** @description Filter by status */
                status?: string | null;
                /** @description Page number */
                page?: number;
                /** @description Items per page */
                page_size?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExecutionListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_execution_endpoint_executions__execution_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                execution_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExecutionDetailResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    execute_workflow_endpoint_workflows__workflow_id__execute_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workflow_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ExecuteWorkflowRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExecuteWorkflowResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_execution_status_endpoint_workflows__workflow_id__executions__execution_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                workflow_id: string;
                execution_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExecutionStatusResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_active_executions_endpoint_workflows_executions_active_get: {
        parameters: {
            query?: {
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExecutionStatusResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    pause_execution_endpoint_executions__execution_id__pause_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                execution_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["PauseRequest"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ControlResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    resume_execution_endpoint_executions__execution_id__resume_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                execution_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ControlResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    cancel_execution_endpoint_executions__execution_id__cancel_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                execution_id: string;
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["CancelRequest"] | null;
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ControlResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    inject_context_endpoint_executions__execution_id__inject_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                execution_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["InjectRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ControlResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_execution_state_endpoint_executions__execution_id__state_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                execution_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StateResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_sessions_endpoint_sessions_get: {
        parameters: {
            query?: {
                /** @description Filter by workflow ID */
                workflow_id?: string | null;
                /** @description Filter by status */
                status?: string | null;
                /** @description Max items to return */
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_session_endpoint_sessions__session_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_artifacts_endpoint_artifacts_get: {
        parameters: {
            query?: {
                /** @description Filter by workflow ID */
                workflow_id?: string | null;
                /** @description Filter by phase ID */
                phase_id?: string | null;
                /** @description Filter by artifact type */
                artifact_type?: string | null;
                /** @description Max items to return */
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ArtifactSummaryResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_artifact_endpoint_artifacts_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateArtifactRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CreateArtifactResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_artifact_endpoint_artifacts__artifact_id__get: {
        parameters: {
            query?: {
                /** @description Include artifact content in response */
                include_content?: boolean;
            };
            header?: never;
            path: {
                artifact_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ArtifactResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_artifact_endpoint_artifacts__artifact_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                artifact_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdateArtifactRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ArtifactActionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_artifact_endpoint_artifacts__artifact_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                artifact_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ArtifactActionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_artifact_content_endpoint_artifacts__artifact_id__content_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                artifact_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ArtifactContentResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    upload_artifact_endpoint_artifacts__artifact_id__upload_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                artifact_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "multipart/form-data": components["schemas"]["Body_upload_artifact_endpoint_artifacts__artifact_id__upload_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UploadArtifactResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_metrics_endpoint_metrics_get: {
        parameters: {
            query?: {
                /** @description Filter by workflow ID */
                workflow_id?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MetricsResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_tool_timeline_endpoint_observability_sessions__session_id__tools_get: {
        parameters: {
            query?: {
                limit?: number;
                include_blocked?: boolean;
            };
            header?: never;
            path: {
                session_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ToolTimelineResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_token_metrics_endpoint_observability_sessions__session_id__tokens_get: {
        parameters: {
            query?: {
                include_records?: boolean;
            };
            header?: never;
            path: {
                session_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionTokenMetrics"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_session_costs_endpoint_costs_sessions_get: {
        parameters: {
            query?: {
                /** @description Filter by execution ID */
                execution_id?: string | null;
                /** @description Max items to return */
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionCostResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_session_cost_endpoint_costs_sessions__session_id__get: {
        parameters: {
            query?: {
                /** @description Include model/tool breakdowns */
                include_breakdown?: boolean;
            };
            header?: never;
            path: {
                session_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionCostResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_execution_costs_endpoint_costs_executions_get: {
        parameters: {
            query?: {
                /** @description Max items to return */
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExecutionCostResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_execution_cost_endpoint_costs_executions__execution_id__get: {
        parameters: {
            query?: {
                /** @description Include phase/model/tool breakdowns */
                include_breakdown?: boolean;
                /** @description Include list of session IDs */
                include_session_ids?: boolean;
            };
            header?: never;
            path: {
                execution_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ExecutionCostResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_cost_summary_endpoint_costs_summary_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["syn_api__routes__costs__CostSummaryResponse"];
                };
            };
        };
    };
    get_recent_activity_endpoint_events_recent_get: {
        parameters: {
            query?: {
                /** @description Max events to return */
                limit?: number;
                /** @description Filter by event type */
                event_type?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EventListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_session_events_endpoint_events_sessions__session_id__get: {
        parameters: {
            query?: {
                /** @description Filter by event type */
                event_type?: string | null;
                /** @description Max events to return */
                limit?: number;
                /** @description Offset for pagination */
                offset?: number;
            };
            header?: never;
            path: {
                session_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EventListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_session_timeline_endpoint_events_sessions__session_id__timeline_get: {
        parameters: {
            query?: {
                /** @description Max entries */
                limit?: number;
            };
            header?: never;
            path: {
                session_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TimelineEntryResponse"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_session_costs_endpoint_events_sessions__session_id__costs_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["syn_api__routes__events__CostSummaryResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_session_tools_endpoint_events_sessions__session_id__tools_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ToolSummary"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_accessible_repos_endpoint_github_repos_get: {
        parameters: {
            query?: {
                installation_id?: string | null;
                include_private?: boolean;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GitHubRepoListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_conversation_log_endpoint_conversations__session_id__get: {
        parameters: {
            query?: {
                offset?: number;
                limit?: number;
            };
            header?: never;
            path: {
                session_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConversationLogResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_conversation_metadata_endpoint_conversations__session_id__metadata_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                session_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConversationMetadataResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_triggers_endpoint_triggers_get: {
        parameters: {
            query?: {
                repository?: string | null;
                status?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TriggerListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    register_trigger_endpoint_triggers_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RegisterTriggerRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TriggerActionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_all_history_endpoint_triggers_history_get: {
        parameters: {
            query?: {
                limit?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TriggerHistoryListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_trigger_endpoint_triggers__trigger_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                trigger_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TriggerDetail"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_trigger_endpoint_triggers__trigger_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                trigger_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TriggerActionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_trigger_endpoint_triggers__trigger_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                trigger_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": {
                    [key: string]: unknown;
                };
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TriggerActionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_trigger_history_endpoint_triggers__trigger_id__history_get: {
        parameters: {
            query?: {
                limit?: number;
            };
            header?: never;
            path: {
                trigger_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TriggerHistoryResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    enable_preset_endpoint_triggers_presets__preset_name__post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                preset_name: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": {
                    [key: string]: unknown;
                };
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["TriggerActionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    github_webhook_endpoint_webhooks_github_post: {
        parameters: {
            query?: never;
            header: {
                "X-GitHub-Event": string;
                "X-GitHub-Delivery": string;
                "X-Hub-Signature-256"?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    execution_sse_sse_executions__execution_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                execution_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    activity_sse_sse_activity_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
        };
    };
    sse_health_sse_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SSEHealthResponse"];
                };
            };
        };
    };
    list_organizations_endpoint_organizations_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OrganizationListResponse"];
                };
            };
        };
    };
    create_organization_endpoint_organizations_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateOrganizationRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OrganizationActionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_organization_endpoint_organizations__organization_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                organization_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OrganizationSummaryResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_organization_endpoint_organizations__organization_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                organization_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdateOrganizationRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OrganizationActionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_organization_endpoint_organizations__organization_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                organization_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OrganizationActionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_systems_endpoint_systems_get: {
        parameters: {
            query?: {
                organization_id?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SystemListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    create_system_endpoint_systems_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateSystemRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SystemCreatedResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_system_endpoint_systems__system_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                system_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SystemSummaryResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_system_endpoint_systems__system_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                system_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdateSystemRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SystemActionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    delete_system_endpoint_systems__system_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                system_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SystemActionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_system_status_endpoint_systems__system_id__status_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                system_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SystemStatusResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_system_cost_endpoint_systems__system_id__cost_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                system_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SystemCostResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_system_activity_endpoint_systems__system_id__activity_get: {
        parameters: {
            query?: {
                offset?: number;
                limit?: number;
            };
            header?: never;
            path: {
                system_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SystemActivityResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_system_patterns_endpoint_systems__system_id__patterns_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                system_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SystemPatternsResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_system_history_endpoint_systems__system_id__history_get: {
        parameters: {
            query?: {
                offset?: number;
                limit?: number;
            };
            header?: never;
            path: {
                system_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SystemHistoryResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_repos_endpoint_repos_get: {
        parameters: {
            query?: {
                organization_id?: string | null;
                system_id?: string | null;
                provider?: string | null;
                unassigned?: boolean;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RepoListResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    register_repo_endpoint_repos_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RegisterRepoRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RepoCreatedResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_repo_endpoint_repos__repo_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                repo_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RepoSummaryResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    update_repo_endpoint_repos__repo_id__put: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                repo_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdateRepoRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RepoActionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    deregister_repo_endpoint_repos__repo_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                repo_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RepoActionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    assign_repo_to_system_endpoint_repos__repo_id__assign_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                repo_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AssignRepoToSystemRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RepoActionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    unassign_repo_from_system_endpoint_repos__repo_id__unassign_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                repo_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RepoActionResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_repo_health_endpoint_repos__repo_id__health_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                repo_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RepoHealthResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_repo_cost_endpoint_repos__repo_id__cost_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                repo_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RepoCostResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_repo_activity_endpoint_repos__repo_id__activity_get: {
        parameters: {
            query?: {
                offset?: number;
                limit?: number;
            };
            header?: never;
            path: {
                repo_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RepoActivityResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_repo_failures_endpoint_repos__repo_id__failures_get: {
        parameters: {
            query?: {
                limit?: number;
            };
            header?: never;
            path: {
                repo_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RepoFailuresResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_repo_sessions_endpoint_repos__repo_id__sessions_get: {
        parameters: {
            query?: {
                limit?: number;
            };
            header?: never;
            path: {
                repo_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RepoSessionsResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_global_overview_endpoint_insights_overview_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GlobalOverviewResponse"];
                };
            };
        };
    };
    get_global_cost_endpoint_insights_cost_get: {
        parameters: {
            query?: {
                /** @description Filter costs by system ID */
                system_id?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GlobalCostResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_contribution_heatmap_endpoint_insights_contribution_heatmap_get: {
        parameters: {
            query?: {
                organization_id?: string | null;
                system_id?: string | null;
                repo_id?: string | null;
                start_date?: string | null;
                end_date?: string | null;
                metric?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ContributionHeatmapResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    root__get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: string;
                    };
                };
            };
        };
    };
    health_health_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
}
