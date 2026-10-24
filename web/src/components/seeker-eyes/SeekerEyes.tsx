/** 診断の間、暗闇から覗く鬼の目。ときどきまばたきし、左右を見回す。飾りなので読み上げない。 */
export function SeekerEyes({ className = "" }: { className?: string }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 64 20" className={`seeker-eyes ${className}`}>
      <g className="seeker-eyes-blink">
        <ellipse cx="18" cy="10" rx="9" ry="5" fill="var(--seeker)" />
        <ellipse cx="46" cy="10" rx="9" ry="5" fill="var(--seeker)" />
        <g className="seeker-eyes-look" fill="var(--paper)">
          <circle cx="18" cy="10" r="2.5" />
          <circle cx="46" cy="10" r="2.5" />
        </g>
      </g>
    </svg>
  );
}
