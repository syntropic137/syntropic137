/**
 * Voice recorder component
 */

import { useEffect, useRef } from 'react';
import { formatDuration, useVoiceRecorder } from '../hooks/useVoiceRecorder';
import { MicIcon, StopIcon, TrashIcon } from './icons';

export interface VoiceRecorderProps {
  onRecordingComplete: (blob: Blob) => void;
  existingAudioUrl?: string | null;
  onDelete?: () => void;
  compact?: boolean;
}

export function VoiceRecorder({ onRecordingComplete, existingAudioUrl, onDelete, compact = false }: VoiceRecorderProps) {
  const { isRecording, duration, audioUrl, startRecording, stopRecording, clearRecording, audioBlob, isSupported, error } = useVoiceRecorder();

  const displayUrl = existingAudioUrl || audioUrl;
  const pendingStopRef = useRef(false);

  // Deliver blob via effect so we always see the updated audioBlob after onstop fires
  useEffect(() => {
    if (pendingStopRef.current && audioBlob) {
      pendingStopRef.current = false;
      onRecordingComplete(audioBlob);
    }
  }, [audioBlob, onRecordingComplete]);

  const handleStopAndSave = () => {
    pendingStopRef.current = true;
    stopRecording();
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

  if (compact) {
    return (
      <CompactVoiceRecorder
        displayUrl={displayUrl} isRecording={isRecording} duration={duration}
        onToggleRecord={isRecording ? handleStopAndSave : startRecording}
        onDelete={handleDelete}
      />
    );
  }

  return (
    <FullVoiceRecorder
      displayUrl={displayUrl} isRecording={isRecording} duration={duration}
      onToggleRecord={isRecording ? handleStopAndSave : startRecording}
      onDelete={handleDelete} error={error}
    />
  );
}

// --- Sub-components for each rendering mode ---

function CompactVoiceRecorder({ displayUrl, isRecording, duration, onToggleRecord, onDelete }: {
  displayUrl: string | null; isRecording: boolean; duration: number;
  onToggleRecord: () => void; onDelete: () => void;
}) {
  return (
    <div className="ui-feedback-voice-recorder ui-feedback-voice-recorder--compact">
      {!displayUrl ? (
        <button
          type="button"
          className={`ui-feedback-voice-button ui-feedback-voice-button--compact ${isRecording ? 'ui-feedback-voice-button--recording' : ''}`}
          onClick={onToggleRecord}
          title={isRecording ? `Stop recording (${formatDuration(duration)})` : 'Record voice note'}
        >
          {isRecording ? <StopIcon /> : <MicIcon />}
          {isRecording && <span className="ui-feedback-voice-timer--compact">{formatDuration(duration)}</span>}
        </button>
      ) : (
        <div className="ui-feedback-voice-playback ui-feedback-voice-playback--compact">
          <audio src={displayUrl} controls />
          <button type="button" className="ui-feedback-voice-delete" onClick={onDelete} title="Delete recording"><TrashIcon /></button>
        </div>
      )}
    </div>
  );
}

function FullVoiceRecorder({ displayUrl, isRecording, duration, onToggleRecord, onDelete, error }: {
  displayUrl: string | null; isRecording: boolean; duration: number;
  onToggleRecord: () => void; onDelete: () => void; error: string | null;
}) {
  return (
    <div className="ui-feedback-voice-recorder">
      {!displayUrl ? (
        <>
          <button
            type="button"
            className={`ui-feedback-voice-button ${isRecording ? 'ui-feedback-voice-button--recording' : ''}`}
            onClick={onToggleRecord}
            title={isRecording ? 'Stop recording' : 'Start recording'}
          >
            {isRecording ? <StopIcon /> : <MicIcon />}
          </button>
          {isRecording && <span className="ui-feedback-voice-timer">{formatDuration(duration)}</span>}
          {!isRecording && <span style={{ color: 'var(--feedback-text-secondary)', fontSize: '13px' }}>Click to record a voice note</span>}
        </>
      ) : (
        <div className="ui-feedback-voice-playback">
          <audio src={displayUrl} controls />
          <button type="button" className="ui-feedback-voice-delete" onClick={onDelete} title="Delete recording"><TrashIcon /></button>
        </div>
      )}
      {error && <span className="ui-feedback-error">{error}</span>}
    </div>
  );
}
