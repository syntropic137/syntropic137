// Model vocabulary shared by every run-time surface.
//
// Run-time screens show the EXPLICIT model id that ran (the API's `*_display`
// fields, rendered verbatim). Aliases such as "opus" belong to workflow
// definitions only; they appear at run time solely as "requested: <alias>".

// cost_by_model key for spend that could not be attributed to an observed
// model. Mirrors UNKNOWN_MODEL_KEY in packages/syn-shared/src/syn_shared/observed_model.py.
export const UNATTRIBUTED_MODEL_KEY = 'unattributed-model'

// Human label for UNATTRIBUTED_MODEL_KEY.
export const UNATTRIBUTED_MODEL_LABEL = 'unknown model'

// Prefix for the secondary "what the workflow asked for" line.
export const REQUESTED_MODEL_PREFIX = 'requested: '
