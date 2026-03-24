/**
 * Hook for voice recording functionality
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { MediaUpload } from '../types';
import { setupMediaRecorder } from '../utils/mediaRecorderSetup';

export interface UseVoiceRecorderResult {
  isRecording: boolean;
  duration: number;
  audioBlob: Blob | null;
  audioUrl: string | null;
  startRecording: () => Promise<void>;
  stopRecording: () => void;
  clearRecording: () => void;
  getMediaUpload: () => MediaUpload | null;
  isSupported: boolean;
  error: string | null;
}

function checkBrowserSupport(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof navigator !== 'undefined' &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof MediaRecorder !== 'undefined'
  );
}

function classifyRecordingError(err: unknown): string {
  if (err instanceof DOMException && err.name === 'NotAllowedError') {
    return 'Microphone permission denied';
  }
  return 'Failed to start recording';
}

function cleanupResources(
  timerRef: React.MutableRefObject<ReturnType<typeof setInterval> | null>,
  streamRef: React.MutableRefObject<MediaStream | null>,
  audioUrl: string | null,
): void {
  if (timerRef.current) clearInterval(timerRef.current);
  if (streamRef.current) streamRef.current.getTracks().forEach((track) => track.stop());
  if (audioUrl) URL.revokeObjectURL(audioUrl);
}

function stopMediaRecorder(
  timerRef: React.MutableRefObject<ReturnType<typeof setInterval> | null>,
  mediaRecorderRef: React.MutableRefObject<MediaRecorder | null>,
): void {
  if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
  if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
    mediaRecorderRef.current.stop();
  }
}

interface RecorderSetters {
  setAudioBlob: (b: Blob) => void;
  setAudioUrl: (u: string) => void;
  setIsRecording: (v: boolean) => void;
  setError: (e: string) => void;
}

function createRecorderCallbacks(
  streamRef: React.MutableRefObject<MediaStream | null>,
  setters: RecorderSetters,
) {
  return {
    onDataAvailable: () => {},
    onStop: (chunks: Blob[], mimeType: string) => {
      const blob = new Blob(chunks, { type: mimeType });
      setters.setAudioBlob(blob);
      setters.setAudioUrl(URL.createObjectURL(blob));
      streamRef.current = null;
    },
    onError: () => { setters.setError('Recording failed'); setters.setIsRecording(false); },
  };
}

export function useVoiceRecorder(): UseVoiceRecorderResult {
  const [isRecording, setIsRecording] = useState(false);
  const [duration, setDuration] = useState(0);
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const isSupported = checkBrowserSupport();

  useEffect(() => {
    return () => cleanupResources(timerRef, streamRef, audioUrl);
  }, [audioUrl]);

  const startRecording = useCallback(async () => {
    if (!isSupported) { setError('Voice recording is not supported in this browser'); return; }
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const callbacks = createRecorderCallbacks(streamRef, { setAudioBlob, setAudioUrl, setIsRecording, setError });
      const recorder = setupMediaRecorder(stream, callbacks);
      mediaRecorderRef.current = recorder;
      recorder.start(100);
      setIsRecording(true);
      setDuration(0);
      timerRef.current = setInterval(() => setDuration((d) => d + 1), 1000);
    } catch (err) {
      setError(classifyRecordingError(err));
      console.error('Recording error:', err);
    }
  }, [isSupported]);

  const stopRecording = useCallback(() => {
    stopMediaRecorder(timerRef, mediaRecorderRef);
    setIsRecording(false);
  }, []);

  const clearRecording = useCallback(() => {
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    setAudioBlob(null);
    setAudioUrl(null);
    setDuration(0);
    setError(null);
  }, [audioUrl]);

  const getMediaUpload = useCallback((): MediaUpload | null => {
    if (!audioBlob) return null;
    return {
      mediaType: 'voice_note',
      mimeType: audioBlob.type || 'audio/webm',
      fileName: `voice-note-${Date.now()}.webm`,
      blob: audioBlob,
    };
  }, [audioBlob]);

  return {
    isRecording, duration, audioBlob, audioUrl,
    startRecording, stopRecording, clearRecording, getMediaUpload,
    isSupported, error,
  };
}

/**
 * Format seconds as MM:SS
 */
export function formatDuration(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}
