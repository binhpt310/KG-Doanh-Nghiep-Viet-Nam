import { useId } from 'react';

/**
 * KG Explorer mark — graph motif (nodes + edges) for header; uses currentColor.
 */
export function BrandLogo({ className }: { className?: string }) {
  const gid = useId().replace(/:/g, '');
  return (
    <svg
      className={className}
      viewBox="0 0 40 40"
      width={40}
      height={40}
      aria-hidden
      xmlns="http://www.w3.org/2000/svg"
    >
      <defs>
        <linearGradient id={gid} x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="currentColor" stopOpacity={0.95} />
          <stop offset="100%" stopColor="currentColor" stopOpacity={0.65} />
        </linearGradient>
      </defs>
      <circle
        cx={20}
        cy={20}
        r={17.5}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        opacity={0.35}
      />
      <path
        d="M11 24 L20 14 L29 24 M11 24 L20 26 L29 24"
        fill="none"
        stroke={`url(#${gid})`}
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx={11} cy={24} r={3.2} fill="currentColor" />
      <circle cx={20} cy={14} r={3.5} fill="currentColor" />
      <circle cx={29} cy={24} r={3.2} fill="currentColor" />
      <circle cx={20} cy={26} r={2.8} fill="currentColor" opacity={0.85} />
    </svg>
  );
}
