/** Inline audio player for base64 WAV/MP3 clips. */

import { useRef, useState } from 'react';

interface Props {
  audioBase64: string;
  format?: string;
  label?: string;
}

export function AudioPlayer({ audioBase64, format = 'wav', label }: Props) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);

  const src = `data:audio/${format};base64,${audioBase64}`;

  const toggle = () => {
    if (!audioRef.current) return;
    if (playing) {
      audioRef.current.pause();
    } else {
      audioRef.current.play();
    }
    setPlaying(!playing);
  };

  return (
    <div className="audio-player">
      {label && <span className="audio-label">{label}</span>}
      <button onClick={toggle} className="play-btn">
        {playing ? '⏸' : '▶'}
      </button>
      <audio
        ref={audioRef}
        src={src}
        onEnded={() => setPlaying(false)}
      />
    </div>
  );
}
