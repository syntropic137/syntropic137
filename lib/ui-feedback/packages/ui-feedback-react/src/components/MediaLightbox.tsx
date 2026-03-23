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
      <img src={src} alt={alt} className="ui-feedback-lightbox-image" />
      <button className="ui-feedback-lightbox-close" onClick={onClose}>
        <CloseIcon />
      </button>
    </div>
  );
}
