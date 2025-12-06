/**
 * Voice recorder component
 */

import { formatDuration, useVoiceRecorder } from '../hooks/useVoiceRecorder';

export interface VoiceRecorderProps {
  onRecordingComplete: (blob: Blob) => void;
  existingAudioUrl?: string | null;
  onDelete?: () => void;
  compact?: boolean;
}

export function VoiceRecorder({
  onRecordingComplete,
  existingAudioUrl,
  onDelete,
  compact = false,
}: VoiceRecorderProps) {
  const {
    isRecording,
    duration,
    audioUrl,
    startRecording,
    stopRecording,
    clearRecording,
    audioBlob,
    isSupported,
    error,
  } = useVoiceRecorder();

  const displayUrl = existingAudioUrl || audioUrl;

  const handleStopAndSave = () => {
    stopRecording();
    // Wait for blob to be available
    setTimeout(() => {
      if (audioBlob) {
        onRecordingComplete(audioBlob);
      }
    }, 100);
  };

  const handleDelete = () => {
    clearRecording();
    onDelete?.();
  };

  if (!isSupported) {
    if (compact) return null;
    return (
      <div className="ui-feedback-voice-recorder">
        <span className="ui-feedback-error">Voice recording not supported in this browser</span>
      </div>
    );
  }

  // Compact mode - just icon button
  if (compact) {
    return (
      <div className="ui-feedback-voice-recorder ui-feedback-voice-recorder--compact">
        {!displayUrl ? (
          <button
            type="button"
            className={`ui-feedback-voice-button ui-feedback-voice-button--compact ${isRecording ? 'ui-feedback-voice-button--recording' : ''}`}
            onClick={isRecording ? handleStopAndSave : startRecording}
            title={isRecording ? `Stop recording (${formatDuration(duration)})` : 'Record voice note'}
          >
            {isRecording ? <StopIcon /> : <MicIcon />}
            {isRecording && <span className="ui-feedback-voice-timer--compact">{formatDuration(duration)}</span>}
          </button>
        ) : (
          <div className="ui-feedback-voice-playback ui-feedback-voice-playback--compact">
            <audio src={displayUrl} controls />
            <button
              type="button"
              className="ui-feedback-voice-delete"
              onClick={handleDelete}
              title="Delete recording"
            >
              <TrashIcon />
            </button>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="ui-feedback-voice-recorder">
      {!displayUrl ? (
        <>
          <button
            type="button"
            className={`ui-feedback-voice-button ${isRecording ? 'ui-feedback-voice-button--recording' : ''}`}
            onClick={isRecording ? handleStopAndSave : startRecording}
            title={isRecording ? 'Stop recording' : 'Start recording'}
          >
            {isRecording ? (
              <StopIcon />
            ) : (
              <MicIcon />
            )}
          </button>
          {isRecording && (
            <span className="ui-feedback-voice-timer">{formatDuration(duration)}</span>
          )}
          {!isRecording && (
            <span style={{ color: 'var(--feedback-text-secondary)', fontSize: '13px' }}>
              Click to record a voice note
            </span>
          )}
        </>
      ) : (
        <div className="ui-feedback-voice-playback">
          <audio src={displayUrl} controls />
          <button
            type="button"
            className="ui-feedback-voice-delete"
            onClick={handleDelete}
            title="Delete recording"
          >
            <TrashIcon />
          </button>
        </div>
      )}
      {error && <span className="ui-feedback-error">{error}</span>}
    </div>
  );
}

// Simple icons
function MicIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <line x1="12" y1="19" x2="12" y2="22" />
    </svg>
  );
}

function StopIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
      <rect x="6" y="6" width="12" height="12" rx="2" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M3 6h18" />
      <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" />
      <path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" />
    </svg>
  );
}
