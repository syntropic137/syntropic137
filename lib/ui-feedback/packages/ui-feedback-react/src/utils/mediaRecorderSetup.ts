/**
 * MediaRecorder setup utilities for voice recording
 */

export interface RecorderCallbacks {
  onDataAvailable: (data: Blob) => void;
  onStop: (chunks: Blob[], mimeType: string) => void;
  onError: () => void;
}

/**
 * Get a supported audio MIME type for MediaRecorder
 */
export function getSupportedMimeType(): string | undefined {
  const types = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/ogg;codecs=opus',
    'audio/mp4',
  ];

  for (const type of types) {
    if (MediaRecorder.isTypeSupported(type)) {
      return type;
    }
  }

  return undefined;
}

/**
 * Create and configure a MediaRecorder with event handlers.
 * Returns the recorder ready to start.
 */
export function setupMediaRecorder(
  stream: MediaStream,
  callbacks: RecorderCallbacks,
): MediaRecorder {
  const mimeType = getSupportedMimeType();
  const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
  const chunks: Blob[] = [];

  recorder.ondataavailable = (event) => {
    if (event.data.size > 0) {
      chunks.push(event.data);
      callbacks.onDataAvailable(event.data);
    }
  };

  recorder.onstop = () => {
    callbacks.onStop(chunks, recorder.mimeType || 'audio/webm');
    stream.getTracks().forEach((track) => track.stop());
  };

  recorder.onerror = () => {
    callbacks.onError();
  };

  return recorder;
}
