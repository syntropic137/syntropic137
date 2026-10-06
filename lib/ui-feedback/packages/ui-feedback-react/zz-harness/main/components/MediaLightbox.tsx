/**
 * Image lightbox overlay for viewing full-size screenshots
 */

import { CloseIcon } from './icons';

interface MediaLightboxProps {
  src: string;
  alt: string;
  onClose: () => void;
}

export function MediaLightbox({ src, alt, onClose }: MediaLightboxProps) {
  return (
    <div className="ui-feedback-lightbox" onClick={onClose}>
      <img src={src} alt={alt} className="ui-feedback-lightbox-image" onClick={(e) => e.stopPropagation()} />
      <button type="button" aria-label="Close lightbox" className="ui-feedback-lightbox-close" onClick={(e) => { e.stopPropagation(); onClose(); }}>
        <CloseIcon />
      </button>
    </div>
  );
}
